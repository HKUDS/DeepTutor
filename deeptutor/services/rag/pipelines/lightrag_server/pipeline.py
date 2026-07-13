"""Retrieval-only pipeline backed by an external LightRAG server.

Implements the same contract as the other pipelines (see ``..base.RAGPipeline``)
but owns no index: a ``lightrag-server`` KB is a connection pointer (``type:
lightrag_server`` in ``kb_config.json``) to a standalone LightRAG server the user
runs and indexed themselves. Only :meth:`search` does real work — it reads the
KB's endpoint, asks the server for grounded context (no server-side generation),
and shapes the result for the ``rag`` tool. Indexing is offloaded entirely to the
server, so :meth:`initialize` / :meth:`add_documents` are not part of this
engine's job and fail with a clear message; :meth:`delete` is a no-op because
deleting the KB only drops DeepTutor's pointer (handled by the manager) and must
never touch the user's server.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.provider_binding import load_kb_config_entry

from ..modes import resolve_kb_mode
from .config import (
    DEFAULT_MODE,
    SUPPORTED_MODES,
    LightRagServerNotConfiguredError,
    config_from_entry,
)

logger = logging.getLogger(__name__)

PROVIDER = "lightrag-server"
DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")


class LightRagServerPipeline:
    """Query an external LightRAG server on behalf of a connected KB."""

    def __init__(self, kb_base_dir: Optional[str] = None, *, client_factory=None, **_: Any) -> None:
        self.logger = logging.getLogger(__name__)
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        # Injection seam for tests: (config) -> client. None uses the real client.
        self._client_factory = client_factory

    # ----- helpers --------------------------------------------------------

    def _client(self, config):
        if self._client_factory is not None:
            return self._client_factory(config)
        from .client import LightRagServerClient

        return LightRagServerClient(config)

    def _resolve_mode(self, kb_name: str, kwargs: dict[str, Any]) -> str:
        return resolve_kb_mode(
            self.kb_base_dir,
            kb_name,
            PROVIDER,
            explicit=kwargs.get("mode"),
            supported=SUPPORTED_MODES,
            default=DEFAULT_MODE,
        )

    # ----- retrieval ------------------------------------------------------

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        try:
            config = config_from_entry(load_kb_config_entry(self.kb_base_dir, kb_name))
        except LightRagServerNotConfiguredError as exc:
            return self._error_result(query, exc, error_type="not_configured")

        mode = self._resolve_mode(kb_name, kwargs)
        try:
            result = await self._client(config).query_context(query, mode)
        except Exception as exc:
            self.logger.error("LightRAG server search failed for '%s': %s", kb_name, exc)
            return self._error_result(query, exc, error_type="retrieval_error")

        content = result.get("content") or ""
        return {
            "query": query,
            "answer": content,
            "content": content,
            "sources": result.get("sources") or [],
            "provider": PROVIDER,
            "mode": mode,
        }

    def _error_result(self, query: str, exc: Exception, *, error_type: str) -> Dict[str, Any]:
        return {
            "query": query,
            "answer": str(exc),
            "content": "",
            "sources": [],
            "provider": PROVIDER,
            "error_type": error_type,
        }

    # ----- indexing (not applicable — owned by the external server) -------

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        raise RuntimeError(
            "LightRAG Server knowledge bases are indexed on the external server; "
            "DeepTutor does not build or store their index. Add documents on the "
            "LightRAG server directly."
        )

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        return await self.initialize(kb_name, file_paths, **kwargs)

    # ----- lifecycle ------------------------------------------------------

    async def delete(self, kb_name: str, **kwargs) -> bool:
        # The KB is only a pointer; the manager removes its config entry. Never
        # touch the user's server. Nothing local to clean up here.
        return True


__all__ = ["LightRagServerPipeline", "PROVIDER"]
