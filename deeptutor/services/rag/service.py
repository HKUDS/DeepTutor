"""Unified RAG service entry point."""

from __future__ import annotations

import asyncio
import contextlib
import importlib
import inspect
import logging
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from deeptutor.runtime.home import get_runtime_data_root

from .factory import DEFAULT_PROVIDER, get_pipeline, list_pipelines, normalize_provider_name
from .provider_binding import resolve_bound_provider

DEFAULT_KB_BASE_DIR = str(get_runtime_data_root() / "knowledge_bases")


class RAGService:
    """Unified RAG service that routes to a KB's bound pipeline.

    The provider is resolved per knowledge base: an explicit ``provider`` passed
    to the constructor wins (used at create time); otherwise it is read from
    DeepTutor's authoritative KB config, with metadata as a legacy fallback.
    """

    def __init__(
        self,
        kb_base_dir: Optional[str] = None,
        provider: Optional[str] = None,
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
        self._provider_override = normalize_provider_name(provider) if provider else None
        # ``self.provider`` kept for callers that read it directly; the real
        # selection happens per kb_name in ``_resolve_provider``.
        self.provider = self._provider_override or DEFAULT_PROVIDER
        self._pipelines: dict[str, Any] = {}

    def _resolve_provider(self, kb_name: Optional[str]) -> str:
        """Pick the provider for ``kb_name`` from DeepTutor's binding."""
        if self._provider_override:
            return self._provider_override
        return resolve_bound_provider(self.kb_base_dir, kb_name)

    def _get_pipeline(self, provider: str):
        if provider not in self._pipelines:
            self._pipelines[provider] = get_pipeline(name=provider, kb_base_dir=self.kb_base_dir)
        return self._pipelines[provider]

    async def initialize(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        provider = self._resolve_provider(kb_name)
        self.logger.info(f"Initializing KB '{kb_name}' (provider={provider})")
        pipeline = self._get_pipeline(provider)
        return await pipeline.initialize(kb_name=kb_name, file_paths=file_paths, **kwargs)

    async def add_documents(self, kb_name: str, file_paths: List[str], **kwargs) -> bool:
        provider = self._resolve_provider(kb_name)
        self.logger.info(
            f"Adding {len(file_paths)} document(s) to KB '{kb_name}' (provider={provider})"
        )
        pipeline = self._get_pipeline(provider)
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
        provider = self._resolve_provider(kb_name)
        with self._capture_raw_logs(event_sink):
            await self._emit_tool_event(
                event_sink,
                "status",
                f"Query: {query}",
                {"query": query, "kb_name": kb_name, "trace_layer": "summary"},
            )

            self.logger.info(f"Searching KB '{kb_name}' with query: {query[:50]}...")
            pipeline = self._get_pipeline(provider)

            await self._emit_tool_event(
                event_sink,
                "status",
                f"Retrieving from knowledge base '{kb_name}'...",
                {"provider": provider, "trace_layer": "summary"},
            )

            result = await pipeline.search(query=query, kb_name=kb_name, **kwargs)

            if "query" not in result:
                result["query"] = query
            if "answer" not in result and "content" in result:
                result["answer"] = result["content"]
            if "content" not in result and "answer" in result:
                result["content"] = result["answer"]
            # The service is authoritative about which engine ran (resolved from
            # the KB's binding), so it overwrites whatever the pipeline reports.
            result["provider"] = provider

            if result.get("error_type") or result.get("needs_reindex"):
                await self._emit_tool_event(
                    event_sink,
                    "status",
                    result.get("answer") or result.get("content") or "RAG search failed.",
                    {
                        "provider": provider,
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
                    "provider": provider,
                    "kb_name": kb_name,
                    "trace_layer": "summary",
                },
            )

            # L1 memory trace — best-effort, never blocks the search path.
            try:
                from deeptutor.services.memory import get_memory_store
                from deeptutor.services.memory.trace import TraceEvent

                await get_memory_store().emit(
                    TraceEvent.new(
                        "kb",
                        "query",
                        {
                            "query": query,
                            "kb_name": kb_name,
                            "answer_chars": len(answer),
                        },
                    )
                )
            except Exception:
                pass

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
        if event_sink is None:
            return contextlib.nullcontext()

        from deeptutor.logging import ProcessLogEvent, capture_process_logs
        from deeptutor.logging.formatters import ContextFilter

        try:
            target_loop = asyncio.get_running_loop()
        except RuntimeError:
            target_loop = None

        def should_skip_noisy_retrieve_log(event: ProcessLogEvent) -> bool:
            if event.level != "INFO":
                return False
            message = event.message.strip()
            logger_name = event.logger
            if logger_name == "nano-vectordb" and (
                message.startswith("Load ") or message.startswith("Init ")
            ):
                return True
            if (
                logger_name.startswith("deeptutor.services.embedding.")
                and (
                    message.startswith("Successfully generated ")
                    or message.startswith("Generated ")
                )
                and "embedding" in message.lower()
            ):
                return True
            return False

        def emit(event):
            if should_skip_noisy_retrieve_log(event):
                return None
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

        class _NamedRawLogHandler(logging.Handler):
            def __init__(self) -> None:
                super().__init__(logging.INFO)
                self.addFilter(ContextFilter())

            def emit(self, record: logging.LogRecord) -> None:
                try:
                    result = emit(ProcessLogEvent.from_record(record))
                    if not inspect.isawaitable(result):
                        return
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        if target_loop and target_loop.is_running():
                            asyncio.run_coroutine_threadsafe(result, target_loop)
                        return
                    asyncio.ensure_future(result, loop=loop)
                except Exception:
                    self.handleError(record)

        @contextlib.contextmanager
        def capture_non_propagating_logs():
            handlers: list[tuple[logging.Logger, logging.Handler]] = []
            for logger_name in ("lightrag", "graphrag", "graphrag_llm"):
                if logger_name == "lightrag":
                    with contextlib.suppress(Exception):
                        importlib.import_module("lightrag.utils")
                source_logger = logging.getLogger(logger_name)
                if source_logger.propagate:
                    continue
                handler = _NamedRawLogHandler()
                source_logger.addHandler(handler)
                handlers.append((source_logger, handler))
            try:
                yield
            finally:
                for source_logger, handler in handlers:
                    if handler in source_logger.handlers:
                        source_logger.removeHandler(handler)
                    handler.close()

        @contextlib.contextmanager
        def capture_all_raw_logs():
            with capture_process_logs(emit, min_level=logging.INFO):
                with capture_non_propagating_logs():
                    yield

        return capture_all_raw_logs()

    async def delete(self, kb_name: str) -> bool:
        provider = self._resolve_provider(kb_name)
        self.logger.info(f"Deleting KB '{kb_name}' (provider={provider})")
        pipeline = self._get_pipeline(provider)

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
        # Global default; per-KB selection happens in ``_resolve_provider``.
        return normalize_provider_name(os.getenv("RAG_PROVIDER"))

    @staticmethod
    def has_provider(name: str) -> bool:
        from .factory import KNOWN_PROVIDERS

        return (name or "").strip().lower() in KNOWN_PROVIDERS
