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
* GraphRAG talks to its models via LiteLLM with ``model_provider: openai`` + a
  custom ``api_base`` — which is exactly how DeepTutor reaches any
  OpenAI-compatible endpoint.

This is the single spot to touch if GraphRAG's config schema shifts between
releases; pin the dependency to the 3.x line (see ``pyproject`` extra).
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

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


def _model_entry(*, model: str, api_base: str | None, api_key: str | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "model_provider": "openai",  # LiteLLM provider for any OpenAI-compatible API
        "model": model,
        "auth_method": "api_key",
    }
    if api_base:
        entry["api_base"] = api_base
    # GraphRAG validates that a key is present for ``auth_method: api_key``; local
    # OpenAI-compatible servers accept a placeholder.
    entry["api_key"] = api_key or "sk-no-key-required"
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

    llm_base = getattr(llm_cfg, "effective_url", None) or getattr(llm_cfg, "base_url", None)
    embed_base = getattr(embedding_cfg, "effective_url", None) or getattr(
        embedding_cfg, "base_url", None
    )

    return {
        "completion_models": {
            COMPLETION_MODEL_ID: _model_entry(
                model=chat_model,
                api_base=llm_base,
                api_key=getattr(llm_cfg, "api_key", None),
            ),
        },
        "embedding_models": {
            EMBEDDING_MODEL_ID: _model_entry(
                model=embed_model,
                api_base=embed_base,
                api_key=getattr(embedding_cfg, "api_key", None),
            ),
        },
        # Plain-text input: DeepTutor's ingestion writes parsed ``.txt`` files
        # into ``input/`` (see ``ingestion.py``) so GraphRAG never parses
        # documents itself.
        "input": {"type": "text", "file_pattern": r".*\.txt$"},
        "input_storage": {"type": "file", "base_dir": "input"},
        "output_storage": {"type": "file", "base_dir": "output"},
        "cache": {"type": "file", "storage": {"type": "file", "base_dir": "cache"}},
        "reporting": {"type": "file", "base_dir": "logs"},
        # GraphRAG/LanceDB defaults to 3072 dimensions; DeepTutor must stamp the
        # active embedding dimension so Qwen-4096 and other non-default models work.
        "vector_store": {
            "type": "lancedb",
            "db_uri": "output/lancedb",
            "vector_size": embed_dim,
        },
    }


def write_settings(root_dir: Path, *, llm_cfg: Any = None, embedding_cfg: Any = None) -> Path:
    """Write ``settings.yaml`` into ``root_dir`` and return its path."""
    import yaml

    root_dir = Path(root_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    settings = build_settings(llm_cfg=llm_cfg, embedding_cfg=embedding_cfg)
    path = root_dir / SETTINGS_FILENAME
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(settings, handle, sort_keys=False, allow_unicode=True)
    return path


__all__ = [
    "SETTINGS_FILENAME",
    "COMPLETION_MODEL_ID",
    "EMBEDDING_MODEL_ID",
    "SUPPORTED_MODES",
    "DEFAULT_MODE",
    "GraphRagNotAvailableError",
    "GraphRagNotConfiguredError",
    "GraphRagQueryConfig",
    "is_graphrag_available",
    "normalize_mode",
    "query_config_from_settings",
    "build_settings",
    "write_settings",
]
