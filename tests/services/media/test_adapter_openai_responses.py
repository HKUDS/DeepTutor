"""MED-02 OpenAI Responses ``image_generation`` adapter tests (offline).

Uses the MOD-02 ``FakeTransport`` so no endpoint is contacted.  Verifies
background submit/retrieve/cancel, that a remote id is never re-submitted, that
edits resolve ``previous_response_id`` from persisted continuation jobs only,
and that an edit without a continuation fails closed with
``unsupported_operation``.
"""

from __future__ import annotations

import base64
from typing import Any
import uuid

import httpx
import pytest

from deeptutor.services.llm.provider_core.unified.transport import FakeTransport
from deeptutor.services.media.adapter_config import (
    ADAPTER_OPENAI_RESPONSES,
    AdapterRuntimeConfig,
)
from deeptutor.services.media.adapters import OpenAIResponsesImageAdapter
from deeptutor.services.media.models import (
    ArtifactOperation,
    ImageGenerationJob,
    ImageJobStatus,
)
from deeptutor.services.media.safe_download import SafeDownloader
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.worker import ImageGenerationJobWorker
from tests.services.media._media_helpers import make_png

RESPONSES_PATH = "/v1/responses"


def _runtime_config(**overrides: Any) -> AdapterRuntimeConfig:
    base = dict(
        adapter_kind=ADAPTER_OPENAI_RESPONSES,
        base_url="https://api.openai.com/v1",
        api_key="sk-test-key",
        model="gpt-5.6",
        supports_background=True,
        supports_continuation=True,
    )
    base.update(overrides)
    return AdapterRuntimeConfig(**base)


def _png_b64() -> str:
    return base64.b64encode(make_png(8, 8)).decode("ascii")


def _submit_response(response_id: str = "resp_bg_1") -> dict[str, Any]:
    return {"id": response_id, "model": "gpt-5.6", "status": "in_progress", "output": []}


def _done_response(response_id: str = "resp_bg_1") -> dict[str, Any]:
    """Official completed response: ``result`` is a base64 string, and the
    image-generation call id / revised prompt live on the output item."""
    return {
        "id": response_id,
        "model": "gpt-5.6",
        "status": "completed",
        "output": [
            {
                "type": "image_generation_call",
                "id": "ig_1",
                "status": "completed",
                "revised_prompt": "a red fox in a snowy forest",
                "result": _png_b64(),
            }
        ],
    }


def _done_response_extension(response_id: str = "resp_bg_1") -> dict[str, Any]:
    """OpenAI-compatible extension: ``result`` is a list of image objects."""
    return {
        "id": response_id,
        "model": "gpt-5.6",
        "status": "completed",
        "output": [
            {
                "type": "image_generation_call",
                "id": "igc_1",
                "call_id": "call_1",
                "name": "image_generation",
                "arguments": '{"prompt":"a red fox"}',
                "status": "completed",
                "result": [
                    {
                        "type": "image",
                        "image_url": f"data:image/png;base64,{_png_b64()}",
                        "asset_id": "asset_1",
                        "revised_prompt": "a red fox in a snowy forest, cinematic",
                    }
                ],
            }
        ],
    }


def _cancelled_response(response_id: str = "resp_bg_1") -> dict[str, Any]:
    return {"id": response_id, "model": "gpt-5.6", "status": "cancelled", "output": []}


def _failed_response(response_id: str = "resp_bg_1") -> dict[str, Any]:
    return {"id": response_id, "model": "gpt-5.6", "status": "failed", "output": []}


def _adapter(
    store: MediaStore,
    transport: FakeTransport,
    *,
    config: AdapterRuntimeConfig | None = None,
) -> OpenAIResponsesImageAdapter:
    downloader = SafeDownloader(
        limits=store.limits,
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(404)),
            follow_redirects=False,
        ),
        resolver=lambda host: ["93.184.216.34"],
    )
    return OpenAIResponsesImageAdapter(
        config=config or _runtime_config(),
        store=store,
        transport=transport,
        downloader=downloader,
    )


