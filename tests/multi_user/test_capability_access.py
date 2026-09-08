"""Tests for capability-based access: has_capability_access.

As of the multi-user release only the LLM capability is grantable per user, so
gating is LLM-only; embedding/search are shared admin infrastructure. The same
helper backs the turn-runtime gate and the frontend lock, so they always agree.
"""

from deeptutor.multi_user import model_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope


def make_user(tmp_path, role="user"):
    uid = "u_admin" if role == "admin" else "u_alice"
    return CurrentUser(
        id=uid,
        username="admin" if role == "admin" else "alice",
        role=role,
        scope=UserScope(
            kind="admin" if role == "admin" else "user",
            user_id=uid,
            root=tmp_path / uid,
        ),
    )


def _fake_access(llm=None):
    """Build a redacted_model_access return value with the given llm bucket."""
    return lambda _user_id=None: {"llm": list(llm or [])}


def test_admin_always_has_access(tmp_path, monkeypatch):
    # Admins are never gated and must not even consult the grant view.
    def _boom(_user_id=None):
        raise AssertionError("redacted_model_access should not be called for admins")

    monkeypatch.setattr(model_access, "redacted_model_access", _boom)
    token = set_current_user(make_user(tmp_path, role="admin"))
    try:
        assert model_access.has_capability_access("llm") is True
    finally:
        reset_current_user(token)


def test_user_with_available_model_has_access(tmp_path, monkeypatch):
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        _fake_access(llm=[{"profile_id": "p", "model_id": "m", "available": True}]),
    )
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        assert model_access.has_capability_access("llm") is True
    finally:
        reset_current_user(token)


def test_user_with_unavailable_model_has_no_access(tmp_path, monkeypatch):
    # A granted profile that no longer resolves in the catalog is available=False.
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        _fake_access(llm=[{"profile_id": "p", "available": False}]),
    )
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        assert model_access.has_capability_access("llm") is False
    finally:
        reset_current_user(token)


def test_user_with_empty_grant_has_no_access(tmp_path, monkeypatch):
    monkeypatch.setattr(model_access, "redacted_model_access", _fake_access())
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        assert model_access.has_capability_access("llm") is False
    finally:
        reset_current_user(token)


def test_user_default_matches_first_available_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        model_access,
        "admin_catalog",
        lambda: {
            "services": {
                "llm": {
                    "active_profile_id": "global",
                    "active_model_id": "global-model",
                }
            }
        },
    )
    monkeypatch.setattr(
        model_access,
        "redacted_model_access",
        _fake_access(
            llm=[
                {
                    "profile_id": "first",
                    "model_id": "first-model",
                    "name": "First model",
                    "available": True,
                },
                {
                    "profile_id": "global",
                    "model_id": "global-model",
                    "name": "Global model",
                    "available": True,
                },
                {
                    "profile_id": "unavailable",
                    "model_id": "unavailable-model",
                    "name": "Unavailable model",
                    "available": False,
                },
            ]
        ),
    )
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        allowed = model_access.allowed_llm_options()
        assert allowed["active"] == {
            "profile_id": "first",
            "model_id": "first-model",
        }
        assert [option["is_active_default"] for option in allowed["options"]] == [
            True,
            False,
        ]
    finally:
        reset_current_user(token)
