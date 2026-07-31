from __future__ import annotations

import pytest

from deeptutor.multi_user import byok_policy
from deeptutor.multi_user.byok_vault import (
    ByokVaultConflict,
    ByokVaultUnavailable,
    UserByokCredentialVault,
)


def test_vault_encrypts_and_redacts_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_BYOK_MASTER_KEY", "test-master-key")
    vault = UserByokCredentialVault(tmp_path / "byok")

    saved = vault.save_profile(
        "u_alice",
        {
            "service": "llm",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "base_url": "https://api.openai.com/v1",
        },
        "sk-user-secret",
    )

    assert saved["configured"] is True
    assert "api_key" not in saved
    assert "secret" not in saved
    assert vault.list_profiles("u_alice")[0]["id"] == saved["id"]
    metadata, secret = vault.load_secret("u_alice", saved["id"])
    assert metadata["model"] == "gpt-4o-mini"
    assert secret == "sk-user-secret"
    raw = (tmp_path / "byok" / "u_alice" / "profiles.v1.json").read_text()
    assert "sk-user-secret" not in raw


def test_vault_fails_closed_without_master_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPTUTOR_BYOK_MASTER_KEY", raising=False)
    vault = UserByokCredentialVault(tmp_path / "byok")
    with pytest.raises(ByokVaultUnavailable):
        vault.save_profile("u_alice", {"service": "mineru", "provider": "mineru"}, "token")


def test_vault_generation_conflict_and_metadata_update(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_BYOK_MASTER_KEY", "test-master-key")
    vault = UserByokCredentialVault(tmp_path / "byok")
    saved = vault.save_profile("u_alice", {"service": "embedding", "provider": "openai"}, "key")
    updated = vault.save_profile(
        "u_alice",
        {"service": "embedding", "provider": "openai", "model": "text-embedding-3-small"},
        None,
        profile_id=saved["id"],
        expected_generation=saved["generation"],
    )
    assert updated["generation"] == saved["generation"] + 1
    assert vault.load_secret("u_alice", saved["id"])[1] == "key"
    with pytest.raises(ByokVaultConflict):
        vault.save_profile(
            "u_alice",
            {"service": "embedding", "provider": "openai"},
            "new-key",
            profile_id=saved["id"],
            expected_generation=saved["generation"],
        )


def test_policy_blocks_private_addresses_and_requires_custom_allowlist(monkeypatch):
    monkeypatch.setattr(byok_policy, "load_auth_settings", lambda: {"enabled": True})
    policy = byok_policy.normalize_policy(
        {
            "services": {
                "llm": {"allowed_bindings": ["openai"], "allow_custom_endpoints": False}
            }
        }
    )
    with pytest.raises(ValueError, match="not allowed"):
        byok_policy.validate_endpoint(
            "https://custom.example/v1",
            service="llm",
            binding="openai",
            policy=policy,
            resolve_dns=False,
        )
    with pytest.raises(ValueError, match="blocked"):
        byok_policy.validate_endpoint(
            "https://127.0.0.1/v1",
            service="llm",
            binding="openai",
            policy=policy,
            resolve_dns=False,
        )


def test_old_grant_migrates_platform_access_and_byok_defaults_deny():
    from deeptutor.multi_user.grants import normalize_grant, validate_grant

    migrated = normalize_grant("u_old", {"version": 2, "models": {"llm": []}})
    fresh = normalize_grant("u_new", None)
    assert migrated["version"] == 3
    assert migrated["platform"]["embedding"]["enabled"] is True
    assert migrated["platform"]["mineru"]["enabled"] is True
    assert fresh["platform"]["embedding"]["enabled"] is False
    assert migrated["byok"]["llm"]["enabled"] is False
    assert fresh["byok"] == {
        "llm": {"enabled": False},
        "embedding": {"enabled": False},
        "mineru": {"enabled": False},
    }
    assert normalize_grant("u_partial", {"byok": {"llm": {}}})["byok"]["llm"]["enabled"] is False
    with pytest.raises(ValueError):
        validate_grant({"byok": {"llm": {"api_key": "sk-secret"}}})
