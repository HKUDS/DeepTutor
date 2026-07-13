"""Thin adapter over the GraphRAG (microsoft/graphrag) Python API.

This is the ONLY module that imports ``graphrag``. Everything GraphRAG-version
sensitive lives here, so a schema/API shift between releases is a one-file fix.
Pinned to the 3.x line (``graphrag>=3,<4``); the indexing/query surface mirrors
``graphrag.cli.{index,query}`` for that line.

All imports are lazy so the package only loads when a GraphRAG KB is actually
used — DeepTutor runs fine without the optional dependency installed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import DEFAULT_MODE, normalize_mode, query_config_from_settings

logger = logging.getLogger(__name__)

# Fallback response style + community granularity. The live values come from the
# persisted graphrag.json slice (query_config_from_settings); these constants are
# kept for tests / call sites that reference the defaults directly.
RESPONSE_TYPE = "Multiple Paragraphs"
DEFAULT_COMMUNITY_LEVEL = 2

# Per-mode output tables the query API needs (mirrors graphrag.cli.query).
_OUTPUTS_BY_MODE: dict[str, tuple[list[str], list[str]]] = {
    "global": (["entities", "communities", "community_reports"], []),
    "local": (
        ["communities", "community_reports", "text_units", "relationships", "entities"],
        ["covariates"],
    ),
    "drift": (
        ["communities", "community_reports", "text_units", "relationships", "entities"],
        [],
    ),
    "basic": (["text_units"], []),
}


def _load_config(root_dir: Path):
    from graphrag.config.load_config import load_config

    return load_config(root_dir=Path(root_dir))


async def build(root_dir: Path, *, is_update: bool = False) -> None:
    """Run the GraphRAG indexing pipeline rooted at ``root_dir``.

    Raises on any failed workflow so the caller can surface an error and clean
    up the (incomplete) version directory.
    """
    from graphrag.api import build_index
    from graphrag.config.enums import IndexingMethod

    config = _load_config(root_dir)
    logger.info("GraphRAG: building index at %s (update=%s)", root_dir, is_update)
    results = await build_index(
        config=config,
        method=IndexingMethod.Standard,
        is_update_run=is_update,
    )
    errors = [r for r in results if getattr(r, "error", None) is not None]
    if errors:
        detail = "; ".join(f"{r.workflow}: {r.error}" for r in errors[:3])
        raise RuntimeError(f"GraphRAG indexing failed: {detail}")


async def _resolve_outputs(config, names: list[str], optional: list[str]) -> dict[str, Any]:
    """Load the requested output parquet tables as DataFrames (mirrors the CLI)."""
    from graphrag.data_model.data_reader import DataReader
    from graphrag_storage import create_storage
    from graphrag_storage.tables.table_provider_factory import create_table_provider

    storage_obj = create_storage(config.output_storage)
    table_provider = create_table_provider(config.table_provider, storage=storage_obj)
    reader = DataReader(table_provider)

    frames: dict[str, Any] = {}
    for name in names:
        frames[name] = await getattr(reader, name)()
    for name in optional:
        frames[name] = await getattr(reader, name)() if await table_provider.has(name) else None
    return frames


async def search(root_dir: Path, query: str, mode: str | None = None) -> tuple[str, dict]:
    """Run a GraphRAG query and return ``(response_text, context_data)``.

    ``context_data`` is normalised to a dict of record lists
    (reports/entities/relationships/claims/sources) via GraphRAG's own helper.
    """
    import graphrag.api as api
    from graphrag.utils.api import reformat_context_data

    resolved_mode = normalize_mode(mode)
    cfg = query_config_from_settings()
    config = _load_config(root_dir)
    names, optional = _OUTPUTS_BY_MODE.get(resolved_mode, _OUTPUTS_BY_MODE[DEFAULT_MODE])
    frames = await _resolve_outputs(config, names, optional)

    if resolved_mode == "global":
        response, context = await api.global_search(
            config=config,
            entities=frames["entities"],
            communities=frames["communities"],
            community_reports=frames["community_reports"],
            community_level=None,
            dynamic_community_selection=cfg.dynamic_community_selection,
            response_type=cfg.response_type,
            query=query,
        )
    elif resolved_mode == "drift":
        response, context = await api.drift_search(
            config=config,
            entities=frames["entities"],
            communities=frames["communities"],
            community_reports=frames["community_reports"],
            text_units=frames["text_units"],
            relationships=frames["relationships"],
            community_level=cfg.community_level,
            response_type=cfg.response_type,
            query=query,
        )
    elif resolved_mode == "basic":
        response, context = await api.basic_search(
            config=config,
            text_units=frames["text_units"],
            response_type=cfg.response_type,
            query=query,
        )
    else:  # local (default)
        response, context = await api.local_search(
            config=config,
            entities=frames["entities"],
            communities=frames["communities"],
            community_reports=frames["community_reports"],
            text_units=frames["text_units"],
            relationships=frames["relationships"],
            covariates=frames.get("covariates"),
            community_level=cfg.community_level,
            response_type=cfg.response_type,
            query=query,
        )

    try:
        context_data = reformat_context_data(context) if isinstance(context, dict) else {}
    except Exception:  # pragma: no cover - context shape is best-effort
        context_data = {}
    return str(response), context_data


__all__ = ["build", "search", "RESPONSE_TYPE", "DEFAULT_COMMUNITY_LEVEL"]
