"""Retrieval-only RAG pipeline backed by an external WeKnora knowledge base."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.provider_binding import load_kb_config_entry

from .config import WeKnoraNotConfiguredError, config_from_entry

logger = logging.getLogger(__name__)

PROVIDER = "weknora"
DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")


class WeKnoraPipeline:
    def __init__(self, kb_base_dir: Optional[str] = None, *, client_factory=None, **_: Any) -> None:
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
        self._client_factory = client_factory

    def _client(self, config):
        if self._client_factory is not None:
            return self._client_factory(config)
        from .client import WeKnoraClient

        return WeKnoraClient(config)

    async def search(self, query: str, kb_name: str, **kwargs) -> Dict[str, Any]:
        try:
            config = config_from_entry(load_kb_config_entry(self.kb_base_dir, kb_name))
        except WeKnoraNotConfiguredError as exc:
            return self._error_result(query, exc, error_type="not_configured")

        try:
            chunks = await self._client(config).search(query)
        except Exception as exc:
            logger.error("WeKnora search failed for '%s': %s", kb_name, exc)
            return self._error_result(query, exc, error_type="retrieval_error")

        return {
            "query": query,
            "answer": "\n\n---\n\n".join(str(item.get("content") or "") for item in chunks),
            "content": "\n\n---\n\n".join(str(item.get("content") or "") for item in chunks),
            "sources": chunks,
            "provider": PROVIDER,
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

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        raise RuntimeError(
            "WeKnora knowledge bases are managed in WeKnora; DeepTutor does not "
            "upload or index their documents."
        )

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        return await self.initialize(kb_name, file_paths, **kwargs)

    async def delete(self, kb_name: str, **kwargs) -> bool:
        return True


__all__ = ["WeKnoraPipeline", "PROVIDER"]
