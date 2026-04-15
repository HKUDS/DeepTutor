"""Web Search Service with TutorBot-style provider selection."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from deeptutor.logging import get_logger
from deeptutor.services.config import (
    DEPRECATED_SEARCH_PROVIDERS,
    PROJECT_ROOT,
    SUPPORTED_SEARCH_PROVIDERS,
    get_env_store,
    load_config_with_main,
    resolve_search_runtime_config,
)

from .base import SEARCH_API_KEY_ENV, BaseSearchProvider
from .consolidation import PROVIDER_TEMPLATES, AnswerConsolidator
from .providers import (
    _DEPRECATED_UNSUPPORTED,
    get_available_providers,
    get_default_provider,
    get_provider,
    get_providers_info,
    list_providers,
)
from .types import Citation, SearchResult, WebSearchResponse

_logger = get_logger("Search", level="INFO")

_PROVIDER_KEY_ENV = {
    "brave": "BRAVE_API_KEY",
    "tavily": "TAVILY_API_KEY",
    "jina": "JINA_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
}


def _get_web_search_config() -> dict[str, Any]:
    try:
        config = load_config_with_main("main.yaml", PROJECT_ROOT)
        return config.get("tools", {}).get("web_search", {})
    except Exception as exc:
        _logger.debug(f"Could not load config: {exc}")
    return {}


def _save_results(result: dict[str, Any], output_dir: str, provider: str) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"search_{provider}_{timestamp}.json"
    file_path = output_path / filename
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    return str(file_path)


def _resolve_provider_key(provider_name: str, default_api_key: str) -> str:
    if default_api_key:
        return default_api_key
    env_key = _PROVIDER_KEY_ENV.get(provider_name)
    if not env_key:
        return ""
    return get_env_store().get(env_key, "").strip()


def _assert_provider_supported(provider_name: str) -> None:
    if provider_name in _DEPRECATED_UNSUPPORTED:
        raise ValueError(
            f"Search provider `{provider_name}` is deprecated/unsupported. "
            "Please switch to brave, tavily, jina, searxng, duckduckgo, perplexity, or serper."
        )
    if provider_name not in SUPPORTED_SEARCH_PROVIDERS:
        allowed = ", ".join(sorted(SUPPORTED_SEARCH_PROVIDERS))
        raise ValueError(f"Unknown search provider `{provider_name}`. Supported providers: {allowed}")


def web_search(
    query: str,
    output_dir: str | None = None,
    verbose: bool = False,
    provider: str | None = None,
    consolidation_custom_template: str | None = None,
    consolidation_llm_model: str | None = None,
    **provider_kwargs: Any,
) -> dict[str, Any]:
    """Execute web search and return DeepTutor structured response shape.

    Consolidation is automatic for providers that return raw SERP results
    (``supports_answer=False``).  Pass ``consolidation_llm_model`` to
    upgrade from template formatting to LLM synthesis.
    """
    config = _get_web_search_config()
    if not config.get("enabled", True):
        _logger.warning("Web search is disabled in config")
        return {
            "timestamp": datetime.now().isoformat(),
            "query": query,
            "answer": "Web search is disabled.",
            "citations": [],
            "search_results": [],
            "provider": "disabled",
        }

    resolved = resolve_search_runtime_config()
    provider_name = (provider or resolved.provider).strip().lower()
    _assert_provider_supported(provider_name)

    if provider_name in {"brave", "tavily", "jina"}:
        api_key = _resolve_provider_key(provider_name, resolved.api_key)
        if not api_key:
            _logger.warning(f"{provider_name} missing API key, falling back to duckduckgo.")
            provider_name = "duckduckgo"
        else:
            provider_kwargs.setdefault("api_key", api_key)
    elif provider_name in {"perplexity", "serper"}:
        api_key = _resolve_provider_key(provider_name, resolved.api_key)
        if not api_key:
            env_hint = "PERPLEXITY_API_KEY" if provider_name == "perplexity" else "SERPER_API_KEY"
            raise ValueError(f"{provider_name} requires api_key (profile.api_key or {env_hint}).")
        provider_kwargs.setdefault("api_key", api_key)
    elif provider_name == "searxng":
        base_url = provider_kwargs.get("base_url") or resolved.base_url
        if not base_url:
            _logger.warning("searxng missing base_url, falling back to duckduckgo.")
            provider_name = "duckduckgo"
        else:
            provider_kwargs.setdefault("base_url", base_url)

    provider_kwargs.setdefault("max_results", resolved.max_results)
    if resolved.proxy and "proxy" not in provider_kwargs:
        provider_kwargs["proxy"] = resolved.proxy

    search_provider = get_provider(provider_name, **provider_kwargs)
    _logger.progress(f"[{search_provider.name}] Searching: {query[:50]}...")
    try:
        response = search_provider.search(query, **provider_kwargs)
    except Exception as exc:
        _logger.error(f"[{search_provider.name}] Search failed: {exc}")
        raise Exception(f"{search_provider.name} search failed: {exc}") from exc

    # Auto-consolidate for providers that don't generate their own answers.
    if not search_provider.supports_answer:
        if consolidation_custom_template is None:
            consolidation_custom_template = config.get("consolidation_template") or None
        use_llm = bool(consolidation_llm_model)
        llm_config = {"model": consolidation_llm_model} if consolidation_llm_model else None
        consolidator = AnswerConsolidator(
            use_llm=use_llm,
            custom_template=consolidation_custom_template,
            llm_config=llm_config,
        )
        response = consolidator.consolidate(response)

    result = response.to_dict()
    if output_dir:
        output_path = _save_results(result, output_dir, provider_name)
        result["result_file"] = output_path
    if verbose:
        _logger.info(f"Query: {query}")
        answer = result.get("answer", "")
        if answer:
            _logger.info(f"Answer: {answer[:200]}..." if len(answer) > 200 else f"Answer: {answer}")
        _logger.info(f"Citations: {len(result.get('citations', []))}")
    return result


def get_current_config() -> dict[str, Any]:
    """Get effective web search configuration for UI/CLI display."""
    config = _get_web_search_config()
    resolved = resolve_search_runtime_config()
    return {
        "enabled": config.get("enabled", True),
        "provider": resolved.provider,
        "requested_provider": resolved.requested_provider,
        "provider_status": resolved.status,
        "missing_credentials": resolved.missing_credentials,
        "fallback_reason": resolved.fallback_reason,
        "base_url": resolved.base_url,
        "max_results": resolved.max_results,
        "proxy": resolved.proxy,
        "providers": get_providers_info(),
        "supported_providers": sorted(SUPPORTED_SEARCH_PROVIDERS),
        "deprecated_providers": sorted(DEPRECATED_SEARCH_PROVIDERS),
        "consolidation_template": config.get("consolidation_template") or None,
        "template_providers": list(PROVIDER_TEMPLATES.keys()),
    }


SearchProvider = BaseSearchProvider

__all__ = [
    "web_search",
    "get_current_config",
    "get_provider",
    "list_providers",
    "get_available_providers",
    "get_default_provider",
    "get_providers_info",
    "WebSearchResponse",
    "Citation",
    "SearchResult",
    "AnswerConsolidator",
    "PROVIDER_TEMPLATES",
    "BaseSearchProvider",
    "SearchProvider",
    "SEARCH_API_KEY_ENV",
]
