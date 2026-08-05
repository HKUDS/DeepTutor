"""MED-01 focused tests: image job lifecycle, atomic-success, restart, cancel, quota slots."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
import threading
from typing import Any
import uuid

import pytest

from deeptutor.services.media import store as media_store_mod
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import (
    ArtifactOperation,
    BackgroundSubmit,
    GeneratedArtifact,
    ImageGenerationJob,
    ImageJobStatus,
    JobConcurrencyError,
    JobStateError,
    MediaError,
    MediaInput,
    MediaValidationError,
    PollOutcome,
    QuotaExceededError,
    ReferenceOwnerType,
)
from deeptutor.services.media.store import MediaStore
from deeptutor.services.media.worker import ImageGenerationJobWorker, _request_hash
from tests.services.media._media_helpers import FakeExecutor, make_media_input, make_png


@pytest.fixture
def worker(media_store: MediaStore) -> ImageGenerationJobWorker:
    return ImageGenerationJobWorker(store=media_store)


def _job_args(**overrides):
    args = dict(
        user_id="u1",
        prompt="a red fox",
        session_id="sess-1",
        turn_id="turn-1",
        tool_call_id="tool-1",
        provider="openai",
        profile="p1",
        protocol="openai_images",
        model="gpt-image-2",
        idempotency_key="",
    )
    args.update(overrides)
    return args


def _persisted_artifact(
    store: MediaStore,
    *,
    user_id: str = "u1",
    session_id: str = "sess-a",
    width: int = 8,
    height: int = 8,
    **overrides,
) -> GeneratedArtifact:
    """Persist a content-addressed artifact record owned by *user_id*."""
    saved = store.persistence.save_media(make_png(width, height), mime_type="image/png")
    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id=user_id,
        session_id=session_id,
        sha256=saved.sha256,
        mime_type=saved.mime_type,
        width=saved.width,
        height=saved.height,
        size_bytes=saved.size_bytes,
        original_path=saved.original_path,
        thumbnail_path=saved.thumbnail_path,
    )
    for key, value in overrides.items():
        setattr(artifact, key, value)
    store.save_artifact(artifact, check_quota=False)
    return artifact


# ── submission / idempotency ────────────────────────────────────────────────


def test_create_job_is_queued_and_persisted(worker: ImageGenerationJobWorker) -> None:
    job = worker.create_job(**_job_args())
    assert job.status == ImageJobStatus.QUEUED
    assert job.status_version == 0
    assert job.request_hash

    reloaded = worker.store.load_job(job.id)
    assert reloaded is not None and reloaded.id == job.id
    assert reloaded.original_prompt == "a red fox"


def test_create_job_is_idempotent_per_key(worker: ImageGenerationJobWorker) -> None:
    first = worker.create_job(**_job_args(idempotency_key="same"))
    second = worker.create_job(**_job_args(idempotency_key="same"))
    assert first.id == second.id


def test_create_job_conflicts_on_same_key_different_payload(
    worker: ImageGenerationJobWorker,
) -> None:
    worker.create_job(**_job_args(idempotency_key="dup"))
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(**_job_args(idempotency_key="dup", prompt="a different prompt"))


def test_create_job_rejects_empty_prompt(worker: ImageGenerationJobWorker) -> None:
    with pytest.raises(MediaError, match="empty prompt"):
        worker.create_job(**_job_args(prompt="   "))


# ── idempotency hash covers the complete frozen request ─────────────────────


@pytest.mark.parametrize(
    "override",
    [
        {"model": "gpt-image-2-alt"},
        {"protocol": "openai_responses"},
        {"provider": "anthropic"},
        {"profile": "p2"},
        {"size": "512x512"},
        {"quality": "low"},
        {"count": 2},
        {"connect_timeout_seconds": 30},
        {"read_timeout_seconds": 900},
    ],
)
def test_idempotency_conflicts_on_semantic_change(
    worker: ImageGenerationJobWorker, override: dict[str, Any]
) -> None:
    worker.create_job(**_job_args(idempotency_key="k"))
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(**_job_args(idempotency_key="k", **override))


def test_idempotency_conflicts_on_operation_change(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1")
    worker = ImageGenerationJobWorker(store=media_store)
    worker.create_job(
        **_job_args(
            idempotency_key="k",
            operation=ArtifactOperation.EDIT,
            source_artifact_ids=[source.id],
        )
    )
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(**_job_args(idempotency_key="k"))


def test_idempotency_conflicts_on_provider_options_change(
    worker: ImageGenerationJobWorker,
) -> None:
    worker.create_job(
        **_job_args(idempotency_key="k", request_snapshot={"provider_options": {"foo": "a"}})
    )
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(
            **_job_args(idempotency_key="k", request_snapshot={"provider_options": {"foo": "b"}})
        )


def test_idempotency_same_semantic_options_are_idempotent(
    worker: ImageGenerationJobWorker,
) -> None:
    first = worker.create_job(
        **_job_args(
            idempotency_key="k",
            request_snapshot={"provider_options": {"a": 1, "b": 2}},
        )
    )
    second = worker.create_job(
        **_job_args(
            idempotency_key="k",
            request_snapshot={"provider_options": {"b": 2, "a": 1}},
        )
    )
    assert first.id == second.id


def test_idempotency_conflicts_on_retry_lineage(media_store: MediaStore) -> None:
    prior_a = _raw_job(media_store, status=ImageJobStatus.FAILED)
    prior_b = _raw_job(media_store, status=ImageJobStatus.FAILED)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.create_job(**_job_args(idempotency_key="k", retry_of_job_id=prior_a.id))
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(**_job_args(idempotency_key="k", retry_of_job_id=prior_b.id))


def test_idempotency_conflicts_on_continuation_lineage(
    media_store: MediaStore,
) -> None:
    prior_a = _raw_job(media_store, status=ImageJobStatus.SUCCEEDED, profile="p1")
    prior_b = _raw_job(media_store, status=ImageJobStatus.SUCCEEDED, profile="p1")
    worker = ImageGenerationJobWorker(store=media_store)
    worker.create_job(
        **_job_args(
            idempotency_key="k",
            operation=ArtifactOperation.EDIT,
            continuation_job_id=prior_a.id,
        )
    )
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(
            **_job_args(
                idempotency_key="k",
                operation=ArtifactOperation.EDIT,
                continuation_job_id=prior_b.id,
            )
        )


def test_idempotency_ignores_implicit_default_deadline(
    worker: ImageGenerationJobWorker,
) -> None:
    first = worker.create_job(**_job_args(idempotency_key="same"))
    second = worker.create_job(**_job_args(idempotency_key="same"))
    assert first.id == second.id
    assert first.deadline_at > 0


def test_idempotency_conflicts_on_explicit_deadline_change(
    worker: ImageGenerationJobWorker,
) -> None:
    worker.create_job(**_job_args(idempotency_key="k", deadline_at=1000.0))
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(**_job_args(idempotency_key="k", deadline_at=2000.0))


@pytest.mark.parametrize("field", ["session_id", "turn_id", "tool_call_id"])
def test_idempotency_conflicts_on_attachment_context_change(
    worker: ImageGenerationJobWorker, field: str
) -> None:
    """Reusing a key + payload in another session/turn/tool context must
    conflict instead of returning a job attached to an earlier context."""
    base = _job_args(idempotency_key="attach-k")
    worker.create_job(**base)
    changed = dict(base)
    changed[field] = base[field] + "-other"
    with pytest.raises(JobStateError, match="different image request"):
        worker.create_job(**changed)


def test_snapshot_includes_attachment_context(worker: ImageGenerationJobWorker) -> None:
    """The frozen request snapshot carries the attachment context so a reused
    idempotency key is bound to the session/turn/tool it was submitted from."""
    job = worker.create_job(**_job_args())
    assert job.request_snapshot["session_id"] == "sess-1"
    assert job.request_snapshot["turn_id"] == "turn-1"
    assert job.request_snapshot["tool_call_id"] == "tool-1"
    reloaded = worker.store.load_job(job.id)
    assert reloaded is not None
    assert reloaded.request_snapshot["session_id"] == "sess-1"
    assert reloaded.request_snapshot["turn_id"] == "turn-1"
    assert reloaded.request_snapshot["tool_call_id"] == "tool-1"


# ── request_snapshot is built from trusted top-level arguments ──────────────


def test_snapshot_canonical_fields_ignore_caller_snapshot(
    worker: ImageGenerationJobWorker,
) -> None:
    job = worker.create_job(
        **_job_args(
            prompt="trusted prompt",
            model="trusted-model",
            profile="trusted-profile",
            request_snapshot={
                "prompt": "evil prompt",
                "operation": "edit",
                "model": "evil-model",
                "profile": "evil-profile",
                "size": "9999x1",
                "provider_options": {"extra": "hacked"},
            },
        )
    )
    snapshot = job.request_snapshot
    assert snapshot["prompt"] == "trusted prompt"
    assert snapshot["operation"] == "generate"
    assert snapshot["model"] == "trusted-model"
    assert snapshot["profile"] == "trusted-profile"
    assert snapshot["size"] == ""
    assert snapshot["provider_options"] == {"extra": "hacked"}


def test_snapshot_never_persists_credentials(worker: ImageGenerationJobWorker) -> None:
    secret_b64 = base64.b64encode(b"fake-image-bytes-" * 20).decode("ascii")
    assert len(secret_b64) >= 128
    job = worker.create_job(
        **_job_args(
            request_snapshot={
                "provider_options": {
                    "api_key": "sk-abcdefghijklmnop",
                    "headers": {
                        "Authorization": "Bearer tok-12345",
                        "X-Api-Key": "abc123",
                    },
                    "cookie": "session=abc123; csrf=def456",
                    "token": "jwt-token-here",
                    "password": "hunter2",
                    "nested": {"secret": "deep-secret"},
                    "image_payload": f"data:image/png;base64,{secret_b64}",
                }
            },
        )
    )
    raw = json.loads((worker.store.root / "jobs" / f"{job.id}.json").read_text(encoding="utf-8"))
    snapshot_text = json.dumps(raw["request_snapshot"])
    for needle in (
        "sk-abcdefghijklmnop",
        "Bearer tok-12345",
        "tok-12345",
        "abc123",
        "jwt-token-here",
        "hunter2",
        "deep-secret",
        secret_b64,
    ):
        assert needle not in snapshot_text
    assert "[REDACTED]" in snapshot_text


def test_complete_job_json_never_persists_prompt_credentials(
    worker: ImageGenerationJobWorker,
) -> None:
    """A credential embedded in the prompt text is scrubbed from *every*
    persisted job metadata field (``original_prompt``, ``request_snapshot``,
    ``request_hash``, ...), not only from the request snapshot (§10.5)."""
    secret_b64 = base64.b64encode(b"prompt-payload-bytes-" * 20).decode("ascii")
    cases = [
        ("api_key", "draw a fox api_key=sk-promptsecret123", ["sk-promptsecret123"]),
        (
            "authorization",
            "draw a cat Authorization: Bearer tok-prompt-abc456",
            ["tok-prompt-abc456"],
        ),
        (
            "cookie",
            "draw a dog cookie: session=abc123; csrf=def456",
            ["session=abc123", "csrf=def456"],
        ),
        ("token", "draw a bird token=prompt-jwt-token", ["prompt-jwt-token"]),
        (
            "base64",
            f"draw a fish data:image/png;base64,{secret_b64}",
            [secret_b64],
        ),
    ]
    for label, prompt, needles in cases:
        job = worker.create_job(
            **_job_args(
                user_id=f"u-{label}",
                idempotency_key=f"prompt-secret-{label}",
                prompt=prompt,
            )
        )
        raw = json.loads(
            (worker.store.root / "jobs" / f"{job.id}.json").read_text(encoding="utf-8")
        )
        # Scan the complete persisted job JSON, not only request_snapshot.
        blob = json.dumps(raw)
        for needle in needles:
            assert needle not in blob, f"{label}: leaked {needle!r} into job JSON"
        # The executor-facing prompt fields are scrubbed, never the raw value.
        assert job.original_prompt != prompt
        assert job.request_snapshot["prompt"] != prompt
        assert "sk-***" in blob or "[REDACTED base64 payload]" in blob or "***" in blob


@pytest.mark.asyncio
async def test_executor_cannot_retrieve_leaked_prompt_secret(
    worker: ImageGenerationJobWorker,
) -> None:
    """The executor receives only the sanitized prompt from the durable job."""
    captured: dict[str, Any] = {}

    class CapturingExecutor(FakeExecutor):
        async def run(self, job: ImageGenerationJob) -> list[MediaInput]:
            captured["original_prompt"] = job.original_prompt
            captured["snapshot_prompt"] = job.request_snapshot.get("prompt")
            return [make_media_input()]

    worker.set_executor(CapturingExecutor())
    leaked = "draw a fox api_key=sk-executorsecret456"
    job = worker.create_job(**_job_args(prompt=leaked))
    await worker.run_job(job.id)
    assert "sk-executorsecret456" not in captured["original_prompt"]
    assert "sk-executorsecret456" not in captured["snapshot_prompt"]
    assert "sk-executorsecret456" not in job.original_prompt
    assert "***" in captured["original_prompt"]


# ── prompt fidelity: precise base64 detection (final defect) ────────────────


def _long_unpunctuated_prompt() -> str:
    """A 128+ character ordinary natural-language image prompt: letters and
    spaces only — no punctuation, no digits, no base64-looking token."""
    return (
        "once upon a time in a cozy little forest there lived a curious red fox "
        "who loved to chase golden butterflies through the tall green grass while "
        "humming a happy tune and dreaming of distant mountains covered in soft "
        "morning mist"
    )


def test_long_unpunctuated_prompt_is_preserved_byte_for_byte(
    worker: ImageGenerationJobWorker,
) -> None:
    """Regression: a long natural-language prompt (spaces, no punctuation) must
    not be collapsed as a "compacted base64 payload" (§10.5)."""
    prompt = _long_unpunctuated_prompt()
    assert len(prompt) >= 128

    job = worker.create_job(**_job_args(prompt=prompt))

    # Executor-facing field and frozen snapshot preserve the prompt verbatim.
    assert job.original_prompt == prompt
    assert job.request_snapshot["prompt"] == prompt

    # Persisted job JSON carries the intended prompt, never the marker.
    raw = json.loads((worker.store.root / "jobs" / f"{job.id}.json").read_text(encoding="utf-8"))
    blob = json.dumps(raw)
    assert raw["original_prompt"] == prompt
    assert raw["request_snapshot"]["prompt"] == prompt
    assert "[REDACTED base64 payload]" not in blob

    # The request hash is the deterministic hash of the intended prompt, not
    # the marker the old whole-string heuristic would have substituted.
    expected = _request_hash(
        operation=ArtifactOperation.GENERATE.value,
        prompt=prompt,
        source_artifact_ids=[],
        mask_artifact_id="",
        continuation_job_id="",
        retry_of_job_id="",
        session_id="sess-1",
        turn_id="turn-1",
        tool_call_id="tool-1",
        provider="openai",
        profile="p1",
        protocol="openai_images",
        model="gpt-image-2",
        size="",
        quality="",
        count=1,
        provider_options={},
        connect_timeout_seconds=20,
        read_timeout_seconds=1800,
        deadline_at=0.0,
    )
    assert job.request_hash == expected
    marker_hash = _request_hash(
        operation=ArtifactOperation.GENERATE.value,
        prompt="[REDACTED base64 payload]",
        source_artifact_ids=[],
        mask_artifact_id="",
        continuation_job_id="",
        retry_of_job_id="",
        session_id="sess-1",
        turn_id="turn-1",
        tool_call_id="tool-1",
        provider="openai",
        profile="p1",
        protocol="openai_images",
        model="gpt-image-2",
        size="",
        quality="",
        count=1,
        provider_options={},
        connect_timeout_seconds=20,
        read_timeout_seconds=1800,
        deadline_at=0.0,
    )
    assert job.request_hash != marker_hash


def test_bare_contiguous_base64_payload_is_still_redacted(
    worker: ImageGenerationJobWorker,
) -> None:
    """A real contiguous base64 payload — with or without ``+``/``/``/``=``
    padding — is still collapsed even when it is not wrapped in a data URI."""
    payloads = [
        base64.b64encode(b"image-bytes-" * 20).decode("ascii"),  # +, /, = present
        base64.b64encode(b"a" * 96).decode("ascii"),  # alphanumeric, no padding
    ]
    for index, payload in enumerate(payloads):
        assert len(payload) >= 64
        assert " " not in payload
        job = worker.create_job(
            **_job_args(
                user_id=f"u-b64-{index}",
                idempotency_key=f"b64-payload-{index}",
                prompt=f"please render {payload}",
            )
        )
        assert job.original_prompt == "[REDACTED base64 payload]"
        assert job.request_snapshot["prompt"] == "[REDACTED base64 payload]"
        raw = json.loads(
            (worker.store.root / "jobs" / f"{job.id}.json").read_text(encoding="utf-8")
        )
        blob = json.dumps(raw)
        assert payload not in blob
        assert "[REDACTED base64 payload]" in blob


def test_looks_like_base64_payload_discriminates_prompt_from_payload() -> None:
    """The heuristic is precise: ordinary words (even 128+ chars with spaces)
    are not base64; a data URI or a long contiguous base64 token is."""
    from deeptutor.services.media.worker import _looks_like_base64_payload

    assert not _looks_like_base64_payload(_long_unpunctuated_prompt())
    assert _looks_like_base64_payload(
        "data:image/png;base64," + base64.b64encode(b"x" * 200).decode("ascii")
    )
    assert _looks_like_base64_payload(base64.b64encode(b"a" * 96).decode("ascii"))


def test_caller_cannot_inject_remote_reference_ids(
    worker: ImageGenerationJobWorker,
) -> None:
    job = worker.create_job(
        **_job_args(
            request_snapshot={
                "provider_options": {
                    "previous_response_id": "resp-injected",
                    "remote_job_id": "job-injected",
                    "response_id": "resp-injected-2",
                    "remote_response_id": "resp-injected-3",
                    "foo": "bar",
                }
            },
        )
    )
    options = job.request_snapshot.get("provider_options", {})
    for forbidden in (
        "previous_response_id",
        "remote_job_id",
        "response_id",
        "remote_response_id",
    ):
        assert forbidden not in options
    assert options["foo"] == "bar"


def test_caller_cannot_bypass_remote_reference_strip_with_casing(
    worker: ImageGenerationJobWorker,
) -> None:
    """Forbidden remote/continuation identity keys are stripped regardless of
    casing and snake/camel separator style (§10.1 server-owned continuation)."""
    job = worker.create_job(
        **_job_args(
            request_snapshot={
                "provider_options": {
                    "Previous_Response_ID": "resp-cased-1",
                    "previousResponseId": "resp-cased-2",
                    "Remote_Job_ID": "job-cased-1",
                    "remoteJobId": "job-cased-2",
                    "RESPONSE_ID": "resp-cased-3",
                    "responseId": "resp-cased-4",
                    "Remote-Asset-Id": "asset-cased-1",
                    "remoteAssetId": "asset-cased-2",
                    "JOB_ID": "job-cased-3",
                    "jobId": "job-cased-4",
                    "continuationJobId": "cont-cased-1",
                    "previous_response_id": "resp-cased-5",
                    "foo": "bar",
                    "background": True,
                    "size": "1024x1024",
                }
            },
        )
    )
    options = job.request_snapshot.get("provider_options", {})
    for forbidden in (
        "Previous_Response_ID",
        "previousResponseId",
        "Remote_Job_ID",
        "remoteJobId",
        "RESPONSE_ID",
        "responseId",
        "Remote-Asset-Id",
        "remoteAssetId",
        "JOB_ID",
        "jobId",
        "continuationJobId",
        "previous_response_id",
    ):
        assert forbidden not in options
    # Legitimate provider options survive.
    assert options["foo"] == "bar"
    assert options["background"] is True
    assert options["size"] == "1024x1024"


# ── success only after atomic persistence ───────────────────────────────────


@pytest.mark.asyncio
async def test_job_succeeds_only_after_atomic_persist(worker: ImageGenerationJobWorker) -> None:
    executor = FakeExecutor(inputs=[make_media_input(), make_media_input(width=4, height=4)])
    worker.set_executor(executor)
    job = worker.create_job(**_job_args())

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    assert executor.runs == 1
    assert len(result.artifact_ids) == 2
    # The final transition is versioned.
    assert result.status_version >= 1

    artifacts = [worker.store.load_artifact(aid) for aid in result.artifact_ids]
    assert all(a is not None for a in artifacts)
    for artifact in artifacts:
        assert worker.store.persistence.resolve(artifact.original_path).exists()
        assert artifact.session_id == "sess-1"
        # The session/turn reference was created at save time.
        refs = worker.store.list_references(artifact_id=artifact.id, live_only=True)
        assert len(refs) == 1
        assert refs[0].owner_type == ReferenceOwnerType.SESSION
        assert refs[0].owner_id == "sess-1"


@pytest.mark.asyncio
async def test_success_with_empty_session_arms_gc_and_is_reclaimable(
    worker: ImageGenerationJobWorker,
) -> None:
    """A succeeded artifact with no session (hence no reference) enters the GC
    grace period immediately so its quota is recoverable (§12.3)."""
    worker.set_executor(FakeExecutor(inputs=[make_media_input()]))
    job = worker.create_job(**_job_args(session_id=""))

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.SUCCEEDED
    artifact = worker.store.load_artifact(result.artifact_ids[0])
    assert artifact is not None
    assert artifact.gc_candidate_since > 0
    assert worker.store.list_references(artifact_id=artifact.id, live_only=True) == []
    # The automatic sweep still waits for the grace period...
    assert worker.store.run_gc(user_id="u1", force=False).deleted_count == 0
    # ...but an explicit GC ends the grace early and frees the quota.
    gc = worker.store.run_gc(user_id="u1", force=True)
    assert gc.deleted_count == 1
    assert worker.store.used_bytes("u1") == 0
    assert worker.store.load_artifact(result.artifact_ids[0]) is None


@pytest.mark.asyncio
async def test_job_never_succeeds_when_persist_rejected(worker: ImageGenerationJobWorker) -> None:
    bad_input = MediaInput(data=b"definitely not an image", mime_type="image/png")
    worker.set_executor(FakeExecutor(inputs=[bad_input]))
    job = worker.create_job(**_job_args())

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "validation_error"
    assert result.artifact_ids == []
    assert worker.store.list_artifacts(user_id="u1") == []
    # Nothing was committed to the originals store.
    assert list((worker.store.root / "originals").rglob("*")) == []


@pytest.mark.asyncio
async def test_job_failed_when_executor_raises_and_error_is_sanitized(
    worker: ImageGenerationJobWorker,
) -> None:
    worker.set_executor(FakeExecutor(error=RuntimeError("boom sk-abcdefghijklmnop")))
    job = worker.create_job(**_job_args())

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "provider_error"
    assert "sk-***" in result.sanitized_error
    assert "abcdefghijklmnop" not in result.sanitized_error


@pytest.mark.asyncio
async def test_job_failed_when_no_executor(worker: ImageGenerationJobWorker) -> None:
    job = worker.create_job(**_job_args())
    result = await worker.run_job(job.id)
    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "no_executor"


@pytest.mark.asyncio
async def test_job_timed_out_when_deadline_passed(worker: ImageGenerationJobWorker) -> None:
    job = worker.create_job(**_job_args(deadline_at=1.0))  # far in the past
    result = await worker.run_job(job.id)
    assert result.status == ImageJobStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_running_non_queued_job_is_rejected(worker: ImageGenerationJobWorker) -> None:
    worker.set_executor(FakeExecutor(inputs=[make_media_input()]))
    job = worker.create_job(**_job_args())
    worker.store.transition_job(
        job.id, from_status=ImageJobStatus.QUEUED, to_status=ImageJobStatus.RUNNING
    )
    with pytest.raises(JobStateError, match="not queued"):
        await worker.run_job(job.id)


# ── restart recovery ────────────────────────────────────────────────────────


def _raw_job(
    store: MediaStore,
    *,
    status: ImageJobStatus = ImageJobStatus.QUEUED,
    remote_response_id: str = "",
    remote_job_id: str = "",
    session_id: str = "",
    user_id: str = "u1",
    profile: str = "",
) -> ImageGenerationJob:
    """Persist a job directly, bypassing the concurrency slot on purpose."""
    job = ImageGenerationJob(
        id=uuid.uuid4().hex,
        user_id=user_id,
        session_id=session_id,
        original_prompt="a red fox",
        request_hash="h",
        status=status,
        remote_response_id=remote_response_id,
        remote_job_id=remote_job_id,
        profile=profile,
    )
    return store.save_job(job)


def test_restart_recovery_maps_states_deterministically(media_store: MediaStore) -> None:
    # queued stays executable
    queued = _raw_job(media_store, status=ImageJobStatus.QUEUED)
    # running/polling without a remote id -> unknown
    running_no_remote = _raw_job(media_store, status=ImageJobStatus.RUNNING)
    polling_no_remote = _raw_job(media_store, status=ImageJobStatus.POLLING)
    # running/polling with a remote id resume reconcile/poll (state unchanged)
    running_remote = _raw_job(
        media_store, status=ImageJobStatus.RUNNING, remote_response_id="resp-1"
    )
    polling_remote = _raw_job(media_store, status=ImageJobStatus.POLLING, remote_job_id="job-1")
    # validating/saving are local-only -> unknown
    validating = _raw_job(media_store, status=ImageJobStatus.VALIDATING)
    saving = _raw_job(media_store, status=ImageJobStatus.SAVING)
    # cancel_requested stays; only cancel confirmation resumes
    cancel_requested = _raw_job(media_store, status=ImageJobStatus.CANCEL_REQUESTED)
    # terminal states never resume
    succeeded = _raw_job(media_store, status=ImageJobStatus.SUCCEEDED)
    failed = _raw_job(media_store, status=ImageJobStatus.FAILED)

    # Simulate a fresh process: new worker over the same durable store.
    fresh = ImageGenerationJobWorker(store=media_store)
    transitions = {row["job_id"]: row for row in fresh.recover()}

    assert queued.id not in transitions  # queued stays executable, no transition
    assert transitions.get(running_no_remote.id, {}).get("to") == ImageJobStatus.UNKNOWN.value
    assert transitions.get(polling_no_remote.id, {}).get("to") == ImageJobStatus.UNKNOWN.value
    assert running_remote.id not in transitions
    assert polling_remote.id not in transitions
    assert transitions.get(validating.id, {}).get("to") == ImageJobStatus.UNKNOWN.value
    assert transitions.get(saving.id, {}).get("to") == ImageJobStatus.UNKNOWN.value
    assert cancel_requested.id not in transitions
    assert succeeded.id not in transitions
    assert failed.id not in transitions

    assert media_store.load_job(running_no_remote.id).status == ImageJobStatus.UNKNOWN
    assert media_store.load_job(validating.id).status == ImageJobStatus.UNKNOWN
    assert media_store.load_job(running_remote.id).status == ImageJobStatus.RUNNING
    assert media_store.load_job(queued.id).status == ImageJobStatus.QUEUED


@pytest.mark.asyncio
async def test_restart_preserves_job_and_artifacts_on_disk(media_store: MediaStore) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(FakeExecutor(inputs=[make_media_input()]))
    job = worker.create_job(**_job_args())
    await worker.run_job(job.id)

    # Fresh process, same root: records and files are all still there.
    fresh_store = MediaStore(root=media_store.root, limits=media_store.limits)
    fresh_worker = ImageGenerationJobWorker(store=fresh_store)
    assert fresh_worker.recover() == []

    reloaded = fresh_store.load_job(job.id)
    assert reloaded is not None
    assert reloaded.status == ImageJobStatus.SUCCEEDED
    artifact = fresh_store.load_artifact(reloaded.artifact_ids[0])
    assert artifact is not None
    assert fresh_store.persistence.resolve(artifact.original_path).exists()


# ── restart recovery isolation (final defect) ───────────────────────────────


def test_restart_recovery_skips_corrupt_record_and_recovers_others(
    media_store: MediaStore, caplog: pytest.LogCaptureFixture
) -> None:
    """One corrupt job record must not block recovery of other jobs or orphan
    cleanup; the recovery-only tolerant listing logs only id + exception type."""
    valid = _raw_job(media_store, status=ImageJobStatus.RUNNING)  # -> unknown
    corrupt_id = uuid.uuid4().hex
    (media_store.root / "jobs" / f"{corrupt_id}.json").write_text(
        "{ this is not json", encoding="utf-8"
    )
    # An orphaned file from a crashed save must still be cleaned up.
    saved = media_store.persistence.save_media(make_png(8, 8), mime_type="image/png")
    orphan = media_store.persistence.resolve(saved.original_path)
    assert orphan.exists()

    with caplog.at_level(logging.WARNING, logger="deeptutor.services.media.store"):
        fresh = ImageGenerationJobWorker(store=media_store)
        transitions = fresh.recover()

    # The valid job recovered; the corrupt one was skipped, not fatal.
    assert [row["job_id"] for row in transitions] == [valid.id]
    assert media_store.load_job(valid.id).status == ImageJobStatus.UNKNOWN
    assert not orphan.exists()
    # The skip is logged with only the record id and the exception type.
    assert corrupt_id in caplog.text
    assert "JSONDecodeError" in caplog.text


def test_normal_listing_still_fails_closed_while_recovery_listing_isolates(
    media_store: MediaStore,
) -> None:
    """Normal paths must NOT silently skip corrupt active records; only the
    recovery-only tolerant listing may isolate them."""
    valid = _raw_job(media_store, status=ImageJobStatus.QUEUED)
    corrupt_id = uuid.uuid4().hex
    (media_store.root / "jobs" / f"{corrupt_id}.json").write_text("{ not json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        media_store.list_jobs()
    with pytest.raises(json.JSONDecodeError):
        media_store.find_job_by_idempotency_key("u1", "whatever")

    assert [job.id for job in media_store.list_jobs_for_recovery()] == [valid.id]


def test_restart_recovery_continues_past_transition_failure(
    media_store: MediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed state transition for one job must not stop later jobs from
    being recovered."""
    blocked = _raw_job(media_store, status=ImageJobStatus.RUNNING)
    later = _raw_job(media_store, status=ImageJobStatus.VALIDATING)
    real_transition = media_store.transition_job

    def flaky_transition(job_id: str, *args: Any, **kwargs: Any) -> Any:
        if job_id == blocked.id:
            raise MediaError("injected transition failure")
        return real_transition(job_id, *args, **kwargs)

    monkeypatch.setattr(media_store, "transition_job", flaky_transition)

    fresh = ImageGenerationJobWorker(store=media_store)
    transitions = fresh.recover()

    # The blocked job's transition failed, but the later job still recovered.
    assert [row["job_id"] for row in transitions] == [later.id]
    assert media_store.load_job(later.id).status == ImageJobStatus.UNKNOWN
    assert media_store.load_job(blocked.id).status == ImageJobStatus.RUNNING