def _job(
    worker: ImageGenerationJobWorker,
    *,
    model: str = "gpt-5.6",
    profile: str = "resp-main",
    protocol: str = "openai_responses",
    operation: ArtifactOperation = ArtifactOperation.GENERATE,
    **overrides: Any,
) -> ImageGenerationJob:
    return worker.create_job(
        user_id="u1",
        prompt="a red fox",
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


def _raw_prior_job(
    store: MediaStore, *, status: ImageJobStatus, remote_response_id: str = "", profile: str = ""
) -> ImageGenerationJob:
    job = ImageGenerationJob(
        id=uuid.uuid4().hex,
        user_id="u1",
        session_id="sess-1",
        original_prompt="a red fox",
        request_hash="h",
        status=status,
        remote_response_id=remote_response_id,
        profile=profile,
    )
    return store.save_job(job)


class _FlakyRetrieveTransport(FakeTransport):
    """FakeTransport that fails the first N GET retrieves with a read error."""

    def __init__(self, *, fail_first_gets: int) -> None:
        super().__init__()
        self.fail_first_gets = fail_first_gets

    async def request_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if method == "GET" and self.fail_first_gets > 0:
            self.requests.append(
                {
                    "method": method,
                    "path": path,
                    "body": body,
                    "headers": dict(headers or {}),
                }
            )
            self.fail_first_gets -= 1
            raise httpx.ReadError("connection lost")
        return await super().request_json(method, path, body, headers)


# ── background submit / retrieve / cancel ───────────────────────────────────


@pytest.mark.asyncio
async def test_run_submits_background_and_returns_remote_identity(
    media_store: MediaStore,
) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker, size="1024x1024", quality="high")

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.POLLING
    assert result.remote_response_id == "resp_bg_1"
    assert result.poll_after > 0
    submits = transport.calls_for("POST", RESPONSES_PATH)
    assert len(submits) == 1
    body = submits[0]["body"]
    assert body["background"] is True
    assert body["store"] is False
    assert body["model"] == "gpt-5.6"
    # Official wire contract: the image tool entry has no `name`, and the
    # built-in tool is forced by its type, not a function choice.
    tool = body["tools"][0]
    assert tool == {"type": "image_generation", "size": "1024x1024", "quality": "high"}
    assert "name" not in tool
    assert body["tool_choice"] == {"type": "image_generation"}
    assert body["input"][0]["content"][0]["text"] == "a red fox"
    # No client-supplied remote identity is ever present on a fresh submit.
    assert "previous_response_id" not in body


@pytest.mark.asyncio
async def test_run_sends_resolved_provider_model_not_catalog_id(
    media_store: MediaStore,
) -> None:
    """The Responses body carries the resolver's provider model, never the
    durable catalog entry id, while the job record keeps the requested model for
    audit (§16.3)."""
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    adapter = _adapter(
        media_store,
        transport,
        config=_runtime_config(model="gpt-image-2"),
    )
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker, model="m1")  # catalog entry id != provider model

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.POLLING
    submits = transport.calls_for("POST", RESPONSES_PATH)
    assert len(submits) == 1
    assert submits[0]["body"]["model"] == "gpt-image-2"
    assert submits[0]["body"]["model"] != job.model
    # The durable job preserves the requested catalog model for audit.
    stored = media_store.load_job(job.id)
    assert stored is not None and stored.model == "m1"


@pytest.mark.asyncio
async def test_run_fails_closed_when_resolved_model_empty(
    media_store: MediaStore,
) -> None:
    """A Responses job whose catalog model resolves to no provider model fails
    closed with a stable config error before any provider call (§11.3)."""
    transport = FakeTransport()
    adapter = _adapter(media_store, transport, config=_runtime_config(model=""))
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker, model="m1")

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "config_error"
    assert transport.requests == [], "an unresolved model must never hit the network"


