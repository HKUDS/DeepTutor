"""MCP configured image-tool adapter (MED-02).

A user configures an MCP server + tool and the argument mapping
(:class:`~deeptutor.services.media.adapter_config.McpImageToolConfig`):
``prompt_arg`` plus optional ``size_arg``/``count_arg``/``static_args``.
Edit is available only when the config explicitly declares ``source_arg`` /
``mask_arg``; otherwise an edit request raises a stable
``unsupported_operation`` and is never silently turned into a generate (§10.4).

The tool result is read through the manager's structured path, preserving
``TextContent``, ``ImageContent``, ``EmbeddedResource`` and ``ResourceLink``.
``ImageContent`` is decoded directly; resource/URL payloads are materialized
through the same safe downloader used by every other adapter.  Progress
notifications are optional metadata, never proof of success.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Any

from deeptutor.services.media.adapter_config import (
    ADAPTER_MCP,
    AdapterRuntimeConfig,
    McpImageToolConfig,
)
from deeptutor.services.media.adapters.base import (
    ImageGenerationRequest,
    UnsupportedOperationError,
    request_from_job,
)
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.media_validation import validate_edit_inputs
from deeptutor.services.media.models import (
    ArtifactOperation,
    BackgroundSubmit,
    ImageGenerationJob,
    MediaError,
    MediaInput,
)
from deeptutor.services.media.redaction import redact_text
from deeptutor.services.media.safe_download import SafeDownloader, validate_media_bytes
from deeptutor.services.media.store import MediaStore

logger = logging.getLogger(__name__)

#: Owner key for deployment-administered MCP servers (mirrors
#: ``deeptutor.services.mcp.manager.SHARED_OWNER``; kept literal to avoid an
#: import cycle in this low-level package).
_SHARED_OWNER = "_shared"


def _safe_asset_id(uri: str) -> str:
    """A durable, non-sensitive identity for a remote resource URI.

    A full ``ResourceLink`` / embedded-resource URI may carry a private host,
    path, query, or credentials; it must never be persisted as
    ``remote_asset_id`` (§10.5/§14).  We store a short content hash so dedup
    and provenance still work without leaking the endpoint.
    """
    if not uri:
        return ""
    return "uri-" + hashlib.sha256(uri.encode("utf-8")).hexdigest()[:16]


def _data_uri(data: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


class McpMediaAdapter:
    """Synchronous MCP tool adapter (no background/poll/cancel)."""

    def __init__(
        self,
        *,
        config: AdapterRuntimeConfig,
        store: MediaStore,
        mcp_manager: Any,
        downloader: SafeDownloader | None = None,
        limits: MediaLimits | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._limits = limits or store.limits
        self._manager = mcp_manager
        self._downloader = downloader
        self._owns_downloader = downloader is None

    @property
    def kind(self) -> str:
        return ADAPTER_MCP

    async def aclose(self) -> None:
        if self._owns_downloader and self._downloader is not None:
            await self._downloader.aclose()

    # ── executor contract ────────────────────────────────────────────────────

    async def run(self, job: ImageGenerationJob) -> list[MediaInput] | BackgroundSubmit:
        request = request_from_job(job)
        mcp_config = self._config.mcp
        if mcp_config is None:
            raise MediaError("No MCP image tool is configured for this profile.")
        if request.operation == ArtifactOperation.EDIT:
            if not mcp_config.supports_edit:
                raise UnsupportedOperationError(
                    "edit", detail="the MCP tool declares no source/mask mapping"
                )
            arguments = self._build_edit_args(job, request, mcp_config)
        else:
            arguments = self._build_generate_args(request, mcp_config)

        owner = mcp_config.owner or _SHARED_OWNER
        result = await self._manager.call_tool_structured(
            owner,
            mcp_config.server_name,
            mcp_config.tool_name,
            arguments,
            timeout=job.read_timeout_seconds,
            on_progress=None,
        )
        if result.is_error:
            raise MediaError(redact_text(result.to_text()))

        media: list[MediaInput] = []
        downloader = await self._downloader_for()
        for block in result.blocks:
            payload = block.to_media_payload()
            if payload is not None:
                sniffed, _w, _h = validate_media_bytes(payload, limits=self._limits)
                media.append(
                    MediaInput(
                        data=payload,
                        mime_type=sniffed,
                        remote_asset_id=_safe_asset_id(block.uri or ""),
                    )
                )
                continue
            # ResourceLink / remote blob resource: materialize via the safe
            # downloader (never a raw fetch).  The URI is never persisted
            # verbatim — only a safe hash identity (§14).
            if block.kind == "resource_link" and block.uri:
                downloaded = await downloader.download(
                    block.uri, declared_mime=block.mime_type or ""
                )
                media.append(
                    MediaInput(
                        data=downloaded.data,
                        mime_type=downloaded.mime_type,
                        remote_asset_id=_safe_asset_id(block.uri),
                    )
                )
            elif block.kind == "resource" and block.uri and not block.resource_text:
                downloaded = await downloader.download(
                    block.uri, declared_mime=block.mime_type or ""
                )
                media.append(
                    MediaInput(
                        data=downloaded.data,
                        mime_type=downloaded.mime_type,
                        remote_asset_id=_safe_asset_id(block.uri),
                    )
                )
            # TextContent / text resources are progress/prose, not images.
        if not media:
            raise MediaError("MCP image tool returned no image content.")
        return media

    async def poll(self, job: ImageGenerationJob) -> Any:
        # MCP tool calls are synchronous; a POLLING job is never routed here.
        raise UnsupportedOperationError("poll")

    async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
        # MCP has no remote cancellation contract.
        return False

    # ── argument mapping ─────────────────────────────────────────────────────

    def _build_generate_args(
        self, request: ImageGenerationRequest, config: McpImageToolConfig
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            config.prompt_arg: request.prompt,
            **dict(config.static_args or {}),
        }
        if config.size_arg and request.size:
            arguments[config.size_arg] = request.size
        if config.count_arg and request.count:
            arguments[config.count_arg] = request.count
        return arguments

    def _build_edit_args(
        self,
        job: ImageGenerationJob,
        request: ImageGenerationRequest,
        config: McpImageToolConfig,
    ) -> dict[str, Any]:
        sources, mask = validate_edit_inputs(self._store, job, limits=self._limits)
        arguments = self._build_generate_args(request, config)
        if config.source_arg:
            source = sources[0]
            arguments[config.source_arg] = _data_uri(source.data, source.mime_type)
        if config.mask_arg and mask is not None:
            arguments[config.mask_arg] = _data_uri(mask.data, mask.mime_type)
        return arguments

    async def _downloader_for(self) -> SafeDownloader:
        if self._downloader is None:
            self._downloader = SafeDownloader(limits=self._limits, read_timeout=1800.0)
        return self._downloader


__all__ = ["McpMediaAdapter", "_data_uri", "_safe_asset_id"]
