"""``supported_reasoning_efforts`` must be absent, not ``null``, when undeclared.

The admin serializer always omitted the field unless the model declared a
list. The two non-admin serializers emitted ``null`` instead, and the web
composer guarded with ``supported_reasoning_efforts !== undefined`` before
calling ``.map`` — so any ordinary account whose granted model declared no
levels crashed on ``/chat`` (#2732, #2833).
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user import model_access, personal_models
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.model_selection.llm import list_llm_options

PROFILE = "llm-profile-shared"


def make_user(tmp_path):
    return CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "u_alice"),
    )


def _catalog(models: list[dict]) -> dict:
    return {
        "services": {
            "llm": {
                "active_profile_id": PROFILE,
                "active_model_id": models[0]["id"],
                "profiles": [
                    {"id": PROFILE, "name": PROFILE, "binding": "openai", "models": models}
                ],
            }
        }
    }


def _grant(model_ids: list[str]):
    return lambda _user_id=None: {
        "models": {"llm": [{"profile_id": PROFILE, "model_ids": list(model_ids)}]}
    }


def _run(tmp_path, monkeypatch, catalog, grant):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    monkeypatch.setattr(model_access, "load_grant", grant)
    token = set_current_user(make_user(tmp_path))
    try:
        return model_access.redacted_model_access(), model_access.allowed_llm_options()
    finally:
        reset_current_user(token)


def test_undeclared_levels_are_omitted_from_both_payloads(tmp_path, monkeypatch):
    rows, allowed = _run(
        tmp_path,
        monkeypatch,
        _catalog([{"id": "m-plain", "name": "Plain", "model": "gpt-plain"}]),
        _grant(["m-plain"]),
    )
    assert "supported_reasoning_efforts" not in rows["llm"][0]
    assert "supported_reasoning_efforts" not in allowed["options"][0]


def test_declared_levels_are_normalized_and_kept(tmp_path, monkeypatch):
    rows, allowed = _run(
        tmp_path,
        monkeypatch,
        _catalog(
            [
                {
                    "id": "m-levels",
                    "name": "Levels",
                    "model": "gpt-levels",
                    "codex_supported_reasoning_levels": ["LOW", " high ", ""],
                }
            ]
        ),
        _grant(["m-levels"]),
    )
    assert rows["llm"][0]["supported_reasoning_efforts"] == ["low", "high"]
    assert allowed["options"][0]["supported_reasoning_efforts"] == ["low", "high"]


def test_admin_serializer_keeps_the_same_contract():
    options = list_llm_options(_catalog([{"id": "m-plain", "name": "Plain", "model": "gpt-plain"}]))
    assert "supported_reasoning_efforts" not in options["options"][0]


@pytest.mark.parametrize(
    "levels, expected",
    [(None, None), (["HIGH"], ["high"]), ([], [])],
)
def test_personal_rows_use_the_same_rule(monkeypatch, levels, expected):
    model = {"id": "m-personal", "name": "Personal", "model": "gpt-personal"}
    if levels is not None:
        model["codex_supported_reasoning_levels"] = levels
    monkeypatch.setattr(
        personal_models,
        "_personal_catalog_profiles",
        lambda: [{"id": "p-personal", "binding": "openai", "models": [model]}],
    )
    row = personal_models.personal_llm_rows()[0]
    if expected is None:
        assert "supported_reasoning_efforts" not in row
    else:
        assert row["supported_reasoning_efforts"] == expected
