"""Async adapter around the synchronous PageIndex SDK clients."""

from __future__ import annotations

import asyncio
from functools import lru_cache
import importlib.util
from pathlib import Path
from typing import Any

from deeptutor.services.provider_registry import find_by_name, strip_provider_prefix

from .config import (
    PageIndexConfig,
    PageIndexOSSNotConfiguredError,
    PageIndexSDKNotAvailableError,
)

_TERMINAL_OK = {"completed", "complete", "done", "ready", "success", "finished"}
_TERMINAL_FAIL = {"failed", "error", "cancelled", "canceled"}


def is_pageindex_sdk_available() -> bool:
    return importlib.util.find_spec("pageindex") is not None


def _sdk_types():
    if not is_pageindex_sdk_available():
        raise PageIndexSDKNotAvailableError(
            "PageIndex SDK is not installed. Install pageindex==0.2.10.dev5."
        )
    from pageindex import PageIndexCloudClient, PageIndexLocalClient

    return PageIndexCloudClient, PageIndexLocalClient


@lru_cache(maxsize=1)
def _cloud_sdk_client(api_key: str):
    """Reuse the SDK's MCP bridge until the global Cloud key changes."""
    cloud_type, _ = _sdk_types()
    return cloud_type(api_key)


def _prefixed_model(prefix: str, model: str) -> str:
    return model if model.startswith(f"{prefix}/") else f"{prefix}/{model}"


def resolve_oss_sdk_config() -> tuple[str, dict[str, Any]]:
    """Translate DeepTutor's active LLM into PageIndex's indexing lane."""
    from deeptutor.services.config import resolve_llm_runtime_config

    cfg = resolve_llm_runtime_config()
    model = str(getattr(cfg, "model", "") or "").strip()
    binding = str(
        getattr(cfg, "binding", None) or getattr(cfg, "provider_name", None) or "openai"
    ).strip()
    spec = find_by_name(binding)
    if not model:
        raise PageIndexOSSNotConfiguredError(
            "PageIndex OSS needs an active LLM. Configure one under Settings → Catalog."
        )
    if (
        spec is None
        or spec.is_oauth
        or spec.backend
        in {
            "openai_codex",
            "github_copilot",
            "codebuddy",
        }
    ):
        raise PageIndexOSSNotConfiguredError(
            "PageIndex OSS indexing needs an API-key or local LLM profile; "
            "the active OAuth-only provider cannot be used."
        )

    resolved_model = strip_provider_prefix(model, spec)
    backend: dict[str, Any] = {}
    api_key = str(getattr(cfg, "api_key", "") or "").strip()
    base_url = str(getattr(cfg, "base_url", "") or "").strip()
    api_version = str(getattr(cfg, "api_version", "") or "").strip()
    headers = getattr(cfg, "extra_headers", None)

    if spec.backend == "anthropic":
        sdk_model = _prefixed_model("anthropic", resolved_model)
        if api_key:
            backend["api_key"] = api_key
        if base_url:
            backend["api_base"] = base_url
        if api_version:
            backend["api_version"] = api_version
        if isinstance(headers, dict) and headers:
            backend["extra_headers"] = dict(headers)
    elif spec.backend == "azure_openai":
        sdk_model = _prefixed_model("azure", resolved_model)
        if api_key:
            backend["api_key"] = api_key
        if base_url:
            backend["api_base"] = base_url
        if api_version:
            backend["api_version"] = api_version
        if isinstance(headers, dict) and headers:
            backend["extra_headers"] = dict(headers)
    elif spec.backend == "openai_compat":
        # PageIndex treats ``openai/...`` as the OpenAI-compatible fast path;
        # this also preserves gateway model ids such as anthropic/claude-*.
        sdk_model = _prefixed_model("openai", resolved_model)
        backend["api_key"] = api_key or "sk-no-key-required"
        if base_url:
            backend["api_base"] = base_url
        if isinstance(headers, dict) and headers:
            backend["default_headers"] = dict(headers)
    else:
        raise PageIndexOSSNotConfiguredError(
            "The active LLM transport is not supported by PageIndex OSS indexing."
        )

    return sdk_model, backend


class PageIndexClient:
    """Small async facade used by the DeepTutor RAG lifecycle."""

    def __init__(self, sdk_client: Any) -> None:
        self.sdk_client = sdk_client

    @classmethod
    def cloud(cls, config: PageIndexConfig) -> "PageIndexClient":
        return cls(_cloud_sdk_client(config.api_key))

    @classmethod
    def local(cls, storage_path: str | Path) -> "PageIndexClient":
        _, local_type = _sdk_types()
        model, backend = resolve_oss_sdk_config()
        return cls(
            local_type(
                storage_path=str(storage_path),
                index_model=model,
                summary_model=model,
                index_backend=backend,
            )
        )

    @classmethod
    def local_read(cls, storage_path: str | Path) -> "PageIndexClient":
        """Open an existing Local Library without resolving indexing credentials."""
        _, local_type = _sdk_types()
        return cls(local_type(storage_path=str(storage_path)))

    async def submit_document(self, file_path: str | Path, *, mode: str | None = None) -> str:
        result = await asyncio.to_thread(
            self.sdk_client.submit_document,
            str(file_path),
            mode=mode,
        )
        doc_id = result.get("doc_id") if isinstance(result, dict) else None
        if not doc_id:
            raise RuntimeError(f"PageIndex submit_document returned no doc_id: {result!r}")
        return str(doc_id)

    async def get_document(self, doc_id: str) -> dict[str, Any]:
        result = await asyncio.to_thread(self.sdk_client.get_document, doc_id)
        return result if isinstance(result, dict) else {}

    async def wait_until_ready(
        self,
        doc_id: str,
        *,
        poll_interval: float = 3.0,
        max_attempts: int = 600,
    ) -> dict[str, Any]:
        for _ in range(max_attempts):
            data = await self.get_document(doc_id)
            status = str(data.get("status") or "").strip().lower()
            if status in _TERMINAL_FAIL:
                raise RuntimeError(f"PageIndex processing failed for {doc_id}: {data!r}")
            if status in _TERMINAL_OK:
                return data
            await asyncio.sleep(poll_interval)
        raise RuntimeError(
            f"PageIndex processing timed out for {doc_id} after {max_attempts} polls"
        )

    async def delete_document(self, doc_id: str) -> bool:
        await asyncio.to_thread(self.sdk_client.delete_document, doc_id)
        return True


__all__ = [
    "PageIndexClient",
    "is_pageindex_sdk_available",
    "resolve_oss_sdk_config",
]
