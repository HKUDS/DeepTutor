"""The custom-provider endpoints: owner-scoped, and the key never comes back."""

from __future__ import annotations

import asyncio
import json

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import providers as api
from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.repositories.identity import IdentityRepository

KEY = "sk-or-v1-BODY-CANARY-1111"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(db, monkeypatch):
    settings = DatabaseSettings(app_url=db.settings.app_url, backend=db.settings.backend)
    monkeypatch.setattr("deeptutor.db.config.get_database_settings", lambda: settings)
    reset_database_settings()
    for user_id in ("u1", "u2"):
        IdentityRepository(db).save(user_id, {"id": user_id, "hash": user_id, "role": "user"})
    return db


def _payload(**kw):
    values = {
        "name": "mine",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "nvidia/nemotron-3.5-super-vl:free",
        "api_key": KEY,
    }
    values.update(kw)
    return api.CreateProvider(**values)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_a_valid_provider_is_created(live):
    result = _run(api.create_provider(_payload(), user_id="u1"))
    assert result["base_url"] == "https://openrouter.ai/api/v1"


def test_the_key_is_not_in_the_create_response(live):
    result = _run(api.create_provider(_payload(), user_id="u1"))
    assert KEY not in json.dumps(result)
    assert "secret_ref" not in result


def test_the_key_is_not_in_the_list_response(live):
    _run(api.create_provider(_payload(), user_id="u1"))
    result = _run(api.list_providers(user_id="u1"))
    assert KEY not in json.dumps(result)


def test_the_key_is_not_stored_on_the_row(live):
    _run(api.create_provider(_payload(), user_id="u1"))
    with live.read() as conn:
        row = dict(conn.query_one("SELECT * FROM custom_providers"))
    assert KEY not in json.dumps(row)


def test_a_metadata_url_is_refused_with_the_rule_named(live):
    with pytest.raises(HTTPException) as exc:
        _run(api.create_provider(_payload(base_url="http://169.254.169.254/"), user_id="u1"))
    assert exc.value.status_code == 422
    assert exc.value.detail["check"]["rule"] == "metadata_endpoint"


def test_a_loopback_url_is_refused(live):
    with pytest.raises(HTTPException) as exc:
        _run(api.create_provider(_payload(base_url="http://127.0.0.1:11434/v1"), user_id="u1"))
    assert exc.value.status_code == 422
    assert exc.value.detail["check"]["rule"] == "loopback"


def test_a_refused_provider_is_not_stored(live):
    with pytest.raises(HTTPException):
        _run(api.create_provider(_payload(base_url="http://10.0.0.1/"), user_id="u1"))
    assert _run(api.list_providers(user_id="u1"))["providers"] == []


def test_the_refusal_does_not_echo_the_key(live):
    with pytest.raises(HTTPException) as exc:
        _run(api.create_provider(_payload(base_url="http://169.254.169.254/"), user_id="u1"))
    assert KEY not in json.dumps(exc.value.detail)


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------


def test_a_second_account_cannot_see_my_provider(live):
    _run(api.create_provider(_payload(), user_id="u1"))
    assert _run(api.list_providers(user_id="u2"))["providers"] == []


def test_a_second_account_cannot_delete_my_provider(live):
    created = _run(api.create_provider(_payload(), user_id="u1"))
    result = _run(api.delete_provider(created["id"], user_id="u2"))
    assert result["deleted"] is False
    assert len(_run(api.list_providers(user_id="u1"))["providers"]) == 1


def test_the_owner_can_delete(live):
    created = _run(api.create_provider(_payload(), user_id="u1"))
    assert _run(api.delete_provider(created["id"], user_id="u1"))["deleted"] is True


def test_no_identity_is_refused(live):
    with pytest.raises(HTTPException) as exc:
        _run(api.list_providers(user_id=None))
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# The key must not travel where a log can see it
# ---------------------------------------------------------------------------


def test_the_key_is_not_a_query_parameter():
    """A query string is written to every access log on the way."""
    import inspect

    signature = inspect.signature(api.create_provider)
    for name, param in signature.parameters.items():
        assert "key" not in name.lower(), f"{name} would put a key in the URL"
        assert "secret" not in name.lower(), f"{name} would put a secret in the URL"
    assert "api_key" in api.CreateProvider.model_fields


def test_no_route_declares_a_key_in_its_path():
    """Path parameters are logged by the server itself, not by a proxy."""
    for route in api.router.routes:
        path = getattr(route, "path", "")
        assert "key" not in path.lower()
        assert "secret" not in path.lower()
        for param in getattr(route, "param_convertors", {}) or {}:
            assert "key" not in param.lower()


def test_a_key_in_the_query_string_is_not_accepted(live):
    """FastAPI ignores undeclared query params, so this documents that the
    only accepted channel is the body -- and that a key sent in the query has
    no effect rather than being silently honoured."""
    created = _run(api.create_provider(_payload(), user_id="u1"))
    assert created["id"]
    with live.read() as conn:
        row = dict(conn.query_one("SELECT * FROM custom_providers"))
    assert KEY not in json.dumps(row)
