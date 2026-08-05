"""FT-05: LLM api_protocol resolution and redacted option exposure."""

from __future__ import annotations

from typing import Any

from deeptutor.services.config.provider_runtime import (
    resolve_api_protocol,
    resolve_llm_runtime_config,
)
from deeptutor.services.model_selection import list_llm_options


def _catalog(*, binding: str, api_protocol: str = "auto", strict: bool = False) -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-p",
                "active_model_id": "llm-m",
                "profiles": [
                    {
                        "id": "llm-p",
                        "name": "LLM",
                        "binding": binding,
                        "api_protocol": api_protocol,
                        "strict_protocol": strict,
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [{"id": "llm-m", "name": "m", "model": "gpt-4o"}],
                    }
                ],
            }
        },
    }


def test_explicit_protocols_are_honored_verbatim():
    for protocol in ("openai_chat_completions", "openai_responses", "anthropic_messages"):
        resolved, reason = resolve_api_protocol("openai", protocol)
        assert resolved == protocol
        assert reason == f"explicit:{protocol}"


def test_auto_defaults_to_chat_completions():
    resolved, reason = resolve_api_protocol("openai", "auto")
    assert resolved == "openai_chat_completions"
    assert reason == "auto:default_chat_completions"


def test_auto_anthropic_binding_resolves_to_anthropic_messages():
    for binding in ("anthropic", "custom_anthropic", "minimax_anthropic"):
        resolved, reason = resolve_api_protocol(binding, "auto")
        assert resolved == "anthropic_messages"
        assert reason == "auto:anthropic_binding"


def test_invalid_protocol_is_treated_as_auto():
    resolved, reason = resolve_api_protocol("openai", "bogus")
    assert resolved == "openai_chat_completions"
    assert reason == "auto:default_chat_completions"


def test_resolve_llm_runtime_config_exposes_protocol_contract():
    resolved = resolve_llm_runtime_config(
        catalog=_catalog(
            binding="anthropic",
            api_protocol="anthropic_messages",
            strict=True,
        )
    )
    assert resolved.api_protocol == "anthropic_messages"
    assert resolved.strict_protocol is True
    assert resolved.resolved_api_protocol == "anthropic_messages"
    assert resolved.protocol_resolution_reason == "explicit:anthropic_messages"


def test_list_llm_options_exposes_protocol_without_secrets():
    catalog = _catalog(binding="openai", api_protocol="openai_responses", strict=True)
    catalog["services"]["llm"]["profiles"][0]["capability_probe_status"] = "passed"

    payload = list_llm_options(catalog)
    option = payload["options"][0]

    assert option["api_protocol"] == "openai_responses"
    assert option["strict_protocol"] is True
    assert option["capability_probe_status"] == "passed"
    assert "api_key" not in option
    assert "base_url" not in option
