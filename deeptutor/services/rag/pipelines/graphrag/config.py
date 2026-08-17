"""Bridge DeepTutor's runtime config into a GraphRAG ``settings.yaml``.

GraphRAG (microsoft/graphrag, 3.x) is a config-file-driven engine: it reads a
``settings.[yaml|json]`` from a project root and wires its own LiteLLM-backed
model clients from it. Rather than hand-build the deeply nested
``GraphRagConfig`` pydantic model, we generate a minimal ``settings.yaml`` from
DeepTutor's already-resolved LLM + embedding runtime config and let
``graphrag.config.load_config`` validate it.

Decoupling notes:
* The only knobs we set are the two model entries + storage layout. Everything
  else (chunking, graph extraction, community reports, the four search configs)
  defaults correctly because each model entry is named with GraphRAG's default
  model id, so the workflow/search sections pick it up automatically.
* Built-in prompts are used (every ``prompt`` field defaults to ``None`` in
  GraphRAG), so we never scaffold prompt files.
* Completion calls use DeepTutor's registered GraphRAG compatibility adapter,
  while embeddings retain GraphRAG's stock LiteLLM path.

This is the single spot to touch if GraphRAG's config schema shifts between
releases; pin the dependency to the 3.x line (see ``pyproject`` extra).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from deeptutor.services.config.embedding_endpoint import canonical_embedding_provider_name
from deeptutor.services.embedding.request_options import should_send_embedding_dimensions

from .errors import GraphRagEmbeddingProviderUnsupportedError
from .provider import (
    COMPLETION_TYPE,
    resolve_completion_call_args,
    resolve_completion_model,
    resolve_completion_provider,
)

logger = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.yaml"

# GraphRAG's default model ids — naming our entries this way means every
# workflow/search section resolves to them without us spelling each one out.
COMPLETION_MODEL_ID = "default_completion_model"
EMBEDDING_MODEL_ID = "default_embedding_model"

# The four retrieval methods GraphRAG ships. ``local`` is the safest general
# default (entity-centric, cheaper than global map-reduce).
SUPPORTED_MODES = ("local", "global", "drift", "basic")
DEFAULT_MODE = "local"

# GraphRAG's stock LiteLLM embedding client uses an OpenAI-style transport and
# appends the ``/embeddings`` operation path to ``api_base``. DeepTutor stores a
# complete operation URL for these bindings, so only this explicitly compatible
# set can be translated safely. Native Cohere, Ollama, DashScope, and Azure
# transports require separate provider adapters and must not be guessed here.
OPENAI_COMPATIBLE_EMBEDDING_BINDINGS = frozenset(
    {
        "custom",
        "custom_openai_sdk",
        "gemini",
        "jina",
        "openai",
        "openrouter",
        "orcarouter",
        "siliconflow",
        "vllm",
    }
)


class GraphRagNotAvailableError(RuntimeError):
    """Raised when the optional ``graphrag`` dependency is not installed."""


class GraphRagNotConfiguredError(RuntimeError):
    """Raised when DeepTutor's LLM / embedding config can't back GraphRAG."""


def is_graphrag_available() -> bool:
    """True when the optional ``graphrag`` package can be imported.

    GraphRAG is heavy (LiteLLM, lancedb, graspologic, …) and ships as an opt-in
    extra: ``pip install 'deeptutor[graphrag]'``. Until it is installed the
    provider is hidden / blocked in the UI.
    """
    import importlib.util

    return importlib.util.find_spec("graphrag") is not None


def normalize_mode(mode: str | None) -> str:
    """Coerce a stored ``search_mode`` to a valid GraphRAG search method.

    The per-KB ``search_mode`` field is shared across engines and defaults to
    ``"hybrid"`` (a LlamaIndex/LightRAG term). Anything that isn't a GraphRAG
    method falls back to :data:`DEFAULT_MODE`.
    """
    candidate = (mode or "").strip().lower()
    return candidate if candidate in SUPPORTED_MODES else DEFAULT_MODE


def graphrag_embedding_api_base(binding: str | None, endpoint: str | None) -> str:
    """Translate a DeepTutor embedding endpoint into GraphRAG ``api_base``.

    DeepTutor's public embedding contract stores and calls the complete
    operation URL. GraphRAG's LiteLLM client expects the API root and appends
    ``/embeddings`` itself. Strip exactly one terminal path segment only for
    known OpenAI-compatible transports. Query-bearing URLs are left untouched
    because the OpenAI SDK does not preserve operation semantics reliably when
    query parameters are embedded in ``base_url``.

    Args:
        binding: Active DeepTutor embedding binding.
        endpoint: Fully qualified endpoint saved in the model catalog.

    Returns:
        The API base GraphRAG should pass to LiteLLM.
    """
    value = str(endpoint or "").strip()
    provider = canonical_embedding_provider_name(binding)
    if not value or provider not in OPENAI_COMPATIBLE_EMBEDDING_BINDINGS:
        return value

    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return value
    if parsed.query or parsed.fragment:
        return value

    path = parsed.path.rstrip("/")
    if not path.endswith("/embeddings"):
        return value

    api_path = path[: -len("/embeddings")] or "/"
    return urlunsplit(parsed._replace(path=api_path))


def ensure_graphrag_embedding_transport(
    binding: str | None,
    endpoint: str | None,
) -> None:
    """Reject native embedding transports that GraphRAG cannot call safely."""
    provider = canonical_embedding_provider_name(binding)
    if provider not in OPENAI_COMPATIBLE_EMBEDDING_BINDINGS:
        raise GraphRagEmbeddingProviderUnsupportedError()
    # Gemini can use either DeepTutor's native ``batchEmbedContents`` adapter
    # or its legacy OpenAI-compatible endpoint. GraphRAG only supports the
    # latter; a provider name alone is no longer enough after Gemini 2 support.
    if provider == "gemini" and not urlsplit(str(endpoint or "")).path.rstrip("/").endswith(
        "/embeddings"
    ):
        raise GraphRagEmbeddingProviderUnsupportedError()


@dataclass(frozen=True)
class GraphRagQueryConfig:
    """Query-time knobs read from the persisted ``graphrag.json`` slice."""

    response_type: str = "Multiple Paragraphs"
    community_level: int = 2
    dynamic_community_selection: bool = False


def query_config_from_settings() -> GraphRagQueryConfig:
    """Load GraphRAG query knobs from runtime settings (defaults on any error)."""
    try:
        from deeptutor.services.config import load_graphrag_settings

        settings = load_graphrag_settings()
        return GraphRagQueryConfig(
            response_type=str(settings.get("response_type") or "Multiple Paragraphs"),
            community_level=int(settings.get("community_level", 2)),
            dynamic_community_selection=bool(settings.get("dynamic_community_selection", False)),
        )
    except Exception:
        return GraphRagQueryConfig()


def _embedding_model_entry(
    *,
    model: str,
    api_base: str | None,
    api_key: str | None,
    binding: str | None,
    dimension: int,
    send_dimensions: bool | None,
    extra_headers: dict[str, str] | None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "model_provider": "openai",
        "model": model,
        "auth_method": "api_key",
    }
    if api_base:
        entry["api_base"] = api_base
    # GraphRAG validates that a key is present for ``auth_method: api_key``; local
    # OpenAI-compatible servers accept a placeholder.
    entry["api_key"] = api_key or "sk-no-key-required"
    call_args: dict[str, Any] = {}
    if isinstance(extra_headers, dict) and extra_headers:
        call_args["extra_headers"] = dict(extra_headers)
    if should_send_embedding_dimensions(
        binding=binding,
        model=model,
        dimension=dimension,
        send_dimensions=send_dimensions,
    ):
        call_args["dimensions"] = dimension
    if call_args:
        entry["call_args"] = call_args
    return entry


def _completion_model_entry(llm_cfg: Any, *, api_base: str | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "type": COMPLETION_TYPE,
        "model_provider": resolve_completion_provider(llm_cfg),
        "model": resolve_completion_model(llm_cfg),
        "auth_method": "api_key",
        "api_key": getattr(llm_cfg, "api_key", None) or "sk-no-key-required",
    }
    if api_base:
        entry["api_base"] = api_base
    api_version = getattr(llm_cfg, "api_version", None)
    if api_version:
        entry["api_version"] = api_version
    call_args = resolve_completion_call_args(llm_cfg)
    if call_args:
        entry["call_args"] = call_args
    return entry


def build_settings(*, llm_cfg: Any = None, embedding_cfg: Any = None) -> dict[str, Any]:
    """Assemble the GraphRAG ``settings.yaml`` payload from DeepTutor config.

    ``llm_cfg`` / ``embedding_cfg`` are injectable for tests; in production they
    are resolved from DeepTutor's catalog. Raises
    :class:`GraphRagNotConfiguredError` if either side has no usable model.
    """
    if llm_cfg is None:
        from deeptutor.services.config import resolve_llm_runtime_config

        llm_cfg = resolve_llm_runtime_config()
    if embedding_cfg is None:
        from deeptutor.services.embedding import get_embedding_config

        embedding_cfg = get_embedding_config()

    chat_model = getattr(llm_cfg, "model", None)
    embed_model = getattr(embedding_cfg, "model", None)
    embed_dim = int(getattr(embedding_cfg, "dim", 0) or 0)
    if not chat_model:
        raise GraphRagNotConfiguredError(
            "No active chat model. Configure one under Settings → Catalog before "
            "creating a GraphRAG knowledge base."
        )
    if not embed_model:
        raise GraphRagNotConfiguredError(
            "No active embedding model. Configure one under Settings → Catalog "
            "before creating a GraphRAG knowledge base."
        )
    if not embed_dim:
        raise GraphRagNotConfiguredError(
            "No active embedding model with a known dimension. Configure one under "
            "Settings → Catalog before creating a GraphRAG knowledge base."
        )

    embedding_binding = str(getattr(embedding_cfg, "binding", "") or "")
    llm_base = getattr(llm_cfg, "effective_url", None) or getattr(llm_cfg, "base_url", None)
    embed_endpoint = getattr(embedding_cfg, "effective_url", None) or getattr(
        embedding_cfg, "base_url", None
    )
    ensure_graphrag_embedding_transport(embedding_binding, embed_endpoint)
    embed_base = graphrag_embedding_api_base(embedding_binding, embed_endpoint)

    return {
        "completion_models": {
            COMPLETION_MODEL_ID: _completion_model_entry(llm_cfg, api_base=llm_base),
        },
        "embedding_models": {
            EMBEDDING_MODEL_ID: _embedding_model_entry(
                model=embed_model,
                api_base=embed_base,
                api_key=getattr(embedding_cfg, "api_key", None),
                binding=embedding_binding,
                dimension=embed_dim,
                send_dimensions=getattr(embedding_cfg, "send_dimensions", None),
                extra_headers=getattr(embedding_cfg, "extra_headers", None),
            ),
        },
        # Plain-text input: DeepTutor's ingestion writes parsed ``.txt`` files
        # into ``input/`` (see ``ingestion.py``) so GraphRAG never parses
        # documents itself. The ``$`` is escaped as ``$$`` because GraphRAG's
        # loader treats the whole config text as a ``string.Template`` and does
        # env-var substitution on it before parsing the YAML; a bare ``$`` is
        # an "Invalid placeholder" to that pass.
        "input": {"type": "text", "file_pattern": r".*\.txt$$"},
        "input_storage": {"type": "file", "base_dir": "input"},
        "output_storage": {"type": "file", "base_dir": "output"},
        # "json" is GraphRAG's on-disk cache backend id (registered in
        # graphrag_cache.CacheFactory); "file" is a *storage* type, not a cache
        # type, and is rejected the first time the pipeline builds a cache.
        "cache": {"type": "json", "storage": {"type": "file", "base_dir": "cache"}},
        "reporting": {"type": "file", "base_dir": "logs"},
        # GraphRAG/LanceDB defaults to 3072 dimensions; DeepTutor must stamp the
        # active embedding dimension so Qwen-4096 and other non-default models work.
        "vector_store": {
            "type": "lancedb",
            "db_uri": "output/lancedb",
            "vector_size": embed_dim,
        },
    }


def write_settings_payload(root_dir: Path, settings: dict[str, Any]) -> Path:
    """Write a previously-built settings snapshot into ``root_dir``."""
    import yaml

    root_dir = Path(root_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / SETTINGS_FILENAME
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(settings, handle, sort_keys=False, allow_unicode=True)
    return path


def write_settings(root_dir: Path, *, llm_cfg: Any = None, embedding_cfg: Any = None) -> Path:
    """Build and write ``settings.yaml`` into ``root_dir``."""
    settings = build_settings(llm_cfg=llm_cfg, embedding_cfg=embedding_cfg)
    return write_settings_payload(root_dir, settings)


__all__ = [
    "SETTINGS_FILENAME",
    "COMPLETION_MODEL_ID",
    "EMBEDDING_MODEL_ID",
    "SUPPORTED_MODES",
    "DEFAULT_MODE",
    "OPENAI_COMPATIBLE_EMBEDDING_BINDINGS",
    "GraphRagNotAvailableError",
    "GraphRagNotConfiguredError",
    "GraphRagQueryConfig",
    "ensure_graphrag_embedding_transport",
    "graphrag_embedding_api_base",
    "is_graphrag_available",
    "normalize_mode",
    "query_config_from_settings",
    "build_settings",
    "write_settings",
    "write_settings_payload",
]