def test_restart_recovery_continues_past_reconciliation_failure(
    media_store: MediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed artifact reconciliation for one job must not stop later
    reconciliations or orphan-file cleanup."""
    _raw_job(media_store, status=ImageJobStatus.FAILED)  # first in sort order
    _raw_job(media_store, status=ImageJobStatus.FAILED)
    real_reconcile = media_store.reconcile_artifacts_for_job
    calls: dict[str, int] = {"count": 0}

    def flaky_reconcile(job: ImageGenerationJob) -> int:
        calls["count"] += 1
        if calls["count"] == 1:
            raise MediaError("injected reconcile failure")
        return real_reconcile(job)

    monkeypatch.setattr(media_store, "reconcile_artifacts_for_job", flaky_reconcile)

    # An orphaned file a crashed save left behind must still be cleaned up
    # even though one reconciliation failed.
    saved = media_store.persistence.save_media(make_png(8, 8), mime_type="image/png")
    orphan = media_store.persistence.resolve(saved.original_path)
    assert orphan.exists()

    fresh = ImageGenerationJobWorker(store=media_store)
    transitions = fresh.recover()

    assert transitions == []  # failed terminal jobs never transition
    assert calls["count"] == 2  # first reconcile failed, second still ran
    assert not orphan.exists()  # orphan cleanup still ran


# ── cancel ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_without_provider_support_becomes_cancelled_unconfirmed(
    media_store: MediaStore,
) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    job = worker.create_job(**_job_args())
    media_store.transition_job(
        job.id,
        from_status=ImageJobStatus.QUEUED,
        to_status=ImageJobStatus.CANCEL_REQUESTED,
    )
    worker.set_executor(FakeExecutor(cancel_confirmed=None))  # not supported

    result = await worker.run_cancel(job.id)
    assert result.status == ImageJobStatus.CANCELLED_UNCONFIRMED


@pytest.mark.asyncio
async def test_cancel_with_provider_confirmation_becomes_cancelled(
    media_store: MediaStore,
) -> None:
    worker = ImageGenerationJobWorker(store=media_store)
    job = worker.create_job(**_job_args())
    media_store.transition_job(
        job.id,
        from_status=ImageJobStatus.QUEUED,
        to_status=ImageJobStatus.CANCEL_REQUESTED,
    )
    worker.set_executor(FakeExecutor(cancel_confirmed=True))

    result = await worker.run_cancel(job.id)
    assert result.status == ImageJobStatus.CANCELLED


# ── concurrency slot ────────────────────────────────────────────────────────


def test_concurrency_slot_blocks_extra_queued_jobs(tmp_path: Path) -> None:
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits(max_concurrent_jobs=1))
    worker = ImageGenerationJobWorker(store=store)
    worker.create_job(**_job_args(idempotency_key="one"))
    with pytest.raises(JobConcurrencyError, match="in-flight"):
        worker.create_job(**_job_args(idempotency_key="two"))


@pytest.mark.asyncio
async def test_edit_job_preserves_parent_and_mask_provenance(
    media_store: MediaStore,
) -> None:
    """§10.5: parent ids are the source record ids; ``mask_sha256`` is the
    mask artifact's *content* hash, never the artifact record id."""
    source = _persisted_artifact(media_store, user_id="u1", width=8, height=8)
    mask = _persisted_artifact(media_store, user_id="u1", width=4, height=4)
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(FakeExecutor(inputs=[make_media_input()]))
    job = worker.create_job(
        **_job_args(
            operation=ArtifactOperation.EDIT,
            source_artifact_ids=[source.id],
            mask_artifact_id=mask.id,
        )
    )
    result = await worker.run_job(job.id)
    artifact = worker.store.load_artifact(result.artifact_ids[0])
    assert artifact.operation == ArtifactOperation.EDIT
    assert artifact.parent_artifact_ids == [source.id]
    assert artifact.mask_sha256 == mask.sha256
    assert artifact.mask_sha256 != mask.id
    assert artifact.mask_sha256 != source.sha256


# ── metadata rollback on partial persist (P0) ───────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fail_method, fail_on",
    [
        ("save_artifact", 1),
        ("save_artifact", 2),
        ("create_reference", 1),
        ("create_reference", 2),
    ],
)
async def test_failed_persist_rolls_back_metadata_atomically(
    media_store: MediaStore,
    fail_method: str,
    fail_on: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed multi-image save leaves no live metadata or media behind.

    Failing on the first or second metadata write covers every partial step:
    after files are persisted, an artifact or reference may already be
    committed when the next write fails.  The rollback must remove the
    committed records and the files so nothing dangles and quota is freed.
    """
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(
        FakeExecutor(inputs=[make_media_input(), make_media_input(width=4, height=4)])
    )
    job = worker.create_job(**_job_args())
    original = getattr(media_store, fail_method)
    calls = {"count": 0}

    def flaky(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        if calls["count"] == fail_on:
            raise MediaError(f"injected {fail_method} failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(media_store, fail_method, flaky)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.artifact_ids == []
    # No artifact records, no references, no media files and no quota charge.
    assert media_store.list_artifacts(user_id="u1") == []
    assert media_store.list_references() == []
    assert list((media_store.root / "originals").rglob("*.png")) == []
    assert list((media_store.root / "thumbnails").rglob("*.jpg")) == []
    assert media_store.used_bytes("u1") == 0


@pytest.mark.asyncio
async def test_failed_persist_with_invalid_second_image_cleans_files(
    worker: ImageGenerationJobWorker,
) -> None:
    """A failure in the file phase cleans the files already written."""
    worker.set_executor(
        FakeExecutor(
            inputs=[
                make_media_input(),
                MediaInput(data=b"definitely not an image", mime_type="image/png"),
            ]
        )
    )
    job = worker.create_job(**_job_args())

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert worker.store.list_artifacts(user_id="u1") == []
    assert list((worker.store.root / "originals").rglob("*.png")) == []


# ── cancellation during/after saving rollback (§11.6) ───────────────────────


@pytest.mark.asyncio
async def test_cancel_during_save_rolls_back_never_exposes_success(
    media_store: MediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close the race where `_persist_media` commits files/artifact/reference
    metadata, then the final `saving/validating -> succeeded` CAS loses to
    `cancel_requested`.  The run's media is rolled back immediately — no leaked
    artifacts/references/files, no restart required, quota recovered (§11.6)."""
    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(
        FakeExecutor(inputs=[make_media_input(), make_media_input(width=4, height=4)])
    )
    job = worker.create_job(**_job_args())
    real_transition = media_store.transition_job

    def canceling_transition(
        job_id: str, *, from_status: Any, to_status: ImageJobStatus, **updates: Any
    ) -> ImageGenerationJob:
        if to_status == ImageJobStatus.SUCCEEDED:
            # A concurrent cancel wins the CAS before succeeded lands.
            real_transition(
                job_id,
                from_status=from_status,
                to_status=ImageJobStatus.CANCEL_REQUESTED,
            )
            raise JobStateError(
                f"job {job_id} cannot transition from cancel_requested to succeeded"
            )
        return real_transition(job_id, from_status=from_status, to_status=to_status, **updates)

    monkeypatch.setattr(media_store, "transition_job", canceling_transition)

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.CANCEL_REQUESTED
    # Zero leaked artifacts/references/files and recovered quota.
    assert media_store.list_artifacts(user_id="u1") == []
    assert media_store.list_references() == []
    assert list((media_store.root / "originals").rglob("*.png")) == []
    assert list((media_store.root / "thumbnails").rglob("*.jpg")) == []
    assert media_store.used_bytes("u1") == 0

    # The cancel then resolves through the normal cancel-confirmation path.
    worker.set_executor(FakeExecutor(cancel_confirmed=True))
    final = await worker.run_cancel(job.id)
    assert final.status == ImageJobStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_during_poll_save_rolls_back(
    media_store: MediaStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same cancel-during-save rollback applies on the background poll path:
    media saved by a completed poll is rolled back when the succeeded CAS loses
    to cancel_requested (§11.6)."""
    from deeptutor.services.media.models import BackgroundSubmit, PollOutcome

    class BackgroundExecutor:
        def __init__(self) -> None:
            self.runs = 0

        async def run(self, job: ImageGenerationJob) -> BackgroundSubmit:
            self.runs += 1
            return BackgroundSubmit(remote_response_id="resp_1")

        async def poll(self, job: ImageGenerationJob) -> PollOutcome:
            return PollOutcome(media=[make_media_input()])

        async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
            return True

    worker = ImageGenerationJobWorker(store=media_store)
    worker.set_executor(BackgroundExecutor())
    job = worker.create_job(**_job_args())

    await worker.run_job(job.id)
    assert media_store.load_job(job.id).status == ImageJobStatus.POLLING

    real_transition = media_store.transition_job

    def canceling_transition(
        job_id: str, *, from_status: Any, to_status: ImageJobStatus, **updates: Any
    ) -> ImageGenerationJob:
        if to_status == ImageJobStatus.SUCCEEDED:
            real_transition(
                job_id,
                from_status=from_status,
                to_status=ImageJobStatus.CANCEL_REQUESTED,
            )
            raise JobStateError(
                f"job {job_id} cannot transition from cancel_requested to succeeded"
            )
        return real_transition(job_id, from_status=from_status, to_status=to_status, **updates)

    monkeypatch.setattr(media_store, "transition_job", canceling_transition)

    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.CANCEL_REQUESTED
    assert media_store.list_artifacts(user_id="u1") == []
    assert media_store.list_references() == []
    assert list((media_store.root / "originals").rglob("*.png")) == []
    assert media_store.used_bytes("u1") == 0


# ── poll-path local persistence failure (independent-review HIGH finding) ───


class _PollCompleteExecutor:
    """Fake adapter whose ``run`` acknowledges a background submit and whose
    first ``poll`` returns apparently-valid completed media with no provider
    error — so any failure in the test is injected locally, after the job has
    already left ``polling``."""

    def __init__(self) -> None:
        self.runs = 0
        self.poll_calls = 0

    async def run(self, job: ImageGenerationJob) -> BackgroundSubmit:
        self.runs += 1
        return BackgroundSubmit(remote_response_id="resp_1")

    async def poll(self, job: ImageGenerationJob) -> PollOutcome:
        self.poll_calls += 1
        return PollOutcome(media=[make_media_input()])

    async def confirm_cancel(self, job: ImageGenerationJob) -> bool:
        return True


async def _background_polling_job(
    media_store: MediaStore, worker: ImageGenerationJobWorker
) -> tuple[_PollCompleteExecutor, ImageGenerationJob]:
    """Advance a fresh queued job to ``polling`` with a durable remote id via
    the real ``run_job`` path, exactly as production would."""
    executor = _PollCompleteExecutor()
    worker.set_executor(executor)
    job = worker.create_job(**_job_args())
    assert (await worker.run_job(job.id)).status == ImageJobStatus.POLLING
    assert media_store.load_job(job.id).status == ImageJobStatus.POLLING
    assert media_store.load_job(job.id).remote_response_id == "resp_1"
    return executor, job


@pytest.mark.asyncio
async def test_poll_persist_validation_failure_fails_job(
    media_store: MediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed poll whose local validation fails (job already left
    ``polling`` for ``validating``) must return a terminal ``failed`` job
    instead of leaving the job stuck in a state the scheduler never processes."""
    worker = ImageGenerationJobWorker(store=media_store)
    executor, job = await _background_polling_job(media_store, worker)

    def corrupt_save(*args: Any, **kwargs: Any) -> Any:
        raise MediaValidationError("corrupt image data during local validation")

    monkeypatch.setattr(media_store, "save_media_tracked", corrupt_save)

    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "validation_error"
    assert "corrupt image data" in result.sanitized_error
    stored = media_store.load_job(job.id)
    assert stored is not None and stored.status == ImageJobStatus.FAILED
    # The durable remote identity is preserved for diagnostics/reconciliation.
    assert stored.remote_response_id == "resp_1"
    # No leaked artifacts, references, files, or quota charge.
    assert media_store.list_artifacts(user_id="u1") == []
    assert media_store.list_references() == []
    assert list((media_store.root / "originals").rglob("*.png")) == []
    assert list((media_store.root / "thumbnails").rglob("*.jpg")) == []
    assert media_store.used_bytes("u1") == 0
    # Exactly one provider submit; a poll failure never resubmits.
    assert executor.runs == 1
    assert executor.poll_calls == 1


@pytest.mark.asyncio
async def test_poll_persist_failure_in_saving_state_fails_job(
    media_store: MediaStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A completed poll that fails while writing artifact metadata (job already
    in ``saving``) rolls the run back and fails the job — never leaking media."""
    worker = ImageGenerationJobWorker(store=media_store)
    executor, job = await _background_polling_job(media_store, worker)

    def failing_save_artifact(*args: Any, **kwargs: Any) -> Any:
        raise MediaError("injected disk failure while writing artifact metadata")

    monkeypatch.setattr(media_store, "save_artifact", failing_save_artifact)

    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    stored = media_store.load_job(job.id)
    assert stored is not None and stored.status == ImageJobStatus.FAILED
    # The file saved before the metadata failure is rolled back, so the
    # failed job charges no quota and leaves no artifact/reference behind.
    assert media_store.list_artifacts(user_id="u1") == []
    assert media_store.list_references() == []
    assert list((media_store.root / "originals").rglob("*.png")) == []
    assert list((media_store.root / "thumbnails").rglob("*.jpg")) == []
    assert media_store.used_bytes("u1") == 0
    assert stored.remote_response_id == "resp_1"
    assert executor.runs == 1
    assert executor.poll_calls == 1


@pytest.mark.asyncio
async def test_poll_completed_but_no_media_or_delay_fails_job(
    media_store: MediaStore,
) -> None:
    """A completed poll that yields neither media nor a poll delay is a provider
    protocol failure: ``poll_job`` must fail it, not leave it stuck in
    ``polling`` (§11.5)."""

    class NoResultExecutor(_PollCompleteExecutor):
        async def poll(self, job: ImageGenerationJob) -> PollOutcome:
            self.poll_calls += 1
            return PollOutcome()

    worker = ImageGenerationJobWorker(store=media_store)
    executor = NoResultExecutor()
    worker.set_executor(executor)
    job = worker.create_job(**_job_args())
    await worker.run_job(job.id)
    assert media_store.load_job(job.id).status == ImageJobStatus.POLLING

    result = await worker.poll_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    stored = media_store.load_job(job.id)
    assert stored is not None and stored.status == ImageJobStatus.FAILED
    assert stored.remote_response_id == "resp_1"
    assert executor.runs == 1
    assert executor.poll_calls == 1


# ── sanitized failure logging (independent-review finding) ──────────────────


@pytest.mark.asyncio
async def test_failure_logs_are_sanitized(
    worker: ImageGenerationJobWorker, caplog: pytest.LogCaptureFixture
) -> None:
    worker.set_executor(FakeExecutor(error=RuntimeError("boom sk-abcdefghijklmnop")))
    job = worker.create_job(**_job_args())
    with caplog.at_level(logging.WARNING, logger="deeptutor.services.media.worker"):
        await worker.run_job(job.id)
    assert "abcdefghijklmnop" not in caplog.text
    assert "sk-***" in caplog.text


#: Secret-shaped test values are assembled at runtime (or kept obviously fake)
#: so the fixtures exercise the redaction patterns without embedding real
#: credential literals in the source tree.
_BASIC_AUTH_VALUE = base64.b64encode(b"not-a-real-credential").decode("ascii")
_FAKE_JWT_VALUE = "header.payload.signature"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message, needle",
    [
        pytest.param(
            f"boom Authorization: Basic {_BASIC_AUTH_VALUE}",
            _BASIC_AUTH_VALUE,
            id="basic",
        ),
        pytest.param(
            "boom authorization: Bearer not-a-real-bearer-token",
            "not-a-real-bearer-token",
            id="bearer",
        ),
        pytest.param("boom X-Api-Key: not-a-real-api-key", "not-a-real-api-key", id="api-key"),
        pytest.param("boom api_key=leaked-key-value", "leaked-key-value", id="api_key"),
        pytest.param("boom password=hunter2", "hunter2", id="password"),
        pytest.param(f"boom token: {_FAKE_JWT_VALUE}", _FAKE_JWT_VALUE, id="token"),
        pytest.param(
            "boom cookie: session=abc123; csrf=def456",
            "session=abc123; csrf=def456",
            id="cookie",
        ),
        pytest.param("boom secret=verysecretvalue", "verysecretvalue", id="secret"),
    ],
)
async def test_failure_error_redacts_authorization_and_credentials(
    worker: ImageGenerationJobWorker, message: str, needle: str
) -> None:
    worker.set_executor(FakeExecutor(error=RuntimeError(message)))
    job = worker.create_job(**_job_args())

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert needle not in result.sanitized_error
    assert "***" in result.sanitized_error
    # Stable error codes stay useful while the message is scrubbed.
    assert result.error_code == "provider_error"


@pytest.mark.asyncio
async def test_failure_error_redacts_entire_cookie_value(
    worker: ImageGenerationJobWorker,
) -> None:
    """A cookie's full value (including ``;``-separated fields) is scrubbed."""
    worker.set_executor(
        FakeExecutor(error=RuntimeError("boom cookie: session=abc123; csrf=def456"))
    )
    job = worker.create_job(**_job_args())

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert "session=abc123" not in result.sanitized_error
    assert "csrf=def456" not in result.sanitized_error
    assert result.sanitized_error == "boom cookie: ***"


# ── adversarial URL/credential redaction (§14) ──────────────────────────────


def _adversarial_error_text() -> str:
    """A hostile provider/MCP error mixing a private URL, percent-encoded
    credentials, auth headers, cookies, tokens and a base64 payload.

    Secret-shaped values are assembled at runtime (mirroring
    ``_BASIC_AUTH_VALUE`` / ``_FAKE_JWT_VALUE`` above) so the source tree never
    embeds credential literals for the privacy filter to trip on.
    """
    userinfo = "user" + ":" + "pass"
    private_url = (
        f"https://{userinfo}@private-host.example:8443/v1/images"
        "?api_key=supersecret&token=abc%20def#frag"
    )
    bearer = "tok-" + "12345"
    secret_key = "sk" + "-" + "abcdefghijklmnop"
    return (
        f"boom {private_url}"
        f" Authorization: Bearer {bearer} cookie: session=abc123; csrf=def456"
        f" {secret_key} api_key=leaked-key-value password=hunter2"
        f" X-Api-Key: not-a-real-api-key"
    )


@pytest.mark.asyncio
async def test_failure_error_collapses_urls_host_path_query_and_secrets(
    worker: ImageGenerationJobWorker,
) -> None:
    """Host, path, query, userinfo, percent-encoded credentials, auth headers,
    cookies and token/key/password labels are all absent from the sanitized
    persisted error — not merely a single token pattern replaced (§14)."""
    message = _adversarial_error_text()
    worker.set_executor(FakeExecutor(error=RuntimeError(message)))
    job = worker.create_job(**_job_args())

    result = await worker.run_job(job.id)

    assert result.status == ImageJobStatus.FAILED
    assert result.error_code == "provider_error"  # stable class/code retained
    for needle in (
        "private-host",
        "/v1/images",
        "user:pass",
        "supersecret",
        "abc%20def",
        "tok-12345",
        "session=abc123",
        "csrf=def456",
        "sk-abcdefghijklmnop",
        "leaked-key-value",
        "hunter2",
        "not-a-real-api-key",
    ):
        assert needle not in result.sanitized_error, f"leaked {needle!r}"
    assert "[url]" in result.sanitized_error
    assert "***" in result.sanitized_error


def test_sanitize_snapshot_collapses_private_urls_in_provider_options(
    worker: ImageGenerationJobWorker,
) -> None:
    """A credential-bearing URL smuggled through provider options is collapsed
    in the persisted job record (§14)."""
    userinfo = "user" + ":" + "pass"
    endpoint = f"https://{userinfo}@private-host.example:8443/v1/images?api_key=supersecret"
    job = worker.create_job(
        **_job_args(
            user_id="u-url",
            idempotency_key="url-snapshot",
            request_snapshot={
                "provider_options": {
                    "endpoint": endpoint,
                    "foo": "bar",
                }
            },
        )
    )
    raw = json.loads((worker.store.root / "jobs" / f"{job.id}.json").read_text(encoding="utf-8"))
    blob = json.dumps(raw["request_snapshot"])
    for needle in ("private-host", "/v1/images", "user:pass", "supersecret"):
        assert needle not in blob, f"leaked {needle!r} into job snapshot"
    assert "[url]" in blob
    assert raw["request_snapshot"]["provider_options"]["foo"] == "bar"


# ── content-addressed dedup save/rollback race (P0) ─────────────────────────


def test_concurrent_same_content_success_and_failure_preserves_files(
    tmp_path: Path,
) -> None:
    """A failed saver must never remove an original/thumbnail now used by a
    concurrent successful artifact sharing the same SHA-256 content.

    Both threads save identical bytes, the barrier guarantees both in-flight
    refcounts are registered, then one commits its artifact while the other
    rolls back.  Whichever order they run in, the surviving artifact's files
    must remain valid.
    """
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits())
    data = make_png(4, 4)
    barrier = threading.Barrier(2)
    outcome: dict[str, Any] = {}

    def success_thread() -> None:
        saved = store.save_media_tracked(data, mime_type="image/png")
        barrier.wait()
        artifact = GeneratedArtifact(
            id=uuid.uuid4().hex,
            user_id="u1",
            session_id="sess-a",
            sha256=saved.sha256,
            mime_type=saved.mime_type,
            width=saved.width,
            height=saved.height,
            size_bytes=saved.size_bytes,
            original_path=saved.original_path,
            thumbnail_path=saved.thumbnail_path,
        )
        store.save_artifact(artifact)
        store.commit_saved_media([saved])
        outcome["artifact"] = artifact
        outcome["saved"] = saved

    def fail_thread() -> None:
        saved = store.save_media_tracked(data, mime_type="image/png")
        barrier.wait()
        store.rollback_save(artifact_ids=[], reference_ids=[], saved_media=[saved])
        outcome["failed_saved"] = saved

    threads = [threading.Thread(target=success_thread), threading.Thread(target=fail_thread)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    artifact = outcome["artifact"]
    saved = outcome["saved"]
    assert store.load_artifact(artifact.id) is not None
    original = store.persistence.resolve(artifact.original_path)
    assert original.exists()
    assert original.read_bytes() == data
    assert store.persistence.resolve(artifact.thumbnail_path).exists()
    # The failed saver must not have deleted the dedup-shared files.
    assert store.persistence.resolve(saved.original_path).exists()
    assert store.persistence.resolve(saved.thumbnail_path).exists()
    assert store.used_bytes("u1") == artifact.size_bytes


def test_two_roots_same_content_rollback_isolates_refcounts(tmp_path: Path) -> None:
    """In-flight content refcounts are scoped per media root.

    Identical bytes saved in root A and root B share a SHA-256 but must never
    alias on the in-flight refcount: root A's rollback removes A's files even
    while B's in-flight save of the same content is still open, and B's later
    success keeps B's files valid.  The refcount registry returns to its prior
    state.
    """
    root_a = tmp_path / "media-a"
    root_b = tmp_path / "media-b"
    store_a = MediaStore(root=root_a, limits=MediaLimits())
    store_b = MediaStore(root=root_b, limits=MediaLimits())
    data = make_png(4, 4)
    before = dict(media_store_mod._save_refcounts)

    saved_a = store_a.save_media_tracked(data, mime_type="image/png")
    saved_b = store_b.save_media_tracked(data, mime_type="image/png")
    assert saved_a.sha256 == saved_b.sha256

    # Root A rolls back while root B's save is still in-flight.
    store_a.rollback_save(artifact_ids=[], reference_ids=[], saved_media=[saved_a])

    # Root A has no original/thumbnail files and no artifact/reference records.
    assert list((root_a / "originals").rglob("*.png")) == []
    assert list((root_a / "thumbnails").rglob("*.jpg")) == []
    assert store_a.list_artifacts() == []
    assert store_a.list_references() == []

    # Root B then commits and its content-addressed files remain valid.
    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id="u1",
        session_id="sess-a",
        sha256=saved_b.sha256,
        mime_type=saved_b.mime_type,
        width=saved_b.width,
        height=saved_b.height,
        size_bytes=saved_b.size_bytes,
        original_path=saved_b.original_path,
        thumbnail_path=saved_b.thumbnail_path,
    )
    store_b.save_artifact(artifact)
    store_b.commit_saved_media([saved_b])

    assert store_b.load_artifact(artifact.id) is not None
    original = store_b.persistence.resolve(artifact.original_path)
    assert original.exists()
    assert original.read_bytes() == data
    assert store_b.persistence.resolve(artifact.thumbnail_path).exists()

    # Every tracked save/release returned the registry to its prior state.
    assert dict(media_store_mod._save_refcounts) == before


# ── size/quality/count live in the request snapshot (independent-review) ────


def test_create_job_preserves_size_quality_count_in_snapshot(
    worker: ImageGenerationJobWorker,
) -> None:
    job = worker.create_job(**_job_args(size="1024x1024", quality="high", count=2))
    reloaded = worker.store.load_job(job.id)
    assert reloaded.request_snapshot["size"] == "1024x1024"
    assert reloaded.request_snapshot["quality"] == "high"
    assert reloaded.request_snapshot["count"] == 2
    # The durable record carries no phantom first-class request kwargs.
    assert not hasattr(reloaded, "size")
    assert not hasattr(reloaded, "quality")
    assert not hasattr(reloaded, "count")


@pytest.mark.asyncio
async def test_executor_receives_request_snapshot(worker: ImageGenerationJobWorker) -> None:
    captured: dict[str, Any] = {}

    class CapturingExecutor(FakeExecutor):
        async def run(self, job: ImageGenerationJob) -> list[MediaInput]:
            captured["snapshot"] = dict(job.request_snapshot)
            return [make_media_input()]

    worker.set_executor(CapturingExecutor())
    job = worker.create_job(**_job_args(size="512x512", quality="medium", count=3))
    await worker.run_job(job.id)
    assert captured["snapshot"]["size"] == "512x512"
    assert captured["snapshot"]["quality"] == "medium"
    assert captured["snapshot"]["count"] == 3


# ── atomic idempotent admission (P0) ────────────────────────────────────────


def test_concurrent_idempotent_create_returns_one_job(tmp_path: Path) -> None:
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits(max_concurrent_jobs=4))
    worker = ImageGenerationJobWorker(store=store)

    def submit(_: int) -> str:
        return worker.create_job(**_job_args(idempotency_key="same")).id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(submit, range(8)))

    assert len(set(ids)) == 1
    assert len(store.list_jobs(user_id="u1")) == 1


