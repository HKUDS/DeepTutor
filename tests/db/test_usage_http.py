"""The spend endpoints, over the real router.

The risk in a "my usage" endpoint is that `user_id` becomes a parameter that
reads someone else's spending. The scope helper discards it when authentication
is on; these tests pin both halves of that, plus the mount policy that keeps the
operator totals off a student's session.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import usage as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.db.repositories.wallets import WalletRepository


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    for user_id in ("u1", "u2"):
        IdentityRepository(db).save(user_id, {"id": user_id, "hash": user_id, "role": "user"})
        WalletRepository(db).grant(user_id, tokens=10_000)
    WalletRepository(db).spend(
        "u1", tokens=120, action="chat_completion", prompt_tokens=100, completion_tokens=20
    )
    return db


# ---------------------------------------------------------------------------
# The student's own view
# ---------------------------------------------------------------------------


def test_my_usage_reports_my_spend(live):
    result = _run(api.my_usage(days=None, user_id="u1"))
    assert result["tokens_spent"] == 120
    assert result["by_surface"]["chat"]["tokens"] == 120


def test_my_usage_does_not_include_another_account(live):
    assert _run(api.my_usage(days=None, user_id="u2"))["tokens_spent"] == 0


def test_recent_returns_my_events(live):
    result = _run(api.my_recent(limit=10, user_id="u1"))
    assert [row["surface"] for row in result["rows"]] == ["chat"]


def test_reconciliation_is_readable_by_the_user(live):
    result = _run(api.my_reconciliation(user_id="u1"))
    assert result["ok"] is True


def test_a_user_with_no_identity_is_refused(live):
    """Better a 401 than a report about an empty account name."""
    with pytest.raises(HTTPException) as exc:
        _run(api.my_usage(days=None, user_id=None))
    assert exc.value.status_code == 401
    assert exc.value.detail["rule"] == "no_identity"


# ---------------------------------------------------------------------------
# The supplied id is discarded when authentication is on
# ---------------------------------------------------------------------------


def test_authentication_overrides_the_supplied_id(live, monkeypatch):
    """The bug class the scope helper exists to close."""
    monkeypatch.setattr("deeptutor.services.scope._auth_enabled", lambda: True)

    class Someone:
        id = "u2"

    monkeypatch.setattr(
        "deeptutor.multi_user.context.get_current_user", lambda: Someone()
    )
    # Ask for u1 while logged in as u2: the session wins.
    result = _run(api.my_usage(days=None, user_id="u1"))
    assert result["user_id"] == "u2"
    assert result["tokens_spent"] == 0


# ---------------------------------------------------------------------------
# The operator view
# ---------------------------------------------------------------------------


def test_operator_totals_span_accounts(live):
    result = _run(api.all_usage(days=30))
    assert result["active_users"] == 1
    assert result["tokens_spent"] == 120


def test_the_operator_view_takes_no_user_id(live):
    """The operator view is admin-mounted; a user id would make it look scoped."""
    import inspect

    assert "user_id" not in inspect.signature(api.all_usage).parameters


def test_the_admin_view_is_on_its_own_router(live):
    """Mount policy is the security boundary, so the routers must stay apart.

    Comparing paths would be the wrong test: an empty path is normal in both,
    because the prefix is applied at mount time. What matters is that the two
    route objects live on different routers and that the manifest mounts the
    admin one with the admin policy.
    """
    assert api.admin_router is not api.router

    import json
    from pathlib import Path

    manifest = json.loads(
        (Path(api.__file__).parents[2] / "modules/manifests/server.json").read_text()
    )
    policies = {
        route["reference"]: route["auth"] for route in manifest["routes"]
    }
    assert policies["deeptutor.api.routers.usage:router"] == "learning"
    assert policies["deeptutor.api.routers.usage:admin_router"] == "admin"


# ---------------------------------------------------------------------------
# The response shape
# ---------------------------------------------------------------------------


def test_the_response_is_json_serialisable(live):
    """A dataclass left in the payload fails at the edge, not in the test."""
    payload = _run(api.my_usage(days=30, user_id="u1"))
    assert json.loads(json.dumps(payload))["tokens_spent"] == 120


def test_recent_rows_carry_no_secret(live):
    payload = _run(api.my_recent(limit=10, user_id="u1"))
    assert "secret" not in json.dumps(payload).lower()
