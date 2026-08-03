"""Embedding endpoint URL helpers.

Embedding adapters post to the configured URL exactly. These helpers keep the
user-visible Settings value aligned with provider-specific endpoint paths.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, quote, urlencode, urlparse

GEMINI_DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
GEMINI_EMBEDDING_API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_OPENAI_COMPAT_EMBEDDING_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/openai/embeddings"
)
GEMINI_API_HOST = "generativelanguage.googleapis.com"
SENSITIVE_ENDPOINT_QUERY_KEYS = frozenset({"access_token", "api_key", "key", "token"})


def redact_embedding_endpoint_for_display(endpoint: str | None) -> str:
    """Hide credential-like query values while retaining endpoint diagnostics."""
    url = str(endpoint or "")
    parsed = urlparse(url)
    if not parsed.query:
        return url
    query = urlencode(
        [
            (
                key,
                "[REDACTED]" if key.lower() in SENSITIVE_ENDPOINT_QUERY_KEYS else value,
            )
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return parsed._replace(query=query).geturl()


def _gemini_model_id(model: str | None) -> str:
    """Return a path-safe Gemini model id without the API ``models/`` prefix."""
    model_id = str(model or GEMINI_DEFAULT_EMBEDDING_MODEL).strip()
    if model_id.startswith("models/"):
        model_id = model_id.removeprefix("models/")
    return model_id or GEMINI_DEFAULT_EMBEDDING_MODEL


def gemini_embedding_endpoint(model: str | None) -> str:
    """Return Gemini's exact native synchronous batch embedding endpoint."""
    model_id = quote(_gemini_model_id(model), safe="")
    return f"{GEMINI_EMBEDDING_API_ROOT}/{model_id}:batchEmbedContents"


def is_gemini_embedding2_model(model: str | None) -> bool:
    """Return whether a model belongs to the Gemini Embedding 2 family."""
    return _gemini_model_id(model).lower().startswith("gemini-embedding-2")


def gemini_default_embedding_endpoint(model: str | None) -> str:
    """Return the endpoint a Gemini profile should default to for *model*.

    Only Embedding 2 defaults to the native batch endpoint. Older models stay
    on the OpenAI-compatible path they have always used: the native route sends
    a ``taskType`` and L2-normalizes the response, so moving an existing
    ``gemini-embedding-001`` profile there would change its document vectors
    and silently invalidate the index built from them. Pointing base_url at the
    native URL explicitly still opts any model in.
    """
    if is_gemini_embedding2_model(model):
        return gemini_embedding_endpoint(model)
    return GEMINI_OPENAI_COMPAT_EMBEDDING_ENDPOINT


def is_gemini_native_embedding_endpoint(endpoint: str | None) -> bool:
    """Return whether an exact URL has Gemini's native batch endpoint shape."""
    path = urlparse(str(endpoint or "")).path.rstrip("/")
    return "/models/" in path and path.endswith(":batchEmbedContents")


def _gemini_endpoint_with_model(endpoint: str, model: str) -> str:
    """Replace the model path segment while preserving a gateway prefix/query."""
    has_scheme = "://" in endpoint
    parsed = urlparse(endpoint if has_scheme else f"https://{endpoint}")
    marker = "/models/"
    if marker not in parsed.path or not parsed.path.endswith(":batchEmbedContents"):
        return endpoint
    prefix = parsed.path.rsplit(marker, 1)[0]
    model_id = quote(_gemini_model_id(model), safe="")
    path = f"{prefix}{marker}{model_id}:batchEmbedContents"
    updated = parsed._replace(path=path).geturl()
    return updated if has_scheme else updated.split("://", 1)[1]


EMBEDDING_PROVIDER_ALIASES = {
    "google": "gemini",
    "huggingface": "custom",
    "lm_studio": "vllm",
    "llama_cpp": "vllm",
    "openai_compatible": "custom",
}

EMBEDDING_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "jina": "Jina",
    "vllm": "vLLM / LM Studio",
    "siliconflow": "SiliconFlow",
    "ollama": "Ollama",
    "cohere": "Cohere",
}

EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS = {
    "openai": "https://api.openai.com/v1/embeddings",
    "gemini": gemini_embedding_endpoint(GEMINI_DEFAULT_EMBEDDING_MODEL),
    "openrouter": "https://openrouter.ai/api/v1/embeddings",
    "cohere": "https://api.cohere.com/v2/embed",
    "jina": "https://api.jina.ai/v1/embeddings",
    "ollama": "http://localhost:11434/api/embed",
    "vllm": "http://localhost:8000/v1/embeddings",
    "siliconflow": "https://api.siliconflow.cn/v1/embeddings",
    "aliyun": (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    ),
}

EMBEDDING_PROVIDERS_REQUIRING_EMBEDDINGS_PATH = {
    "openai",
    "openrouter",
    "jina",
    "vllm",
    "siliconflow",
}

# DashScope (Aliyun) serves text and multimodal embeddings from DIFFERENT native
# endpoints, and the `dashscope` SDK derives the URL from the model id. A text
# model (text-embedding-v1..v4) sent to the multimodal endpoint fails with HTTP
# 400 "url error" (issue #660). These constants + predicate are the single
# source of truth for which DashScope endpoint a given model uses, shared by the
# runtime resolver (endpoint display) and the DashScope adapter (SDK routing).
DASHSCOPE_MULTIMODAL_EMBEDDING_ENDPOINT = EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS["aliyun"]
DASHSCOPE_TEXT_EMBEDDING_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding"
)


