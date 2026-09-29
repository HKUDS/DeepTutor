"""Retrieval-only RAG pipeline over an existing kiwix-serve ZIM archive."""

from __future__ import annotations

from typing import Any

from deeptutor.runtime.home import get_runtime_data_root
from deeptutor.services.rag.provider_binding import load_kb_config_entry

from .client import KiwixClient, KiwixError

PROVIDER = "kiwix"


class KiwixPipeline:
    def __init__(self, kb_base_dir: str | None = None, *, client_factory=None, **_: Any) -> None:
        self.kb_base_dir = kb_base_dir or str(get_runtime_data_root() / "knowledge_bases")
        self._client_factory = client_factory or KiwixClient

    async def search(self, query: str, kb_name: str, **kwargs: Any) -> dict[str, Any]:
        entry = load_kb_config_entry(self.kb_base_dir, kb_name)
        if entry.get("type") != PROVIDER:
            return self._error(
                query, "This knowledge base is not connected to Kiwix.", "not_configured"
            )
        try:
            client = self._client_factory(entry["server_url"], entry["zim_name"])
            hits = await client.search(query, top_k=kwargs.get("top_k") or 5)
        except (KiwixError, KeyError, TypeError, ValueError) as exc:
            return self._error(query, str(exc), "retrieval_error")
        sources = [
            {
                "title": hit.title,
                "content": content,
                "source": f"{entry.get('zim_title') or entry['zim_name']} / {hit.title}",
                "id": f"{entry['zim_name']}:{hit.article_path}",
                "chunk_id": f"{entry['zim_name']}:{hit.article_path}",
                "article_path": hit.article_path,
                "archive": entry["zim_name"],
            }
            for hit, content in hits
            if content.strip()
        ]
        context = "\n\n".join(
            f"[{index}] {source['source']}\n{source['content']}"
            for index, source in enumerate(sources, start=1)
        )
        return {
            "query": query,
            "answer": context,
            "content": context,
            "sources": sources,
            "provider": PROVIDER,
        }

    @staticmethod
    def _error(query: str, message: str, error_type: str) -> dict[str, Any]:
        return {
            "query": query,
            "answer": message,
            "content": "",
            "sources": [],
            "provider": PROVIDER,
            "error_type": error_type,
        }

    async def initialize(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool:
        raise RuntimeError("Kiwix owns this ZIM archive and its search index. Add content there.")

    async def add_documents(self, kb_name: str, file_paths: list[str], **kwargs: Any) -> bool:
        return await self.initialize(kb_name, file_paths, **kwargs)

    async def delete(self, kb_name: str, **kwargs: Any) -> bool:
        # The manager deletes only its pointer; never delete a user's archive.
        return True
