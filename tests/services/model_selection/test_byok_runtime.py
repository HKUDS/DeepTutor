from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.config import provider_runtime
from deeptutor.services.model_selection import LLMSelection


class _Vault:
    def load_secret(self, user_id: str, profile_id: str):
        assert user_id == "u_alice"
        assert profile_id == "p_user"
        return (
            {
                "service": "llm",
                "provider": "openai",
                "model": "gpt-user",
                "base_url": "https://api.openai.com/v1",
                "generation": 4,
            },
            "sk-user-secret",
        )


def test_byok_runtime_uses_vault_and_skips_platform_catalog(monkeypatch):
    monkeypatch.setattr(
        provider_runtime,
        "get_current_user",
        lambda: SimpleNamespace(id="u_alice", is_admin=False),
    )
    monkeypatch.setattr(provider_runtime, "load_policy", lambda: {})
    monkeypatch.setattr(provider_runtime, "load_grant", lambda _user_id: {})
    monkeypatch.setattr(provider_runtime, "byok_runtime_enabled", lambda *_args: True)
    monkeypatch.setattr(provider_runtime, "grant_service_enabled", lambda *_args: True)
    monkeypatch.setattr(provider_runtime, "allowed_binding", lambda *_args: True)
    monkeypatch.setattr(provider_runtime, "get_user_byok_vault", lambda: _Vault())
    def validate_endpoint(endpoint, **kwargs):
        assert kwargs["resolve_dns"] is False
        return endpoint

    monkeypatch.setattr(provider_runtime, "validate_endpoint", validate_endpoint)

    resolved = provider_runtime.resolve_llm_runtime_config(
        catalog={"this": "must not be read"},
        llm_selection=LLMSelection(
            profile_id="p_user", model_id=None, source="byok", generation=4
        ),
    )

    assert resolved.model == "gpt-user"
    assert resolved.api_key == "sk-user-secret"
    assert resolved.base_url == "https://api.openai.com/v1"
    assert resolved.source == "byok"


def test_byok_runtime_rejects_stale_generation(monkeypatch):
    monkeypatch.setattr(
        provider_runtime,
        "get_current_user",
        lambda: SimpleNamespace(id="u_alice", is_admin=False),
    )
    monkeypatch.setattr(provider_runtime, "load_policy", lambda: {})
    monkeypatch.setattr(provider_runtime, "load_grant", lambda _user_id: {})
    monkeypatch.setattr(provider_runtime, "byok_runtime_enabled", lambda *_args: True)
    monkeypatch.setattr(provider_runtime, "grant_service_enabled", lambda *_args: True)
    monkeypatch.setattr(provider_runtime, "allowed_binding", lambda *_args: True)
    monkeypatch.setattr(provider_runtime, "get_user_byok_vault", lambda: _Vault())

    with pytest.raises(PermissionError, match="changed"):
        provider_runtime.resolve_llm_runtime_config(
            llm_selection={
                "source": "byok",
                "profile_id": "p_user",
                "generation": 3,
            }
        )


def test_platform_runtime_uses_authorized_selection_result(monkeypatch):
    from deeptutor.multi_user import model_access

    monkeypatch.setattr(
        provider_runtime,
        "get_current_user",
        lambda: SimpleNamespace(id="u_alice", is_admin=False),
    )
    monkeypatch.setattr(
        model_access,
        "apply_allowed_llm_selection",
        lambda _selection: {"source": "platform", "profile_id": "p_allowed", "model_id": "m_allowed"},
    )
    seen: dict[str, object] = {}
    catalog = {
        "services": {
            "llm": {
                "active_profile_id": "p_active",
                "active_model_id": "m_active",
                "profiles": [
                    {
                        "id": "p_active",
                        "binding": "openai",
                        "api_key": "sk-active",
                        "models": [{"id": "m_active", "model": "gpt-active"}],
                    }
                ],
            }
        }
    }

    def capture_selection(loaded, selection):
        seen["selection"] = selection
        return loaded

    monkeypatch.setattr(provider_runtime, "apply_llm_selection_to_catalog", capture_selection)
    resolved = provider_runtime.resolve_llm_runtime_config(
        catalog=catalog,
        llm_selection={"source": "platform", "profile_id": "p_untrusted", "model_id": "m_untrusted"},
    )

    assert seen["selection"] == LLMSelection(
        source="platform", profile_id="p_allowed", model_id="m_allowed"
    )
    assert resolved.source == "platform"