def is_dashscope_multimodal_embedding_model(model: str | None) -> bool:
    """Whether a DashScope embedding model uses the multimodal endpoint.

    Multimodal models (``qwen3-vl-embedding``, ``multimodal-embedding-v1``) use
    the MultiModalEmbedding surface; text models (``text-embedding-v1..v4``) and
    any unrecognised id fall through to the text-embedding surface.
    """
    name = str(model or "").strip().lower()
    return "multimodal" in name or "vl-embedding" in name or name.endswith("-vl")


def dashscope_embedding_endpoint(model: str | None) -> str:
    """Return the native DashScope embedding endpoint the SDK will POST to."""
    if is_dashscope_multimodal_embedding_model(model):
        return DASHSCOPE_MULTIMODAL_EMBEDDING_ENDPOINT
    return DASHSCOPE_TEXT_EMBEDDING_ENDPOINT


def canonical_embedding_provider_name(name: str | None) -> str:
    value = str(name or "").strip().lower().replace("-", "_")
    return EMBEDDING_PROVIDER_ALIASES.get(value, value)


def _same_origin_url(url: str, path: str) -> str:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}{path}"
    return url.rstrip("/") + path


def _append_endpoint_path(url: str, parsed, suffix: str) -> str:
    """Append a path suffix without moving query parameters into the path."""
    if parsed.scheme and parsed.netloc:
        path = f"{parsed.path.rstrip('/')}{suffix}"
        appended = parsed._replace(path=path).geturl()
        return appended if "://" in url else appended.split("://", 1)[1]
    return f"{url.rstrip('/')}{suffix}"


def normalize_embedding_endpoint_for_display(
    provider: str | None,
    base_url: str | None,
    model: str | None = None,
) -> str:
    """Return the full endpoint URL that should be shown and saved in Settings."""
    provider_name = canonical_embedding_provider_name(provider)
    url = str(base_url or "").strip()
    if not url:
        if provider_name == "gemini":
            return gemini_default_embedding_endpoint(model)
        return EMBEDDING_PROVIDER_DEFAULT_ENDPOINTS.get(provider_name, "")

    trimmed = url.rstrip("/")
    if provider_name == "gemini":
        parsed = urlparse(trimmed if "://" in trimmed else f"https://{trimmed}")
        path = parsed.path.rstrip("/")
        if path.endswith("/embeddings"):
            return trimmed
        if path.endswith("/openai"):
            return _append_endpoint_path(trimmed, parsed, "/embeddings")
        if path.endswith("/v1"):
            return _append_endpoint_path(trimmed, parsed, "/embeddings")
        if path.endswith(":batchEmbedContents"):
            # The native URL embeds the model id in its path. Synchronize that
            # segment while retaining custom gateway prefixes and query params.
            if model:
                return _gemini_endpoint_with_model(trimmed, model)
            return trimmed
        if path.endswith("/v1beta/models"):
            suffix = f"/{quote(_gemini_model_id(model), safe='')}:batchEmbedContents"
            return _append_endpoint_path(trimmed, parsed, suffix)
        return url
    if provider_name in EMBEDDING_PROVIDERS_REQUIRING_EMBEDDINGS_PATH:
        if trimmed.endswith("/embeddings"):
            return trimmed
        if trimmed.endswith("/v1"):
            return f"{trimmed}/embeddings"
    if provider_name == "ollama":
        if trimmed.endswith("/api/embed"):
            return trimmed
        if trimmed.endswith("/api"):
            return f"{trimmed}/embed"
        parsed = urlparse(trimmed if "://" in trimmed else f"http://{trimmed}")
        if parsed.scheme and parsed.netloc and parsed.path in {"", "/"}:
            return _same_origin_url(trimmed, "/api/embed")
    if provider_name == "cohere":
        if trimmed.endswith("/embed"):
            return trimmed
        if trimmed.endswith("/v2"):
            return f"{trimmed}/embed"
    return url


def embedding_endpoint_validation_error(provider: str | None, base_url: str | None) -> str | None:
    """Validate that known providers use the exact endpoint path shown to users."""
    provider_name = canonical_embedding_provider_name(provider)
    url = str(base_url or "").strip()
    if not url:
        return "Embedding endpoint URL is empty."

    parsed = urlparse(url if "://" in url else f"http://{url}")
    path = parsed.path.rstrip("/")
    label = EMBEDDING_PROVIDER_LABELS.get(provider_name, provider_name or "Embedding provider")

    if provider_name == "gemini":
        is_native = is_gemini_native_embedding_endpoint(url)
        if not (path.endswith("/embeddings") or is_native):
            return (
                "Gemini embedding endpoint must end with /embeddings "
                "or use /models/{model}:batchEmbedContents."
            )
    elif provider_name in EMBEDDING_PROVIDERS_REQUIRING_EMBEDDINGS_PATH:
        if not path.endswith("/embeddings"):
            return f"{label} embedding endpoint must end with /embeddings."
    elif provider_name == "ollama":
        if path != "/api/embed":
            return "Ollama embedding endpoint must be the full /api/embed URL."
    elif provider_name == "cohere":
        if not path.endswith("/embed"):
            return "Cohere embedding endpoint must end with /embed."

    return None
