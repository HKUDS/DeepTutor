"""Owner-bound profiles are never lent to other accounts through grants.

Codex authenticates one person's ChatGPT plan rather than a billable team key,
so granting that profile to other users would run a whole deployment on a single
subscription. Administrators still use their own sign-in: they resolve models
straight from the catalog and never pass through the grant view tested here.
"""

from types import SimpleNamespace

import pytest

from deeptutor.multi_user import model_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope

CODEX_PROFILE = "llm-profile-openai-codex-managed"


def make_user(tmp_path):
    return CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "u_alice"),
    )


def _catalog(*, owner_bound: bool) -> dict:
    profile: dict = {
        "id": CODEX_PROFILE,
        "name": "OpenAI Codex",
        "models": [{"id": "m-sol", "name": "GPT-5.6-Sol", "model": "gpt-5.6-sol"}],
    }
    if owner_bound:
        profile["owner_bound"] = True
    return {"services": {"llm": {"profiles": [profile]}}}


def _grant(_user_id=None) -> dict:
    return {"models": {"llm": [{"profile_id": CODEX_PROFILE, "model_ids": ["m-sol"]}]}}


def test_owner_bound_profile_is_withheld_from_granted_users(tmp_path, monkeypatch):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog(owner_bound=True))
    monkeypatch.setattr(model_access, "load_grant", _grant)
    token = set_current_user(make_user(tmp_path))
    try:
        assert model_access.redacted_model_access()["llm"] == []
        assert model_access.allowed_llm_options()["options"] == []
        assert model_access.has_capability_access("llm") is False
        with pytest.raises(PermissionError):
            model_access.apply_allowed_llm_selection(
                {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
            )
    finally:
        reset_current_user(token)


def test_owner_bound_profile_is_not_offered_as_assignable(tmp_path, monkeypatch):
    """Admins must not be shown a grant the server would silently discard."""
    from deeptutor.multi_user import router as multi_user_router

    monkeypatch.setattr(
        multi_user_router,
        "ModelCatalogService",
        lambda path=None: SimpleNamespace(load=lambda: _catalog(owner_bound=True)),
    )
    monkeypatch.setattr(
        multi_user_router,
        "get_admin_path_service",
        lambda: SimpleNamespace(get_settings_file=lambda _name: tmp_path / "catalog.json"),
    )

    assert multi_user_router._admin_catalog_summary() == {"llm": []}


def test_ordinary_shared_profiles_stay_grantable(tmp_path, monkeypatch):
    """The filter has to stay narrow: an API-key profile is still shareable."""
    monkeypatch.setattr(model_access, "admin_catalog", lambda: _catalog(owner_bound=False))
    monkeypatch.setattr(model_access, "load_grant", _grant)
    token = set_current_user(make_user(tmp_path))
    try:
        granted = model_access.redacted_model_access()["llm"]
        assert [item["model_id"] for item in granted] == ["m-sol"]
        assert model_access.has_capability_access("llm") is True
        assert model_access.apply_allowed_llm_selection(
            {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
        ) == {"profile_id": CODEX_PROFILE, "model_id": "m-sol"}
    finally:
        reset_current_user(token)


def test_a_codebuddy_profile_is_owner_bound_by_its_binding() -> None:
    """CodeBuddy reads the operator's own IDE-plugin login on this host.

    Codex stamps ``owner_bound`` onto the managed profile it publishes, but a
    CodeBuddy profile is created by hand in the settings editor and has nowhere
    to acquire the flag — so without this the administrator's own subscription
    would be grantable to every account on the deployment.
    """
    assert model_access.is_owner_bound({"binding": "codebuddy"}) is True
    assert model_access.is_owner_bound({"binding": "CodeBuddy"}) is True
    # An ordinary team key stays grantable.
    assert model_access.is_owner_bound({"binding": "openai"}) is False
    # The explicit flag still wins for anything else that sets it.
    assert model_access.is_owner_bound({"binding": "openai", "owner_bound": True}) is True
