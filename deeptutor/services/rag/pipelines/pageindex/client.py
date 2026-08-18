"""Async adapter around the synchronous PageIndex SDK clients."""

from __future__ import annotations

import asyncio
from functools import lru_cache
from pathlib import Path
from typing import Any

from deeptutor.services.provider_registry import find_by_name, strip_provider_prefix

from .config import PageIndexConfig


def _sdk_types():
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
        raise RuntimeError(
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
        raise RuntimeError(
            "PageIndex OSS indexing needs an API-key or local LLM profile; "
            "the active OAuth-only provider cannot be used."
        )

    resolved_model = strip_provider_prefix(model, spec)
    prefix = {
        "anthropic": "anthropic",
        "azure_openai": "azure",
        "openai_compat": "openai",
    }.get(spec.backend)
    if prefix is None:
        raise RuntimeError("The active LLM transport is not supported by PageIndex OSS indexing.")

    sdk_model = _prefixed_model(prefix, resolved_model)
    backend: dict[str, Any] = {}
    api_key = str(getattr(cfg, "api_key", "") or "").strip()
    base_url = str(getattr(cfg, "base_url", "") or "").strip()
    api_version = str(getattr(cfg, "api_version", "") or "").strip()
    headers = getattr(cfg, "extra_headers", None)

    if spec.backend == "openai_compat":
        # PageIndex treats ``openai/...`` as the OpenAI-compatible fast path;
        # this also preserves gateway model ids such as anthropic/claude-*.
        backend["api_key"] = api_key or "sk-no-key-required"
    elif api_key:
        backend["api_key"] = api_key

    if base_url:
        backend["api_base"] = base_url
    if api_version and spec.backend != "openai_compat":
        backend["api_version"] = api_version
    if isinstance(headers, dict) and headers:
        if spec.backend == "openai_compat":
            backend["default_headers"] = dict(headers)
        else:
            backend["extra_headers"] = dict(headers)

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
            wait=True,
        )
        doc_id = result.get("doc_id") if isinstance(result, dict) else None
        if not doc_id:
            raise RuntimeError(f"PageIndex submit_document returned no doc_id: {result!r}")
        return str(doc_id)

    async def delete_document(self, doc_id: str) -> bool:
        await asyncio.to_thread(self.sdk_client.delete_document, doc_id)
        return True


__all__ = [
    "PageIndexClient",
    "resolve_oss_sdk_config",
]