def test_concurrent_same_key_different_payload_conflicts(tmp_path: Path) -> None:
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits(max_concurrent_jobs=4))
    worker = ImageGenerationJobWorker(store=store)
    prompts = ["a red fox", "a blue fox", "a green fox", "a yellow fox"]

    def submit(prompt: str) -> str:
        try:
            worker.create_job(**_job_args(idempotency_key="dup", prompt=prompt))
            return "ok"
        except JobStateError:
            return "conflict"
        except Exception as exc:  # noqa: BLE001
            return f"other:{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(submit, prompts))

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 3


def test_concurrent_slot_limit_not_exceeded(tmp_path: Path) -> None:
    store = MediaStore(root=tmp_path / "media", limits=MediaLimits(max_concurrent_jobs=1))
    worker = ImageGenerationJobWorker(store=store)

    def submit(index: int) -> str:
        try:
            worker.create_job(**_job_args(idempotency_key=f"k{index}"))
            return "ok"
        except JobConcurrencyError:
            return "rejected"
        except Exception as exc:  # noqa: BLE001
            return f"other:{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(submit, range(4)))

    assert outcomes.count("ok") == 1
    assert outcomes.count("rejected") == 3
    assert store.active_job_count("u1") == 1


def test_concurrent_quota_admission_is_atomic(tmp_path: Path) -> None:
    """Concurrent artifact saves can never exceed the per-user quota."""
    store = MediaStore(
        root=tmp_path / "media",
        limits=MediaLimits(max_user_bytes=100, grace_period_seconds=60.0),
    )

    def submit(_: int) -> str:
        try:
            artifact = GeneratedArtifact(
                id=uuid.uuid4().hex,
                user_id="u1",
                sha256=uuid.uuid4().hex,
                size_bytes=100,
            )
            store.save_artifact(artifact)
            return "ok"
        except QuotaExceededError:
            return "rejected"
        except Exception as exc:  # noqa: BLE001
            return f"other:{type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(submit, range(4)))

    assert outcomes.count("ok") == 1
    assert outcomes.count("rejected") == 3
    assert store.used_bytes("u1") == 100


