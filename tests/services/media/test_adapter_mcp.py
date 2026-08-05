"""MED-02 MCP media adapter tests (offline fixtures).

Uses a fake MCP manager returning structured results so no MCP server is ever
contacted.  Verifies prompt/size/count/static argument mapping, edit source/mask
mapping via data URIs, unsupported-edit fail-closed, ImageContent decoding,
ResourceLink/EmbeddedResource materialization through the safe downloader, and
error propagation.
"""

from __future__ import annotations

import base64
import json
from typing import Any
import uuid

import httpx
import pytest

from deeptutor.services.mcp.manager import MCPContentBlock, MCPStructuredResult
from deeptutor.services.media.adapter_config import (
    ADAPTER_MCP,
    AdapterRuntimeConfig,
    McpImageToolConfig,
)
from deeptutor.services.media.adapters import McpMediaAdapter
from deeptutor.services.media.models import (
    ArtifactOperation,
    GeneratedArtifact,
    ImageJobStatus,
)
from deeptutor.services.media.safe_download import SafeDownloader
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.worker import ImageGenerationJobWorker
from tests.services.media._media_helpers import make_png


def _png_b64() -> str:
    return base64.b64encode(make_png(8, 8)).decode("ascii")


class FakeMcpManager:
    def __init__(self, result: MCPStructuredResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def call_tool_structured(
        self,
        owner: str,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: int,
        on_progress: Any = None,
    ) -> MCPStructuredResult:
        self.calls.append(
            {
                "owner": owner,
                "server": server_name,
                "tool": tool_name,
                "args": dict(arguments),
                "timeout": timeout,
            }
        )
        return self._result


def _mcp_config(source_arg: str = "", mask_arg: str = "") -> McpImageToolConfig:
    return McpImageToolConfig(
        server_name="images",
        tool_name="make",
        prompt_arg="prompt",
        size_arg="size",
        count_arg="count",
        static_args={"style": "watercolor"},
        source_arg=source_arg,
        mask_arg=mask_arg,
        owner="u1",
    )


def _runtime_config(mcp: McpImageToolConfig) -> AdapterRuntimeConfig:
    return AdapterRuntimeConfig(
        adapter_kind=ADAPTER_MCP,
        model="mcp-image",
        supports_edit=mcp.supports_edit,
        mcp=mcp,
    )


def _adapter(
    store: MediaStore,
    manager: FakeMcpManager,
    mcp: McpImageToolConfig | None = None,
    *,
    handler=None,
) -> McpMediaAdapter:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler or (lambda req: httpx.Response(404))),
        follow_redirects=False,
    )
    downloader = SafeDownloader(
        limits=store.limits,
        client=client,
        resolver=lambda host: ["93.184.216.34"],
    )
    return McpMediaAdapter(
        config=_runtime_config(mcp or _mcp_config()),
        store=store,
        mcp_manager=manager,
        downloader=downloader,
    )


def _persisted_artifact(
    store: MediaStore,
    *,
    user_id: str = "u1",
    width: int = 8,
    height: int = 8,
) -> GeneratedArtifact:
    saved = store.persistence.save_media(make_png(width, height), mime_type="image/png")
    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id=user_id,
        session_id="sess-a",
        sha256=saved.sha256,
        mime_type=saved.mime_type,
        width=saved.width,
        height=saved.height,
        size_bytes=saved.size_bytes,
        original_path=saved.original_path,
        thumbnail_path=saved.thumbnail_path,
    )
    store.save_artifact(artifact, check_quota=False)
    return artifact


def _job(
    worker: ImageGenerationJobWorker,
    *,
    prompt: str = "a red fox",
    protocol: str = "mcp",
    profile: str = "mcp-img",
    model: str = "mcp-image",
    operation: ArtifactOperation = ArtifactOperation.GENERATE,
    **overrides: Any,
):
    return worker.create_job(
        user_id="u1",
        prompt=prompt,
        operation=operation,
        session_id="sess-1",
        turn_id="turn-1",
        tool_call_id="tool-1",
        provider="mcp",
        profile=profile,
        protocol=protocol,
        model=model,
        **overrides,
    )


# ── generate mapping ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_maps_prompt_size_count_and_static_args(
    media_store: MediaStore,
) -> None:
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[MCPContentBlock(kind="image", data=make_png(), mime_type="image/png")]
        )
    )
    adapter = _adapter(media_store, manager)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker, size="1024x1024", count=2)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    call = manager.calls[0]
    assert call["owner"] == "u1"
    assert call["server"] == "images"
    assert call["tool"] == "make"
    assert call["args"] == {
        "prompt": "a red fox",
        "size": "1024x1024",
        "count": 2,
        "style": "watercolor",
    }
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.mime_type == "image/png"


@pytest.mark.asyncio
async def test_generate_ignores_absent_optional_mappings(media_store: MediaStore) -> None:
    mcp = McpImageToolConfig(server_name="images", tool_name="make", prompt_arg="prompt")
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[MCPContentBlock(kind="image", data=make_png(), mime_type="image/png")]
        )
    )
    adapter = _adapter(media_store, manager, mcp=mcp)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker, size="512x512", count=3)

    await worker.run_job(job.id)

    assert manager.calls[0]["args"] == {"prompt": "a red fox"}


