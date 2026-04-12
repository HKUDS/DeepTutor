"""RAG pipeline factory.

This module keeps a lightweight provider registry with a single built-in
provider (`llamaindex`) while preserving the extension mechanism for future
providers via `register_pipeline`.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional
import warnings

DEFAULT_PROVIDER = "llamaindex"
LEGACY_PROVIDER_ALIASES = {
    "raganything": DEFAULT_PROVIDER,
    "raganything_docling": DEFAULT_PROVIDER,
}

# Pipeline registry - populated lazily
_PIPELINES: Dict[str, Callable] = {}
_PIPELINES_INITIALIZED = False

# Cached pipeline instances keyed by (name, kb_base_dir)
_PIPELINE_CACHE: Dict[tuple[str, Optional[str]], object] = {}


def normalize_provider_name(name: Optional[str]) -> str:
    """Normalize provider names, folding legacy providers to llamaindex."""
    candidate = (name or DEFAULT_PROVIDER).strip().lower() or DEFAULT_PROVIDER
    return LEGACY_PROVIDER_ALIASES.get(candidate, candidate)


def _init_pipelines() -> None:
    """Lazily initialize the built-in pipeline registry."""
    global _PIPELINES_INITIALIZED
    if _PIPELINES_INITIALIZED:
        return

    def _build_llamaindex(**kwargs):
        # Optional dependency: llama_index.
        from .pipelines.llamaindex import LlamaIndexPipeline

        return LlamaIndexPipeline(**kwargs)

    def _build_lightrag(**kwargs):
        from .pipelines.lightrag import LightRAGPipeline

        return LightRAGPipeline(**kwargs)

    _PIPELINES.update(
        {
            DEFAULT_PROVIDER: _build_llamaindex,
            "lightrag": _build_lightrag,
        }
    )
    _PIPELINES_INITIALIZED = True


def get_pipeline(name: str = DEFAULT_PROVIDER, kb_base_dir: Optional[str] = None, **kwargs):
    """Get a pipeline instance by name.

    Legacy provider names are normalized to `llamaindex` for backward
    compatibility with historical KB metadata/config.
    """
    _init_pipelines()
    normalized_name = normalize_provider_name(name)
    if normalized_name not in _PIPELINES:
        available = sorted(_PIPELINES.keys())
        raise ValueError(f"Unknown pipeline: {name}. Available: {available}")

    if not kwargs:
        cache_key = (normalized_name, kb_base_dir)
        if cache_key in _PIPELINE_CACHE:
            return _PIPELINE_CACHE[cache_key]

    factory = _PIPELINES[normalized_name]

    try:
        if kb_base_dir:
            kwargs["kb_base_dir"] = kb_base_dir
        instance = factory(**kwargs)

        if not kwargs or (len(kwargs) == 1 and "kb_base_dir" in kwargs):
            _PIPELINE_CACHE[(normalized_name, kb_base_dir)] = instance

        return instance
    except ImportError as e:
        raise ValueError(
            f"Pipeline '{normalized_name}' is not available because an optional dependency "
            f"is missing: {e}. Please install llama-index dependencies."
        ) from e


def list_pipelines() -> List[Dict[str, str]]:
    """List available pipelines."""
    return [
        {
            "id": DEFAULT_PROVIDER,
            "name": "LlamaIndex",
            "description": "Pure vector retrieval, fastest processing speed.",
        },
        {
            "id": "lightrag",
            "name": "LightRAG",
            "description": "Dual-layer knowledge graphs with vector retrieval. Better for complex relationships.",
        },
    ]


def register_pipeline(name: str, factory: Callable) -> None:
    """Register a custom pipeline factory."""
    _init_pipelines()
    normalized_name = name.strip().lower()
    _PIPELINES[normalized_name] = factory


def has_pipeline(name: str) -> bool:
    """Check whether a pipeline exists.

    NOTE: this checks explicit registrations only. Legacy aliases are not treated
    as valid user-selectable providers.
    """
    _init_pipelines()
    candidate = (name or "").strip().lower()
    return candidate in _PIPELINES


# Backward compatibility with old plugin API

def get_plugin(name: str) -> Dict[str, Callable]:
    """DEPRECATED: Use get_pipeline() instead."""
    warnings.warn(
        "get_plugin() is deprecated, use get_pipeline() instead",
        DeprecationWarning,
        stacklevel=2,
    )

    pipeline = get_pipeline(name)
    return {
        "initialize": pipeline.initialize,
        "search": pipeline.search,
        "delete": getattr(pipeline, "delete", lambda kb: True),
    }


def list_plugins() -> List[Dict[str, str]]:
    """DEPRECATED: Use list_pipelines() instead."""
    warnings.warn(
        "list_plugins() is deprecated, use list_pipelines() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return list_pipelines()


def has_plugin(name: str) -> bool:
    """DEPRECATED: Use has_pipeline() instead."""
    warnings.warn(
        "has_plugin() is deprecated, use has_pipeline() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    return has_pipeline(name)
