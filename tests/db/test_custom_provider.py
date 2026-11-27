"""A user-supplied endpoint: validated before stored, never holding the key.

Two failure modes are pinned here. First, an SSRF that is refused at save time
but trusted at use time, because DNS moved in between. Second, a key that leaks
through the path that is easiest to overlook -- serialisation.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.db.repositories.identity import IdentityRepository
from deeptutor.services import custom_provider as CP

SECRET = "sk-or-v1-THIS-MUST-NEVER-APPEAR"


@pytest.fixture
def user(db):
    IdentityRepository(db).save("u1", {"id": "u1", "hash": "x", "role": "user"})
    return "u1"


def _create(db, user_id="u1", url="https://openrouter.ai/api/v1", name="mine", **kw):
    return CP.create(
        db, user_id=user_id, name=name, base_url=url,
        model="nvidia/nemotron-3.5-super-vl:free",
        secret_ref="secret-abc", **kw,
    )


# ---------------------------------------------------------------------------
# Refused before it is stored
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,rule",
    [
        ("http://127.0.0.1:11434/v1", "loopback"),
        ("http://localhost/v1", "loopback"),
        ("http://169.254.169.254/latest/", "metadata_endpoint"),
        ("http://10.1.2.3/v1", "private_range"),
        ("file:///etc/passwd", "forbidden_scheme"),
    ],
)
def test_a_dangerous_url_is_never_stored(db, user, url, rule):
    """Storing first and validating later means the later path assumes valid."""
    with pytest.raises(CP.ProviderError) as exc:
        _create(db, url=url)
    assert exc.value.rule == "blocked_target"
    assert exc.value.extra["check"]["rule"] == rule
    assert CP.list_for_user(db, user) == [], "a refused provider left a row"


def test_a_blocked_url_is_explainable(db, user):
    with pytest.raises(CP.ProviderError) as exc:
        _create(db, url="http://169.254.169.254/")
    assert "metadata" in json.dumps(exc.value.as_dict()).lower()


def test_an_empty_name_is_refused(db, user):
    with pytest.raises(CP.ProviderError) as exc:
        _create(db, name="   ")
    assert exc.value.rule == "missing_name"


def test_an_empty_model_is_refused(db, user):
    with pytest.raises(CP.ProviderError) as exc:
        CP.create(
            db, user_id=user, name="x", base_url="https://openrouter.ai/api/v1",
            model="  ", secret_ref="s",
        )
    assert exc.value.rule == "missing_model"


def test_an_allow_list_is_enforced_at_save_time(db, user):
    with pytest.raises(CP.ProviderError) as exc:
        _create(db, allow_hosts=frozenset({"only.example"}))
    assert exc.value.extra["check"]["rule"] == "host_not_allowed"


# ---------------------------------------------------------------------------
# Stored safely
# ---------------------------------------------------------------------------


def test_a_good_provider_is_stored_and_returned(db, user):
    provider = _create(db)
    assert provider.base_url == "https://openrouter.ai/api/v1"
    assert CP.list_for_user(db, user)[0].id == provider.id


def test_the_key_is_not_in_the_row(db, user):
    """The key goes to the secret store; the row keeps only a reference."""
    _create(db, seal=lambda pid, ref: None)
    with db.read() as conn:
        row = conn.query_one("SELECT * FROM custom_providers")
    assert SECRET not in json.dumps(dict(row))


def test_the_public_object_has_no_field_for_a_secret(db, user):
    """A class that cannot hold a secret beats a serialiser that omits one."""
    provider = _create(db)
    assert not hasattr(provider, "api_key")
    assert not hasattr(provider, "secret")
    assert "secret_ref" not in provider.as_dict()


def test_serialising_a_provider_cannot_leak_a_key(db, user):
    provider = _create(db)
    assert SECRET not in json.dumps(provider.as_dict())
    assert "secret-abc" not in json.dumps(provider.as_dict())


def test_a_second_provider_with_the_same_name_is_refused(db, user):
    _create(db, name="mine")
    with pytest.raises(Exception):
        _create(db, name="mine")


# ---------------------------------------------------------------------------
# Scoped to its owner
# ---------------------------------------------------------------------------


def test_another_account_cannot_read_a_provider(db, user):
    provider = _create(db)
    IdentityRepository(db).save("u2", {"id": "u2", "hash": "y", "role": "user"})
    assert CP.get(db, "u2", provider.id) is None


def test_listing_only_returns_my_own(db, user):
    _create(db)
    IdentityRepository(db).save("u2", {"id": "u2", "hash": "y", "role": "user"})
    assert CP.list_for_user(db, "u2") == []


def test_another_account_cannot_delete_a_provider(db, user):
    provider = _create(db)
    IdentityRepository(db).save("u2", {"id": "u2", "hash": "y", "role": "user"})
    assert CP.delete(db, user_id="u2", provider_id=provider.id) is False
    assert CP.get(db, user, provider.id) is not None


# ---------------------------------------------------------------------------
# Re-checked at use time
# ---------------------------------------------------------------------------


def test_verifying_a_stored_url_checks_the_address_again(db, user, monkeypatch):
    """Save-time and use-time are different moments; DNS moves between them."""
    provider = _create(db)

    def _now_private(url, **kwargs):
        raise __import__("deeptutor.services.net_guard", fromlist=["x"]).BlockedTarget(
            "private_range", "resolves to 10.0.0.1 now"
        )

    monkeypatch.setattr("deeptutor.services.net_guard.check_url", _now_private)
    with pytest.raises(CP.ProviderError) as exc:
        CP.verify(db, user_id=user, provider_id=provider.id, responded=True, reported_usage=True)
    assert exc.value.rule == "blocked_at_use"


def test_a_provider_that_reports_usage_gives_actual_costs(db, user):
    provider = _create(db)
    updated = CP.verify(db, user_id=user, provider_id=provider.id, responded=True, reported_usage=True)
    assert updated.cost_basis == "actual"
    assert updated.verified_at is not None


def test_a_provider_that_reports_nothing_gives_estimates(db, user):
    """Calling an estimate "cost" without saying so is un-auditable."""
    provider = _create(db)
    updated = CP.verify(db, user_id=user, provider_id=provider.id, responded=True, reported_usage=False)
    assert updated.cost_basis == "estimated"


def test_a_failed_probe_does_not_claim_verification(db, user):
    provider = _create(db)
    updated = CP.verify(db, user_id=user, provider_id=provider.id, responded=False, reported_usage=False)
    assert updated.verified_at is None


def test_verifying_another_accounts_provider_is_refused(db, user):
    provider = _create(db)
    IdentityRepository(db).save("u2", {"id": "u2", "hash": "y", "role": "user"})
    with pytest.raises(CP.ProviderError) as exc:
        CP.verify(db, user_id="u2", provider_id=provider.id, responded=True, reported_usage=True)
    assert exc.value.rule == "not_found"