# ── cross-user job input denial (P0) ────────────────────────────────────────


def test_create_job_rejects_cross_user_source_artifact(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(MediaError, match="source artifact"):
        worker.create_job(
            **_job_args(
                user_id="u2",
                operation=ArtifactOperation.EDIT,
                source_artifact_ids=[source.id],
            )
        )


def test_create_job_rejects_cross_user_mask_artifact(media_store: MediaStore) -> None:
    own_source = _persisted_artifact(media_store, user_id="u2", width=4, height=4)
    mask = _persisted_artifact(media_store, user_id="u1")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(MediaError, match="mask artifact"):
        worker.create_job(
            **_job_args(
                user_id="u2",
                operation=ArtifactOperation.EDIT,
                source_artifact_ids=[own_source.id],
                mask_artifact_id=mask.id,
            )
        )


def test_create_job_rejects_cross_user_continuation_job(media_store: MediaStore) -> None:
    prior = _raw_job(media_store, status=ImageJobStatus.FAILED, user_id="u1")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(MediaError, match="continuation job"):
        worker.create_job(
            **_job_args(
                user_id="u2",
                operation=ArtifactOperation.EDIT,
                continuation_job_id=prior.id,
            )
        )


def test_create_job_rejects_cross_user_retry_job(media_store: MediaStore) -> None:
    prior = _raw_job(media_store, status=ImageJobStatus.FAILED, user_id="u1")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(MediaError, match="retried job"):
        worker.create_job(**_job_args(user_id="u2", retry_of_job_id=prior.id))


# ── §10.1 operation contract at submission ──────────────────────────────────


def test_generate_rejects_source_artifact(worker: ImageGenerationJobWorker) -> None:
    source = _persisted_artifact(worker.store, user_id="u1")
    with pytest.raises(MediaError, match="generate cannot reference"):
        worker.create_job(**_job_args(source_artifact_ids=[source.id]))


def test_generate_rejects_mask_artifact(worker: ImageGenerationJobWorker) -> None:
    mask = _persisted_artifact(worker.store, user_id="u1")
    with pytest.raises(MediaError, match="generate cannot reference"):
        worker.create_job(**_job_args(mask_artifact_id=mask.id))


def test_generate_rejects_continuation(media_store: MediaStore) -> None:
    prior = _raw_job(media_store, status=ImageJobStatus.SUCCEEDED, profile="p1")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(MediaError, match="generate cannot reference"):
        worker.create_job(**_job_args(continuation_job_id=prior.id))


def test_edit_requires_source_or_continuation(worker: ImageGenerationJobWorker) -> None:
    with pytest.raises(MediaError, match="edit requires"):
        worker.create_job(**_job_args(operation=ArtifactOperation.EDIT))


def test_edit_rejects_missing_source_artifact(worker: ImageGenerationJobWorker) -> None:
    with pytest.raises(MediaError, match="source artifact not found"):
        worker.create_job(
            **_job_args(operation=ArtifactOperation.EDIT, source_artifact_ids=["missing"])
        )


def test_edit_rejects_missing_mask_artifact(media_store: MediaStore) -> None:
    source = _persisted_artifact(media_store, user_id="u1")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(MediaError, match="mask artifact not found"):
        worker.create_job(
            **_job_args(
                operation=ArtifactOperation.EDIT,
                source_artifact_ids=[source.id],
                mask_artifact_id="missing-mask",
            )
        )


def test_edit_continuation_requires_same_profile(media_store: MediaStore) -> None:
    prior = _raw_job(media_store, status=ImageJobStatus.SUCCEEDED, profile="p1")
    worker = ImageGenerationJobWorker(store=media_store)
    with pytest.raises(MediaError, match="uses profile"):
        worker.create_job(
            **_job_args(
                operation=ArtifactOperation.EDIT,
                continuation_job_id=prior.id,
                profile="p2",
            )
        )


def test_edit_continuation_same_profile_ok(media_store: MediaStore) -> None:
    prior = _raw_job(media_store, status=ImageJobStatus.SUCCEEDED, profile="p1")
    worker = ImageGenerationJobWorker(store=media_store)
    job = worker.create_job(
        **_job_args(operation=ArtifactOperation.EDIT, continuation_job_id=prior.id)
    )
    assert job.continuation_job_id == prior.id


# ── orphan recovery / GC arming (P0) ────────────────────────────────────────


def _crashed_save_artifact(
    store: MediaStore,
    *,
    job_id: str,
    session_id: str,
    user_id: str = "u1",
    width: int = 8,
    height: int = 8,
    with_session_ref: bool = False,
) -> GeneratedArtifact:
    """Simulate one artifact a crashed save already committed to disk."""
    saved = store.persistence.save_media(make_png(width, height), mime_type="image/png")
    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id=user_id,
        job_id=job_id,
        session_id=session_id,
        sha256=saved.sha256,
        mime_type=saved.mime_type,
        width=saved.width,
        height=saved.height,
        size_bytes=saved.size_bytes,
        original_path=saved.original_path,
        thumbnail_path=saved.thumbnail_path,
    )
    store.save_artifact(artifact, check_quota=False)
    if with_session_ref:
        store.create_reference(
            artifact_id=artifact.id,
            user_id=user_id,
            owner_type=ReferenceOwnerType.SESSION,
            owner_id=session_id,
        )
    return artifact


