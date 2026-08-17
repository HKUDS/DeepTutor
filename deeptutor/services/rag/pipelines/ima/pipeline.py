"""Retrieval-only pipeline backed by a Tencent IMA knowledge base.

Implements the same contract as the other pipelines (see ``..base.RAGPipeline``)
but owns no index: an ``ima`` KB is a connection pointer (``type: ima`` in
``kb_config.json``) to a library the user keeps in IMA and curates there. Only
:meth:`search` does real work — it resolves the KB's credentials, asks IMA for
matching passages, and shapes them for the ``rag`` tool. Documents are added in
IMA, so :meth:`initialize` / :meth:`add_documents` are not part of this engine's
job and fail with a clear message; :meth:`delete` is a no-op because deleting the
KB only drops DeepTutor's pointer (handled by the manager) and must never touch
the user's IMA library.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import PurePath
from typing import Any, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.provider_binding import load_kb_config_entry
from deeptutor.utils.document_extractor import (
    SUPPORTED_DOC_EXTENSIONS,
    extract_text_from_bytes,
)

from .client import MAX_MEDIA_BYTES, ImaMediaContent
from .config import ImaNotConfiguredError, resolve_kb_config

logger = logging.getLogger(__name__)

PROVIDER = "ima"
DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")

# How many matched passages one retrieval feeds into the prompt. IMA returns a
# highlight snippet per item rather than whole documents, so this is a passage
# budget, not a document budget.
_DEFAULT_TOP_K = 10

# Full-document retrieval is only a fallback for title-only IMA matches. Keep
# its network and prompt footprint predictable even when ``top_k`` is large.
_MAX_FULLTEXT_ITEMS = 3
_MAX_FULLTEXT_CHARS = 12_000


class ImaPipeline:
    """Query a Tencent IMA knowledge base on behalf of a connected KB."""

    def __init__(self, kb_base_dir: Optional[str] = None, *, client_factory=None, **_: Any) -> None:
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        # Injection seam for tests: (config) -> client. None uses the real client.
        self._client_factory = client_factory

    # ----- helpers --------------------------------------------------------

    def _client(self, config):
        if self._client_factory is not None:
            return self._client_factory(config)
        from .client import ImaClient

        return ImaClient(config)

    @staticmethod
    def _top_k(kwargs: dict[str, Any]) -> int:
        try:
            requested = int(kwargs.get("top_k") or _DEFAULT_TOP_K)
        except (TypeError, ValueError):
            return _DEFAULT_TOP_K
        return max(1, min(requested, 50))

    # ----- retrieval ------------------------------------------------------

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        try:
            config = resolve_kb_config(load_kb_config_entry(self.kb_base_dir, kb_name))
        except ImaNotConfiguredError as exc:
            return self._error_result(query, exc, error_type="not_configured")

        try:
            client = self._client(config)
            items = await client.search_knowledge(query, limit=self._top_k(kwargs))
        except Exception as exc:
            self.logger.error("IMA search failed for '%s': %s", kb_name, exc)
            return self._error_result(query, exc, error_type="retrieval_error")

        sources = _sources_from_items(items)
        await self._hydrate_title_only_sources(client, sources)
        content = _render_context(sources)
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": sources,
            "provider": PROVIDER,
        }

    async def _hydrate_title_only_sources(self, client, sources: list[dict[str, Any]]) -> None:
        remaining = _MAX_FULLTEXT_ITEMS
        for source in sources:
            if remaining == 0:
                break
            if source["content"] or not source["chunk_id"]:
                continue
            remaining -= 1
            try:
                media = await client.get_media_content(source["chunk_id"])
                source["content"] = await _extract_media_text(media, source["title"])
            except Exception as exc:
                # Search results remain useful as title-only references. One
                # unavailable document must not discard the other matches.
                # HTTP errors may contain a signed COS URL; log only the error
                # class so short-lived download credentials never reach logs.
                self.logger.warning(
                    "Could not load IMA media '%s' (%s)",
                    source["chunk_id"],
                    type(exc).__name__,
                )

    def _error_result(self, query: str, exc: Exception, *, error_type: str) -> Dict[str, Any]:
        return {
            "query": query,
            "answer": str(exc),
            "content": "",
            "sources": [],
            "provider": PROVIDER,
            "error_type": error_type,
        }

    # ----- indexing (not applicable — owned by IMA) ------------------------

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        raise RuntimeError(
            "Tencent IMA knowledge bases are indexed by IMA; DeepTutor does not "
            "build or store their index. Add documents in IMA directly."
        )

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        return await self.initialize(kb_name, file_paths, **kwargs)

    # ----- lifecycle ------------------------------------------------------

    async def delete(self, kb_name: str, **kwargs) -> bool:
        # The KB is only a pointer; the manager removes its config entry. Never
        # touch the user's IMA library. Nothing local to clean up here.
        return True


def _sources_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map IMA search items into DeepTutor's ``sources`` shape.

    ``highlight_content`` is the matched snippet IMA returns; items whose match
    was on the title alone carry none and are still listed, so the model can see
    the document exists even without a quotable passage.
    """
    sources: list[dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "").strip()
        media_id = str(item.get("media_id") or "").strip()
        if not title and not media_id:
            continue
        sources.append(
            {
                "title": title or media_id,
                "content": str(item.get("highlight_content") or "").strip(),
                "source": title or media_id,
                "chunk_id": media_id,
            }
        )
    return sources


async def _extract_media_text(media: ImaMediaContent | None, title: str) -> str:
    if media is None:
        return ""
    if media.text:
        return media.text[:_MAX_FULLTEXT_CHARS].strip()
    if not media.data:
        return ""

    filename = _extractable_filename(title, media.filename)
    if not filename:
        return ""
    return await asyncio.to_thread(
        extract_text_from_bytes,
        filename,
        media.data,
        max_bytes=MAX_MEDIA_BYTES,
        max_chars=_MAX_FULLTEXT_CHARS,
    )


def _extractable_filename(*candidates: str) -> str:
    for candidate in candidates:
        if PurePath(candidate).suffix.lower() in SUPPORTED_DOC_EXTENSIONS:
            return candidate
    return ""


def _render_context(sources: list[dict[str, Any]]) -> str:
    """Flatten retrieved snippets into the grounded context block."""
    blocks = [
        f"[{index}] {source['title']}\n{source['content']}".rstrip()
        for index, source in enumerate(sources, start=1)
    ]
    return "\n\n".join(blocks)


__all__ = ["ImaPipeline", "PROVIDER"]
