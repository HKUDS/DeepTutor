"""Thin adapter over the GraphRAG (microsoft/graphrag) Python API.

This is the ONLY module that imports ``graphrag``. Everything GraphRAG-version
sensitive lives here, so a schema/API shift between releases is a one-file fix.
Pinned to the 3.x line (``graphrag>=3,<4``); the indexing/query surface mirrors
``graphrag.cli.{index,query}`` for that line.

All imports are lazy so the package only loads when a GraphRAG KB is actually
used — DeepTutor runs fine without the optional dependency installed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from pathlib import Path
from typing import Any, TypeVar

from .config import DEFAULT_MODE, normalize_mode, query_config_from_settings
from .errors import (
    GraphRagModelIncompatibleError,
    GraphRagStructuredOutputError,
    GraphRagUnsupportedProviderError,
    classify_model_error,
)
from .provider import (
    COMPLETION_TYPE,
    resolve_completion_model,
    resolve_completion_provider,
    resolve_persisted_completion_provider,
)

logger = logging.getLogger(__name__)

# Fallback response style + community granularity. The live values come from the
# persisted graphrag.json slice (query_config_from_settings); these constants are
# kept for tests / call sites that reference the defaults directly.
RESPONSE_TYPE = "Multiple Paragraphs"
DEFAULT_COMMUNITY_LEVEL = 2
PROBE_MAX_TOKENS = 1024
PROBE_TIMEOUT_SECONDS = 25

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


_T = TypeVar("_T")


def _load_config(root_dir: Path):
    from graphrag.config.load_config import load_config

    from .completion_adapter import register_completion_adapter

    register_completion_adapter()
    config = load_config(root_dir=Path(root_dir))
    for model_config in config.completion_models.values():
        if model_config.type in {"litellm", COMPLETION_TYPE}:
            model_config.type = COMPLETION_TYPE
            model_config.model_provider = resolve_persisted_completion_provider(model_config)
    return config


async def _run_isolated(work: Callable[[], Awaitable[_T]]) -> _T:
    """Run one GraphRAG entry point on a private, plain-asyncio event loop.

    ``graphrag_llm`` calls ``nest_asyncio2.apply()`` at import time, and that
    patch refuses uvloop ("Can't patch loop of type <class 'uvloop.Loop'>") —
    which is precisely the loop ``uvicorn[standard]`` gives the backend, so on
    macOS/Linux the first GraphRAG import aborted indexing before it started
    (issue #695). Importing and driving GraphRAG from a worker thread that owns
    a stock asyncio loop hands that patch — and GraphRAG's own nested
    ``run_until_complete`` calls — the reentrant loop they expect, and leaves
    the server's uvloop loop untouched.

    Every ``graphrag`` import therefore has to happen inside ``work``, which is
    why the entry points below keep their imports function-local.
    """

    def _runner() -> _T:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(work())
        finally:
            try:
                loop.close()
            finally:
                asyncio.set_event_loop(None)

    return await asyncio.to_thread(_runner)


def _create_probe_completion(llm_cfg: Any):
    """Create the same adapted completion client/schema used by community reports."""
    from graphrag.index.operations.summarize_communities.community_reports_extractor import (
        CommunityReportResponse,
    )
    from graphrag_llm.completion import create_completion
    from graphrag_llm.config import ModelConfig

    from .completion_adapter import register_completion_adapter

    api_base = getattr(llm_cfg, "effective_url", None) or getattr(llm_cfg, "base_url", None)
    call_args: dict[str, Any] = {}
    extra_headers = getattr(llm_cfg, "extra_headers", None)
    if isinstance(extra_headers, dict) and extra_headers:
        call_args["extra_headers"] = dict(extra_headers)
    reasoning_effort = getattr(llm_cfg, "reasoning_effort", None)
    if reasoning_effort:
        call_args["reasoning_effort"] = reasoning_effort
    register_completion_adapter()
    model_config = ModelConfig(
        type=COMPLETION_TYPE,
        model_provider=resolve_completion_provider(llm_cfg),
        model=resolve_completion_model(llm_cfg),
        api_base=api_base,
        api_version=getattr(llm_cfg, "api_version", None),
        api_key=getattr(llm_cfg, "api_key", None) or "sk-no-key-required",
        auth_method="api_key",
        call_args=call_args,
    )
    return create_completion(model_config), CommunityReportResponse


async def _probe_completion_model_impl(llm_cfg: Any) -> None:
    """Request and validate one minimal GraphRAG community-report response."""
    completion, response_model = _create_probe_completion(llm_cfg)
    response = await completion.completion_async(
        messages=(
            "Return one concise community report for a graph containing one topic named "
            "'compatibility test'. Include a title, summary, one finding with summary and "
            "explanation, a numeric rating, and a rating explanation."
        ),
        response_format=response_model,
        max_tokens=PROBE_MAX_TOKENS,
        stream=False,
        timeout=PROBE_TIMEOUT_SECONDS,
    )
    if not isinstance(getattr(response, "formatted_response", None), response_model):
        raise GraphRagStructuredOutputError("GraphRAG structured response validation failed.")


def _failed_probe_result(llm_cfg: Any, error: Exception) -> dict[str, Any]:
    """Classify a probe failure without returning provider messages or credentials."""
    classified = classify_model_error(error)
    if isinstance(
        classified,
        (GraphRagModelIncompatibleError, GraphRagUnsupportedProviderError),
    ):
        status = "incompatible"
        compatible: bool | None = False
    else:
        status = "unverifiable"
        compatible = None
    if classified is not None:
        return {
            "status": status,
            "compatible": compatible,
            "code": classified.code,
            "message": str(classified),
            "model": str(getattr(llm_cfg, "model", "") or ""),
            "binding": str(getattr(llm_cfg, "binding", "") or ""),
            "retryable": classified.retryable,
        }
    return {
        "status": "unverifiable",
        "compatible": None,
        "code": "graphrag_model_probe_failed",
        "message": "GraphRAG compatibility could not be verified with this model.",
        "model": str(getattr(llm_cfg, "model", "") or ""),
        "binding": str(getattr(llm_cfg, "binding", "") or ""),
        "retryable": False,
    }


async def probe_completion_model(llm_cfg: Any) -> dict[str, Any]:
    """Test one completion config against GraphRAG's structured-output contract."""
    try:
        await _run_isolated(lambda: _probe_completion_model_impl(llm_cfg))
    except Exception as error:  # noqa: BLE001 - converted into a secret-free probe result
        return _failed_probe_result(llm_cfg, error)
    return {
        "status": "compatible",
        "compatible": True,
        "code": "graphrag_model_compatible",
        "message": "The model returned valid GraphRAG structured output.",
        "model": str(getattr(llm_cfg, "model", "") or ""),
        "binding": str(getattr(llm_cfg, "binding", "") or ""),
        "retryable": False,
    }


async def build(root_dir: Path, *, is_update: bool = False) -> None:
    """Run the GraphRAG indexing pipeline rooted at ``root_dir``.

    Raises on any failed workflow so the caller can surface an error and clean
    up the (incomplete) version directory.
    """
    try:
        await _run_isolated(lambda: _build_impl(root_dir, is_update=is_update))
    except Exception as error:
        classified = classify_model_error(error)
        if classified is not None and classified is not error:
            raise classified from error
        raise


async def _build_impl(root_dir: Path, *, is_update: bool) -> None:
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
        for result in errors:
            error = getattr(result, "error", None)
            if isinstance(error, BaseException):
                classified = classify_model_error(error)
                if classified is not None:
                    raise classified from error
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
    try:
        return await _run_isolated(lambda: _search_impl(root_dir, query, mode))
    except Exception as error:
        classified = classify_model_error(error)
        if classified is not None and classified is not error:
            raise classified from error
        raise


async def _search_impl(root_dir: Path, query: str, mode: str | None) -> tuple[str, dict]:
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


__all__ = [
    "build",
    "search",
    "probe_completion_model",
    "RESPONSE_TYPE",
    "DEFAULT_COMMUNITY_LEVEL",
]