@pytest.mark.asyncio
async def test_poll_retrieves_and_completes_official_base64_result(
    media_store: MediaStore,
) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_response("GET", "/v1/responses/resp_bg_1", _done_response())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.remote_response_id == "resp_bg_1"
    # Official shape: remote_asset_id is the image-generation call id and the
    # revised prompt is the item-level field.
    assert artifact.remote_asset_id == "ig_1"
    assert artifact.revised_prompt == "a red fox in a snowy forest"
    # The persisted bytes are exactly the decoded base64 PNG.
    persisted = media_store.persistence.resolve(artifact.original_path).read_bytes()
    assert persisted == make_png(8, 8)
    # The only POST to /v1/responses is the original submit.
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


@pytest.mark.asyncio
async def test_compatible_list_result_extension_still_works(
    media_store: MediaStore,
) -> None:
    """OpenAI-compatible endpoints returning `result` as a list of image
    objects keep working; the official shape is authoritative but the
    extension is not regressed."""
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_response("GET", "/v1/responses/resp_bg_1", _done_response_extension())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = media_store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.remote_asset_id == "asset_1"
    assert artifact.revised_prompt == "a red fox in a snowy forest, cinematic"
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


@pytest.mark.asyncio
async def test_poll_while_in_progress_returns_poll_after(media_store: MediaStore) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_response("GET", "/v1/responses/resp_bg_1", _submit_response())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.POLLING
    assert result.poll_after > 0
    # No resubmit ever.
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1
    assert len(transport.calls_for("GET", "/v1/responses/resp_bg_1")) == 1


@pytest.mark.asyncio
async def test_poll_failed_response_fails_job(media_store: MediaStore) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_response("GET", "/v1/responses/resp_bg_1", _failed_response())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert "failed" in result.sanitized_error
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


@pytest.mark.asyncio
async def test_confirm_cancel_posts_cancel_and_confirms(media_store: MediaStore) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_response("POST", "/v1/responses/resp_bg_1/cancel", _cancelled_response())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    media_store.transition_job(
        job.id,
        from_status=ImageJobStatus.POLLING,
        to_status=ImageJobStatus.CANCEL_REQUESTED,
    )
    result = await worker.run_cancel(job.id)

    assert result.status == ImageJobStatus.CANCELLED
    assert transport.calls_for("POST", "/v1/responses/resp_bg_1/cancel")
    # Cancel is not a submit.
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


@pytest.mark.asyncio
async def test_confirm_cancel_unconfirmed_when_provider_does_not_confirm(
    media_store: MediaStore,
) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_error("POST", "/v1/responses/resp_bg_1/cancel", RuntimeError("gone"))
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    media_store.transition_job(
        job.id,
        from_status=ImageJobStatus.POLLING,
        to_status=ImageJobStatus.CANCEL_REQUESTED,
    )
    result = await worker.run_cancel(job.id)

    assert result.status == ImageJobStatus.CANCELLED_UNCONFIRMED
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


# ── durable remote id before materialization (§11.5) ────────────────────────


@pytest.mark.asyncio
async def test_completed_post_persists_remote_id_before_materialization(
    media_store: MediaStore,
) -> None:
    """A completed POST response still returns a BackgroundSubmit: the remote id
    is durable on the job before any image decode/download can fail."""
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _done_response())  # completed
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.POLLING
    assert result.remote_response_id == "resp_bg_1"
    stored = media_store.load_job(job.id)
    assert stored is not None and stored.remote_response_id == "resp_bg_1"
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


