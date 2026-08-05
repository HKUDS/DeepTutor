"""MED-02 provider adapters and the job executor router.

The :class:`MediaAdapterRouter` implements the worker's
:class:`~deeptutor.services.media.worker.JobExecutor` contract: each job is
dispatched to the adapter for its protocol (Images API, Responses image tool or
MCP), the adapter resolves its secret-bearing config from the model catalog at
execution time, and the router owns the shared HTTP/downloader resources so
background polling and cancel reuse the same connection pool.
"""

from __future__ import annotations

from typing import Any

import httpx

from deeptutor.services.media.adapter_config import (
    ADAPTER_MCP,
    ADAPTER_OPENAI_IMAGES,
    ADAPTER_OPENAI_RESPONSES,
    AdapterConfigResolver,
    AdapterRuntimeConfig,
)
from deeptutor.services.media.adapters.base import UnsupportedOperationError
from deeptutor.services.media.adapters.mcp import McpMediaAdapter
from deeptutor.services.media.adapters.openai_images import OpenAIImagesAdapter
from deeptutor.services.media.adapters.openai_responses import (
    OpenAIResponsesImageAdapter,
)
from deeptutor.services.media.models import (
    BackgroundSubmit,
    ImageGenerationJob,
    MediaError,
    MediaInput,
    PollOutcome,
)
from deeptutor.services.media.resolver import default_resolver
from deeptutor.services.media.safe_download import SafeDownloader
from deeptutor.services.media.store import MediaStore


class MediaAdapterRouter:
    """Dispatches each job to the adapter for its protocol (§10)."""

    def __init__(
        self,
        *,
        store: MediaStore,
        mcp_manager: Any | None = None,
        resolver: AdapterConfigResolver | None = None,
        http_client: httpx.AsyncClient | None = None,
        downloader: SafeDownloader | None = None,
    ) -> None:
        self._store = store
        self._manager = mcp_manager
        self._resolver = resolver or default_resolver()
        self._http_client = http_client
        self._owns_http_client = http_client is None
        self._downloader = downloader
        self._owns_downloader = downloader is None
        # Built adapters, keyed by the *complete* resolved runtime config.  The
        # job is resolved on every run/poll/cancel boundary before this cache is
        # consulted, so a different model, profile removal, or any endpoint /
        # credential / config change can never alias onto an older adapter.
        # Config objects (which carry the api key) are held in memory only and
        # are never logged or persisted.
        self._adapters: list[tuple[AdapterRuntimeConfig, Any]] = []

    async def aclose(self) -> None:
        for _config, adapter in self._adapters:
            closer = getattr(adapter, "aclose", None)
            if closer is not None:
                try:
                    await closer()
                except Exception:  # noqa: BLE001 - best-effort close
                    pass
        self._adapters.clear()
        if self._owns_http_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        if self._owns_downloader and self._downloader is not None:
            await self._downloader.aclose()
            self._downloader = None

    def _http_client_for(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=60.0, trust_env=False)
        return self._http_client

    def _downloader_for(self) -> SafeDownloader:
        if self._downloader is None:
            self._downloader = SafeDownloader(limits=self._store.limits)
        return self._downloader

    def _adapter_for(self, job: ImageGenerationJob) -> Any:
        # Resolve the job on every run/poll/cancel boundary (§11.3): the durable
        # job's explicit profile/model are authoritative, and a removed or
        # changed catalog entry fails closed here — before any cached adapter
        # can be reused or any provider called.
        config = self._resolver(job)
        # Reuse an adapter only when the resolved config is identical in every
        # routing-relevant field (adapter kind, base URL, provider model, auth
        # style, credentials, headers, capability flags, MCP mapping).  A
        # different catalog model id or a changed endpoint/credential therefore
        # builds a fresh adapter instead of reusing a stale one.
        for cached_config, adapter in self._adapters:
            if cached_config == config:
                return adapter
        adapter = self._build(config)
        self._adapters.append((config, adapter))
        return adapter

    def _build(self, config: AdapterRuntimeConfig) -> Any:
        if config.adapter_kind == ADAPTER_OPENAI_RESPONSES:
            return OpenAIResponsesImageAdapter(
                config=config,
                store=self._store,
                downloader=self._downloader_for(),
                limits=self._store.limits,
            )
        if config.adapter_kind == ADAPTER_MCP:
            if self._manager is None:
                raise MediaError("No MCP manager is configured for the MCP image profile.")
            return McpMediaAdapter(
                config=config,
                store=self._store,
                mcp_manager=self._manager,
                downloader=self._downloader_for(),
                limits=self._store.limits,
            )
        if config.adapter_kind == ADAPTER_OPENAI_IMAGES:
            return OpenAIImagesAdapter(
                config=config,
                store=self._store,
                client=self._http_client_for(),
                downloader=self._downloader_for(),
                limits=self._store.limits,
            )
        raise MediaError(f"Unknown adapter kind {config.adapter_kind!r}.")

    # ── JobExecutor contract ─────────────────────────────────────────────────

    async def run(self, job: ImageGenerationJob) -> list[MediaInput] | BackgroundSubmit:
        return await self._adapter_for(job).run(job)

    async def poll(self, job: ImageGenerationJob) -> PollOutcome:
        return await self._adapter_for(job).poll(job)

    async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
        return await self._adapter_for(job).confirm_cancel(job)


__all__ = [
    "ADAPTER_MCP",
    "ADAPTER_OPENAI_IMAGES",
    "ADAPTER_OPENAI_RESPONSES",
    "McpMediaAdapter",
    "MediaAdapterRouter",
    "OpenAIImagesAdapter",
    "OpenAIResponsesImageAdapter",
    "UnsupportedOperationError",
    "default_resolver",
]
