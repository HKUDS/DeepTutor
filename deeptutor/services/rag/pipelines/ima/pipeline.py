"""Retrieval-only pipeline backed by a Tencent IMA knowledge base.

Implements the same contract as the other pipelines (see ``..base.RAGPipeline``)
but owns no index: an ``ima`` KB is a connection pointer (``type: ima`` in
``kb_config.json``) to a library the user keeps in IMA and curates there. Only
:meth:`search` does real work — it resolves the KB's credentials, asks IMA for
matching passages, tops the thin ones up with real source text, and shapes them
for the ``rag`` tool. Documents are added in IMA (or through the IMA capability's
own tools), so :meth:`initialize` / :meth:`add_documents` are not part of this
engine's job and fail with a clear message; :meth:`delete` is a no-op because
deleting the KB only drops DeepTutor's pointer (handled by the manager) and must
never touch the user's IMA library.

The retrieval *policy* — which matches deserve a full-text fetch — lives in
:mod:`.sources`; this module only orchestrates.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

import httpx

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.provider_binding import load_kb_config_entry

from . import media as media_ops
from . import sources as source_policy
from .config import ImaNotConfiguredError, resolve_kb_config
from .envelope import ImaAuthError, ImaRateLimitError

logger = logging.getLogger(__name__)

PROVIDER = "ima"
DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")

# How many matched passages one retrieval feeds into the prompt. IMA returns a
# highlight snippet per item rather than whole documents, so this is a passage
# budget, not a document budget.
_DEFAULT_TOP_K = 10
_MAX_TOP_K = 50


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
        return max(1, min(requested, _MAX_TOP_K))

    # ----- retrieval ------------------------------------------------------

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        try:
            config = resolve_kb_config(load_kb_config_entry(self.kb_base_dir, kb_name))
        except ImaNotConfiguredError as exc:
            return self._error_result(query, exc, error_type="not_configured")

        try:
            client = self._client(config)
            page = await client.search_knowledge(query, limit=self._top_k(kwargs))
        except Exception as exc:
            self.logger.error("IMA search failed for '%s' (%s)", kb_name, type(exc).__name__)
            return self._error_result(query, exc, error_type="retrieval_error")

        matched = source_policy.documents_to_sources(page.documents)
        hydration_failures = await self._hydrate(client, matched)
        # A title match without a snippet or readable media is useful for
        # hydration, but it is not evidence that the rag tool may cite (#1500).
        sources = [source for source in matched if str(source.get("content") or "").strip()]
        diagnostics = {
            "knowledge_base": kb_name,
            "matched_documents": len(matched),
            "readable_documents": len(sources),
            "unreadable_documents": len(matched) - len(sources),
            "unverified_documents": page.unverified_documents + len(page.documents) - len(matched),
            "hydration_failures": hydration_failures,
        }
        if diagnostics["unverified_documents"] and not matched:
            return {
                "query": query,
                "answer": "Tencent IMA returned matches without usable source identifiers. No source passage could be verified.",
                "content": "",
                "sources": [],
                "provider": PROVIDER,
                "error_type": "unverified_sources",
                "retrieval_status": "unverified_sources",
                "diagnostics": diagnostics,
            }
        if matched and not sources:
            return {
                "query": query,
                "answer": (
                    "Tencent IMA matched document titles, but returned no readable text. "
                    "Check access to the matched media or try again."
                ),
                "content": "",
                "sources": [],
                "provider": PROVIDER,
                "error_type": "content_unavailable",
                "retrieval_status": "content_unavailable",
                "diagnostics": diagnostics,
            }
        content = source_policy.render_context(sources)
        status = "ready"
        if not matched:
            status = "no_matches"
            content = f"Tencent IMA returned no matching passages for this query in '{kb_name}'."
        elif (
            len(sources) < len(matched) or hydration_failures or diagnostics["unverified_documents"]
        ):
            status = "partial"
            content += (
                "\n\nSome IMA matches could not be read in full. Use only the returned "
                "passages as evidence; do not invent missing source text or locations."
            )
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": sources,
            "provider": PROVIDER,
            "retrieval_status": status,
            "diagnostics": diagnostics,
        }

    async def _hydrate(self, client, sources: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Replace thin or missing snippets with real source text, concurrently.

        Each fetch is independent, so they run together — a search that needs
        four documents costs one round-trip's latency, not four. A document that
        cannot be loaded keeps its snippet (or stays a title-only reference):
        one unavailable file must never discard the other matches.
        """
        targets = source_policy.hydration_targets(sources)
        if not targets:
            return []
        results = await asyncio.gather(
            *(self._fetch_text(client, sources[index]) for index in targets),
            return_exceptions=True,
        )
        failures = []
        for index, result in zip(targets, results):
            if isinstance(result, BaseException):
                # HTTP errors may embed a signed COS URL; log only the error
                # class so short-lived download credentials never reach logs.
                self.logger.warning(
                    "Could not load IMA media '%s' (%s)",
                    sources[index]["chunk_id"],
                    type(result).__name__,
                )
                failures.append(
                    {"source_id": sources[index]["chunk_id"], "error_type": type(result).__name__}
                )
            elif result:
                sources[index]["content"] = result
            else:
                failures.append(
                    {"source_id": sources[index]["chunk_id"], "error_type": "content_unavailable"}
                )
        return failures

    @staticmethod
    async def _fetch_text(client, source: dict[str, Any]) -> str:
        media = await client.get_media_content(source["chunk_id"])
        return await media_ops.extract_text(
            media,
            source["title"],
            max_chars=source_policy.MAX_FULLTEXT_CHARS,
        )

    def _error_result(self, query: str, exc: Exception, *, error_type: str) -> Dict[str, Any]:
        # #1500: preserve observable failure classes without exposing signed
        # media URLs or credentials carried by transport exceptions.
        message = str(exc)
        if isinstance(exc, ImaAuthError):
            error_type = "authentication_error"
            message = "Tencent IMA rejected the credentials or library access. Check this account's IMA connection and permissions."
        elif isinstance(exc, ImaRateLimitError):
            error_type = "rate_limited"
            message = "Tencent IMA rate limit reached. Wait before retrying this search."
        elif isinstance(exc, httpx.TimeoutException):
            error_type = "timeout"
            message = "Tencent IMA did not respond in time. Retry the search."
        elif isinstance(exc, httpx.TransportError):
            error_type = "network_error"
            message = "Tencent IMA could not be reached. Check the connection and retry."
        return {
            "query": query,
            "answer": message,
            "content": "",
            "sources": [],
            "provider": PROVIDER,
            "error_type": error_type,
            "retrieval_status": "failed",
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


__all__ = ["ImaPipeline", "PROVIDER"]
