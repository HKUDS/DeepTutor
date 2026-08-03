"""Tests for TutorBot-style runtime config adapter."""

from __future__ import annotations

from deeptutor.services.config.provider_runtime import (
    resolve_llm_runtime_config,
    resolve_search_runtime_config,
)


def _build_catalog(
    *,
    llm_profile: dict | None = None,
    llm_model: dict | None = None,
    search_profile: dict | None = None,
) -> dict:
    llm_profile = llm_profile or {
        "id": "llm-p",
        "name": "LLM",
        "binding": "openai",
        "base_url": "",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "llm-m", "name": "m", "model": "gpt-4o-mini"}],
    }
    llm_model = llm_model or llm_profile["models"][0]
    search_profile = search_profile or {
        "id": "search-p",
        "name": "Search",
        "provider": "brave",
        "base_url": "",
        "api_key": "",
        "proxy": "",
        "models": [],
    }
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": llm_profile["id"],
                "active_model_id": llm_model["id"],
                "profiles": [llm_profile],
            },
            "embedding": {
                "active_profile_id": None,
                "active_model_id": None,
                "profiles": [],
            },
            "search": {
                "active_profile_id": search_profile["id"],
                "profiles": [search_profile],
            },
        },
    }


def test_llm_explicit_binding_and_headers() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "dashscope",
            "base_url": "",
            "api_key": "dash-key",
            "api_version": "",
            "extra_headers": {"APP-Code": "abc"},
            "models": [{"id": "llm-m", "name": "q", "model": "qwen-max"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "dashscope"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert resolved.extra_headers == {"APP-Code": "abc"}


def test_llm_api_key_prefix_gateway() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "",
            "base_url": "",
            "api_key": "sk-or-test-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "gemini-2.5-pro"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "openrouter"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://openrouter.ai/api/v1"


def test_llm_api_base_keyword_gateway() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "",
            "base_url": "https://api.aihubmix.com/v1",
            "api_key": "k",
            "api_version": "",
            "extra_headers": {"APP-Code": "x"},
            "models": [{"id": "llm-m", "name": "m", "model": "claude-3-7-sonnet"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "aihubmix"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://api.aihubmix.com/v1"
    assert resolved.extra_headers == {"APP-Code": "x"}


def test_llm_atlascloud_binding_uses_default_openai_compatible_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "Atlas Cloud",
            "binding": "atlascloud",
            "base_url": "",
            "api_key": "atlas-key",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "llm-m",
                    "name": "Qwen 3.5 Flash",
                    "model": "qwen/qwen3.5-flash",
                }
            ],
        }
    )

    resolved = resolve_llm_runtime_config(catalog=catalog)

    assert resolved.provider_name == "atlascloud"
    assert resolved.provider_mode == "gateway"
    assert resolved.binding == "atlascloud"
    assert resolved.model == "qwen/qwen3.5-flash"
    assert resolved.api_key == "atlas-key"
    assert resolved.effective_url == "https://api.atlascloud.ai/v1"


def test_llm_atlascloud_base_url_detection_preserves_openai_binding_compatibility() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "OpenAI Compatible",
            "binding": "openai",
            "base_url": "https://api.atlascloud.ai/v1",
            "api_key": "atlas-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "Qwen", "model": "qwen/qwen3.5-flash"}],
        }
    )

    resolved = resolve_llm_runtime_config(catalog=catalog)

    assert resolved.provider_name == "atlascloud"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://api.atlascloud.ai/v1"


def test_llm_edenai_binding_uses_default_openai_compatible_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "Eden AI",
            "binding": "edenai",
            "base_url": "",
            "api_key": "eden-key",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "llm-m",
                    "name": "Mistral Large",
                    "model": "mistral/mistral-large-latest",
                }
            ],
        }
    )

    resolved = resolve_llm_runtime_config(catalog=catalog)

    assert resolved.provider_name == "edenai"
    assert resolved.provider_mode == "gateway"
    assert resolved.binding == "edenai"
    assert resolved.model == "mistral/mistral-large-latest"
    assert resolved.api_key == "eden-key"
    assert resolved.effective_url == "https://api.edenai.run/v3"


def test_llm_edenai_base_url_detection_preserves_openai_binding_compatibility() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "OpenAI Compatible",
            "binding": "openai",
            "base_url": "https://api.edenai.run/v3",
            "api_key": "eden-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "GPT", "model": "openai/gpt-5.5"}],
        }
    )

    resolved = resolve_llm_runtime_config(catalog=catalog)

    assert resolved.provider_name == "edenai"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://api.edenai.run/v3"


def test_llm_local_fallback() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "",
            "base_url": "http://localhost:11434/v1",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "llama3.2"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert resolved.api_key == "sk-no-key-required"


def test_llm_minimax_binding_uses_minimaxi_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "minimax",
            "base_url": "",
            "api_key": "minimax-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "MiniMax-M3"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "minimax"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://api.minimaxi.com/v1"