# ── edit mapping ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_maps_source_and_mask_as_data_uris(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    mask = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[MCPContentBlock(kind="image", data=make_png(), mime_type="image/png")]
        )
    )
    adapter = _adapter(media_store, manager, _mcp_config(source_arg="source", mask_arg="mask"))
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
        mask_artifact_id=mask.id,
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    args = manager.calls[0]["args"]
    source_uri = args["source"]
    mask_uri = args["mask"]
    assert source_uri.startswith("data:image/png;base64,")
    assert mask_uri.startswith("data:image/png;base64,")
    decoded_source = base64.b64decode(source_uri.split(",", 1)[1])
    assert decoded_source == make_png(8, 8)


@pytest.mark.asyncio
async def test_edit_unsupported_is_never_silently_generated(
    media_store: MediaStore,
) -> None:
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    manager = FakeMcpManager(MCPStructuredResult())  # no source_arg mapping
    adapter = _adapter(media_store, manager, _mcp_config(source_arg=""))
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "unsupported_operation"
    assert manager.calls == [], "an unsupported edit must never reach the MCP tool"


@pytest.mark.asyncio
async def test_edit_rejects_mask_dimension_mismatch(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    mask = _persisted_artifact(media_store, user_id="u1", width=4, height=4)
    manager = FakeMcpManager(MCPStructuredResult())
    adapter = _adapter(media_store, manager, _mcp_config(source_arg="source", mask_arg="mask"))
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
        mask_artifact_id=mask.id,
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "validation_error"
    assert manager.calls == []


# ── structured content materialization ──────────────────────────────────────


@pytest.mark.asyncio
async def test_image_content_is_decoded_directly(media_store: MediaStore) -> None:
    png = make_png(8, 8)
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[
                MCPContentBlock(kind="image", data=png, mime_type="image/png"),
            ]
        )
    )
    adapter = _adapter(media_store, manager)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert media_store.persistence.resolve(artifact.original_path).read_bytes() == png


@pytest.mark.asyncio
async def test_blob_resource_is_materialized_from_payload(media_store: MediaStore) -> None:
    png = make_png(8, 8)
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[
                MCPContentBlock(
                    kind="resource",
                    uri="images://blob-1",
                    data=png,
                    mime_type="image/png",
                )
            ]
        )
    )
    adapter = _adapter(media_store, manager)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.mime_type == "image/png"


@pytest.mark.asyncio
async def test_resource_link_is_materialized_through_safe_downloader(
    media_store: MediaStore,
) -> None:
    png = make_png(8, 8)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[MCPContentBlock(kind="resource_link", uri="https://cdn.example/img.png")]
        )
    )
    adapter = _adapter(media_store, manager, handler=handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.mime_type == "image/png"


# ── durable privacy (§10.5/§14) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resource_link_remote_asset_id_is_safe_hash_not_uri(
    media_store: MediaStore,
) -> None:
    """A full ResourceLink URI (private host/path/query) must never be persisted
    as ``remote_asset_id`` — only a safe opaque hash identity (§14)."""
    png = make_png(8, 8)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    secret_uri = "https://private-host.example:8443/v1/images?api_key=supersecret&token=abc%20def"
    manager = FakeMcpManager(
        MCPStructuredResult(blocks=[MCPContentBlock(kind="resource_link", uri=secret_uri)])
    )
    adapter = _adapter(media_store, manager, handler=handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.remote_asset_id.startswith("uri-")
    # The full URI and its host/path/query/secrets never enter the durable
    # artifact record.
    raw = json.loads(
        (media_store.root / "artifacts" / f"{artifact.id}.json").read_text(encoding="utf-8")
    )
    blob = json.dumps(raw)
    for needle in (
        "private-host",
        "/v1/images",
        "supersecret",
        "abc%20def",
        "?api_key=",
    ):
        assert needle not in blob, f"leaked {needle!r} into artifact JSON"


@pytest.mark.asyncio
async def test_error_result_with_private_url_is_sanitized(media_store: MediaStore) -> None:
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[
                MCPContentBlock(
                    kind="resource_link",
                    uri="https://private-host.example/v1/images?key=secret",
                )
            ],
            is_error=True,
        )
    )
    adapter = _adapter(media_store, manager)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "provider_error"
    assert "private-host" not in result.sanitized_error
    assert "/v1/images" not in result.sanitized_error
    assert "secret" not in result.sanitized_error


@pytest.mark.asyncio
async def test_text_only_result_yields_no_media(media_store: MediaStore) -> None:
    manager = FakeMcpManager(
        MCPStructuredResult(blocks=[MCPContentBlock(kind="text", text="progress 50%")])
    )
    adapter = _adapter(media_store, manager)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert "no image content" in result.sanitized_error


@pytest.mark.asyncio
async def test_error_result_is_propagated_without_raw_dump(media_store: MediaStore) -> None:
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[MCPContentBlock(kind="text", text="(MCP tool call failed: RuntimeError)")],
            is_error=True,
        )
    )
    adapter = _adapter(media_store, manager)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "provider_error"
    assert "(MCP tool call failed: RuntimeError)" in result.sanitized_error


@pytest.mark.asyncio
async def test_mcp_adapter_never_polls_or_cancels(media_store: MediaStore) -> None:
    manager = FakeMcpManager(
        MCPStructuredResult(
            blocks=[MCPContentBlock(kind="image", data=make_png(), mime_type="image/png")]
        )
    )
    adapter = _adapter(media_store, manager)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    # Sync completion: no background, no poll, no cancel.
    result = await worker.run_job(job.id)
    assert result.status == ImageJobStatus.SUCCEEDED
    assert await adapter.confirm_cancel(job) is False
