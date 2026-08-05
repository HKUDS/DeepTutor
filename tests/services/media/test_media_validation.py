"""MED-02 execution-time validation and redaction tests (offline).

Covers source/mask/continuation ownership and content rules enforced by the
adapters, the atomic-save-before-success guarantee when a provider returns a
corrupt payload, and that provider/MCP error text is scrubbed from durable job
metadata (no keys, no base64, no raw URLs).
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
from deeptutor.services.media.media_validation import (
    load_artifact_bytes,
    validate_edit_inputs,
    validate_mask_dimensions,
)
from deeptutor.services.media.models import (
    ArtifactOperation,
    GeneratedArtifact,
    ImageJobStatus,
    MediaError,
    MediaValidationError,
)
from deeptutor.services.media.safe_download import SafeDownloader
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.worker import ImageGenerationJobWorker
from tests.services.media._media_helpers import make_png


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


def _adapter(
    store: MediaStore,
    handler,
    *,
    config: AdapterRuntimeConfig | None = None,
) -> OpenAIImagesAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    downloader = SafeDownloader(
        limits=store.limits, client=client, resolver=lambda host: ["93.184.216.34"]
    )
    return OpenAIImagesAdapter(
        config=config
        or AdapterRuntimeConfig(
            adapter_kind=ADAPTER_OPENAI_IMAGES,
            base_url="https://api.openai.com/v1",
            api_key="sk-test-key",
            model="gpt-image-2",
        ),
        store=store,
        client=client,
        downloader=downloader,
    )


def _job(
    worker: ImageGenerationJobWorker,
    *,
    operation: ArtifactOperation = ArtifactOperation.GENERATE,
    prompt: str = "a red fox",
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
        profile="p1",
        protocol="openai_images",
        model="gpt-image-2",
        **overrides,
    )


# ── source/mask ownership + content validation ──────────────────────────────


def test_load_artifact_bytes_rejects_cross_user(media_store: MediaStore) -> None:
    artifact = _persisted_artifact(media_store, user_id="u2")
    with pytest.raises(MediaError, match="belongs to user"):
        load_artifact_bytes(
            media_store, artifact.id, user_id="u1", limits=media_store.limits, label="source"
        )


def test_load_artifact_bytes_rejects_missing(media_store: MediaStore) -> None:
    with pytest.raises(MediaError, match="not found"):
        load_artifact_bytes(
            media_store, "missing", user_id="u1", limits=media_store.limits, label="source"
        )


def test_validate_mask_dimensions_mismatch_rejected() -> None:
    from deeptutor.services.media.media_validation import LoadedImage

    source = LoadedImage(data=b"", mime_type="image/png", width=8, height=8)
    mask = LoadedImage(data=b"", mime_type="image/png", width=4, height=4)
    with pytest.raises(MediaValidationError, match="must equal"):
        validate_mask_dimensions(source, mask)


@pytest.mark.asyncio
async def test_validate_edit_inputs_enforces_mask_dimensions(
    media_store: MediaStore,
) -> None:
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    mask = _persisted_artifact(media_store, user_id="u1", width=4, height=4)
    worker = ImageGenerationJobWorker(store=media_store)
    job = _job(
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[source.id],
        mask_artifact_id=mask.id,
    )
    with pytest.raises(MediaValidationError, match="must equal"):
        validate_edit_inputs(media_store, job, limits=media_store.limits)


@pytest.mark.asyncio
async def test_edit_rejects_cross_user_source_server_side(
    media_store: MediaStore,
) -> None:
    """Ownership is re-enforced at execution time even for a hand-rolled job."""
    from deeptutor.services.media.models import ImageGenerationJob

    other = _persisted_artifact(media_store, user_id="u2", width=8, height=8)
    # Build the job record directly (bypassing the worker's submission-time
    # ownership check) to prove the adapter re-validates ownership itself.
    job = ImageGenerationJob(
        id=uuid.uuid4().hex,
        user_id="u1",
        original_prompt="a red fox",
        request_hash="h",
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[other.id],
        profile="p1",
        protocol="openai_images",
        model="gpt-image-2",
    )
    media_store.save_job(job)
    adapter = _adapter(media_store, lambda req: httpx.Response(500))
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert "belongs to user" in result.sanitized_error


# ── atomic save before success ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_corrupt_provider_payload_never_succeeds(media_store: MediaStore) -> None:
    """A provider returning a corrupt image must fail the job with no artifact,
    no reference and no media file — success is only after a validated save."""
    png_b64 = base64.b64encode(make_png(8, 8)).decode("ascii")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/images/generations"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"b64_json": png_b64},
                        {
                            "b64_json": base64.b64encode(b"<script>alert(1)</script>").decode(
                                "ascii"
                            )
                        },
                    ]
                },
            )
        return httpx.Response(404)

    adapter = _adapter(media_store, handler)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "validation_error"
    assert result.artifact_ids == []
    assert media_store.list_artifacts(user_id="u1") == []
    assert media_store.list_references() == []
    assert list((media_store.root / "originals").rglob("*.png")) == []


# ── redaction of adapter errors ─────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_message",
    [
        "provider boom sk-abcdefghijklmnop",
        "provider boom Authorization: Bearer tok-secret-abc",
        "provider boom api_key=leaked-key-value",
    ],
)
async def test_adapter_error_redacted_from_job_metadata(
    media_store: MediaStore, error_message: str
) -> None:
    class _BoomAdapter:
        async def run(self, job):
            raise RuntimeError(error_message)

        async def poll(self, job):
            raise AssertionError("not used")

        async def confirm_cancel(self, job):
            return False

    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(_BoomAdapter())  # type: ignore[arg-type]
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    for needle in ("sk-abcdefghijklmnop", "tok-secret-abc", "leaked-key-value"):
        assert needle not in result.sanitized_error
    assert "***" in result.sanitized_error or "[REDACTED" in result.sanitized_error


@pytest.mark.asyncio
async def test_base64_payload_never_reaches_job_json(media_store: MediaStore) -> None:
    secret_b64 = base64.b64encode(b"image-payload-bytes-" * 20).decode("ascii")
    worker = ImageGenerationJobWorker(store=media_store)
    job = _job(worker, prompt=f"please render {secret_b64}")

    import json

    raw = json.loads((media_store.root / "jobs" / f"{job.id}.json").read_text(encoding="utf-8"))
    assert secret_b64 not in json.dumps(raw)
    assert "[REDACTED base64 payload]" in json.dumps(raw)
