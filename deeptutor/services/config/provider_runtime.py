"""Nanobot-style normalized runtime configuration for DeepTutor."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
from urllib.parse import urlparse

from deeptutor.services.provider_registry import (
    NANOBOT_LLM_PROVIDERS,
    PROVIDERS,
    ProviderSpec,
    canonical_provider_name,
    find_by_model,
    find_by_name,
    find_gateway,
)

from .env_store import EnvStore, get_env_store
from .loader import load_config_with_main
from .model_catalog import ModelCatalogService, get_model_catalog_service

SUPPORTED_SEARCH_PROVIDERS = {"brave", "tavily", "jina", "searxng", "duckduckgo", "perplexity"}
DEPRECATED_SEARCH_PROVIDERS = {"exa", "serper", "baidu", "openrouter"}

SEARCH_ENV_FALLBACK = {
    "brave": ("BRAVE_API_KEY",),
    "tavily": ("TAVILY_API_KEY",),
    "jina": ("JINA_API_KEY",),
    "perplexity": ("PERPLEXITY_API_KEY",),
}

LLM_LOCALHOST_PROVIDERS = ("ollama", "vllm")

EMBEDDING_PROVIDER_ALIASES = {
    "google": "openai",
    "gemini": "openai",
    "huggingface": "custom",
    "lm_studio": "vllm",
    "llama_cpp": "vllm",
    "openai_compatible": "custom",
}

EMBEDDING_PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "custom": {
        "mode": "direct",
        "default_api_base": "",
        "keywords": (),
        "is_local": False,
        "api_key_envs": ("OPENAI_API_KEY",),
    },
    "openai": {
        "mode": "standard",
        "default_api_base": "https://api.openai.com/v1",
        "keywords": ("openai", "text-embedding", "ada-002", "embedding-3"),
        "is_local": False,
        "api_key_envs": ("OPENAI_API_KEY",),
    },
    "azure_openai": {
        "mode": "direct",
        "default_api_base": "",
        "keywords": ("azure", "aoai"),
        "is_local": False,
        "api_key_envs": ("AZURE_OPENAI_API_KEY", "AZURE_API_KEY"),
    },
    "cohere": {
        "mode": "standard",
        "default_api_base": "https://api.cohere.ai",
        "keywords": ("cohere", "embed-v4", "embed-english", "embed-multilingual"),
        "is_local": False,
        "api_key_envs": ("COHERE_API_KEY",),
    },
    "jina": {
        "mode": "standard",
        "default_api_base": "https://api.jina.ai/v1",
        "keywords": ("jina", "jina-embeddings"),
        "is_local": False,
        "api_key_envs": ("JINA_API_KEY",),
    },
    "ollama": {
        "mode": "local",
        "default_api_base": "http://localhost:11434",
        "keywords": ("ollama", "nomic-embed", "mxbai", "snowflake-arctic", "all-minilm"),
        "is_local": True,
        "api_key_envs": (),
    },
    "vllm": {
        "mode": "local",
        "default_api_base": "http://localhost:8000/v1",
        "keywords": ("vllm", "lmstudio"),
        "is_local": True,
        "api_key_envs": ("HOSTED_VLLM_API_KEY",),
    },
}


@dataclass(slots=True)
class NormalizedProviderConfig:
    """Normalized provider configuration input."""

    name: str
    api_key: str = ""
    api_base: str | None = None
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None


@dataclass(slots=True)
class ResolvedLLMConfig:
    """Resolved runtime LLM config used by get_llm_config/factory."""

    model: str
    provider_name: str
    provider_mode: str
    binding_hint: str | None = None
    binding: str = "openai"
    api_key: str = ""
    base_url: str | None = None
    effective_url: str | None = None
    api_version: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    reasoning_effort: str | None = None


@dataclass(slots=True)
class ResolvedEmbeddingConfig:
    """Resolved runtime embedding config."""

    model: str
    provider_name: str
    provider_mode: str
    binding_hint: str | None = None
    binding: str = "openai"
    api_key: str = ""
    base_url: str | None = None
    effective_url: str | None = None
    api_version: str | None = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    dimension: int = 3072
    request_timeout: int = 60
    batch_size: int = 10
    batch_delay: float = 0.0


@dataclass(slots=True)
class ResolvedSearchConfig:
    """Resolved runtime web-search config."""

    provider: str
    requested_provider: str
    api_key: str = ""
    base_url: str = ""
    max_results: int = 5
    proxy: str | None = None
    unsupported_provider: bool = False
    deprecated_provider: bool = False
    missing_credentials: bool = False
    fallback_reason: str | None = None

    @property
    def status(self) -> str:
        if self.unsupported_provider:
            return "unsupported"
        if self.deprecated_provider:
            return "deprecated"
        if self.missing_credentials:
            return "missing_credentials"
        if self.fallback_reason:
            return "fallback"
        return "ok"


def _as_str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _to_headers(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items() if str(k).strip() and v is not None}
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items() if str(k).strip() and v is not None}
    return {}


def _is_local_base_url(base_url: str | None) -> bool:
    if not base_url:
        return False
    try:
        parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")


def _load_catalog(catalog: dict[str, Any] | None) -> dict[str, Any]:
    if catalog is not None:
        return catalog
    return get_model_catalog_service().load()


def _active_profile_and_model(
    catalog: dict[str, Any],
    service: ModelCatalogService,
    service_name: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    profile = service.get_active_profile(catalog, service_name)
    model = service.get_active_model(catalog, service_name)
    return profile, model


def _collect_provider_pool(catalog: dict[str, Any]) -> dict[str, NormalizedProviderConfig]:
    providers: dict[str, NormalizedProviderConfig] = {}
    llm_profiles = catalog.get("services", {}).get("llm", {}).get("profiles", [])
    for profile in llm_profiles:
        name = canonical_provider_name(_as_str(profile.get("binding")))
        if not name:
            continue
        providers[name] = NormalizedProviderConfig(
            name=name,
            api_key=_as_str(profile.get("api_key")),
            api_base=_as_str(profile.get("base_url")) or None,
            api_version=_as_str(profile.get("api_version")) or None,
            extra_headers=_to_headers(profile.get("extra_headers")) or None,
        )
    return providers


def _choose_resolved_provider(
    *,
    hint: str | None,
    model: str,
    api_key: str,
    api_base: str | None,
    provider_pool: dict[str, NormalizedProviderConfig],
) -> ProviderSpec:
    explicit_spec = find_by_name(hint) if hint else None
    detected_gateway = find_gateway(
        provider_name=None,
        api_key=api_key or None,
        api_base=api_base or None,
    )
    # Keep backward compatibility: old `binding=openai` should not block
    # gateway detection when key/base clearly indicates a gateway provider.
    if explicit_spec and detected_gateway and explicit_spec.name == "openai":
        return detected_gateway
    if explicit_spec:
        return explicit_spec
    if detected_gateway:
        return detected_gateway

    model_spec = find_by_model(model)
    if model_spec:
        return model_spec

    if _is_local_base_url(api_base):
        if api_base and "11434" in api_base:
            return find_by_name("ollama") or find_by_name("vllm") or find_by_name("openai")
        return find_by_name("vllm") or find_by_name("ollama") or find_by_name("openai")

    for spec in PROVIDERS:
        configured = provider_pool.get(spec.name)
        if not configured:
            continue
        if spec.is_gateway and (configured.api_key or configured.api_base):
            return spec
    for spec in PROVIDERS:
        configured = provider_pool.get(spec.name)
        if not configured:
            continue
        if spec.is_local and configured.api_base:
            return spec
        if not spec.is_oauth and configured.api_key:
            return spec

    return find_by_name("openai") or PROVIDERS[0]


def resolve_llm_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    env_store: EnvStore | None = None,
    service: ModelCatalogService | None = None,
) -> ResolvedLLMConfig:
    """Resolve active LLM config with TutorBot-style provider matching."""
    env = env_store or get_env_store()
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)

    profile, model = _active_profile_and_model(loaded, catalog_service, "llm")
    summary = env.as_summary()
    env_values = env.load()

    resolved_model = _as_str((model or {}).get("model")) or summary.llm.get("model", "").strip()
    if not resolved_model:
        resolved_model = "gpt-4o-mini"

    binding_hint_raw = _as_str((profile or {}).get("binding"))
    if not binding_hint_raw and "LLM_BINDING" in env_values:
        binding_hint_raw = _as_str(summary.llm.get("binding", ""))
    binding_hint = canonical_provider_name(binding_hint_raw)

    active_api_key = _as_str((profile or {}).get("api_key")) or summary.llm.get("api_key", "")
    active_api_base = _as_str((profile or {}).get("base_url")) or summary.llm.get("host", "")
    active_api_version = (
        _as_str((profile or {}).get("api_version")) or summary.llm.get("api_version", "")
    )
    active_extra_headers = _to_headers((profile or {}).get("extra_headers"))
    reasoning_effort = _as_str((model or {}).get("reasoning_effort")) or None

    provider_pool = _collect_provider_pool(loaded)
    spec = _choose_resolved_provider(
        hint=binding_hint,
        model=resolved_model,
        api_key=active_api_key,
        api_base=active_api_base or None,
        provider_pool=provider_pool,
    )

    mapped = provider_pool.get(spec.name)
    api_key = active_api_key or (mapped.api_key if mapped else "")
    api_base = active_api_base or ((mapped.api_base or "") if mapped else "")
    api_version = active_api_version or ((mapped.api_version or "") if mapped else "")
    if not api_base and spec.default_api_base:
        api_base = spec.default_api_base
    if not api_key and spec.is_local:
        api_key = "sk-no-key-required"
    extra_headers = active_extra_headers or ((mapped.extra_headers or {}) if mapped else {})

    return ResolvedLLMConfig(
        model=resolved_model,
        provider_name=spec.name,
        provider_mode=spec.mode,
        binding_hint=binding_hint,
        binding=spec.name,
        api_key=api_key,
        base_url=api_base or None,
        effective_url=api_base or None,
        api_version=api_version or None,
        extra_headers=extra_headers,
        reasoning_effort=reasoning_effort,
    )


def _canonical_embedding_provider_name(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().replace("-", "_")
    if not key:
        return None
    key = EMBEDDING_PROVIDER_ALIASES.get(key, key)
    key = canonical_provider_name(key) or key
    key = EMBEDDING_PROVIDER_ALIASES.get(key, key)
    if key in EMBEDDING_PROVIDER_DEFAULTS:
        return key
    return None


def _collect_embedding_provider_pool(catalog: dict[str, Any]) -> dict[str, NormalizedProviderConfig]:
    providers: dict[str, NormalizedProviderConfig] = {}
    embedding_profiles = catalog.get("services", {}).get("embedding", {}).get("profiles", [])
    for profile in embedding_profiles:
        name = _canonical_embedding_provider_name(_as_str(profile.get("binding")))
        if not name:
            continue
        providers[name] = NormalizedProviderConfig(
            name=name,
            api_key=_as_str(profile.get("api_key")),
            api_base=_as_str(profile.get("base_url")) or None,
            api_version=_as_str(profile.get("api_version")) or None,
            extra_headers=_to_headers(profile.get("extra_headers")) or None,
        )
    return providers


def _resolve_embedding_dimension(value: Any, default: int = 3072) -> int:
    try:
        parsed = int(str(value).strip())
        return max(1, parsed)
    except (TypeError, ValueError):
        return default


def _resolve_embedding_provider(
    *,
    hint: str | None,
    model: str,
    api_base: str | None,
    provider_pool: dict[str, NormalizedProviderConfig],
) -> str:
    if hint and hint in EMBEDDING_PROVIDER_DEFAULTS:
        return hint

    model_lower = (model or "").lower()
    model_prefix = model_lower.split("/", 1)[0].replace("-", "_") if "/" in model_lower else ""
    if model_prefix in EMBEDDING_PROVIDER_DEFAULTS:
        return model_prefix

    for provider_name, spec in EMBEDDING_PROVIDER_DEFAULTS.items():
        keywords = spec.get("keywords", ())
        if any(keyword in model_lower for keyword in keywords):
            return provider_name

    if _is_local_base_url(api_base):
        if api_base and "11434" in api_base:
            return "ollama"
        return "vllm"

    for provider_name, spec in EMBEDDING_PROVIDER_DEFAULTS.items():
        configured = provider_pool.get(provider_name)
        if not configured:
            continue
        if spec.get("is_local") and configured.api_base:
            return provider_name
        if configured.api_key:
            return provider_name

    return "openai"


def _embedding_provider_env_key(provider: str, env: EnvStore) -> str:
    spec = EMBEDDING_PROVIDER_DEFAULTS.get(provider, {})
    for key in spec.get("api_key_envs", ()):
        value = env.get(key, "").strip()
        if value:
            return value
    return ""


def resolve_embedding_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    env_store: EnvStore | None = None,
    service: ModelCatalogService | None = None,
) -> ResolvedEmbeddingConfig:
    """Resolve active embedding config using provider-runtime normalization."""
    env = env_store or get_env_store()
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile, model = _active_profile_and_model(loaded, catalog_service, "embedding")
    summary = env.as_summary()
    env_values = env.load()

    resolved_model = _as_str((model or {}).get("model")) or summary.embedding.get("model", "").strip()
    if not resolved_model:
        raise ValueError("No active embedding model is configured. Please set it in Settings > Catalog.")

    binding_hint_raw = _as_str((profile or {}).get("binding"))
    if not binding_hint_raw and "EMBEDDING_BINDING" in env_values:
        binding_hint_raw = _as_str(summary.embedding.get("binding", ""))
    binding_hint = _canonical_embedding_provider_name(binding_hint_raw)

    active_api_key = _as_str((profile or {}).get("api_key")) or summary.embedding.get("api_key", "")
    active_api_base = _as_str((profile or {}).get("base_url")) or summary.embedding.get("host", "")
    active_api_version = (
        _as_str((profile or {}).get("api_version")) or summary.embedding.get("api_version", "")
    )
    active_extra_headers = _to_headers((profile or {}).get("extra_headers"))
    dimension = _resolve_embedding_dimension(
        (model or {}).get("dimension") or summary.embedding.get("dimension") or 3072
    )

    provider_pool = _collect_embedding_provider_pool(loaded)
    provider_name = _resolve_embedding_provider(
        hint=binding_hint,
        model=resolved_model,
        api_base=active_api_base or None,
        provider_pool=provider_pool,
    )
    spec = EMBEDDING_PROVIDER_DEFAULTS[provider_name]
    mapped = provider_pool.get(provider_name)

    api_key = active_api_key or (mapped.api_key if mapped else "")
    if not api_key:
        api_key = _embedding_provider_env_key(provider_name, env)

    api_base = active_api_base or ((mapped.api_base or "") if mapped else "")
    if not api_base and spec.get("default_api_base"):
        api_base = str(spec["default_api_base"])
    api_version = active_api_version or ((mapped.api_version or "") if mapped else "")
    extra_headers = active_extra_headers or ((mapped.extra_headers or {}) if mapped else {})

    if spec.get("is_local") and not api_key:
        api_key = "sk-no-key-required"

    return ResolvedEmbeddingConfig(
        model=resolved_model,
        provider_name=provider_name,
        provider_mode=str(spec.get("mode") or "standard"),
        binding_hint=binding_hint,
        binding=provider_name,
        api_key=api_key,
        base_url=api_base or None,
        effective_url=api_base or None,
        api_version=api_version or None,
        extra_headers=extra_headers,
        dimension=dimension,
        request_timeout=60,
        batch_size=10,
        batch_delay=0.0,
    )


def _resolve_search_max_results(catalog: dict[str, Any], default: int = 5) -> int:
    profile = get_model_catalog_service().get_active_profile(catalog, "search") or {}
    raw = profile.get("max_results")
    if raw is not None:
        try:
            value = int(raw)
            return max(1, min(value, 10))
        except (TypeError, ValueError):
            pass
    try:
        settings = load_config_with_main("main.yaml")
    except Exception:
        return default
    tools = settings.get("tools", {}) if isinstance(settings, dict) else {}
    web_search = tools.get("web_search", {}) if isinstance(tools, dict) else {}
    if isinstance(web_search, dict):
        raw = web_search.get("max_results")
        if raw is not None:
            try:
                value = int(raw)
                return max(1, min(value, 10))
            except (TypeError, ValueError):
                pass
    web = tools.get("web", {}) if isinstance(tools, dict) else {}
    search = web.get("search", {}) if isinstance(web, dict) else {}
    raw = search.get("max_results") if isinstance(search, dict) else None
    if raw is None:
        return default
    try:
        value = int(raw)
        return max(1, min(value, 10))
    except (TypeError, ValueError):
        return default


def _provider_env_key(provider: str, env: EnvStore) -> str:
    for key in SEARCH_ENV_FALLBACK.get(provider, ()):
        value = env.get(key, "").strip()
        if value:
            return value
    return ""


def resolve_search_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    env_store: EnvStore | None = None,
    service: ModelCatalogService | None = None,
) -> ResolvedSearchConfig:
    """Resolve active web-search config with TutorBot-style fallback behavior."""
    env = env_store or get_env_store()
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile = catalog_service.get_active_profile(loaded, "search") or {}
    summary = env.as_summary().search

    requested_provider = (
        _as_str(profile.get("provider"))
        or _as_str(summary.get("provider"))
        or env.get("SEARCH_PROVIDER", "").strip()
        or "brave"
    ).lower()
    provider = requested_provider
    api_key = _as_str(profile.get("api_key")) or _as_str(summary.get("api_key"))
    base_url = _as_str(profile.get("base_url")) or _as_str(summary.get("base_url"))
    proxy = _as_str(profile.get("proxy")) or env.get("SEARCH_PROXY", "").strip() or None
    max_results = _resolve_search_max_results(loaded)

    deprecated = provider in DEPRECATED_SEARCH_PROVIDERS
    unsupported = provider not in SUPPORTED_SEARCH_PROVIDERS
    fallback_reason: str | None = None
    missing_credentials = False

    if provider == "searxng" and not base_url:
        base_url = env.get("SEARXNG_BASE_URL", "").strip()

    if provider in SEARCH_ENV_FALLBACK and not api_key:
        api_key = _provider_env_key(provider, env)

    if provider == "perplexity" and not api_key:
        missing_credentials = True

    if unsupported:
        return ResolvedSearchConfig(
            provider=provider,
            requested_provider=requested_provider,
            api_key=api_key,
            base_url=base_url,
            max_results=max_results,
            proxy=proxy,
            unsupported_provider=True,
            deprecated_provider=deprecated,
            missing_credentials=missing_credentials,
        )

    if provider in {"brave", "tavily", "jina"} and not api_key:
        fallback_reason = f"{provider} requires api_key, falling back to duckduckgo"
        provider = "duckduckgo"
    elif provider == "searxng" and not base_url:
        fallback_reason = "searxng requires base_url, falling back to duckduckgo"
        provider = "duckduckgo"

    return ResolvedSearchConfig(
        provider=provider,
        requested_provider=requested_provider,
        api_key=api_key,
        base_url=base_url,
        max_results=max_results,
        proxy=proxy,
        unsupported_provider=False,
        deprecated_provider=deprecated,
        missing_credentials=missing_credentials,
        fallback_reason=fallback_reason,
    )


def search_provider_state(provider: str | None) -> str:
    """Return provider status class for UI/CLI/system output."""
    value = (provider or "").strip().lower()
    if not value:
        return "not_configured"
    if value in DEPRECATED_SEARCH_PROVIDERS:
        return "deprecated"
    if value not in SUPPORTED_SEARCH_PROVIDERS:
        return "unsupported"
    return "supported"


__all__ = [
    "SUPPORTED_SEARCH_PROVIDERS",
    "DEPRECATED_SEARCH_PROVIDERS",
    "NANOBOT_LLM_PROVIDERS",
    "EMBEDDING_PROVIDER_DEFAULTS",
    "EMBEDDING_PROVIDER_ALIASES",
    "NormalizedProviderConfig",
    "ResolvedLLMConfig",
    "ResolvedEmbeddingConfig",
    "ResolvedSearchConfig",
    "LLM_LOCALHOST_PROVIDERS",
    "resolve_llm_runtime_config",
    "resolve_embedding_runtime_config",
    "resolve_search_runtime_config",
    "search_provider_state",
]
