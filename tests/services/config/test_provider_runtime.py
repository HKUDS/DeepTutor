"""Tests for TutorBot-style runtime config adapter."""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.env_store import EnvStore
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


def _empty_env(tmp_path: Path) -> EnvStore:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LLM_BINDING=",
                "LLM_MODEL=",
                "LLM_API_KEY=",
                "LLM_HOST=",
                "LLM_API_VERSION=",
                "SEARCH_PROVIDER=",
                "SEARCH_API_KEY=",
                "SEARCH_BASE_URL=",
                "SEARCH_PROXY=",
                "BRAVE_API_KEY=",
                "TAVILY_API_KEY=",
                "JINA_API_KEY=",
                "SEARXNG_BASE_URL=",
                "PERPLEXITY_API_KEY=",
                "SERPER_API_KEY=",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return EnvStore(path=env_path)


def test_llm_explicit_binding_and_headers(tmp_path: Path) -> None:
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
    resolved = resolve_llm_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider_name == "dashscope"
    assert resolved.provider_mode == "standard"
    assert resolved.effective_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert resolved.extra_headers == {"APP-Code": "abc"}


def test_llm_api_key_prefix_gateway(tmp_path: Path) -> None:
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
    resolved = resolve_llm_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider_name == "openrouter"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://openrouter.ai/api/v1"


def test_llm_api_base_keyword_gateway(tmp_path: Path) -> None:
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
    resolved = resolve_llm_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider_name == "aihubmix"
    assert resolved.provider_mode == "gateway"
    assert resolved.effective_url == "https://api.aihubmix.com/v1"
    assert resolved.extra_headers == {"APP-Code": "x"}


def test_llm_local_fallback(tmp_path: Path) -> None:
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
    resolved = resolve_llm_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider_name == "ollama"
    assert resolved.provider_mode == "local"
    assert resolved.api_key == "sk-no-key-required"


def test_search_fallback_to_duckduckgo_without_key(tmp_path: Path) -> None:
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
    resolved = resolve_search_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider == "duckduckgo"
    assert resolved.requested_provider == "brave"
    assert resolved.fallback_reason is not None
    assert resolved.proxy == "http://127.0.0.1:7890"


def test_search_marks_deprecated_provider(tmp_path: Path) -> None:
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
    resolved = resolve_search_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.unsupported_provider is True
    assert resolved.deprecated_provider is True
    assert resolved.provider == "exa"


def test_search_perplexity_missing_credentials(tmp_path: Path) -> None:
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
    resolved = resolve_search_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider == "perplexity"
    assert resolved.unsupported_provider is False
    assert resolved.deprecated_provider is False
    assert resolved.missing_credentials is True


def test_search_serper_missing_credentials(tmp_path: Path) -> None:
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
    resolved = resolve_search_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider == "serper"
    assert resolved.unsupported_provider is False
    assert resolved.deprecated_provider is False
    assert resolved.missing_credentials is True


def test_search_searxng_without_url_fallback(tmp_path: Path) -> None:
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
    resolved = resolve_search_runtime_config(catalog=catalog, env_store=_empty_env(tmp_path))
    assert resolved.provider == "duckduckgo"
    assert resolved.fallback_reason is not None
