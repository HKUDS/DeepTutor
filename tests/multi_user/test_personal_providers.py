"""Offline tests for the per-owner "bring your own key" storage foundation.

These exercise the security invariants of #1927 slice-1 without HTTP or the
network: a personal key lives only in the owner's private secrets store and
never in a catalog, one account cannot see another's, the feature is gated
behind a default-off deployment policy, and a user-supplied base URL cannot
aim the app process inward.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from deeptutor.services import personal_providers as pp


@pytest.fixture(autouse=True)
def _clear_service_cache():
    pp._SERVICE_INSTANCES.clear()
    yield
    pp._SERVICE_INSTANCES.clear()


@pytest.fixture
def policy_on(mu_isolated_root):
    from deeptutor.services.config.runtime_settings import get_runtime_settings_service

    get_runtime_settings_service().save_system({"allow_personal_providers": True})
    return mu_isolated_root


def _save(service, provider_id="openai", **overrides):
    kwargs = {
        "api_key": "sk-personal-secret",
        "base_url": "https://1.1.1.1/v1",
        "binding": "openai_compat",
        "label": "My key",
    }
    kwargs.update(overrides)
    return asyncio.run(service.save(provider_id, **kwargs))


def test_policy_is_off_by_default(mu_isolated_root) -> None:
    assert pp.personal_providers_enabled() is False


def test_policy_round_trips_through_system_settings(policy_on) -> None:
    assert pp.personal_providers_enabled() is True


def test_disabled_policy_blocks_writes_and_reads(mu_isolated_root, as_user) -> None:
    with as_user("u_alice"):
        service = pp.get_personal_provider_service()
        with pytest.raises(pp.PersonalProviderError) as exc:
            _save(service)
        assert exc.value.http_status == 403
        with pytest.raises(pp.PersonalProviderError):
            service.list_public()
        with pytest.raises(pp.PersonalProviderError):
            service.delete("openai")


def test_disabled_policy_preserves_an_existing_secret(policy_on, as_user, monkeypatch) -> None:
    with as_user("u_alice"):
        _save(pp.get_personal_provider_service())
        secret_path = _only_secret_file(policy_on)
        assert secret_path.exists()
    monkeypatch.setattr(pp, "personal_providers_enabled", lambda: False)
    with as_user("u_alice"):
        with pytest.raises(pp.PersonalProviderError):
            pp.get_personal_provider_service().delete("openai")
    assert secret_path.exists(), "disabling the policy must not delete a stored key"


def test_save_stores_key_only_in_owner_secrets(policy_on, as_user) -> None:
    with as_user("u_alice"):
        row = _save(pp.get_personal_provider_service())
    assert row["has_key"] is True
    assert "api_key" not in row

    secret_path = _only_secret_file(policy_on)
    assert secret_path is not None
    assert "user-secrets" in secret_path.as_posix()
    assert "u_alice" in secret_path.as_posix()
    stored = json.loads(secret_path.read_text(encoding="utf-8"))
    assert stored["api_key"] == "sk-personal-secret"

    # The key must not appear in any catalog or workspace settings file.
    for path in (policy_on / "data").rglob("*.json"):
        if "user-secrets" in path.as_posix():
            continue
        assert "sk-personal-secret" not in path.read_text(encoding="utf-8"), path


def test_public_view_never_leaks_the_key(policy_on, as_user) -> None:
    with as_user("u_alice"):
        service = pp.get_personal_provider_service()
        _save(service)
        rows = service.list_public()
    assert len(rows) == 1
    assert rows[0]["id"] == "openai"
    assert rows[0]["has_key"] is True
    assert "api_key" not in rows[0]
    assert "sk-personal-secret" not in json.dumps(rows)


def test_one_account_cannot_see_anothers_key(policy_on, as_user) -> None:
    with as_user("u_alice"):
        _save(pp.get_personal_provider_service())
    with as_user("u_bob"):
        assert pp.get_personal_provider_service().list_public() == []
    bob_secrets = policy_on / "data" / "system" / "user-secrets" / "u_bob"
    assert not bob_secrets.exists() or not list(bob_secrets.rglob("*.v1.json"))


def test_delete_removes_only_the_named_provider(policy_on, as_user) -> None:
    with as_user("u_alice"):
        service = pp.get_personal_provider_service()
        _save(service, "openai")
        _save(service, "azure", label="Azure")
        result = service.delete("openai")
        assert result == {"id": "openai", "removed": True}
        remaining = [row["id"] for row in service.list_public()]
        assert remaining == ["azure"]
        assert service.delete("openai") == {"id": "openai", "removed": False}


@pytest.mark.parametrize(
    "base_url",
    [
        "https://169.254.169.254/v1",  # cloud metadata
        "https://127.0.0.1/v1",  # loopback
        "https://10.0.0.1/v1",  # RFC1918
        "https://192.168.1.1/v1",  # RFC1918
        "ftp://1.1.1.1/v1",  # non-http scheme
        "https://user:pass@1.1.1.1/v1",  # embedded credentials
    ],
)
def test_save_rejects_inward_or_invalid_base_url(policy_on, as_user, base_url) -> None:
    with as_user("u_alice"):
        with pytest.raises(pp.PersonalProviderError) as exc:
            _save(pp.get_personal_provider_service(), base_url=base_url)
        assert exc.value.code in {"base_url_not_allowed"}
    assert _only_secret_file(policy_on) is None


def test_save_rejects_unknown_binding_and_bad_id(policy_on, as_user) -> None:
    with as_user("u_alice"):
        service = pp.get_personal_provider_service()
        with pytest.raises(pp.PersonalProviderError) as binding_exc:
            _save(service, binding="not_a_provider")
        assert binding_exc.value.code == "unsupported_binding"
        with pytest.raises(pp.PersonalProviderError) as id_exc:
            _save(service, "../escape")
        assert id_exc.value.code == "invalid_provider_id"
        with pytest.raises(pp.PersonalProviderError) as key_exc:
            _save(service, api_key="   ")
        assert key_exc.value.code == "missing_api_key"


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX permission bits are not authoritative on Windows"
)
def test_secret_file_is_owner_private(policy_on, as_user) -> None:
    import stat

    with as_user("u_alice"):
        _save(pp.get_personal_provider_service())
    secret_path = _only_secret_file(policy_on)
    mode = stat.S_IMODE(secret_path.stat().st_mode)
    assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0, "secret file must not be group/world readable"


def _only_secret_file(root: Path) -> Path | None:
    secrets = root / "data" / "system" / "user-secrets"
    if not secrets.exists():
        return None
    files = list(secrets.rglob("*.v1.json"))
    return files[0] if files else None
