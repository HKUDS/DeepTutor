"""Unified RAG service entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from .factory import DEFAULT_PROVIDER, get_pipeline, list_pipelines

DEFAULT_KB_BASE_DIR = str(
    Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge_bases"
)


class RAGService:
    """Unified RAG service backed by the LlamaIndex pipeline."""

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        provider: Optional[str] = None,  # accepted for backward compatibility
    ):
        self.logger = logging.getLogger(__name__)
        if kb_base_dir is None:
            try:
                from deeptutor.services.path_service import get_path_service

                kb_base_dir = str(get_path_service().get_knowledge_bases_root())
            except Exception:
                self.logger.warning(
                    "RAGService falling back to DEFAULT_KB_BASE_DIR (%s); "
                    "this should only happen in single-user / CLI mode. "
                    "Multi-user requests must reach this path with an explicit kb_base_dir.",
                    DEFAULT_KB_BASE_DIR,
                )
                kb_base_dir = DEFAULT_KB_BASE_DIR
        self.kb_base_dir = kb_base_dir
        self.provider = DEFAULT_PROVIDER
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is None:
            self._pipeline = get_pipeline(kb_base_dir=self.kb_base_dir)
        return self._pipeline

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self.logger.info(f"Initializing KB '{kb_name}'")
        pipeline = self._get_pipeline()
        return await pipeline.initialize(kb_name=kb_name, file_paths=file_paths, **kwargs)

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        self.logger.info(f"Adding {len(file_paths)} document(s) to KB '{kb_name}'")
        pipeline = self._get_pipeline()
        if not hasattr(pipeline, "add_documents"):
            return await pipeline.initialize(kb_name=kb_name, file_paths=file_paths, **kwargs)
        return await pipeline.add_documents(kb_name=kb_name, file_paths=file_paths, **kwargs)

    async def search(
        self,
        query: str,
        kb_name: str,
        event_sink=None,
        **kwargs,
    ) -> Dict[str, Any]:
        kwargs.pop("mode", None)
        with self._capture_raw_logs(event_sink):
            await self._emit_tool_event(
                event_sink,
                "status",
                f"Query: {query}",
                {"query": query, "kb_name": kb_name, "trace_layer": "summary"},
            )

            self.logger.info(f"Searching KB '{kb_name}' with query: {query[:50]}...")
            pipeline = self._get_pipeline()

            await self._emit_tool_event(
                event_sink,
                "status",
                f"Retrieving from knowledge base '{kb_name}'...",
                {"provider": DEFAULT_PROVIDER, "trace_layer": "summary"},
            )

            result = await pipeline.search(query=query, kb_name=kb_name, **kwargs)

            if "query" not in result:
                result["query"] = query
            if "answer" not in result and "content" in result:
                result["answer"] = result["content"]
            if "content" not in result and "answer" in result:
                result["content"] = result["answer"]
            result["provider"] = DEFAULT_PROVIDER

            if result.get("error_type") or result.get("needs_reindex"):
                await self._emit_tool_event(
                    event_sink,
                    "status",
                    result.get("answer") or result.get("content") or "RAG search failed.",
                    {
                        "provider": DEFAULT_PROVIDER,
                        "kb_name": kb_name,
                        "trace_layer": "summary",
                        "call_state": "error",
                        "error_type": result.get("error_type"),
                        "needs_reindex": bool(result.get("needs_reindex")),
                    },
                )
                return result

            answer = result.get("answer") or result.get("content") or ""
            await self._emit_tool_event(
                event_sink,
                "status",
                f"Retrieved {len(answer)} characters of grounded context.",
                {
                    "provider": DEFAULT_PROVIDER,
                    "kb_name": kb_name,
                    "trace_layer": "summary",
                },
            )

            return result

    async def _emit_tool_event(
        self,
        event_sink,
        event_type: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        if event_sink is None:
            return
        await event_sink(event_type, message, metadata or {})

    def _capture_raw_logs(self, event_sink):
        from contextlib import nullcontext

        if event_sink is None:
            return nullcontext()

        from deeptutor.logging import capture_process_logs

        def emit(event):
            return self._emit_tool_event(
                event_sink,
                "raw_log",
                event.message,
                {
                    "level": event.level,
                    "logger": event.logger,
                    "timestamp": event.timestamp,
                    "trace_layer": "raw",
                    **event.context,
                },
            )

        return capture_process_logs(emit, min_level=logging.INFO)

    async def delete(self, kb_name: str) -> bool:
        self.logger.info(f"Deleting KB '{kb_name}'")
        pipeline = self._get_pipeline()

        if hasattr(pipeline, "delete"):
            return await pipeline.delete(kb_name=kb_name)

        kb_dir = Path(self.kb_base_dir) / kb_name
        if kb_dir.exists():
            shutil.rmtree(kb_dir)
            self.logger.info(f"Deleted KB directory: {kb_dir}")
            return True
        return False

    async def smart_retrieve(
        self,
        context: str,
        kb_name: str,
        query_hints: Optional[List[str]] = None,
        max_queries: int = 3,
    ) -> Dict[str, Any]:
        from .smart_retriever import SmartRetriever

        return await SmartRetriever(self.search).retrieve(
            context=context,
            kb_name=kb_name,
            query_hints=query_hints,
            max_queries=max_queries,
        )

    @staticmethod
    def list_providers() -> List[Dict[str, str]]:
        return list_pipelines()

    @staticmethod
    def get_current_provider() -> str:
        # ``RAG_PROVIDER`` env var is honoured for visibility but the
        # service only ships with a single backend.
        os.getenv("RAG_PROVIDER")
        return DEFAULT_PROVIDER

    @staticmethod
    def has_provider(name: str) -> bool:
        return (name or "").strip().lower() == DEFAULT_PROVIDER
