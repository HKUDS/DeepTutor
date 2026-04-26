"""Unified RAG service entry point."""

from __future__ import annotations

import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from deeptutor.logging import get_logger

from .factory import DEFAULT_PROVIDER, get_pipeline, list_pipelines


class _RAGRawLogHandler(logging.Handler):
    def __init__(self, event_sink, loop) -> None:
        super().__init__(level=logging.DEBUG)
        self._event_sink = event_sink
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        if self._event_sink is None:
            return
        try:
            module_name = getattr(record, "module_name", record.name.split(".")[-1])
            level_name = getattr(record, "display_level", record.levelname)
            message = record.getMessage()
            line = f"[{module_name}] {level_name}: {message}".strip()
            if not line:
                return

            async def _emit() -> None:
                await self._event_sink(
                    "raw_log",
                    line,
                    {
                        "trace_layer": "raw",
                        "logger_name": record.name,
                        "log_level": level_name,
                        "module_name": module_name,
                    },
                )

            self._loop.create_task(_emit())
        except Exception:
            pass


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
        self.logger = get_logger("RAGService")
        self.kb_base_dir = kb_base_dir or DEFAULT_KB_BASE_DIR
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
        import asyncio
        from contextlib import ExitStack, contextmanager

        @contextmanager
        def _manager():
            if event_sink is None:
                yield
                return

            loop = asyncio.get_running_loop()
            handler = _RAGRawLogHandler(event_sink, loop)
            handler.setLevel(logging.DEBUG)
            targets = [
                logging.getLogger(name)
                for name in (
                    "deeptutor.RAGService",
                    "deeptutor.RAGForward",
                    "deeptutor.LlamaIndexPipeline",
                )
            ]
            with ExitStack() as stack:
                for logger in targets:
                    logger.addHandler(handler)
                    stack.callback(logger.removeHandler, handler)
                try:
                    yield
                finally:
                    handler.close()

        return _manager()

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
        import asyncio

        queries = query_hints if query_hints else await self._generate_queries(context, max_queries)

        tasks = [self.search(query=q, kb_name=kb_name) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        passages: list[str] = []
        all_sources: list[dict] = []
        for r in results:
            if isinstance(r, Exception):
                continue
            content = r.get("content") or r.get("answer") or ""
            if content:
                passages.append(content)
                all_sources.append({"query": r.get("query", ""), "provider": r.get("provider", "")})

        if not passages:
            return {"answer": "", "sources": []}

        aggregated = await self._aggregate(context, passages)
        return {"answer": aggregated, "sources": all_sources}

    async def _generate_queries(self, context: str, n: int) -> list[str]:
        try:
            from deeptutor.services.llm import complete

            prompt = (
                f"Generate {n} diverse search queries to retrieve information relevant "
                f"to the following context. Return ONLY the queries, one per line.\n\n"
                f"Context:\n{context[:2000]}"
            )
            raw = await complete(prompt, system_prompt="You are a search query generator.")
            lines = [
                line.strip().lstrip("0123456789.-) ")
                for line in raw.strip().split("\n")
                if line.strip()
            ]
            return lines[:n] if lines else [context[:200]]
        except Exception:
            return [context[:200]]

    async def _aggregate(self, context: str, passages: list[str]) -> str:
        try:
            from deeptutor.services.llm import complete

            combined = "\n---\n".join(passages)
            prompt = (
                "Synthesise the following retrieved passages into a concise, "
                "relevant summary for the given context.\n\n"
                f"Context:\n{context[:1000]}\n\n"
                f"Passages:\n{combined[:6000]}"
            )
            return await complete(prompt, system_prompt="You are a knowledge synthesiser.")
        except Exception:
            return "\n\n".join(passages)

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
