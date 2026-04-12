from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import os
from threading import Lock
import threading
import time
from typing import Any
from uuid import uuid4

from .env_store import get_env_store
from .model_catalog import get_model_catalog_service
from .provider_runtime import resolve_search_runtime_config


def _redact(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


@contextmanager
def temporary_env(values: dict[str, str]):
    original = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@dataclass
class TestRun:
    id: str
    service: str
    status: str = "running"
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)
    cancelled: bool = False

    def emit(self, kind: str, message: str, **extra: Any) -> None:
        payload = {
            "type": kind,
            "message": message,
            "timestamp": time.time(),
            **extra,
        }
        with self.lock:
            self.events.append(payload)

    def snapshot(self, start: int) -> list[dict[str, Any]]:
        with self.lock:
            return self.events[start:]


class ConfigTestRunner:
    _instance: "ConfigTestRunner | None" = None

    def __init__(self) -> None:
        self._runs: dict[str, TestRun] = {}
        self._lock = Lock()

    @classmethod
    def get_instance(cls) -> "ConfigTestRunner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self, service: str, catalog: dict[str, Any] | None = None) -> TestRun:
        run = TestRun(id=f"{service}-{uuid4().hex[:10]}", service=service)
        with self._lock:
            self._runs[run.id] = run
        resolved = catalog or get_model_catalog_service().load()
        thread = threading.Thread(target=self._run_sync, args=(run, resolved), daemon=True)
        thread.start()
        return run

    def get(self, run_id: str) -> TestRun:
        return self._runs[run_id]

    def cancel(self, run_id: str) -> None:
        self.get(run_id).cancelled = True

    def _run_sync(self, run: TestRun, catalog: dict[str, Any]) -> None:
        try:
            env_values = get_env_store().render_from_catalog(catalog)
            service = run.service
            profile = get_model_catalog_service().get_active_profile(catalog, service)
            model = get_model_catalog_service().get_active_model(catalog, service)

            run.emit("info", "Preparing configuration snapshot.")
            if profile:
                run.emit(
                    "config",
                    "Using active profile.",
                    profile={
                        "name": profile.get("name", ""),
                        "base_url": profile.get("base_url", ""),
                        "binding": profile.get("binding") or profile.get("provider"),
                        "api_key": _redact(str(profile.get("api_key", ""))),
                        "api_version": profile.get("api_version", ""),
                    },
                    model=model,
                )

            with temporary_env(env_values):
                if service == "llm":
                    asyncio.run(self._test_llm(run))
                elif service == "embedding":
                    asyncio.run(self._test_embedding(run, model or {}))
                elif service == "search":
                    self._test_search(run)
                else:
                    raise ValueError(f"Unsupported service: {service}")
            if not run.cancelled and run.status == "running":
                run.status = "completed"
                run.emit("completed", f"{service.upper()} test completed successfully.")
        except Exception as exc:
            run.status = "failed"
            run.emit("failed", str(exc))

    async def _test_llm(self, run: TestRun) -> None:
        from deeptutor.services.llm import clear_llm_config_cache, complete as llm_complete
        from deeptutor.services.llm import get_llm_config, get_token_limit_kwargs

        clear_llm_config_cache()
        run.emit("info", "Loading LLM config from the active catalog selection.")
        llm_config = get_llm_config()
        run.emit("info", f"Resolved model `{llm_config.model}` with binding `{llm_config.binding}`.")
        run.emit("info", f"Request target: {llm_config.base_url}")
        token_kwargs = get_token_limit_kwargs(llm_config.model, max_tokens=200)
        run.emit("info", f"Token options: {json.dumps(token_kwargs)}")
        response = await llm_complete(
            model=llm_config.model,
            prompt="Say 'OK' and identify the model you are using.",
            system_prompt="Respond briefly but include your model identity if possible.",
            binding=llm_config.binding,
            api_key=llm_config.api_key or "sk-no-key-required",
            base_url=llm_config.base_url or "",
            temperature=0.1,
            **token_kwargs,
        )
        snippet = (response or "").strip()
        run.emit("response", "Received LLM response.", snippet=snippet[:400])
        if not snippet:
            raise ValueError("LLM returned an empty response.")

    async def _test_embedding(self, run: TestRun, model: dict[str, Any]) -> None:
        from deeptutor.services.embedding import get_embedding_client, get_embedding_config

        run.emit("info", "Loading embedding config from the active catalog selection.")
        config = get_embedding_config()
        run.emit("info", f"Resolved embedding model `{config.model}` with binding `{config.binding}`.")
        run.emit("info", f"Request target: {config.base_url}")
        client = get_embedding_client()
        vectors = await client.embed(["DeepTutor embedding smoke test"])
        if not vectors or not vectors[0]:
            raise ValueError("Embedding service returned an empty vector.")
        actual_dimension = len(vectors[0])
        expected_dimension = int(str(model.get("dimension") or config.dim or 0))
        run.emit(
            "response",
            "Embedding vector received.",
            actual_dimension=actual_dimension,
            expected_dimension=expected_dimension,
        )
        if expected_dimension and actual_dimension != expected_dimension:
            raise ValueError(
                f"Embedding dimension mismatch. expected={expected_dimension}, actual={actual_dimension}"
            )

    def _test_search(self, run: TestRun) -> None:
        from deeptutor.services.search import web_search

        resolved = resolve_search_runtime_config()
        if not resolved.requested_provider:
            run.status = "completed"
            run.emit("completed", "Search skipped because no active provider is configured.")
            return
        if resolved.unsupported_provider:
            raise ValueError(
                f"Search provider `{resolved.requested_provider}` is deprecated/unsupported. "
                "Switch to brave/tavily/jina/searxng/duckduckgo/perplexity."
            )
        if resolved.missing_credentials:
            raise ValueError(
                f"Search provider `{resolved.requested_provider}` requires api_key. "
                "Set profile.api_key or PERPLEXITY_API_KEY."
            )
        provider = resolved.provider
        run.emit("info", f"Resolved search provider `{provider}`.")
        if resolved.fallback_reason:
            run.emit("warning", resolved.fallback_reason)
        run.emit("info", "Running search query: DeepTutor configuration health check")
        result = web_search("DeepTutor configuration health check", provider=provider)
        run.emit(
            "response",
            "Search result received.",
            answer_preview=str(result.get("answer", ""))[:240],
            citation_count=len(result.get("citations", []) or []),
            search_result_count=len(result.get("search_results", []) or []),
        )
        if not (result.get("answer") or result.get("search_results")):
            raise ValueError("Search provider returned no answer and no search results.")


def get_config_test_runner() -> ConfigTestRunner:
    return ConfigTestRunner.get_instance()


__all__ = ["ConfigTestRunner", "TestRun", "get_config_test_runner", "temporary_env"]