@pytest.mark.asyncio
async def test_materialization_failure_after_durable_id_never_resubmits(
    media_store: MediaStore,
) -> None:
    """If image decode/validation fails on the polling path, the job fails but
    the remote id is retained for diagnostics and no duplicate POST is issued."""
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    bad = _done_response()
    bad["output"][0]["result"] = "@@@not-a-png@@@"  # decodes to empty/non-image
    transport.add_response("GET", "/v1/responses/resp_bg_1", bad)
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    assert media_store.load_job(job.id).status == ImageJobStatus.POLLING
    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.remote_response_id == "resp_bg_1"
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1
    assert len(transport.calls_for("GET", "/v1/responses/resp_bg_1")) == 1


@pytest.mark.asyncio
async def test_multiple_image_generation_call_items(media_store: MediaStore) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    done = _done_response()
    done["output"].append(
        {
            "type": "image_generation_call",
            "id": "ig_2",
            "status": "completed",
            "revised_prompt": "second image",
            "result": _png_b64(),
        }
    )
    transport.add_response("GET", "/v1/responses/resp_bg_1", done)
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    assert len(result.artifact_ids) == 2
    artifacts = [media_store.load_artifact(aid) for aid in result.artifact_ids]
    assert {artifact.remote_asset_id for artifact in artifacts} == {"ig_1", "ig_2"}
    assert {artifact.revised_prompt for artifact in artifacts} == {
        "a red fox in a snowy forest",
        "second image",
    }
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


# ── ambiguous submit outcomes (§11.5) ───────────────────────────────────────


@pytest.mark.asyncio
async def test_ambiguous_submit_read_timeout_becomes_unknown(
    media_store: MediaStore,
) -> None:
    transport = FakeTransport()
    transport.add_error("POST", RESPONSES_PATH, httpx.ReadTimeout("read timed out"))
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.UNKNOWN
    assert result.error_code == "submit_outcome_unknown"
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1
    # An UNKNOWN job is terminal: restart must not resubmit it.
    assert worker.recover() == []


@pytest.mark.asyncio
async def test_definite_connect_failure_submit_fails(media_store: MediaStore) -> None:
    transport = FakeTransport()
    transport.add_error("POST", RESPONSES_PATH, httpx.ConnectError("connection refused"))
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "provider_error"
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


# ── transient retrieve resilience (§11.5) ───────────────────────────────────


@pytest.mark.asyncio
async def test_transient_poll_failure_keeps_polling_with_backoff(
    media_store: MediaStore,
) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_error("GET", "/v1/responses/resp_bg_1", httpx.ReadTimeout("read timed out"))
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    stored = media_store.load_job(job.id)
    assert stored is not None and stored.status == ImageJobStatus.POLLING
    assert stored.poll_delay_seconds == 2.0

    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.POLLING
    assert result.poll_delay_seconds == 4.0  # backoff doubled, never failed
    assert result.remote_response_id == "resp_bg_1"
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1


@pytest.mark.asyncio
async def test_transient_poll_failure_then_success_no_resubmit(
    media_store: MediaStore,
) -> None:
    """A transient retrieve failure must not abort a still-running remote job:
    the next poll succeeds and no duplicate POST is issued."""
    transport = _FlakyRetrieveTransport(fail_first_gets=1)
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_response("GET", "/v1/responses/resp_bg_1", _done_response())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)

    await worker.run_job(job.id)
    stored = media_store.load_job(job.id)
    assert stored is not None and stored.status == ImageJobStatus.POLLING

    result = await worker.poll_job(job.id)  # transient failure -> backoff
    assert result.status == ImageJobStatus.POLLING

    result = await worker.poll_job(job.id)  # success
    assert result.status == ImageJobStatus.SUCCEEDED
    assert len(transport.calls_for("POST", RESPONSES_PATH)) == 1
    assert len(transport.calls_for("GET", "/v1/responses/resp_bg_1")) == 2


