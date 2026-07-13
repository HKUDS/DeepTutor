"""RAG pipeline factory.

Selects a KB's index/retrieve engine by provider name. Three pipelines ship
today:

* ``llamaindex`` (default) — local vector retrieval with hybrid BM25 fusion.
* ``pageindex``           — hosted, vectorless reasoning retrieval (needs an
                            API key configured under Knowledge → RAG settings).
* ``graphrag``            — local knowledge-graph retrieval (microsoft/graphrag);
                            optional dependency, ``pip install 'deeptutor[graphrag]'``.
* ``lightrag``            — graph + vector retrieval (HKUDS/LightRAG, multimodal
                            via RAG-Anything); optional dependency,
                            ``pip install 'deeptutor[rag-lightrag]'``.
* ``lightrag-server``     — retrieval offloaded to an external, standalone
                            LightRAG server the user runs. No local index: each
                            KB is a connection pointer queried over HTTP.

A KB is bound to one provider at creation time; later adds and retrieval always
go through that same pipeline (enforced upstream in the knowledge router).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PROVIDER = "llamaindex"
PAGEINDEX_PROVIDER = "pageindex"
GRAPHRAG_PROVIDER = "graphrag"
LIGHTRAG_PROVIDER = "lightrag"
LIGHTRAG_SERVER_PROVIDER = "lightrag-server"

# Providers the factory can instantiate. Unknown / legacy strings fall back to
# the default with a re-index hint upstream.
KNOWN_PROVIDERS = frozenset(
    {
        DEFAULT_PROVIDER,
        PAGEINDEX_PROVIDER,
        GRAPHRAG_PROVIDER,
        LIGHTRAG_PROVIDER,
        LIGHTRAG_SERVER_PROVIDER,
    }
)

# Cached pipeline instances keyed by (kb_base_dir, provider).
_PIPELINE_CACHE: Dict[Tuple[Optional[str], str], Any] = {}


def normalize_provider_name(name: Optional[str] = None) -> str:
    """Return a known provider name, falling back to the default.

    Unknown / removed provider strings collapse to the default so a stale config
    never selects a pipeline that no longer exists.
    """
    candidate = (name or "").strip().lower()
    return candidate if candidate in KNOWN_PROVIDERS else DEFAULT_PROVIDER


def provider_uses_embedding_versions(provider: Optional[str]) -> bool:
    """Whether this provider's index versions are keyed by embedding signature.

    Today only the LlamaIndex pipeline uses DeepTutor's active embedding
    signature to select/read index versions. PageIndex, GraphRAG and LightRAG
    write synthetic provider signatures (``pageindex``/``graphrag``/``lightrag``)
    and should not be marked stale merely because the active embedding profile
    changed.
    """
    return normalize_provider_name(provider) == DEFAULT_PROVIDER


def version_matches_provider(entry: dict[str, Any], provider: Optional[str]) -> bool:
    """Return True when a version-list entry belongs to ``provider``."""
    resolved = normalize_provider_name(provider)
    entry_provider = str(entry.get("provider") or "").strip().lower()
    signature = str(entry.get("signature") or "").strip().lower()

    if resolved == DEFAULT_PROVIDER:
        return entry_provider in {"", DEFAULT_PROVIDER} and signature not in {
            PAGEINDEX_PROVIDER,
            GRAPHRAG_PROVIDER,
            LIGHTRAG_PROVIDER,
            LIGHTRAG_SERVER_PROVIDER,
        }

    return entry_provider == resolved or signature == resolved


def has_ready_provider_index(kb_dir: str | Path, provider: Optional[str]) -> bool:
    """Return whether ``kb_dir`` has a ready index for ``provider``."""
    from .index_probe import has_ready_provider_index as _has_ready_provider_index

    return _has_ready_provider_index(kb_dir, provider)


def version_has_provider_output(entry: dict[str, Any], provider: Optional[str]) -> bool:
    """Return True when a version entry is ready and has real provider output."""
    from .index_probe import inspect_provider_version

    return inspect_provider_version(entry, provider).ready


def provider_failure_summary(
    kb_dir: str | Path,
    provider: Optional[str],
    *,
    limit: int = 3,
) -> str:
    """Return a short provider-specific failure summary, when available."""
    from .index_probe import provider_failure_summary as _provider_failure_summary

    return _provider_failure_summary(kb_dir, provider, limit=limit)


def _build_pipeline(provider: str, kb_base_dir: Optional[str], **kwargs: Any):
    if provider == PAGEINDEX_PROVIDER:
        from .pipelines.pageindex.pipeline import PageIndexPipeline

        if kb_base_dir is not None:
            kwargs.setdefault("kb_base_dir", kb_base_dir)
        return PageIndexPipeline(**kwargs)

    if provider == GRAPHRAG_PROVIDER:
        from .pipelines.graphrag.pipeline import GraphRagPipeline

        if kb_base_dir is not None:
            kwargs.setdefault("kb_base_dir", kb_base_dir)
        return GraphRagPipeline(**kwargs)

    if provider == LIGHTRAG_PROVIDER:
        from .pipelines.lightrag.pipeline import LightRagPipeline

        if kb_base_dir is not None:
            kwargs.setdefault("kb_base_dir", kb_base_dir)
        return LightRagPipeline(**kwargs)

    if provider == LIGHTRAG_SERVER_PROVIDER:
        from .pipelines.lightrag_server.pipeline import LightRagServerPipeline

        if kb_base_dir is not None:
            kwargs.setdefault("kb_base_dir", kb_base_dir)
        return LightRagServerPipeline(**kwargs)

    from .pipelines.llamaindex.pipeline import LlamaIndexPipeline

    if kb_base_dir is not None:
        kwargs.setdefault("kb_base_dir", kb_base_dir)
    return LlamaIndexPipeline(**kwargs)


def get_pipeline(
    name: str = DEFAULT_PROVIDER,
    kb_base_dir: Optional[str] = None,
    **kwargs: Any,
):
    """Return a pipeline instance for ``name`` (cached when no custom kwargs)."""
    provider = normalize_provider_name(name)

    if kwargs:
        # Custom kwargs (e.g. an injected client/loader): build a fresh instance
        # and skip the cache so overrides are honoured.
        return _build_pipeline(provider, kb_base_dir, **kwargs)

    cache_key = (kb_base_dir, provider)
    if cache_key not in _PIPELINE_CACHE:
        _PIPELINE_CACHE[cache_key] = _build_pipeline(provider, kb_base_dir)
    return _PIPELINE_CACHE[cache_key]


def list_pipelines() -> List[Dict[str, Any]]:
    """Describe the available pipelines for the UI provider picker."""
    try:
        from .pipelines.pageindex.config import is_pageindex_configured

        pageindex_ready = is_pageindex_configured()
    except Exception:
        pageindex_ready = False

    try:
        from .pipelines.graphrag import config as graphrag_config

        graphrag_ready = graphrag_config.is_graphrag_available()
        graphrag_modes = list(graphrag_config.SUPPORTED_MODES)
        graphrag_default_mode = graphrag_config.DEFAULT_MODE
    except Exception:
        graphrag_ready, graphrag_modes, graphrag_default_mode = False, [], ""

    try:
        from .pipelines.lightrag import config as lightrag_config

        lightrag_ready = lightrag_config.is_lightrag_available()
        lightrag_modes = list(lightrag_config.SUPPORTED_MODES)
        lightrag_default_mode = lightrag_config.DEFAULT_MODE
    except Exception:
        lightrag_ready, lightrag_modes, lightrag_default_mode = False, [], ""

    try:
        from .pipelines.lightrag_server import config as lightrag_server_config

        lightrag_server_modes = list(lightrag_server_config.SUPPORTED_MODES)
        lightrag_server_default_mode = lightrag_server_config.DEFAULT_MODE
    except Exception:
        lightrag_server_modes, lightrag_server_default_mode = [], ""

    return [
        {
            "id": DEFAULT_PROVIDER,
            "name": "LlamaIndex",
            "description": "Local vector retrieval with hybrid BM25/vector fusion. Works out of the box.",
            "configured": True,
            "requires_api_key": False,
        },
        {
            "id": PAGEINDEX_PROVIDER,
            "name": "PageIndex",
            "description": "Hosted, vectorless reasoning retrieval with page-level citations. Requires an API key; PDF/Markdown only.",
            "configured": pageindex_ready,
            "requires_api_key": True,
        },
        {
            "id": GRAPHRAG_PROVIDER,
            "name": "GraphRAG",
            "description": "Local knowledge-graph retrieval (global/local/drift/basic). Needs `pip install 'deeptutor[graphrag]'`; indexing is LLM-heavy.",
            "configured": graphrag_ready,
            "requires_api_key": False,
            "modes": graphrag_modes,
            "default_mode": graphrag_default_mode,
        },
        {
            "id": LIGHTRAG_PROVIDER,
            "name": "LightRAG",
            "description": "Graph + vector retrieval with multimodal parsing (naive/local/global/hybrid/mix). Needs `pip install 'deeptutor[rag-lightrag]'`; indexing is LLM-heavy.",
            "configured": lightrag_ready,
            "requires_api_key": False,
            "modes": lightrag_modes,
            "default_mode": lightrag_default_mode,
        },
        {
            "id": LIGHTRAG_SERVER_PROVIDER,
            "name": "LightRAG Server",
            "description": "Retrieval offloaded to an external, standalone LightRAG server you run. No local index — connect a KB to its URL and query it over HTTP (naive/local/global/hybrid/mix).",
            # Always available: it's a thin HTTP client with no install or global
            # credential. The endpoint is configured per-KB at connect time.
            "configured": True,
            "requires_api_key": False,
            "modes": lightrag_server_modes,
            "default_mode": lightrag_server_default_mode,
        },
    ]


__all__ = [
    "DEFAULT_PROVIDER",
    "PAGEINDEX_PROVIDER",
    "GRAPHRAG_PROVIDER",
    "LIGHTRAG_PROVIDER",
    "LIGHTRAG_SERVER_PROVIDER",
    "KNOWN_PROVIDERS",
    "get_pipeline",
    "has_ready_provider_index",
    "list_pipelines",
    "normalize_provider_name",
    "provider_failure_summary",
    "provider_uses_embedding_versions",
    "version_has_provider_output",
    "version_matches_provider",
]
