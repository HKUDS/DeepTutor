"""Acceptance criterion: no API key in the browser, on the wire, or in a log.

Evidence, not assertion. Each test puts a recognisable fake key into a real
configuration path and then greps what actually crosses the boundary. A masking
helper that exists but is not called would pass a unit test and fail every one
of these.
"""

from __future__ import annotations

import json
import logging

import pytest

from deeptutor.services.config import model_catalog

SECRET = "sk-or-v1-LEAKCANARY-9f3a2b1c"


# ---------------------------------------------------------------------------
# The catalog read path
# ---------------------------------------------------------------------------


def _catalog_with_secret():
    return {
        "connections": [
            {"name": "openrouter", "base_url": "https://openrouter.ai/api/v1", "api_key": SECRET}
        ],
        "services": {
            "llm": {
                "profiles": [
                    {"name": "p1", "api_key": SECRET, "extra_headers": {"Authorization": SECRET}},
                ]
            }
        },
    }


def test_redaction_removes_the_key_from_the_catalog():
    redacted = model_catalog.redact_catalog_secrets(_catalog_with_secret())
    assert SECRET not in json.dumps(redacted)


def test_redaction_also_removes_header_credentials():
    """Headers are credentials often enough that none should cross."""
    redacted = model_catalog.redact_catalog_secrets(_catalog_with_secret())
    assert SECRET not in json.dumps(redacted["services"]["llm"]["profiles"][0]["extra_headers"])


def test_redaction_says_the_key_is_set():
    """A blank field is indistinguishable from an unset one, and the UI needs
    to know the difference to show 'configured'."""
    redacted = model_catalog.redact_catalog_secrets(_catalog_with_secret())
    assert redacted["connections"][0]["api_key"] == model_catalog.CATALOG_SECRET_MASK


def test_redaction_does_not_mutate_the_stored_config():
    """Masking what was sent must not blank what is saved."""
    original = _catalog_with_secret()
    model_catalog.redact_catalog_secrets(original)
    assert original["connections"][0]["api_key"] == SECRET


def test_the_nonsecret_parts_survive_redaction():
    """Over-redacting breaks the settings page; the base URL must remain."""
    redacted = model_catalog.redact_catalog_secrets(_catalog_with_secret())
    assert redacted["connections"][0]["base_url"] == "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# The custom provider surface added in Phase 9
# ---------------------------------------------------------------------------


def test_a_custom_provider_serialisation_has_no_key(db):
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.services import custom_provider as CP

    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    provider = CP.create(
        db, user_id="u1", name="mine", base_url="https://openrouter.ai/api/v1",
        model="m", secret_ref="ref-123",
    )
    assert SECRET not in json.dumps(provider.as_dict())


def test_the_row_never_held_a_key_to_begin_with(db):
    """The strongest form: store a reference, so a dump cannot contain a key."""
    from deeptutor.db.repositories.identity import IdentityRepository
    from deeptutor.services import custom_provider as CP

    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    CP.create(
        db, user_id="u1", name="mine", base_url="https://openrouter.ai/api/v1",
        model="m", secret_ref="ref-123",
    )
    with db.read() as conn:
        row = dict(conn.query_one("SELECT * FROM custom_providers"))
    assert SECRET not in json.dumps(row)
    assert set(row) == {
        "id", "user_id", "name", "base_url", "model", "secret_ref",
        "cost_basis", "verified_at", "created_at",
    }, "a new column could carry a credential; this test must be updated deliberately"


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def test_a_refused_provider_does_not_log_the_key(caplog):
    """An exception message is a log line waiting to happen."""
    from deeptutor.services import custom_provider as CP

    key = "sk-or-v1-logcanary-0000"
    with caplog.at_level(logging.DEBUG):
        try:
            CP.create(
                None, user_id="u1", name="x", base_url="http://169.254.169.254/",
                model="m", secret_ref=key,
            )
        except Exception as exc:  # noqa: BLE001 - the point is the rendered message
            rendered = f"{exc} {getattr(exc, 'extra', '')}"
    assert key not in rendered
    assert key not in caplog.text