def test_llm_minimax_anthropic_binding_uses_anthropic_endpoint() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "minimax_anthropic",
            "base_url": "",
            "api_key": "minimax-key",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "c", "model": "claude-sonnet-4-20250514"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "minimax_anthropic"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://api.minimaxi.com/anthropic"


def test_llm_custom_anthropic_binding_stays_direct() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "custom_anthropic",
            "base_url": "https://claude-proxy.example/v1/messages",
            "api_key": "anthropic-key",
            "api_version": "",
            "extra_headers": {"x-tenant": "lab"},
            "models": [{"id": "llm-m", "name": "c", "model": "claude-sonnet-4-20250514"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "custom_anthropic"
    assert resolved.provider_mode == "direct"
    assert resolved.binding == "custom_anthropic"
    assert resolved.effective_url == "https://claude-proxy.example/v1/messages"
    assert resolved.extra_headers == {"x-tenant": "lab"}


def test_llm_lm_studio_alias_resolves_to_local_provider() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "lm-studio",
            "base_url": "",
            "api_key": "",
            "api_version": "",
            "extra_headers": {},
            "models": [{"id": "llm-m", "name": "m", "model": "llama-3.2"}],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.provider_name == "lm_studio"
    assert resolved.provider_mode == "local"
    assert resolved.effective_url == "http://localhost:1234/v1"
    assert resolved.api_key == "sk-no-key-required"


def test_llm_context_window_passes_through_from_catalog() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "llm-m",
                    "name": "GPT 4o mini",
                    "model": "gpt-4o-mini",
                    "context_window": 128000,
                }
            ],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.context_window == 128000


def test_llm_selection_overrides_active_model_without_mutating_catalog() -> None:
    profile_a = {
        "id": "p-a",
        "name": "OpenRouter",
        "binding": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "sk-or-test",
        "api_version": "",
        "extra_headers": {},
        "models": [
            {
                "id": "m-a",
                "name": "Gemini",
                "model": "google/gemini-3-flash-preview",
            }
        ],
    }
    profile_b = {
        "id": "p-b",
        "name": "Local",
        "binding": "ollama",
        "base_url": "http://localhost:11434/v1",
        "api_key": "",
        "api_version": "",
        "extra_headers": {},
        "models": [{"id": "m-b", "name": "Llama", "model": "llama3.2"}],
    }
    catalog = _build_catalog(llm_profile=profile_a, llm_model=profile_a["models"][0])
    catalog["services"]["llm"]["profiles"].append(profile_b)

    resolved = resolve_llm_runtime_config(
        catalog=catalog,
        llm_selection={"profile_id": "p-b", "model_id": "m-b"},
    )

    assert resolved.model == "llama3.2"
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert catalog["services"]["llm"]["active_profile_id"] == "p-a"
    assert catalog["services"]["llm"]["active_model_id"] == "m-a"


def test_llm_reasoning_effort_resolves_from_catalog() -> None:
    catalog = _build_catalog(
        llm_profile={
            "id": "llm-p",
            "name": "LLM",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "api_version": "",
            "extra_headers": {},
            "models": [
                {
                    "id": "llm-m",
                    "name": "GPT 4o mini",
                    "model": "gpt-4o-mini",
                    "reasoning_effort": "high",
                }
            ],
        }
    )
    resolved = resolve_llm_runtime_config(catalog=catalog)
    assert resolved.reasoning_effort == "high"


def test_search_fallback_to_duckduckgo_without_key() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "brave",
            "base_url": "",
            "api_key": "",
            "proxy": "http://127.0.0.1:7890",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "duckduckgo"
    assert resolved.requested_provider == "brave"
    assert resolved.fallback_reason is not None
    assert resolved.proxy == "http://127.0.0.1:7890"


def test_search_none_disables_runtime_provider() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "none",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "none"
    assert resolved.requested_provider == "none"
    assert resolved.status == "ok"


def test_search_marks_deprecated_provider() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "exa",
            "base_url": "",
            "api_key": "k",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.unsupported_provider is True
    assert resolved.deprecated_provider is True
    assert resolved.provider == "exa"


def test_search_perplexity_missing_credentials() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "perplexity",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "perplexity"
    assert resolved.unsupported_provider is False
    assert resolved.deprecated_provider is False
    assert resolved.missing_credentials is True


def test_search_serper_missing_credentials() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "serper",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "serper"
    assert resolved.unsupported_provider is False
    assert resolved.deprecated_provider is False
    assert resolved.missing_credentials is True


def test_search_searxng_without_url_fallback() -> None:
    catalog = _build_catalog(
        search_profile={
            "id": "search-p",
            "name": "Search",
            "provider": "searxng",
            "base_url": "",
            "api_key": "",
            "proxy": "",
            "models": [],
        }
    )
    resolved = resolve_search_runtime_config(catalog=catalog)
    assert resolved.provider == "duckduckgo"
    assert resolved.fallback_reason is not None
