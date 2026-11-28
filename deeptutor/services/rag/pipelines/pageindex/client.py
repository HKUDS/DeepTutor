"""Async adapter around the synchronous PageIndex SDK clients."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path
from typing import Any

from deeptutor.services.provider_registry import find_by_name, strip_provider_prefix
from deeptutor.services.rag.pipelines.oauth_completion import (
    OAUTH_PROVIDER,
    OAuthCompletion,
    oauth_binding,
)

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


def _resolve_index_model():
    """Use the background Task model when configured, otherwise the chat model."""
    from deeptutor.services.config import resolve_llm_runtime_config
    from deeptutor.services.model_selection.tasks import TASK_SERVICE, task_service_configured

    if task_service_configured():
        return resolve_llm_runtime_config(service_name=TASK_SERVICE)
    return resolve_llm_runtime_config()


def resolve_oss_sdk_config() -> tuple[str, dict[str, Any]]:
    """Translate DeepTutor's indexing model into PageIndex's indexing lane."""
    return _oss_sdk_config(_resolve_index_model())


def _oss_sdk_config(cfg: Any) -> tuple[str, dict[str, Any]]:
    model = str(getattr(cfg, "model", "") or "").strip()
    binding = str(
        getattr(cfg, "binding", None) or getattr(cfg, "provider_name", None) or "openai"
    ).strip()
    spec = find_by_name(binding)
    if not model:
        raise RuntimeError("PageIndex OSS needs an LLM. Configure one under Settings → Catalog.")
    if oauth_binding(cfg):
        return _prefixed_model(OAUTH_PROVIDER, model), {}
    if spec is None:
        raise RuntimeError("The active LLM transport is not supported by PageIndex OSS indexing.")

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

    if spec.backend == "anthropic":
        # litellm appends /v1/messages itself; a base ending in /v1 would 404.
        base_url = base_url.rstrip("/").removesuffix("/v1")
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

    def __init__(self, sdk_client: Any, oauth_completion: OAuthCompletion | None = None) -> None:
        self.sdk_client = sdk_client
        self._oauth_completion = oauth_completion

    @classmethod
    def cloud(cls, config: PageIndexConfig) -> "PageIndexClient":
        return cls(_cloud_sdk_client(config.api_key))

    @classmethod
    def local(cls, storage_path: str | Path) -> "PageIndexClient":
        from deeptutor.services.model_selection.runtime import llm_config_from_resolved

        _, local_type = _sdk_types()
        cfg = _resolve_index_model()
        model, backend = _oss_sdk_config(cfg)
        oauth_completion = (
            OAuthCompletion.for_current_user(llm_config_from_resolved(cfg))
            if oauth_binding(cfg)
            else None
        )
        return cls(
            local_type(
                storage_path=str(storage_path),
                index_model=model,
                summary_model=model,
                index_backend=backend or None,
            ),
            oauth_completion,
        )

    @classmethod
    def local_read(cls, storage_path: str | Path) -> "PageIndexClient":
        """Open an existing Local Library without resolving indexing credentials."""
        _, local_type = _sdk_types()
        return cls(local_type(storage_path=str(storage_path)))

    async def submit_document(self, file_path: str | Path, *, mode: str | None = None) -> str:
        scope = self._oauth_completion.activate() if self._oauth_completion else nullcontext()
        with scope:
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
