"""Nanobot-style normalized runtime configuration for DeepTutor."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any
from urllib.parse import urlparse

from deeptutor.services.imagegen.config import ImagegenConfig
from deeptutor.services.model_selection import LLMSelection, apply_llm_selection_to_catalog
from deeptutor.services.provider_registry import (
    NANOBOT_LLM_PROVIDERS,
    PROVIDERS,
    ProviderSpec,
    canonical_provider_name,
    find_by_model,
    find_by_name,
    find_gateway,
)
from deeptutor.services.videogen.config import VideogenConfig
from deeptutor.services.voice.config import (
    AUTH_API_KEY_HEADER,
    AUTH_BEARER,
    STT_BASE64_JSON,
    STT_MULTIPART,
    STTConfig,
    TTSConfig,
)

from .embedding_endpoint import (
    EMBEDDING_PROVIDER_ALIASES,
    EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS,
    embedding_endpoint_validation_error,
    normalize_embedding_endpoint_for_display,
)
from .loader import load_config_with_main
from .model_catalog import ModelCatalogService, get_model_catalog_service

SUPPORTED_SEARCH_PROVIDERS = {
    "brave",
    "tavily",
    "jina",
    "searxng",
    "duckduckgo",
    "perplexity",
    "serper",
    "none",
}
DEPRECATED_SEARCH_PROVIDERS = {"exa", "baidu", "openrouter"}


LLM_LOCALHOST_PROVIDERS = ("ollama", "vllm")


@dataclass(frozen=True)
class EmbeddingProviderSpec:
    """Single embedding-provider metadata entry.

    Note on `default_api_base`: as of v1.3.0 this is the **fully-qualified
    embedding endpoint URL** (e.g. ``https://api.openai.com/v1/embeddings``),
    not a base. Adapters use the configured URL verbatim — no path appending.
    """

    label: str
    default_api_base: str
    keywords: tuple[str, ...]
    is_local: bool
    adapter: str = "openai_compat"
    mode: str = "standard"
    default_model: str = ""
    default_dim: int = 0
    # Per-provider cap on items per embedding request batch. Adapters/clients
    # clamp `batch_size` against this. SiliconFlow Qwen3 family caps at 32;
    # DashScope caps at 20; most others have generous limits.
    max_batch_items: int = 256
    # Whether the active default model supports multimodal `contents` input.
    multimodal: bool = False


EMBEDDING_PROVIDERS: dict[str, EmbeddingProviderSpec] = {
    "openai": EmbeddingProviderSpec(
        label="OpenAI",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["openai"],
        keywords=("openai", "text-embedding", "ada-002", "embedding-3"),
        is_local=False,
        default_model="text-embedding-3-large",
        default_dim=3072,
    ),
    "gemini": EmbeddingProviderSpec(
        label="Gemini",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["gemini"],
        keywords=("gemini", "gemini-embedding", "text-embedding"),
        is_local=False,
        default_model="gemini-embedding-001",
        default_dim=3072,
    ),
    "azure_openai": EmbeddingProviderSpec(
        label="Azure OpenAI",
        mode="direct",
        default_api_base="",
        keywords=("azure", "aoai"),
        is_local=False,
    ),
    "cohere": EmbeddingProviderSpec(
        label="Cohere",
        adapter="cohere",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["cohere"],
        keywords=("cohere", "embed-v4", "embed-english", "embed-multilingual"),
        is_local=False,
        default_model="embed-v4.0",
        default_dim=1024,
        multimodal=True,
    ),
    "jina": EmbeddingProviderSpec(
        label="Jina",
        adapter="jina",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["jina"],
        keywords=("jina", "jina-embeddings"),
        is_local=False,
        default_model="jina-embeddings-v3",
        default_dim=1024,
    ),
    "ollama": EmbeddingProviderSpec(
        label="Ollama",
        adapter="ollama",
        mode="local",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["ollama"],
        keywords=("ollama", "nomic-embed", "mxbai", "snowflake-arctic", "all-minilm"),
        is_local=True,
        default_model="nomic-embed-text",
        default_dim=768,
    ),
    "vllm": EmbeddingProviderSpec(
        label="vLLM / LM Studio",
        mode="local",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["vllm"],
        keywords=("vllm", "lmstudio"),
        is_local=True,
    ),
    "siliconflow": EmbeddingProviderSpec(
        label="SiliconFlow",
        adapter="openai_compat",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["siliconflow"],
        keywords=(
            "siliconflow",
            "qwen3-embedding",
            "qwen3-vl-embedding",
            "bge-m3",
            "Pro/BAAI",
        ),
        is_local=False,
        default_model="Qwen/Qwen3-Embedding-8B",
        default_dim=4096,
        max_batch_items=32,
        multimodal=True,
    ),
    "aliyun": EmbeddingProviderSpec(
        label="Aliyun DashScope",
        adapter="dashscope_native",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["aliyun"],
        keywords=("dashscope", "qwen3-vl-embedding", "qwen3-embedding", "aliyun", "bailian"),
        is_local=False,
        default_model="qwen3-vl-embedding",
        default_dim=2560,
        max_batch_items=20,
        multimodal=True,
    ),
    "custom": EmbeddingProviderSpec(
        label="OpenAI Compatible",
        mode="direct",
        default_api_base="",
        keywords=(),
        is_local=False,
    ),
    # Retained for legacy configs only. Public Settings providers use exact
    # endpoint URLs and raw HTTP adapters so no request path is hidden.
    "custom_openai_sdk": EmbeddingProviderSpec(
        label="Custom (OpenAI SDK)",
        adapter="openai_sdk",
        mode="direct",
        default_api_base="",
        keywords=(),
        is_local=False,
    ),
    "openrouter": EmbeddingProviderSpec(
        label="OpenRouter",
        adapter="openai_compat",
        default_api_base=EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["openrouter"],
        keywords=("openrouter",),
        is_local=False,
    ),
}


@dataclass(frozen=True)
class VoiceProviderSpec:
    """Metadata for one TTS or STT provider entry.

    ``default_api_base`` is the provider's **API base** (e.g.
    ``https://api.openai.com/v1``); the voice adapter appends ``/audio/speech``
    or ``/audio/transcriptions``. ``adapter`` selects the HTTP adapter; the
    OpenAI-compatible cluster all share ``openai_compat`` and differ only by
    ``auth_style`` (Azure uses ``api-key``) and STT ``request_style``
    (OpenRouter uses base64-JSON).
    """

    label: str
    default_api_base: str
    adapter: str = "openai_compat"
    auth_style: str = AUTH_BEARER
    default_model: str = ""
    default_voice: str = ""  # TTS only
    request_style: str = STT_MULTIPART  # STT only
    is_local: bool = False


# Voice providers in the OpenAI-compatible cluster. A single adapter covers all
# of these; bespoke providers (DashScope native, ElevenLabs, Gemini, Deepgram)
# would register their own ``adapter`` value once implemented.
TTS_PROVIDERS: dict[str, VoiceProviderSpec] = {
    "openai": VoiceProviderSpec(
        label="OpenAI",
        default_api_base="https://api.openai.com/v1",
        default_model="gpt-4o-mini-tts",
        default_voice="alloy",
    ),
    "openrouter": VoiceProviderSpec(
        label="OpenRouter",
        default_api_base="https://openrouter.ai/api/v1",
        adapter="openrouter_tts",
        default_model="openai/gpt-4o-mini-tts",
        default_voice="alloy",
    ),
    "groq": VoiceProviderSpec(
        label="Groq",
        default_api_base="https://api.groq.com/openai/v1",
        default_model="canopylabs/orpheus-v1-english",
        default_voice="autumn",
    ),
    "siliconflow": VoiceProviderSpec(
        label="SiliconFlow",
        default_api_base="https://api.siliconflow.cn/v1",
        default_model="FunAudioLLM/CosyVoice2-0.5B",
        default_voice="FunAudioLLM/CosyVoice2-0.5B:alex",
    ),
    "azure_openai": VoiceProviderSpec(
        label="Azure OpenAI",
        default_api_base="",
        auth_style=AUTH_API_KEY_HEADER,
        default_model="tts-1",
        default_voice="alloy",
    ),
    "vllm": VoiceProviderSpec(
        label="vLLM / Local",
        default_api_base="http://localhost:8000/v1",
        default_model="",
        default_voice="",
        is_local=True,
    ),
    "custom": VoiceProviderSpec(
        label="OpenAI Compatible",
        default_api_base="",
        default_model="",
        default_voice="",
    ),
}

STT_PROVIDERS: dict[str, VoiceProviderSpec] = {
    "openai": VoiceProviderSpec(
        label="OpenAI",
        default_api_base="https://api.openai.com/v1",
        default_model="gpt-4o-mini-transcribe",
    ),
    "openrouter": VoiceProviderSpec(
        label="OpenRouter",
        default_api_base="https://openrouter.ai/api/v1",
        default_model="openai/whisper-large-v3",
        request_style=STT_BASE64_JSON,
    ),
    "groq": VoiceProviderSpec(
        label="Groq",
        default_api_base="https://api.groq.com/openai/v1",
        default_model="whisper-large-v3-turbo",
    ),
    "siliconflow": VoiceProviderSpec(
        label="SiliconFlow",
        default_api_base="https://api.siliconflow.cn/v1",
        default_model="FunAudioLLM/SenseVoiceSmall",
    ),
    "azure_openai": VoiceProviderSpec(
        label="Azure OpenAI",
        default_api_base="",
        auth_style=AUTH_API_KEY_HEADER,
        default_model="whisper-1",
    ),
    "vllm": VoiceProviderSpec(
        label="vLLM / Local",
        default_api_base="http://localhost:8000/v1",
        default_model="",
        is_local=True,
    ),
    "custom": VoiceProviderSpec(
        label="OpenAI Compatible",
        default_api_base="",
        default_model="",
    ),
}

# Provider-name aliases accepted from older/loose catalog values.
VOICE_PROVIDER_ALIASES = {
    "azure": "azure_openai",
    "aoai": "azure_openai",
    "openai_compatible": "custom",
    "lmstudio": "vllm",
}


def _canonical_voice_provider(name: str | None, table: dict[str, VoiceProviderSpec]) -> str:
    key = (name or "").strip().lower().replace("-", "_")
    key = VOICE_PROVIDER_ALIASES.get(key, key)
    return key if key in table else "custom"


@dataclass(frozen=True)
class GenerationProviderSpec:
    """Metadata for one image- or video-generation provider entry.

    ``default_api_base`` is the provider's **API base** (e.g.
    ``https://api.openai.com/v1`` or ``https://ark.cn-beijing.volces.com/api/v3``);
    the adapter appends the relative path (``images/generations`` or
    ``contents/generations/tasks``). ``adapter`` selects the HTTP adapter:
    imagegen providers share ``openai_compat``; videogen task-style providers
    use ``async_task``.
    """

    label: str
    default_api_base: str
    adapter: str = "openai_compat"
    auth_style: str = AUTH_BEARER
    default_model: str = ""
    is_local: bool = False


# Image-generation providers in the OpenAI-compatible cluster. A single adapter
# covers all of these; ``default_model`` is only a Settings prefill hint.
IMAGEGEN_PROVIDERS: dict[str, GenerationProviderSpec] = {
    "openai": GenerationProviderSpec(
        label="OpenAI",
        default_api_base="https://api.openai.com/v1",
        default_model="gpt-image-1",
    ),
    "volcengine": GenerationProviderSpec(
        label="Volcengine Ark (Seedream)",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seedream-3-0-t2i-250415",
    ),
    "siliconflow": GenerationProviderSpec(
        label="SiliconFlow",
        default_api_base="https://api.siliconflow.cn/v1",
        default_model="Kwai-Kolors/Kolors",
    ),
    # OpenRouter generates images through /chat/completions (modalities), not the
    # OpenAI Images API — so it uses the chat_completions adapter, not openai_compat.
    "openrouter": GenerationProviderSpec(
        label="OpenRouter",
        default_api_base="https://openrouter.ai/api/v1",
        adapter="chat_completions",
        default_model="google/gemini-2.5-flash-image-preview",
    ),
    "azure_openai": GenerationProviderSpec(
        label="Azure OpenAI",
        default_api_base="",
        auth_style=AUTH_API_KEY_HEADER,
        default_model="dall-e-3",
    ),
    "custom": GenerationProviderSpec(
        label="OpenAI Compatible",
        default_api_base="",
        default_model="",
    ),
    # Generic chat-completions image output (any OpenRouter-style gateway).
    "custom_chat": GenerationProviderSpec(
        label="Chat Completions (Custom)",
        default_api_base="",
        adapter="chat_completions",
        default_model="",
    ),
}

# Video-generation providers. Text-to-video has no synchronous standard; these
# all use the async-task adapter (submit → poll → download).
VIDEOGEN_PROVIDERS: dict[str, GenerationProviderSpec] = {
    "volcengine": GenerationProviderSpec(
        label="Volcengine Ark (Seedance)",
        default_api_base="https://ark.cn-beijing.volces.com/api/v3",
        adapter="async_task",
        default_model="doubao-seedance-1-0-pro-250528",
    ),
    "custom": GenerationProviderSpec(
        label="Async Task (Custom)",
        default_api_base="",
        adapter="async_task",
        default_model="",
    ),
}

# Provider-name aliases accepted from older/loose catalog values.
GENERATION_PROVIDER_ALIASES = {
    "ark": "volcengine",
    "volces": "volcengine",
    "doubao": "volcengine",
    "seedream": "volcengine",
    "seedance": "volcengine",
    "azure": "azure_openai",
    "aoai": "azure_openai",
    "openai_compatible": "custom",
}


def _canonical_generation_provider(
    name: str | None, table: dict[str, GenerationProviderSpec]
) -> str:
    key = (name or "").strip().lower().replace("-", "_")
    key = GENERATION_PROVIDER_ALIASES.get(key, key)
    return key if key in table else "custom"


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
    context_window: int | None = None


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
    dimension: int = 0
    send_dimensions: bool | None = None
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
    service: ModelCatalogService | None = None,
    llm_selection: dict[str, Any] | LLMSelection | None = None,
) -> ResolvedLLMConfig:
    """Resolve active LLM config with TutorBot-style provider matching."""
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    loaded = apply_llm_selection_to_catalog(loaded, llm_selection)

    profile, model = _active_profile_and_model(loaded, catalog_service, "llm")
    resolved_model = _as_str((model or {}).get("model"))
    if not resolved_model:
        resolved_model = "gpt-4o-mini"

    binding_hint_raw = _as_str((profile or {}).get("binding"))
    binding_hint = canonical_provider_name(binding_hint_raw)

    active_api_key = _as_str((profile or {}).get("api_key"))
    active_api_base = _as_str((profile or {}).get("base_url"))
    active_api_version = _as_str((profile or {}).get("api_version"))
    reasoning_effort = _as_str((model or {}).get("reasoning_effort")) or None
    active_extra_headers = _to_headers((profile or {}).get("extra_headers"))
    context_window = _coerce_optional_int((model or {}).get("context_window"))
    if context_window is None:
        context_window = _coerce_optional_int((model or {}).get("context_window_tokens"))

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
        context_window=context_window,
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
    if key in EMBEDDING_PROVIDERS:
        return key
    return None


def _collect_embedding_provider_pool(
    catalog: dict[str, Any],
) -> dict[str, NormalizedProviderConfig]:
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


def _resolve_embedding_dimension(value: Any, default: int = 0) -> int:
    """Parse the dimension value. Returns 0 when unknown/unparseable.

    A value of 0 means "use the provider's native default" downstream;
    test_runner auto-fills the catalog with the actual response dim on
    first successful connection test.
    """
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _coerce_optional_bool(value: Any) -> bool | None:
    """Parse a tri-state bool from catalog values.

    Returns ``True``/``False`` for explicit values and ``None`` for missing,
    empty, or unrecognised inputs (which means "use the default behaviour").
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _coerce_optional_int(value: Any) -> int | None:
    """Parse a positive int from catalog values, returning ``None`` when unset."""
    if value is None:
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _resolve_embedding_provider(
    *,
    hint: str | None,
    model: str,
    api_base: str | None,
    provider_pool: dict[str, NormalizedProviderConfig],
) -> str:
    if hint and hint in EMBEDDING_PROVIDERS:
        return hint

    model_lower = (model or "").lower()
    model_prefix = model_lower.split("/", 1)[0].replace("-", "_") if "/" in model_lower else ""
    if model_prefix in EMBEDDING_PROVIDERS:
        return model_prefix

    for provider_name, spec in EMBEDDING_PROVIDERS.items():
        if any(keyword in model_lower for keyword in spec.keywords):
            return provider_name

    if _is_local_base_url(api_base):
        if api_base and "11434" in api_base:
            return "ollama"
        return "vllm"

    for provider_name, spec in EMBEDDING_PROVIDERS.items():
        configured = provider_pool.get(provider_name)
        if not configured:
            continue
        if spec.is_local and configured.api_base:
            return provider_name
        if configured.api_key:
            return provider_name

    return "openai"


def resolve_embedding_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    service: ModelCatalogService | None = None,
) -> ResolvedEmbeddingConfig:
    """Resolve active embedding config using provider-runtime normalization."""
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile, model = _active_profile_and_model(loaded, catalog_service, "embedding")
    resolved_model = _as_str((model or {}).get("model"))
    if not resolved_model:
        raise ValueError(
            "No active embedding model is configured. Please set it in Settings > Catalog."
        )

    binding_hint_raw = _as_str((profile or {}).get("binding"))
    binding_hint = _canonical_embedding_provider_name(binding_hint_raw)

    active_api_key = _as_str((profile or {}).get("api_key"))
    active_api_base = _as_str((profile or {}).get("base_url"))
    active_api_version = _as_str((profile or {}).get("api_version"))
    active_extra_headers = _to_headers((profile or {}).get("extra_headers"))
    # Default 0 means "not yet known" — the test_runner auto-fills on first
    # successful connection. Adapters/clients should treat 0 as "let the
    # provider use its native default". 3072 used to be hard-coded here, which
    # forced every non-OpenAI provider to fail dim validation on first use.
    dimension = _resolve_embedding_dimension((model or {}).get("dimension") or 0, default=0)
    # ``None`` means "fall back to adapter heuristic".
    send_dimensions = _coerce_optional_bool((model or {}).get("send_dimensions"))

    provider_pool = _collect_embedding_provider_pool(loaded)
    provider_name = _resolve_embedding_provider(
        hint=binding_hint,
        model=resolved_model,
        api_base=active_api_base or None,
        provider_pool=provider_pool,
    )
    spec = EMBEDDING_PROVIDERS[provider_name]
    mapped = provider_pool.get(provider_name)

    api_key = active_api_key or (mapped.api_key if mapped else "")
    api_base = active_api_base or ((mapped.api_base or "") if mapped else "")
    if not api_base and spec.default_api_base:
        api_base = spec.default_api_base
    api_version = active_api_version or ((mapped.api_version or "") if mapped else "")
    extra_headers = active_extra_headers or ((mapped.extra_headers or {}) if mapped else {})

    return ResolvedEmbeddingConfig(
        model=resolved_model,
        provider_name=provider_name,
        provider_mode=spec.mode,
        binding_hint=binding_hint,
        binding=provider_name,
        api_key=api_key,
        base_url=api_base or None,
        effective_url=api_base or None,
        api_version=api_version or None,
        extra_headers=extra_headers,
        dimension=dimension,
        send_dimensions=send_dimensions,
        request_timeout=60,
        batch_size=10,
        batch_delay=0.0,
    )


