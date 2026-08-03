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


async def query_with_sources(
    rag: Any, question: str, mode: str | None = None
) -> tuple[str, list[dict[str, Any]]]:
    """Return a LightRAG answer together with its structured provenance.

    ``RAGAnything.aquery`` owns the answer path, including its optional VLM
    enhancement. LightRAG exposes the records used for retrieval separately via
    ``aquery_data``. Keeping those calls separate preserves the existing answer
    behavior while allowing DeepTutor to surface citation metadata.
    """
    answer = await query(rag, question, mode)
    return answer, await query_sources(rag, question, mode)


async def query_sources(rag: Any, question: str, mode: str | None = None) -> list[dict[str, Any]]:
    """Fetch and normalize the structured records used by a LightRAG query.

    ``aquery_data`` was added by LightRAG after some supported RAG-Anything
    releases. Missing or failed provenance must not turn a successful answer
    into a failed user request, so older installations gracefully return no
    citations.
    """
    await ensure_ready(rag)
    lightrag = getattr(rag, "lightrag", None)
    aquery_data = getattr(lightrag, "aquery_data", None)
    if not callable(aquery_data):
        logger.debug("Installed LightRAG has no structured query data API.")
        return []

    resolved = normalize_mode(mode) or DEFAULT_MODE
    extra = query_kwargs_from_settings()
    try:
        from lightrag import QueryParam

        try:
            result = await aquery_data(question, param=QueryParam(mode=resolved, **extra))
        except TypeError:
            if not extra:
                raise
            logger.debug("LightRAG rejected extra provenance query kwargs; retrying mode-only.")
            result = await aquery_data(question, param=QueryParam(mode=resolved))
    except Exception as exc:
        logger.warning("LightRAG provenance lookup failed; omitting citations: %s", exc)
        return []

    return _query_data_to_sources(result)


def _query_data_to_sources(result: Any) -> list[dict[str, Any]]:
    """Map LightRAG's structured retrieval result to DeepTutor citations."""
    if not isinstance(result, dict):
        return []
    data = result.get("data")
    if not isinstance(data, dict):
        return []

    reference_paths = {
        str(record.get("reference_id")): str(record.get("file_path"))
        for record in data.get("references", [])
        if isinstance(record, dict) and record.get("reference_id") and record.get("file_path")
    }
    sources: list[dict[str, Any]] = []

    def source_path(record: dict[str, Any]) -> str:
        return str(
            record.get("file_path") or reference_paths.get(str(record.get("reference_id")), "")
        )

    def source_title(path: str, fallback: str) -> str:
        return Path(path).name if path else fallback

    for record in data.get("chunks", []):
        if not isinstance(record, dict):
            continue
        path = source_path(record)
        content = str(record.get("content") or "")
        chunk_id = str(record.get("chunk_id") or "")
        if not (path or content or chunk_id):
            continue
        sources.append(
            {
                "title": source_title(path, "LightRAG chunk"),
                "content": content[:200],
                "source": path,
                "page": str(record.get("page") or ""),
                "chunk_id": chunk_id,
                "reference_id": str(record.get("reference_id") or ""),
            }
        )

    for record in data.get("entities", []):
        if not isinstance(record, dict):
            continue
        path = source_path(record)
        entity_id = str(record.get("entity_name") or record.get("entity_id") or "")
        description = str(record.get("description") or "")
        if not (path or entity_id or description):
            continue
        sources.append(
            {
                "title": entity_id or source_title(path, "LightRAG entity"),
                "content": description[:200],
                "source": path,
                "page": str(record.get("page") or ""),
                "entity_id": entity_id,
                "entity_type": str(record.get("entity_type") or ""),
                "source_id": str(record.get("source_id") or ""),
                "reference_id": str(record.get("reference_id") or ""),
            }
        )

    for record in data.get("relationships", []):
        if not isinstance(record, dict):
            continue
        path = source_path(record)
        source_id = str(record.get("src_id") or "")
        target_id = str(record.get("tgt_id") or "")
        relation_id = str(record.get("relation_id") or f"{source_id}->{target_id}")
        description = str(record.get("description") or "")
        if not (path or relation_id or description):
            continue
        sources.append(
            {
                "title": relation_id or source_title(path, "LightRAG relationship"),
                "content": description[:200],
                "source": path,
                "page": str(record.get("page") or ""),
                "relation_id": relation_id,
                "source_entity_id": source_id,
                "target_entity_id": target_id,
                "source_id": str(record.get("source_id") or ""),
                "reference_id": str(record.get("reference_id") or ""),
            }
        )

    return sources


__all__ = ["build_rag", "insert", "ensure_ready", "query", "query_with_sources"]