def test_restart_recovery_reconciles_orphan_artifacts(media_store: MediaStore) -> None:
    job = _raw_job(media_store, status=ImageJobStatus.SAVING, session_id="sess-crash")
    # Artifact A: file persisted but no reference and gc_candidate_since == 0
    # (crash between save_artifact and create_reference).
    orphan_a = _crashed_save_artifact(media_store, job_id=job.id, session_id="sess-crash")
    assert orphan_a.gc_candidate_since == 0
    # Artifact B: file persisted with a dangling live session reference
    # (crash between create_reference and the succeeded transition).
    orphan_b = _crashed_save_artifact(
        media_store,
        job_id=job.id,
        session_id="sess-crash",
        width=4,
        height=4,
        with_session_ref=True,
    )
    assert len(media_store.list_references(artifact_id=orphan_b.id, live_only=True)) == 1

    fresh = ImageGenerationJobWorker(store=media_store)
    transitions = fresh.recover()

    # The crashed job is deterministically moved to unknown, never a success.
    assert [row["to"] for row in transitions] == [ImageJobStatus.UNKNOWN.value]
    assert media_store.load_job(job.id).status == ImageJobStatus.UNKNOWN

    # Orphan A is armed and visible to GC; orphan B lost its dangling
    # reference and is armed too.
    reloaded_a = media_store.load_artifact(orphan_a.id)
    reloaded_b = media_store.load_artifact(orphan_b.id)
    assert reloaded_a is not None and reloaded_a.gc_candidate_since > 0
    assert reloaded_b is not None and reloaded_b.gc_candidate_since > 0
    assert media_store.list_references(artifact_id=orphan_b.id, live_only=True) == []
    assert {artifact.id for artifact in media_store.candidate_artifacts("u1")} == {
        orphan_a.id,
        orphan_b.id,
    }

    # After the grace period the sweep reclaims both and frees quota.
    gc = media_store.run_gc(user_id="u1", force=True)
    assert gc.deleted_count == 2
    assert media_store.used_bytes("u1") == 0


