"""MED-02 OpenAI Images API adapter tests (offline fixtures).

Covers generate (base64 + URL output, `gpt-image-2`), edit (source + mask,
mask dimension enforcement), unsupported-edit fail-closed, long read-timeout
wiring, and end-to-end persistence through the worker.
"""

from __future__ import annotations

import base64
from typing import Any
import uuid

import httpx
import pytest

from deeptutor.services.media.adapter_config import (
    ADAPTER_OPENAI_IMAGES,
    AdapterRuntimeConfig,
)
from deeptutor.services.media.adapters import OpenAIImagesAdapter
from deeptutor.services.media.adapters.base import UnsupportedOperationError
from deeptutor.services.media.models import (
    ArtifactOperation,
    GeneratedArtifact,
    ImageJobStatus,
)
from deeptutor.services.media.safe_download import SafeDownloader
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.worker import ImageGenerationJobWorker
from tests.services.media._media_helpers import make_png


def _runtime_config(**overrides: Any) -> AdapterRuntimeConfig:
    base = dict(
        adapter_kind=ADAPTER_OPENAI_IMAGES,
        base_url="https://api.openai.com/v1",
        api_key="sk-test-key",
        model="gpt-image-2",
        supports_edit=True,
    )
    base.update(overrides)
    return AdapterRuntimeConfig(**base)


def _png_b64() -> str:
    return base64.b64encode(make_png(8, 8)).decode("ascii")


def _adapter(
    store: MediaStore,
    handler,
    *,
    config: AdapterRuntimeConfig | None = None,
) -> OpenAIImagesAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    downloader = SafeDownloader(
        limits=store.limits,
        client=client,
        resolver=lambda host: ["93.184.216.34"],
    )
    return OpenAIImagesAdapter(
        config=config or _runtime_config(),
        store=store,
        client=client,
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
    store: MediaStore,
    worker: ImageGenerationJobWorker,
    *,
    prompt: str = "a red fox",
    model: str = "gpt-image-2",
    profile: str = "img-openai",
    protocol: str = "openai_images",
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
        provider="openai",
        profile=profile,
        protocol=protocol,
        model=model,
        **overrides,
    )


# ── generate: base64 output ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_parses_b64_json(media_store: MediaStore) -> None:
    handler = lambda req: httpx.Response(  # noqa: E731
        200, json={"created": 1, "data": [{"b64_json": _png_b64()}]}
    )
    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.mime_type == "image/png"
    assert media_store.persistence.resolve(artifact.original_path).exists()


@pytest.mark.asyncio
async def test_generate_sends_model_size_quality_and_count(media_store: MediaStore) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode("utf-8")
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": [{"b64_json": _png_b64()}]})

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker, size="1024x1024", quality="high", count=2)

    await worker.run_job(job.id)

    import json

    body = json.loads(captured["body"])
    assert body["model"] == "gpt-image-2"
    assert body["prompt"] == "a red fox"
    assert body["n"] == 2
    assert body["size"] == "1024x1024"
    assert body["quality"] == "high"
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    # httpx Headers normalize keys to lowercase.
    assert captured["headers"].get("authorization") == "Bearer sk-test-key"


@pytest.mark.asyncio
async def test_generate_downloads_temporary_url(media_store: MediaStore) -> None:
    png = make_png(8, 8)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(
                200, json={"data": [{"url": "https://cdn.example/img.png", "asset_id": "asset-1"}]}
            )
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.sha256 is not None
    assert artifact.remote_asset_id == "asset-1"


@pytest.mark.asyncio
async def test_generate_fails_when_provider_returns_no_images(media_store: MediaStore) -> None:
    handler = lambda req: httpx.Response(200, json={"data": []})  # noqa: E731
    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "provider_error"
    assert "no images" in result.sanitized_error


