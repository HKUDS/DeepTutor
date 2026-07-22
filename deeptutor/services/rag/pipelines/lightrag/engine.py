"""Thin adapter over the RAG-Anything / LightRAG Python API.

This is the ONLY module that imports ``raganything`` / ``lightrag``. Everything
version-sensitive lives here, so an API shift between releases is a one-file
fix. All imports are lazy so DeepTutor runs fine without the optional dependency
installed.

A RAG-Anything instance is built from DeepTutor's LLM/vision/embedding adapters
(see ``config.py``) over a per-KB ``working_dir``. Documents are inserted as a
MinerU-style ``content_list`` (produced upstream by the parse layer), so the
multimodal step never re-parses anything; retrieval delegates to LightRAG's
native query modes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_MODE,
    build_embedding_func,
    build_llm_model_func,
    build_vision_model_func,
    normalize_mode,
    query_kwargs_from_settings,
)

logger = logging.getLogger(__name__)


def build_rag(working_dir: Path) -> Any:
    """Construct a RAG-Anything instance rooted at ``working_dir``.

    Pinned to RAG-Anything's config-based constructor; this is the single spot
    to touch if its API changes between releases.
    """
    from raganything import RAGAnything, RAGAnythingConfig

    config = RAGAnythingConfig(working_dir=str(working_dir))
    rag = RAGAnything(
        config=config,
        llm_model_func=build_llm_model_func(),
        vision_model_func=build_vision_model_func(),
        embedding_func=build_embedding_func(),
    )
    # DeepTutor always feeds RAG-Anything a pre-parsed ``content_list`` (the
    # parse layer runs upstream via DeepTutor's own ParseService), so
    # RAG-Anything's bundled document parser is never invoked. Its LightRAG init
    # nevertheless runs a one-time installation check on its *default* parser
    # (``mineru``); when MinerU isn't installed that check hard-fails indexing
    # with "Parser 'mineru' is not properly installed" — even though the user
    # picked an entirely different parse engine (see issue #594). Marking the
    # check as already satisfied skips that spurious gate for a parser we don't
    # use, while leaving the real pre-parsed insert path untouched.
    rag._parser_installation_checked = True
    return rag


async def insert(rag: Any, content_list: list[dict], *, file_name: str, doc_id: str) -> None:
    """Insert a pre-parsed ``content_list`` (multimodal-aware, no re-parsing)."""
    await rag.insert_content_list(
        content_list=content_list,
        file_path=file_name,
        doc_id=doc_id,
    )


async def ensure_ready(rag: Any) -> None:
    """Ensure RAG-Anything has an initialized LightRAG instance."""
    if getattr(rag, "lightrag", None) is not None:
        return

    initializer = getattr(rag, "_ensure_lightrag_initialized", None)
    if initializer is None:
        return

    result = await initializer()
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(result.get("error") or "Failed to initialize LightRAG")


async def query(rag: Any, question: str, mode: str | None = None) -> str:
    """Run a LightRAG query and return the synthesized answer string.

    Extra knobs (top_k, response_type) from the lightrag.json slice ride into
    LightRAG's ``QueryParam`` via aquery's ``**kwargs``. Wiring is defensive: an
    older RAG-Anything that rejects one of these kwargs falls back to a
    mode-only query rather than failing the search.
    """
    resolved = normalize_mode(mode) or DEFAULT_MODE
    extra = query_kwargs_from_settings()
    await ensure_ready(rag)
    try:
        result = await rag.aquery(question, mode=resolved, **extra)
    except TypeError:
        if extra:
            logger.debug("RAG-Anything rejected extra query kwargs; retrying mode-only.")
            result = await rag.aquery(question, mode=resolved)
        else:
            raise
    return result if isinstance(result, str) else str(result)


__all__ = ["build_rag", "insert", "ensure_ready", "query"]