def test_restart_recovery_reclaims_file_without_record(media_store: MediaStore) -> None:
    job = _raw_job(media_store, status=ImageJobStatus.SAVING, session_id="sess-crash")
    # Crash between the atomic file save and the artifact metadata write: the
    # content-addressed file exists but no artifact record references it, so
    # GC (which iterates records) cannot see it and it would leak disk space.
    saved = media_store.persistence.save_media(make_png(8, 8), mime_type="image/png")
    original = media_store.persistence.resolve(saved.original_path)
    assert original.exists()
    assert media_store.candidate_artifacts("u1") == []

    fresh = ImageGenerationJobWorker(store=media_store)
    fresh.recover()

    # The crashed job is terminal non-succeeded and the orphaned file is
    # removed rather than leaking disk space invisibly.
    assert media_store.load_job(job.id).status == ImageJobStatus.UNKNOWN
    assert not original.exists()
    assert list((media_store.root / "originals").rglob("*.png")) == []
    assert list((media_store.root / "thumbnails").rglob("*.jpg")) == []


def test_reconcile_preserves_user_created_reference_on_orphan_artifact(
    media_store: MediaStore,
) -> None:
    job = _raw_job(media_store, status=ImageJobStatus.SAVING, session_id="sess-crash")
    orphan = _crashed_save_artifact(media_store, job_id=job.id, session_id="sess-crash")
    # A user explicitly re-referenced the orphan artifact from another owner.
    media_store.create_reference(
        artifact_id=orphan.id,
        user_id="u1",
        owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
        owner_id="card-1",
    )

    fresh = ImageGenerationJobWorker(store=media_store)
    fresh.recover()

    # The user-created live reference is preserved; the artifact stays live and
    # GC must not delete user-owned data.
    reloaded = media_store.load_artifact(orphan.id)
    assert reloaded is not None and reloaded.gc_candidate_since == 0
    assert len(media_store.list_references(artifact_id=orphan.id, live_only=True)) == 1
    assert media_store.run_gc(user_id="u1", force=True).deleted_count == 0
    assert media_store.load_artifact(orphan.id) is not None