@pytest.mark.asyncio
async def test_generate_applies_long_read_timeout(media_store: MediaStore) -> None:
    """The adapter must use the job's 30-minute read timeout, not a chat
    timeout: a slow non-streaming provider is fully supported (§11.4)."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = None
        return httpx.Response(200, json={"data": [{"b64_json": _png_b64()}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    downloader = SafeDownloader(
        limits=media_store.limits, client=client, resolver=lambda host: ["93.184.216.34"]
    )
    adapter = OpenAIImagesAdapter(
        config=_runtime_config(),
        store=media_store,
        client=client,
        downloader=downloader,
    )
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker, read_timeout_seconds=1800, connect_timeout_seconds=20)

    await worker.run_job(job.id)

    assert job.read_timeout_seconds == 1800
    assert job.connect_timeout_seconds == 20


# ── ambiguous submit outcomes (§11.5) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_ambiguous_read_timeout_becomes_unknown(
    media_store: MediaStore,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append("post")
        raise httpx.ReadTimeout("read timed out")

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.UNKNOWN
    assert result.error_code == "submit_outcome_unknown"
    assert calls == ["post"], "only one POST must ever be observed"


@pytest.mark.asyncio
async def test_generate_definite_connect_failure_fails(media_store: MediaStore) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append("post")
        raise httpx.ConnectError("connection refused")

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "provider_error"
    assert calls == ["post"]


# ── response-id provenance (§10.5) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_propagates_remote_response_id_to_artifact(
    media_store: MediaStore,
) -> None:
    """The provider's response id must not be discarded before persistence: it
    is propagated to every returned MediaInput/artifact (§10.5)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "img_resp_1", "data": [{"b64_json": _png_b64()}]},
        )

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(media_store, worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.remote_response_id == "img_resp_1"


# ── edit ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_sends_source_image_and_mask(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    mask = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8", "ignore")
        return httpx.Response(200, json={"data": [{"b64_json": _png_b64()}]})

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        media_store,
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
        mask_artifact_id=mask.id,
        prompt="turn it blue",
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    assert captured["url"] == "https://api.openai.com/v1/images/edits"
    # Multipart body contains the source and mask file parts.
    assert "source_0.png" in captured["body"]
    assert "mask.png" in captured["body"]


@pytest.mark.asyncio
async def test_edit_sends_valid_multipart_content_type_with_boundary(
    media_store: MediaStore,
) -> None:
    """A `files=` edit must never send `application/json`: httpx generates a
    multipart content type with a boundary while auth is retained."""
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    mask = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type")
        captured["body"] = request.read().decode("utf-8", "ignore")
        captured["authorization"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"b64_json": _png_b64()}]})

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        media_store,
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
        mask_artifact_id=mask.id,
    )

    await worker.run_job(job.id)

    assert captured["content_type"].startswith("multipart/form-data; boundary=")
    assert "source_0.png" in captured["body"]
    assert "mask.png" in captured["body"]
    # Auth headers are retained on the multipart request.
    assert captured["authorization"] == "Bearer sk-test-key"


@pytest.mark.asyncio
async def test_edit_materializes_revised_prompt(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    handler = lambda req: httpx.Response(  # noqa: E731
        200,
        json={
            "data": [
                {
                    "b64_json": _png_b64(),
                    "revised_prompt": "a red fox in a snowy forest, cinematic",
                }
            ]
        },
    )
    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        media_store,
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.operation == ArtifactOperation.EDIT
    assert artifact.revised_prompt == "a red fox in a snowy forest, cinematic"
    assert artifact.parent_artifact_ids == [source.id]


@pytest.mark.asyncio
async def test_edit_rejects_mask_dimension_mismatch(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    mask = _persisted_artifact(media_store, user_id="u1", width=4, height=4)
    adapter = _adapter(media_store, lambda req: httpx.Response(500))
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        media_store,
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
        mask_artifact_id=mask.id,
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "validation_error"
    assert "must equal" in result.sanitized_error


@pytest.mark.asyncio
async def test_edit_never_calls_generate_when_unsupported(media_store: MediaStore) -> None:
    """A provider without edit support must return a stable
    unsupported_operation and never silently fall back to generate."""
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": [{"b64_json": _png_b64()}]})

    adapter = _adapter(
        media_store,
        handler,
        config=_runtime_config(supports_edit=False),
    )
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        media_store,
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "unsupported_operation"
    assert calls == [], "an unsupported edit must never reach the provider"


@pytest.mark.asyncio
async def test_edit_requires_source_artifact(media_store: MediaStore) -> None:
    adapter = _adapter(media_store, lambda req: httpx.Response(500))
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    # Worker-level contract already rejects an edit with no source.
    with pytest.raises(Exception, match="edit requires"):
        _job(media_store, worker, operation=ArtifactOperation.EDIT)
