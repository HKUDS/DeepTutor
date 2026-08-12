"""Per-user Codex sign-in in an authenticated deployment (issue #781).

An owner-bound profile authenticates one person's ChatGPT plan, so it is
never grantable — which used to leave ordinary users with no path to Codex
at all, because the OAuth endpoints were admin-only too. They can now sign
in for themselves, and the isolation that makes it safe is asserted here:

* the profile is written to the user's OWN catalog, never the shared one;
* it reaches that user's options, capability gate, and selection validation;
* it reaches nobody else's — not another user's, not the administrator's,
  and not the grant editor's view of that user.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptutor.multi_user import model_access, personal_models

CODEX_PROFILE = "llm-profile-openai-codex-managed"
SHARED_PROFILE = "llm-profile-shared-key"


def _codex_profile(model_id: str, model: str) -> dict[str, Any]:
    """The shape ``sync_codex_catalog`` publishes — note the empty api_key:
    a managed Codex profile carries no secret, the token lives in the
    owner's credential store."""
    return {
        "id": CODEX_PROFILE,
        "name": "OpenAI Codex",
        "binding": "openai_codex",
        "api_key": "",
        "owner_bound": True,
        "read_only": True,
        "managed_by": "openai_codex_oauth",
        "models": [{"id": model_id, "name": model_id, "model": model}],
    }


def _write_catalog(path: Path, profiles: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "services": {"llm": {"profiles": profiles}}}),
        encoding="utf-8",
    )


def _sign_in_codex(as_user, uid: str, model_id: str, model: str) -> None:
    """Simulate a completed OAuth sign-in for *uid* by writing the profile
    exactly where the service publishes it: that owner's own catalog."""
    with as_user(uid):
        _write_catalog(
            personal_models.owner_catalog_service().path, [_codex_profile(model_id, model)]
        )


def _admin_catalog(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    return {"services": {"llm": {"profiles": profiles}}}


@pytest.fixture
def no_grants(monkeypatch):
    monkeypatch.setattr(model_access, "load_grant", lambda _uid=None: {"models": {"llm": []}})


def test_personal_catalog_is_the_users_own_file_not_the_shared_one(as_user, mu_isolated_root):
    """The whole isolation argument rests on this: nothing a user does can
    reach the catalog the administrator manages."""
    with as_user("u_alice"):
        alice_path = personal_models.owner_catalog_service().path
    with as_user("root", role="admin"):
        admin_path = personal_models.owner_catalog_service().path

    assert alice_path != admin_path
    assert "users/u_alice" in alice_path.as_posix()
    assert alice_path.is_relative_to((mu_isolated_root / "data" / "users" / "u_alice").resolve())


def test_signed_in_user_sees_their_own_codex_models(as_user, monkeypatch, no_grants):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _admin_catalog([]))
    _sign_in_codex(as_user, "u_alice", "m-sol", "gpt-5.6-sol")

    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert [(r["model_id"], r["source"], r["available"]) for r in rows] == [
            ("m-sol", "personal", True)
        ]
        # The option list, the gate, and selection validation all read that
        # same function, so a personal model works end to end without a grant.
        options = model_access.allowed_llm_options()["options"]
        assert [(o["model_id"], o["source"]) for o in options] == [("m-sol", "personal")]
        assert model_access.has_capability_access("llm") is True
        assert model_access.apply_allowed_llm_selection(
            {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
        ) == {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}


def test_one_users_codex_is_invisible_to_another(as_user, monkeypatch, no_grants):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _admin_catalog([]))
    _sign_in_codex(as_user, "u_alice", "m-sol", "gpt-5.6-sol")

    with as_user("u_bob"):
        assert model_access.redacted_model_access()["llm"] == []
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(
                {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
            )


def test_two_users_connect_different_accounts_without_crossover(as_user, monkeypatch, no_grants):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _admin_catalog([]))
    _sign_in_codex(as_user, "u_alice", "m-sol", "gpt-5.6-sol")
    _sign_in_codex(as_user, "u_bob", "m-mini", "gpt-5.6-mini")

    with as_user("u_alice"):
        assert [r["model_id"] for r in model_access.redacted_model_access()["llm"]] == ["m-sol"]
    with as_user("u_bob"):
        assert [r["model_id"] for r in model_access.redacted_model_access()["llm"]] == ["m-mini"]


def test_administrator_never_sees_a_users_personal_sign_in(as_user, monkeypatch, no_grants):
    """Two claims at once: the admin's own view is unchanged (it resolves
    straight from the catalog they manage), and asking for a user's grants
    does not surface that user's personal login."""
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _admin_catalog([]))
    _sign_in_codex(as_user, "u_alice", "m-sol", "gpt-5.6-sol")

    with as_user("root", role="admin"):
        assert model_access.redacted_model_access("u_alice")["llm"] == []
        assert personal_models.personal_llm_rows() == []


def test_granted_admin_models_and_personal_models_coexist(as_user, monkeypatch):
    shared = {
        "id": SHARED_PROFILE,
        "name": "Team key",
        "models": [{"id": "m-team", "name": "Team model", "model": "gpt-4o"}],
    }
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _admin_catalog([shared]))
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _uid=None: {
            "models": {"llm": [{"profile_id": SHARED_PROFILE, "model_ids": ["m-team"]}]}
        },
    )
    _sign_in_codex(as_user, "u_alice", "m-sol", "gpt-5.6-sol")

    with as_user("u_alice"):
        rows = model_access.redacted_model_access()["llm"]
        assert [(r["model_id"], r["source"]) for r in rows] == [
            ("m-team", "admin"),
            ("m-sol", "personal"),
        ]


def test_merge_lets_the_owners_profile_win_over_the_shared_one(as_user, monkeypatch, no_grants):
    """A managed profile id is a constant, so an administrator who also signed
    in holds one under the same id — listing *their* models. Resolving a user's
    selection against that would fail for any model their own plan added."""
    admin_side = _codex_profile("m-admin-only", "gpt-5.6-admin")
    _sign_in_codex(as_user, "u_alice", "m-sol", "gpt-5.6-sol")

    with as_user("u_alice"):
        merged = personal_models.merge_personal_llm_profiles(_admin_catalog([admin_side]))
        profiles = merged["services"]["llm"]["profiles"]
        assert [p["id"] for p in profiles] == [CODEX_PROFILE]
        assert [m["id"] for m in profiles[0]["models"]] == ["m-sol"]


def test_merge_is_a_no_op_without_a_personal_sign_in(as_user, monkeypatch, no_grants):
    catalog = _admin_catalog([{"id": SHARED_PROFILE, "models": []}])
    with as_user("u_alice"):
        assert personal_models.merge_personal_llm_profiles(catalog) is catalog


def test_reading_options_does_not_create_a_catalog_file(as_user, monkeypatch, no_grants):
    """A user who never touched Codex must not get a settings file written on
    every options request."""
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _admin_catalog([]))
    with as_user("u_alice"):
        catalog_path = personal_models.owner_catalog_service().path
        assert model_access.redacted_model_access()["llm"] == []
        assert not catalog_path.exists()
