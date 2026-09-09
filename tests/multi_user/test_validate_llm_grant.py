"""Grant LLM validation: a grant that could never resolve must save as a 400.

The production walkthrough (2026-09-09) found accounts showing "no model
assigned" because the admin saved a grant whose ``models.llm`` item lacked
``model_ids`` (or pointed at a deleted profile) — the runtime silently matched
zero models. Now the save endpoint rejects those payloads with a field-level
error instead.
"""

from __future__ import annotations

import asyncio

import pytest

CATALOG = {
    "services": {
        "llm": {
            "active_profile_id": "prof-main",
            "active_model_id": "m-main",
            "profiles": [
                {
                    "id": "prof-main",
                    "models": [
                        {"id": "m-main", "name": "Main", "model": "main-v1"},
                        {"id": "m-mini", "name": "Mini", "model": "mini-v1"},
                    ],
                }
            ],
        }
    }
}


def _validate(items):
    from deeptutor.multi_user.model_access import validate_llm_grant_items

    validate_llm_grant_items(items, catalog=CATALOG)


def test_valid_grant_item_passes() -> None:
    _validate([{"profile_id": "prof-main", "model_ids": ["m-main", "m-mini"]}])


def test_missing_model_ids_is_rejected_with_field_path() -> None:
    with pytest.raises(ValueError, match=r"grant\.models\.llm\[0\]\.model_ids is required"):
        _validate([{"profile_id": "prof-main"}])

    with pytest.raises(ValueError, match=r"model_ids is required"):
        _validate([{"profile_id": "prof-main", "model_ids": []}])


def test_unknown_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown profile 'prof-gone'"):
        _validate([{"profile_id": "prof-gone", "model_ids": ["m-main"]}])


def test_unknown_model_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown model 'm-gone' in profile 'prof-main'"):
        _validate([{"profile_id": "prof-main", "model_ids": ["m-main", "m-gone"]}])


def test_missing_profile_id_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"grant\.models\.llm\[0\]\.profile_id is required"):
        _validate([{"model_ids": ["m-main"]}])


def _patch_identity(monkeypatch) -> None:
    """Every ``get_user_by_id`` consumer resolves 'u_alice' → a teacher record."""
    record = ("alice", {"role": "teacher"})
    for module in (
        "deeptutor.api.routers.multi_user",
        "deeptutor.multi_user.grants",
    ):
        monkeypatch.setattr(f"{module}.get_user_by_id", lambda user_id, r=record: r)


def test_put_user_grants_returns_400_on_unresolvable_llm(mu_isolated_root, monkeypatch) -> None:
    """The endpoint converts the validation failure into a 400, not a save."""
    from deeptutor.api.routers.multi_user import GrantPayload, put_user_grants
    from deeptutor.multi_user.grants import empty_grant, load_grant

    _patch_identity(monkeypatch)
    monkeypatch.setattr("deeptutor.multi_user.model_access.admin_catalog", lambda: CATALOG)

    payload = GrantPayload(grant={"models": {"llm": [{"profile_id": "prof-main"}]}})
    with pytest.raises(Exception) as exc:
        asyncio.run(put_user_grants("u_alice", payload))
    assert getattr(exc.value, "status_code", None) == 400
    assert "model_ids" in str(getattr(exc.value, "detail", ""))

    # The broken grant was never persisted.
    assert load_grant("u_alice") == empty_grant("u_alice")


def test_put_user_grants_accepts_resolvable_llm(mu_isolated_root, monkeypatch) -> None:
    from deeptutor.api.routers.multi_user import GrantPayload, put_user_grants
    from deeptutor.multi_user.grants import load_grant

    _patch_identity(monkeypatch)
    monkeypatch.setattr("deeptutor.multi_user.model_access.admin_catalog", lambda: CATALOG)

    payload = GrantPayload(
        grant={"models": {"llm": [{"profile_id": "prof-main", "model_ids": ["m-main"]}]}}
    )
    result = asyncio.run(put_user_grants("u_alice", payload))
    assert result["grant"]["models"]["llm"] == [
        {"profile_id": "prof-main", "model_ids": ["m-main"]}
    ]
    assert load_grant("u_alice")["models"]["llm"][0]["model_ids"] == ["m-main"]
