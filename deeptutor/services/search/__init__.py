"""Web Search Service with TutorBot-style provider selection."""

from __future__ import annotations

from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.services.config import (
    DEPRECATED_SEARCH_PROVIDERS,
    PROJECT_ROOT,
    SEARCH_FALLBACK_PROVIDER,
    SUPPORTED_SEARCH_PROVIDERS,
    ResolvedSearchConfig,
    load_config_with_main,
    load_system_settings,
    resolve_search_runtime_config,
    search_fallback_candidates,
    search_missing_credential,
    search_provider_credentials,
    search_provider_spec,
    supported_search_providers_hint,
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
from .source_filter import filter_web_search_response, settings_from_config
from .types import Citation, SearchResult, WebSearchResponse

_logger = logging.getLogger(__name__)


def _get_web_search_config() -> dict[str, Any]:
    try:
        config = load_config_with_main("main.yaml", PROJECT_ROOT)
        return config.get("tools", {}).get("web_search", {})
    except Exception as exc:
        _logger.debug(f"Could not load config: {exc}")
    return {}


def _get_source_filter_settings() -> dict[str, Any]:
    """Resolve the post-provider reference policy from runtime system JSON."""
    try:
        system = load_system_settings()
    except Exception as exc:
        _logger.warning("Could not load web-search source policy: %s", exc)
        system = {}
    raw = system.get("web_search_source_filtering", {})
    return settings_from_config({"source_filtering": raw})


def _save_results(result: dict[str, Any], output_dir: str, provider: str) -> str:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"search_{provider}_{timestamp}.json"
    file_path = output_path / filename
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    return str(file_path)


def _credentials_for(provider_name: str, resolved: ResolvedSearchConfig) -> tuple[str, str]:
    """Return ``(api_key, base_url)`` to run *provider_name* with.

    The resolved config already carries the active profile's credentials; any
    other provider gets its own profile's, so switching providers can't send one
    vendor's key to another.
    """
    if provider_name in {resolved.provider, resolved.requested_provider}:
        return resolved.api_key, resolved.base_url
    return search_provider_credentials(provider_name)


def _assert_provider_supported(provider_name: str) -> None:
    if provider_name == "none":
        return
    if provider_name in _DEPRECATED_UNSUPPORTED:
        raise ValueError(
            f"Search provider `{provider_name}` is deprecated/unsupported. "
            f"Please switch to {supported_search_providers_hint()}."
        )
    if provider_name not in SUPPORTED_SEARCH_PROVIDERS:
        raise ValueError(
            f"Unknown search provider `{provider_name}`. "
            f"Supported providers: {supported_search_providers_hint()}."
        )


def _disabled_result(
    query: str,
    provider: str,
    *,
    error_code: str,
    answer: str,
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(),
        "query": query,
        "answer": answer,
        "citations": [],
        "search_results": [],
        "provider": provider,
        "error_code": error_code,
    }


def _run_provider(
    provider_name: str,
    query: str,
    provider_kwargs: dict[str, Any],
) -> tuple[WebSearchResponse, bool]:
    """Run one query through *provider_name*, also reporting answer support."""
    search_provider = get_provider(provider_name, **provider_kwargs)
    _logger.info(f"[{search_provider.name}] Searching: {query[:50]}...")
    response = search_provider.search(query, **provider_kwargs)
    return response, search_provider.supports_answer


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
        return _disabled_result(
            query,
            "disabled",
            error_code="web_search_disabled",
            answer="Web search is disabled by system configuration.",
        )

    resolved = resolve_search_runtime_config()
    provider_name = (provider or resolved.provider).strip().lower()
    _assert_provider_supported(provider_name)
    if provider_name == "none":
        return _disabled_result(
            query,
            "none",
            error_code="search_provider_not_configured",
            answer=(
                "Web search is enabled but no search provider is configured. "
                "Open Settings > Search and choose a provider; DuckDuckGo works "
                "without an API key."
            ),
        )

    api_key, base_url = _credentials_for(provider_name, resolved)
    base_url = provider_kwargs.get("base_url") or base_url
    missing = search_missing_credential(provider_name, api_key, base_url)
    if missing:
        spec = search_provider_spec(provider_name)
        if spec is not None and not spec.soft_fallback:
            raise ValueError(
                f"{provider_name} requires {missing} (profile.{missing} in Settings > Catalog)."
            )
        _logger.warning(
            f"{provider_name} missing {missing}, falling back to {SEARCH_FALLBACK_PROVIDER}."
        )
        provider_name = SEARCH_FALLBACK_PROVIDER
        api_key, base_url = _credentials_for(provider_name, resolved)

    if api_key:
        provider_kwargs.setdefault("api_key", api_key)
    if base_url:
        provider_kwargs.setdefault("base_url", base_url)
    provider_kwargs.setdefault("max_results", resolved.max_results)
    if resolved.proxy and "proxy" not in provider_kwargs:
        provider_kwargs["proxy"] = resolved.proxy

    # A rate-limited or unreachable engine costs the query its first choice, not
    # the whole turn: fall through the user's other configured search profiles
    # and finally the credential-free provider, recording what was skipped.
    attempts: list[str] = [provider_name, *search_fallback_candidates(provider_name)]
    failures: list[str] = []
    response: WebSearchResponse | None = None
    supports_answer = False
    for candidate in attempts:
        candidate_kwargs = dict(provider_kwargs)
        if candidate != provider_name:
            candidate_key, candidate_base_url = _credentials_for(candidate, resolved)
            candidate_kwargs.pop("api_key", None)
            candidate_kwargs.pop("base_url", None)
            if candidate_key:
                candidate_kwargs["api_key"] = candidate_key
            if candidate_base_url:
                candidate_kwargs["base_url"] = candidate_base_url
        try:
            response, supports_answer = _run_provider(candidate, query, candidate_kwargs)
        except Exception as exc:
            _logger.error(f"[{candidate}] Search failed: {exc}")
            failures.append(f"{candidate}: {exc}")
            continue
        if candidate != provider_name:
            _logger.warning(f"Search fell back from {provider_name} to {candidate}.")
            response.metadata["search_fallback"] = {
                "requested": provider_name,
                "used": candidate,
                "failures": failures,
            }
        provider_name = candidate
        break
    if response is None:
        raise Exception("web search failed: " + "; ".join(failures))

    response = filter_web_search_response(response, **_get_source_filter_settings())
    if response.metadata.get("source_filter", {}).get("answer_invalidated"):
        # A provider-authored answer may have relied on a rejected source. Run
        # the ordinary safe-results consolidator instead of returning prose
        # whose citations no longer support it.
        supports_answer = False

    # Auto-consolidate for providers that don't generate their own answers.
    if not supports_answer:
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
        "source_filtering": _get_source_filter_settings(),
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
    "filter_web_search_response",
    "PROVIDER_TEMPLATES",
    "BaseSearchProvider",
    "SearchProvider",
    "SEARCH_API_KEY_ENV",
]