# ── restart with/without remote id ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_restart_with_remote_id_resumes_retrieve_not_resubmit(
    media_store: MediaStore,
) -> None:
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response())
    transport.add_response("GET", "/v1/responses/resp_bg_1", _done_response())
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(worker)
    await worker.run_job(job.id)
    assert media_store.load_job(job.id).status == ImageJobStatus.POLLING

    # Fresh process: same durable store, a new adapter over a new transport.
    fresh_transport = FakeTransport()
    fresh_transport.add_response("GET", "/v1/responses/resp_bg_1", _done_response())
    fresh_adapter = _adapter(media_store, fresh_transport)
    fresh_worker = ImageGenerationJobWorker(store=media_store)
    fresh_worker.set_executor(fresh_adapter)

    transitions = fresh_worker.recover()
    assert transitions == [], "a remote-id polling job resumes without a transition"

    result = await fresh_worker.poll_job(job.id)
    assert result.status == ImageJobStatus.SUCCEEDED
    # The fresh process retrieved; it never re-submitted.
    assert fresh_transport.calls_for("GET", "/v1/responses/resp_bg_1")
    assert fresh_transport.calls_for("POST", RESPONSES_PATH) == []


def test_restart_without_remote_id_becomes_unknown(media_store: MediaStore) -> None:
    job = _raw_prior_job(media_store, status=ImageJobStatus.POLLING)
    worker = ImageGenerationJobWorker(store=media_store)
    transitions = worker.recover()
    assert [row["to"] for row in transitions] == [ImageJobStatus.UNKNOWN.value]
    assert media_store.load_job(job.id).status == ImageJobStatus.UNKNOWN


@pytest.mark.asyncio
async def test_polling_job_without_remote_id_cannot_resume(media_store: MediaStore) -> None:
    transport = FakeTransport()
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _raw_prior_job(media_store, status=ImageJobStatus.POLLING)

    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.UNKNOWN
    assert transport.requests == [], "an id-less job must never hit the network"


# ── edit lineage ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_uses_previous_response_id_from_persisted_continuation(
    media_store: MediaStore,
) -> None:
    prior = _raw_prior_job(
        media_store,
        status=ImageJobStatus.SUCCEEDED,
        remote_response_id="resp_prior_1",
        profile="resp-main",
    )
    transport = FakeTransport()
    transport.add_response("POST", RESPONSES_PATH, _submit_response("resp_edit_1"))
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        worker,
        operation=ArtifactOperation.EDIT,
        continuation_job_id=prior.id,
    )

    await worker.run_job(job.id)

    submits = transport.calls_for("POST", RESPONSES_PATH)
    assert len(submits) == 1
    assert submits[0]["body"]["previous_response_id"] == "resp_prior_1"
    assert media_store.load_job(job.id).status == ImageJobStatus.POLLING


@pytest.mark.asyncio
async def test_edit_without_continuation_is_unsupported(media_store: MediaStore) -> None:
    source = media_store.persistence.save_media(make_png(8, 8), mime_type="image/png")
    from deeptutor.services.media.models import GeneratedArtifact

    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id="u1",
        session_id="sess-a",
        sha256=source.sha256,
        mime_type="image/png",
        width=source.width,
        height=source.height,
        size_bytes=source.size_bytes,
        original_path=source.original_path,
        thumbnail_path=source.thumbnail_path,
    )
    media_store.save_artifact(artifact, check_quota=False)

    transport = FakeTransport()
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        worker,
        operation=ArtifactOperation.EDIT,
        source_artifact_ids=[artifact.id],
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "unsupported_operation"
    # The adapter must never silently call generate for a source edit.
    assert transport.requests == []


@pytest.mark.asyncio
async def test_edit_continuation_without_remote_id_fails(media_store: MediaStore) -> None:
    prior = _raw_prior_job(media_store, status=ImageJobStatus.SUCCEEDED, profile="resp-main")
    transport = FakeTransport()
    adapter = _adapter(media_store, transport)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(adapter)
    job = _job(
        worker,
        operation=ArtifactOperation.EDIT,
        continuation_job_id=prior.id,
    )

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert "no remote response id" in result.sanitized_error
    assert transport.requests == []