def _coerce_optional_float(value: Any) -> float | None:
    """Parse a positive float from catalog values, returning ``None`` when unset."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def resolve_tts_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    service: ModelCatalogService | None = None,
) -> TTSConfig:
    """Resolve the active text-to-speech config from the model catalog."""
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile, model = _active_profile_and_model(loaded, catalog_service, "tts")
    resolved_model = _as_str((model or {}).get("model"))
    if not resolved_model:
        raise ValueError("No active TTS model is configured. Set it in Settings > Voice.")

    provider = _canonical_voice_provider(_as_str((profile or {}).get("binding")), TTS_PROVIDERS)
    spec = TTS_PROVIDERS[provider]
    api_base = _as_str((profile or {}).get("base_url")) or spec.default_api_base
    api_key = _as_str((profile or {}).get("api_key"))
    if not api_key and spec.is_local:
        api_key = "sk-no-key-required"
    voice = _as_str((model or {}).get("voice")) or spec.default_voice
    response_format = _as_str((model or {}).get("response_format")) or "mp3"

    return TTSConfig(
        model=resolved_model,
        provider_name=provider,
        adapter=spec.adapter,
        auth_style=spec.auth_style,
        api_key=api_key,
        base_url=api_base,
        api_version=_as_str((profile or {}).get("api_version")) or None,
        extra_headers=_to_headers((profile or {}).get("extra_headers")),
        voice=voice,
        response_format=response_format,
        speed=_coerce_optional_float((model or {}).get("speed")),
    )


def resolve_stt_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    service: ModelCatalogService | None = None,
) -> STTConfig:
    """Resolve the active speech-to-text config from the model catalog."""
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile, model = _active_profile_and_model(loaded, catalog_service, "stt")
    resolved_model = _as_str((model or {}).get("model"))
    if not resolved_model:
        raise ValueError("No active STT model is configured. Set it in Settings > Voice.")

    provider = _canonical_voice_provider(_as_str((profile or {}).get("binding")), STT_PROVIDERS)
    spec = STT_PROVIDERS[provider]
    api_base = _as_str((profile or {}).get("base_url")) or spec.default_api_base
    api_key = _as_str((profile or {}).get("api_key"))
    if not api_key and spec.is_local:
        api_key = "sk-no-key-required"

    return STTConfig(
        model=resolved_model,
        provider_name=provider,
        adapter=spec.adapter,
        request_style=spec.request_style,
        auth_style=spec.auth_style,
        api_key=api_key,
        base_url=api_base,
        api_version=_as_str((profile or {}).get("api_version")) or None,
        extra_headers=_to_headers((profile or {}).get("extra_headers")),
        language=_as_str((model or {}).get("language")) or None,
    )


def resolve_imagegen_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    service: ModelCatalogService | None = None,
) -> ImagegenConfig:
    """Resolve the active text-to-image config from the model catalog."""
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile, model = _active_profile_and_model(loaded, catalog_service, "imagegen")
    resolved_model = _as_str((model or {}).get("model"))
    if not resolved_model:
        raise ValueError(
            "No active image-generation model is configured. "
            "Set it in Settings > Media Generation > Image Generation."
        )

    provider = _canonical_generation_provider(
        _as_str((profile or {}).get("binding")), IMAGEGEN_PROVIDERS
    )
    spec = IMAGEGEN_PROVIDERS[provider]
    api_base = _as_str((profile or {}).get("base_url")) or spec.default_api_base
    api_key = _as_str((profile or {}).get("api_key"))
    if not api_key and spec.is_local:
        api_key = "sk-no-key-required"

    return ImagegenConfig(
        model=resolved_model,
        provider_name=provider,
        adapter=spec.adapter,
        auth_style=spec.auth_style,
        api_key=api_key,
        base_url=api_base,
        api_version=_as_str((profile or {}).get("api_version")) or None,
        extra_headers=_to_headers((profile or {}).get("extra_headers")),
        size=_as_str((model or {}).get("size")),
        quality=_as_str((model or {}).get("quality")),
        style=_as_str((model or {}).get("style")),
        response_format=_as_str((model or {}).get("response_format")),
    )


def resolve_videogen_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    service: ModelCatalogService | None = None,
) -> VideogenConfig:
    """Resolve the active text-to-video config from the model catalog."""
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile, model = _active_profile_and_model(loaded, catalog_service, "videogen")
    resolved_model = _as_str((model or {}).get("model"))
    if not resolved_model:
        raise ValueError(
            "No active video-generation model is configured. "
            "Set it in Settings > Media Generation > Video Generation."
        )

    provider = _canonical_generation_provider(
        _as_str((profile or {}).get("binding")), VIDEOGEN_PROVIDERS
    )
    spec = VIDEOGEN_PROVIDERS[provider]
    api_base = _as_str((profile or {}).get("base_url")) or spec.default_api_base
    api_key = _as_str((profile or {}).get("api_key"))
    if not api_key and spec.is_local:
        api_key = "sk-no-key-required"

    return VideogenConfig(
        model=resolved_model,
        provider_name=provider,
        adapter=spec.adapter,
        auth_style=spec.auth_style,
        api_key=api_key,
        base_url=api_base,
        api_version=_as_str((profile or {}).get("api_version")) or None,
        extra_headers=_to_headers((profile or {}).get("extra_headers")),
        aspect_ratio=_as_str((model or {}).get("aspect_ratio")),
        duration=_as_str((model or {}).get("duration")),
        resolution=_as_str((model or {}).get("resolution")),
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


def resolve_search_runtime_config(
    catalog: dict[str, Any] | None = None,
    *,
    service: ModelCatalogService | None = None,
) -> ResolvedSearchConfig:
    """Resolve active web-search config with TutorBot-style fallback behavior."""
    catalog_service = service or get_model_catalog_service()
    loaded = _load_catalog(catalog)
    profile = catalog_service.get_active_profile(loaded, "search") or {}

    requested_provider = (_as_str(profile.get("provider")) or "duckduckgo").lower()
    provider = requested_provider
    api_key = _as_str(profile.get("api_key"))
    base_url = _as_str(profile.get("base_url"))
    proxy = _as_str(profile.get("proxy")) or None
    max_results = _resolve_search_max_results(loaded)

    deprecated = provider in DEPRECATED_SEARCH_PROVIDERS
    unsupported = provider not in SUPPORTED_SEARCH_PROVIDERS
    fallback_reason: str | None = None
    missing_credentials = False

    if provider == "none":
        return ResolvedSearchConfig(
            provider="none",
            requested_provider="none",
            api_key="",
            base_url="",
            max_results=max_results,
            proxy=proxy,
        )

    if provider in {"perplexity", "serper"} and not api_key:
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
    "EmbeddingProviderSpec",
    "EMBEDDING_PROVIDERS",
    "VoiceProviderSpec",
    "TTS_PROVIDERS",
    "STT_PROVIDERS",
    "resolve_tts_runtime_config",
    "resolve_stt_runtime_config",
    "GenerationProviderSpec",
    "IMAGEGEN_PROVIDERS",
    "VIDEOGEN_PROVIDERS",
    "resolve_imagegen_runtime_config",
    "resolve_videogen_runtime_config",
    "EMBEDDING_PROVIDER_ALIASES",
    "embedding_endpoint_validation_error",
    "normalize_embedding_endpoint_for_display",
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
