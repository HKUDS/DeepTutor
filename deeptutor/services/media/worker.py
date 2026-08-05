"""ImageGenerationJob worker and restart recovery (MED-01).

The worker owns the job state machine (§11.2/§11.3): it submits a durable
``queued`` job, hands execution to a pluggable :class:`JobExecutor`, and only
marks the job ``succeeded`` after every produced image has been atomically
persisted, registered as a :class:`GeneratedArtifact` and referenced by its
session (§12.1).  Provider adapters (MED-02) implement :class:`JobExecutor`;
this module deliberately contains no provider logic.

Restart recovery (§11.3/§11.5) is deterministic:

* ``queued``            -> stays queued, executable
* ``running``/``polling``-> resumes when a remote id exists, else ``unknown``
* ``validating``/``saving``-> ``unknown`` (local-only result lost on restart)
* ``cancel_requested``  -> stays, only cancel confirmation resumes
* terminal states      -> never re-run
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import time
from typing import Any, Callable, Protocol, runtime_checkable
import uuid

from deeptutor.services.media.adapter_config import ImageAdapterSettings
from deeptutor.services.media.config import MediaLimits
from deeptutor.services.media.models import (
    TERMINAL_JOB_STATUSES,
    AmbiguousSubmitError,
    ArtifactOperation,
    BackgroundSubmit,
    GeneratedArtifact,
    ImageGenerationJob,
    ImageJobStatus,
    JobStateError,
    MediaConfigError,
    MediaError,
    MediaInput,
    MediaValidationError,
    PollOutcome,
    QuotaExceededError,
    ReferenceOwnerType,
    SavedMedia,
    TransientPollError,
)
from deeptutor.services.media.redaction import (
    looks_like_base64_payload,
    redact_text,
    sanitize_snapshot,
)
from deeptutor.services.media.safe_download import SafeDownloadError
from deeptutor.services.media.store import MediaStore

logger = logging.getLogger(__name__)

# Back-compatible private aliases for tests that import the sanitizer directly.
_redact_text = redact_text
_sanitize_snapshot = sanitize_snapshot
_looks_like_base64_payload = looks_like_base64_payload

#: Provider-option keys a client may never inject.  Continuation/remote
#: identity is resolved by the server from persisted job/artifact metadata, so
#: any caller-supplied remote id is dropped rather than trusted.
_REMOTE_REFERENCE_KEYS = frozenset(
    {
        "remote_response_id",
        "remote_job_id",
        "remote_asset_id",
        "previous_response_id",
        "response_id",
        "job_id",
        "continuation_job_id",
    }
)


@dataclass
class _SavedMediaRun:
    """One completed media-save pass, pending the final ``succeeded`` CAS.

    The caller either finalizes it (releasing the in-flight content refcounts)
    or rolls it back when the CAS loses to a concurrent cancel (§11.6).
    """

    artifact_ids: list[str]
    reference_ids: list[str]
    saved_media: list[SavedMedia]


def _request_hash(
    *,
    operation: str,
    prompt: str,
    source_artifact_ids: list[str],
    mask_artifact_id: str,
    continuation_job_id: str,
    retry_of_job_id: str,
    session_id: str,
    turn_id: str,
    tool_call_id: str,
    provider: str,
    profile: str,
    protocol: str,
    model: str,
    size: str,
    quality: str,
    count: int,
    provider_options: dict[str, Any],
    connect_timeout_seconds: int,
    read_timeout_seconds: int,
    deadline_at: float,
) -> str:
    """Fingerprint the complete semantically relevant frozen request.

    The implicit default deadline (``deadline_at == 0``) hashes as the marker
    ``"default"`` so equivalent repeated calls stay idempotent, while an
    explicit deadline (or any other meaningful change) produces a different
    hash and conflicts on the same idempotency key.  The attachment context
    (``session_id``/``turn_id``/``tool_call_id``) is part of the frozen request
    so reusing a key across sessions/turns/tool calls conflicts instead of
    silently returning a job attached to an earlier context.  Provider options
    and the prompt enter the hash already sanitized, so a hidden secret never
    looks like a different request.
    """
    canonical = json.dumps(
        {
            "operation": operation,
            "prompt": prompt,
            "source_artifact_ids": source_artifact_ids,
            "mask_artifact_id": mask_artifact_id,
            "continuation_job_id": continuation_job_id,
            "retry_of_job_id": retry_of_job_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "provider": provider,
            "profile": profile,
            "protocol": protocol,
            "model": model,
            "size": size,
            "quality": quality,
            "count": count,
            "provider_options": provider_options,
            "connect_timeout_seconds": connect_timeout_seconds,
            "read_timeout_seconds": read_timeout_seconds,
            "deadline": "default" if not deadline_at else deadline_at,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sanitize(message: str) -> str:
    """Trim and redact likely secrets from a persisted error message."""
    return _redact_text(str(message or "")[:500])


def _classify_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, QuotaExceededError):
        return "quota_exceeded", str(exc)
    if isinstance(exc, MediaValidationError):
        return "validation_error", str(exc)
    if isinstance(exc, JobStateError):
        return "state_error", str(exc)
    if isinstance(exc, MediaConfigError):
        return "config_error", str(exc)
    # MED-02 adapter errors: a requested operation the provider cannot perform
    # keeps a stable code and must never be replayed as a generate.
    from deeptutor.services.media.adapters.base import UnsupportedOperationError

    if isinstance(exc, UnsupportedOperationError):
        return "unsupported_operation", str(exc)
    if isinstance(exc, SafeDownloadError):
        return "download_error", str(exc)
    return "provider_error", str(exc)


@runtime_checkable
class JobExecutor(Protocol):
    """Provider execution contract implemented by MED-02 adapters.

    ``run`` performs the generation/edit and returns either the produced images
    as :class:`MediaInput` (bytes + MIME + remote ids) for a synchronous
    completion, or a :class:`BackgroundSubmit` when the provider accepted an
    asynchronous job and the worker must switch to ``polling``.  ``poll``
    reconciles a remote-id job (§11.5): a :class:`PollOutcome` with media means
    the job is complete, one with ``poll_after > 0`` means keep polling.
    ``confirm_cancel`` returns ``True`` only when the provider confirmed the
    remote cancellation.
    """

    async def run(self, job: ImageGenerationJob) -> list[MediaInput] | BackgroundSubmit: ...

    async def poll(self, job: ImageGenerationJob) -> PollOutcome: ...

    async def confirm_cancel(self, job: ImageGenerationJob) -> bool: ...


class ImageGenerationJobWorker:
    """Owns job lifecycle, local persistence and deterministic recovery."""

    def __init__(
        self,
        store: MediaStore,
        executor: JobExecutor | None = None,
        *,
        limits: MediaLimits | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._store = store
        self._executor = executor
        self._limits = limits or store.limits
        # Injectable clock so timeout/backoff behavior is deterministic in
        # tests; production defaults to wall time.
        self._now = now or time.time

    @property
    def store(self) -> MediaStore:
        return self._store

    @property
    def executor(self) -> JobExecutor | None:
        return self._executor

    def set_executor(self, executor: JobExecutor) -> None:
        self._executor = executor

    # ── submission ───────────────────────────────────────────────────────────

    def create_job(
        self,
        *,
        user_id: str,
        prompt: str,
        operation: ArtifactOperation = ArtifactOperation.GENERATE,
        session_id: str = "",
        turn_id: str = "",
        tool_call_id: str = "",
        provider: str = "",
        profile: str = "",
        protocol: str = "",
        model: str = "",
        idempotency_key: str = "",
        source_artifact_ids: list[str] | None = None,
        mask_artifact_id: str = "",
        continuation_job_id: str = "",
        size: str = "",
        quality: str = "",
        count: int = 1,
        request_snapshot: dict[str, Any] | None = None,
        retry_of_job_id: str = "",
        connect_timeout_seconds: int = 20,
        read_timeout_seconds: int = 1800,
        deadline_at: float = 0.0,
    ) -> ImageGenerationJob:
        """Create a durable ``queued`` job (idempotent per key + payload).

        ``size``, ``quality`` and ``count`` are part of the frozen request
        snapshot (and of the request hash), not separate first-class job
        fields: the durable/executor contract reads them from
        ``job.request_snapshot``.  Idempotency lookup, concurrency-slot
        admission and the durable write are performed atomically by the store.

        §10.1 submission contract: ``generate`` rejects source/mask/
        continuation references; ``edit`` requires at least one owned
        persistent source artifact or an owned continuation job whose profile
        matches.  The request snapshot is built exclusively from the trusted
        top-level server arguments; caller-supplied snapshot/provider options
        can never override those canonical fields and are sanitized (credentials
        redacted, remote/continuation references dropped) before anything is
        persisted.

        The effective prompt is redacted *before* hashing, snapshotting,
        storing or exposing to the executor (§10.5): any credential or base64
        payload a caller embeds in the prompt text never reaches the durable
        job JSON (``original_prompt``, ``request_snapshot``) nor the request
        hash, so the executor cannot retrieve the leaked value from the job.
        """
        prompt = (prompt or "").strip()
        if not prompt:
            raise MediaError("Cannot create an image job for an empty prompt.")
        effective_prompt = _redact_text(prompt)
        sources = list(source_artifact_ids or [])

        if operation == ArtifactOperation.GENERATE:
            if sources or mask_artifact_id or continuation_job_id:
                raise MediaError("generate cannot reference source/mask/continuation artifacts")
        elif operation == ArtifactOperation.EDIT:
            if not sources and not continuation_job_id:
                raise MediaError(
                    "edit requires at least one owned source artifact or an owned continuation job"
                )
        else:  # pragma: no cover - enum boundary, defensive
            raise MediaError(f"unsupported operation: {operation!r}")

        self._validate_owned_inputs(
            user_id,
            sources,
            mask_artifact_id,
            continuation_job_id,
            retry_of_job_id,
            profile,
        )
        effective_count = max(1, count)

        # Caller-controlled provider options are the only untrusted input.
        # They are sanitized and any remote/continuation reference is dropped:
        # the server resolves continuation identity from persisted records.
        if request_snapshot is not None and not isinstance(request_snapshot, dict):
            raise MediaError("request_snapshot must be a mapping")
        caller_snapshot = dict(request_snapshot or {})
        raw_options = caller_snapshot.get("provider_options")
        if raw_options is None:
            raw_options = {}
        if not isinstance(raw_options, dict):
            raise MediaError("provider_options must be a mapping")
        provider_options = _sanitize_snapshot(raw_options, strip_keys=_REMOTE_REFERENCE_KEYS)
        if not isinstance(provider_options, dict):
            provider_options = {}

        request_hash = _request_hash(
            operation=operation.value,
            prompt=effective_prompt,
            source_artifact_ids=sources,
            mask_artifact_id=mask_artifact_id,
            continuation_job_id=continuation_job_id,
            retry_of_job_id=retry_of_job_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            provider=provider,
            profile=profile,
            protocol=protocol,
            model=model,
            size=size,
            quality=quality,
            count=effective_count,
            provider_options=provider_options,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            deadline_at=deadline_at,
        )
        # Trusted snapshot: canonical fields come from top-level arguments only.
        # The attachment context is frozen with the request so a reused
        # idempotency key in another session/turn/tool context conflicts.
        snapshot: dict[str, Any] = {
            "operation": operation.value,
            "prompt": effective_prompt,
            "size": size,
            "quality": quality,
            "count": effective_count,
            "source_artifact_ids": sources,
            "mask_artifact_id": mask_artifact_id,
            "continuation_job_id": continuation_job_id,
            "retry_of_job_id": retry_of_job_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_call_id": tool_call_id,
            "provider": provider,
            "profile": profile,
            "protocol": protocol,
            "model": model,
            "connect_timeout_seconds": connect_timeout_seconds,
            "read_timeout_seconds": read_timeout_seconds,
            "deadline": "default" if not deadline_at else deadline_at,
        }
        if provider_options:
            snapshot["provider_options"] = provider_options
        snapshot = _sanitize_snapshot(snapshot)

        job = ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id=user_id,
            session_id=session_id,
            turn_id=turn_id,
            tool_call_id=tool_call_id,
            operation=operation,
            original_prompt=effective_prompt,
            provider=provider,
            profile=profile,
            protocol=protocol,
            model=model,
            request_snapshot=snapshot,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            source_artifact_ids=sources,
            mask_artifact_id=mask_artifact_id,
            continuation_job_id=continuation_job_id,
            retry_of_job_id=retry_of_job_id,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            # The default one-hour deadline uses the injected worker clock so
            # timeout tests stay deterministic (§11.4).  The request hash still
            # treats an implicit deadline as the ``"default"`` marker (the
            # parameter, not the effective value) so idempotency is unaffected.
            deadline_at=deadline_at or (self._now() + 3600.0),
        )
        return self._store.create_job_atomically(job)

    def _validate_owned_inputs(
        self,
        user_id: str,
        source_artifact_ids: list[str],
        mask_artifact_id: str,
        continuation_job_id: str,
        retry_of_job_id: str,
        profile: str,
    ) -> None:
        """Reject source/mask/continuation/retry references that are not the
        requesting user's own persistent records (§10.1).

        Every source and mask id must resolve to a persistent artifact owned by
        the user; a continuation or retried job must exist, belong to the user,
        and a continuation must use the same profile as the new job.  Missing
        ids and cross-user ids are rejected — a client can never inject an
        arbitrary remote reference.
        """
        for artifact_id in source_artifact_ids:
            artifact = self._store.load_artifact(artifact_id)
            if artifact is None:
                raise MediaError(f"source artifact not found: {artifact_id}")
            if artifact.user_id != user_id:
                raise MediaError(
                    f"source artifact {artifact_id} belongs to user "
                    f"{artifact.user_id!r}, not {user_id!r}"
                )
        if mask_artifact_id:
            artifact = self._store.load_artifact(mask_artifact_id)
            if artifact is None:
                raise MediaError(f"mask artifact not found: {mask_artifact_id}")
            if artifact.user_id != user_id:
                raise MediaError(
                    f"mask artifact {mask_artifact_id} belongs to user "
                    f"{artifact.user_id!r}, not {user_id!r}"
                )
        if continuation_job_id:
            prior = self._store.load_job(continuation_job_id)
            if prior is None:
                raise MediaError(f"continuation job not found: {continuation_job_id}")
            if prior.user_id != user_id:
                raise MediaError(
                    f"continuation job {continuation_job_id} belongs to user "
                    f"{prior.user_id!r}, not {user_id!r}"
                )
            if prior.profile != profile:
                raise MediaError(
                    f"continuation job {continuation_job_id} uses profile "
                    f"{prior.profile!r}, not {profile!r}"
                )
        if retry_of_job_id:
            prior = self._store.load_job(retry_of_job_id)
            if prior is None:
                raise MediaError(f"retried job not found: {retry_of_job_id}")
            if prior.user_id != user_id:
                raise MediaError(
                    f"retried job {retry_of_job_id} belongs to user "
                    f"{prior.user_id!r}, not {user_id!r}"
                )

    # ── execution ────────────────────────────────────────────────────────────

    async def run_job(self, job_id: str) -> ImageGenerationJob:
        """Execute a queued job: provider call -> atomic save -> ``succeeded``."""
        job = self._store.load_job(job_id)
        if job is None:
            raise MediaError(f"job not found: {job_id}")
        if job.status != ImageJobStatus.QUEUED:
            raise JobStateError(f"job {job_id} is not queued (status={job.status.value!r})")
        if job.deadline_at and self._now() > job.deadline_at:
            return self._store.transition_job(
                job_id,
                from_status=ImageJobStatus.QUEUED,
                to_status=ImageJobStatus.TIMED_OUT,
                error_code="deadline_exceeded",
                sanitized_error="Job deadline passed before execution started.",
            )
        if self._executor is None:
            return self._store.transition_job(
                job_id,
                from_status=ImageJobStatus.QUEUED,
                to_status=ImageJobStatus.FAILED,
                error_code="no_executor",
                sanitized_error="No image-generation executor is configured.",
            )

        self._store.transition_job(
            job_id,
            from_status=ImageJobStatus.QUEUED,
            to_status=ImageJobStatus.RUNNING,
            started_at=self._now(),
        )
        try:
            result = await self._executor.run(job)
            if isinstance(result, BackgroundSubmit):
                # Background acknowledged (§11.5): persist the provider's own
                # remote identity and schedule the first poll.  Nothing was
                # submitted by the client, so this is always safe to resume.
                delay = self._clamp_poll_after(result.poll_after, job.poll_delay_seconds)
                return self._store.transition_job(
                    job_id,
                    from_status=ImageJobStatus.RUNNING,
                    to_status=ImageJobStatus.POLLING,
                    remote_response_id=result.remote_response_id,
                    remote_job_id=result.remote_job_id,
                    poll_after=self._now() + delay,
                    poll_delay_seconds=delay,
                )
            if not result:
                raise MediaError("Executor returned no media for the job.")
            run = self._persist_media(job, result)
            return self._finalize_succeeded(job_id, run)
        except AmbiguousSubmitError as exc:
            # The provider may have accepted and billed the request, but we have
            # no remote id to reconcile it.  Deterministically transition to
            # ``unknown`` — never a generic ``failed`` that invites a duplicate
            # user retry, and never an automatic re-submit (§11.5).
            logger.warning("image job %s submit outcome unknown: %s", job_id, _sanitize(str(exc)))
            try:
                return self._store.transition_job(
                    job_id,
                    from_status={
                        ImageJobStatus.RUNNING,
                        ImageJobStatus.VALIDATING,
                        ImageJobStatus.SAVING,
                    },
                    to_status=ImageJobStatus.UNKNOWN,
                    error_code="submit_outcome_unknown",
                    sanitized_error=_sanitize(str(exc)),
                )
            except JobStateError:
                # A concurrent cancel finalized the job first; the failure is
                # diagnostic only.
                logger.debug(
                    "job %s already left runnable state during ambiguous submit",
                    job_id,
                    exc_info=True,
                )
                final_job = self._store.load_job(job_id)
                assert final_job is not None
                return final_job
        except Exception as exc:
            logger.warning("image job %s failed: %s", job_id, _sanitize(str(exc)))
            error_code, message = _classify_error(exc)
            try:
                return self._store.transition_job(
                    job_id,
                    from_status={
                        ImageJobStatus.RUNNING,
                        ImageJobStatus.VALIDATING,
                        ImageJobStatus.SAVING,
                    },
                    to_status=ImageJobStatus.FAILED,
                    error_code=error_code,
                    sanitized_error=_sanitize(message),
                )
            except JobStateError:
                # Another transition already finalized the job (e.g. cancel);
                # the failure is diagnostic only.
                logger.debug("job %s already left runnable state", job_id, exc_info=True)
                final_job = self._store.load_job(job_id)
                assert final_job is not None
                return final_job

    def _clamp_poll_after(self, hint: float, current_delay: float) -> float:
        """Clamp the next poll delay to the backoff window (§11.4).

        The adapter may suggest a provider-native delay (a floor); the worker
        always backs the current delay off (doubles it) so repeated polls grow
        2s → 4s → 8s → 15s and stay capped at 15s.  A hint below the floor
        never shrinks the delay.
        """
        settings = ImageAdapterSettings()
        start = settings.poll_start_seconds
        cap = settings.poll_backoff_cap_seconds
        if current_delay and current_delay > 0:
            floor = max(current_delay * 2, start)
        else:
            floor = start
        if hint and hint > 0:
            floor = max(floor, hint)
        return min(max(floor, start), cap)

    async def poll_job(self, job_id: str) -> ImageGenerationJob:
        """Poll a background job that already has a remote id (§11.5).

        Only ``polling`` jobs reach this path.  A completed poll persists the
        media and succeeds exactly like a synchronous run; a still-running poll
        updates ``poll_after``; a deadline that passed becomes ``timed_out``;
        and a completed poll whose local persistence/finalization fails is
        failed deterministically from any applicable state.  A poll must never
        resubmit the request — the remote id is provider identity, and only
        retrieve is performed here.
        """
        job = self._store.load_job(job_id)
        if job is None:
            raise MediaError(f"job not found: {job_id}")
        if job.status != ImageJobStatus.POLLING:
            raise JobStateError(f"job {job_id} is not polling (status={job.status.value!r})")
        if not (job.remote_response_id or job.remote_job_id):
            # No remote identity: the provider may have accepted the request but
            # we cannot reconcile it.  Deterministic transition to unknown; the
            # user must explicitly retry (§11.5).
            return self._store.transition_job(
                job_id,
                from_status=ImageJobStatus.POLLING,
                to_status=ImageJobStatus.UNKNOWN,
                error_code="missing_remote_id",
                sanitized_error=(
                    "Job has no remote identity; the provider result cannot be "
                    "reconciled. Retry to create a new job."
                ),
            )
        if job.deadline_at and self._now() > job.deadline_at:
            return self._store.transition_job(
                job_id,
                from_status=ImageJobStatus.POLLING,
                to_status=ImageJobStatus.TIMED_OUT,
                error_code="deadline_exceeded",
                sanitized_error="Job deadline passed while waiting for the provider.",
            )
        if self._executor is None:
            return self._store.transition_job(
                job_id,
                from_status=ImageJobStatus.POLLING,
                to_status=ImageJobStatus.FAILED,
                error_code="no_executor",
                sanitized_error="No image-generation executor is configured.",
            )
        try:
            outcome = await self._executor.poll(job)
        except TransientPollError as exc:
            # A transient retrieve/read failure for a job with a durable remote
            # id must not become a generic failed state (§11.5): the remote job
            # may still be running.  Keep polling with bounded backoff until the
            # deadline and never resubmit.
            logger.warning("image job %s poll transient failure: %s", job_id, _sanitize(str(exc)))
            delay = self._clamp_poll_after(0.0, job.poll_delay_seconds)
            try:
                return self._store.update_job(
                    job_id,
                    expected_status_version=job.status_version,
                    poll_after=self._now() + delay,
                    poll_delay_seconds=delay,
                )
            except JobStateError:
                logger.debug(
                    "job %s already left polling state during transient poll",
                    job_id,
                    exc_info=True,
                )
                final_job = self._store.load_job(job_id)
                assert final_job is not None
                return final_job
        except Exception as exc:
            logger.warning("image job %s poll failed: %s", job_id, _sanitize(str(exc)))
            error_code, message = _classify_error(exc)
            try:
                return self._store.transition_job(
                    job_id,
                    from_status=ImageJobStatus.POLLING,
                    to_status=ImageJobStatus.FAILED,
                    error_code=error_code,
                    sanitized_error=_sanitize(message),
                )
            except JobStateError:
                logger.debug("job %s already left polling state", job_id, exc_info=True)
                final_job = self._store.load_job(job_id)
                assert final_job is not None
                return final_job

        if outcome.poll_after and outcome.poll_after > 0:
            # Still running; schedule the next poll with the backoff clamp.
            delay = self._clamp_poll_after(outcome.poll_after, job.poll_delay_seconds)
            return self._store.update_job(
                job_id,
                expected_status_version=job.status_version,
                poll_after=self._now() + delay,
                poll_delay_seconds=delay,
            )
        try:
            if not outcome.media:
                raise MediaError("Executor poll returned neither media nor a poll delay.")
            run = self._persist_media(job, outcome.media, from_status=ImageJobStatus.POLLING)
            return self._finalize_succeeded(job_id, run)
        except Exception as exc:
            # A completed remote poll whose local validation, persistence or
            # finalization fails must fail the job deterministically, exactly
            # like a synchronous run (§11.5/§12.1).  ``_persist_media`` may
            # already have moved the job from ``polling`` to ``validating``/
            # ``saving`` before re-raising, so the terminal transition accepts
            # any applicable state — never leaving the job stuck in a state the
            # scheduler does not process.  The durable remote id is untouched by
            # the transition, and no resubmit or extra provider call happens.
            logger.warning(
                "image job %s failed during poll persistence: %s",
                job_id,
                _sanitize(str(exc)),
            )
            error_code, message = _classify_error(exc)
            try:
                return self._store.transition_job(
                    job_id,
                    from_status={
                        ImageJobStatus.POLLING,
                        ImageJobStatus.VALIDATING,
                        ImageJobStatus.SAVING,
                    },
                    to_status=ImageJobStatus.FAILED,
                    error_code=error_code,
                    sanitized_error=_sanitize(message),
                )
            except JobStateError:
                # Another transition already finalized the job (e.g. cancel);
                # the failure is diagnostic only and must not overwrite it.
                logger.debug(
                    "job %s already left runnable state during poll persistence",
                    job_id,
                    exc_info=True,
                )
                final_job = self._store.load_job(job_id)
                assert final_job is not None
                return final_job

    def _persist_media(
        self,
        job: ImageGenerationJob,
        inputs: list[MediaInput],
        *,
        from_status: ImageJobStatus = ImageJobStatus.RUNNING,
    ) -> "_SavedMediaRun":
        """Atomically persist every image, then register artifacts + references.

        All files are committed to the content-addressed store before any
        artifact metadata is written; a failure at any point removes only the
        files this job created, rolls back any artifact/reference metadata
        already committed, and leaves the job non-succeeded.  A failed save
        never leaves live metadata pointing at deleted media.

        In-flight content is tracked across the whole save-metadata-rollback
        boundary (see :meth:`MediaStore.save_media_tracked` /
        ``rollback_save``), so a failed saver can never remove an original or
        thumbnail now used by a concurrent successful artifact.

        The returned :class:`_SavedMediaRun` is *not* yet committed: the caller
        must either call :meth:`_finalize_succeeded` (which releases the
        in-flight content refcounts only after the ``succeeded`` CAS succeeds)
        or roll it back when the CAS loses to a concurrent cancel (§11.6).
        """
        self._store.transition_job(
            job.id,
            from_status=from_status,
            to_status=ImageJobStatus.VALIDATING,
        )
        persisted: list[SavedMedia] = []
        written_artifact_ids: list[str] = []
        written_reference_ids: list[str] = []
        try:
            pending_bytes = 0
            for media in inputs:
                # Cumulative fast-fail so we never write files we cannot afford.
                self._store.check_quota_for_bytes(job.user_id, len(media.data) + pending_bytes)
                pending_bytes += len(media.data)
                saved = self._store.save_media_tracked(media.data, mime_type=media.mime_type)
                persisted.append(saved)

            self._store.transition_job(
                job.id,
                from_status=ImageJobStatus.VALIDATING,
                to_status=ImageJobStatus.SAVING,
            )
            artifact_ids: list[str] = []
            for media, saved in zip(inputs, persisted):
                artifact = self._build_artifact(job, media, saved)
                self._store.save_artifact(artifact)
                artifact_ids.append(artifact.id)
                written_artifact_ids.append(artifact.id)
                if job.session_id:
                    reference = self._store.create_reference(
                        artifact_id=artifact.id,
                        user_id=job.user_id,
                        owner_type=ReferenceOwnerType.SESSION,
                        owner_id=job.session_id,
                    )
                    written_reference_ids.append(reference.id)
                # An artifact with no session (hence no reference) enters the GC
                # grace period immediately so its quota is recoverable (§12.3).
                self._store.arm_gc_if_unreferenced(artifact.id)
            return _SavedMediaRun(
                artifact_ids=artifact_ids,
                reference_ids=written_reference_ids,
                saved_media=persisted,
            )
        except Exception:
            # Roll back metadata written by this save before removing files, so
            # a failed job leaves neither a dangling live reference nor an
            # invisible orphan artifact record.  File removal is refcount- and
            # artifact-reference guarded to never break a concurrent dedup
            # partner's files.
            self._store.rollback_save(
                artifact_ids=written_artifact_ids,
                reference_ids=written_reference_ids,
                saved_media=persisted,
            )
            raise

    def _finalize_succeeded(self, job_id: str, run: "_SavedMediaRun") -> ImageGenerationJob:
        """Apply the final ``saving/validating -> succeeded`` CAS and release
        the in-flight content refcounts on success.

        If the CAS loses to a concurrent transition (typically a
        ``cancel_requested`` arriving while media is being saved), every
        artifact/reference/file created by this run is rolled back immediately
        — never exposed as a successful result, and no restart required to
        clean it up (§11.6).
        """
        try:
            final = self._store.transition_job(
                job_id,
                from_status={ImageJobStatus.SAVING, ImageJobStatus.VALIDATING},
                to_status=ImageJobStatus.SUCCEEDED,
                artifact_ids=run.artifact_ids,
            )
        except JobStateError:
            # Another transition (e.g. cancel_requested) won the CAS.  Roll back
            # this run's media before returning the final job.
            self._store.rollback_save(
                artifact_ids=run.artifact_ids,
                reference_ids=run.reference_ids,
                saved_media=run.saved_media,
            )
            final = self._store.load_job(job_id)
            assert final is not None
            return final
        self._store.commit_saved_media(run.saved_media)
        return final

    def _build_artifact(
        self, job: ImageGenerationJob, media: MediaInput, saved: SavedMedia
    ) -> GeneratedArtifact:
        # §10.5: mask_sha256 is the mask artifact's *content* SHA-256, never
        # the artifact record id.
        mask_sha256 = ""
        if job.mask_artifact_id:
            mask = self._store.load_artifact(job.mask_artifact_id)
            if mask is not None:
                mask_sha256 = mask.sha256
        return GeneratedArtifact(
            id=uuid.uuid4().hex,
            user_id=job.user_id,
            job_id=job.id,
            session_id=job.session_id,
            turn_id=job.turn_id,
            tool_call_id=job.tool_call_id,
            provider=job.provider,
            profile=job.profile,
            protocol=job.protocol,
            model=job.model,
            original_prompt=job.original_prompt,
            revised_prompt=media.revised_prompt or "",
            operation=job.operation,
            parent_artifact_ids=(
                job.source_artifact_ids if job.operation == ArtifactOperation.EDIT else []
            ),
            mask_sha256=mask_sha256,
            continuation_job_id=job.continuation_job_id,
            remote_response_id=media.remote_response_id or job.remote_response_id,
            remote_asset_id=media.remote_asset_id or "",
            sha256=saved.sha256,
            mime_type=saved.mime_type,
            width=saved.width,
            height=saved.height,
            size_bytes=saved.size_bytes,
            original_path=saved.original_path,
            thumbnail_path=saved.thumbnail_path,
        )

    # ── cancel ───────────────────────────────────────────────────────────────

    async def run_cancel(self, job_id: str) -> ImageGenerationJob:
        """Resume cancel confirmation for a ``cancel_requested`` job.

        Without a provider that can confirm remote cancellation this resolves to
        ``cancelled_unconfirmed`` — the local side stops, but the remote task
        may still run; it is never turned into a success.
        """
        job = self._store.load_job(job_id)
        if job is None:
            raise MediaError(f"job not found: {job_id}")
        if job.status != ImageJobStatus.CANCEL_REQUESTED:
            raise JobStateError(
                f"job {job_id} is not cancel_requested (status={job.status.value!r})"
            )
        confirmed = False
        if self._executor is not None:
            try:
                confirmed = await self._executor.confirm_cancel(job)
            except Exception as exc:
                logger.warning("cancel confirmation failed for %s: %s", job_id, _sanitize(str(exc)))
        if confirmed:
            return self._store.transition_job(
                job_id,
                from_status=ImageJobStatus.CANCEL_REQUESTED,
                to_status=ImageJobStatus.CANCELLED,
            )
        return self._store.transition_job(
            job_id,
            from_status=ImageJobStatus.CANCEL_REQUESTED,
            to_status=ImageJobStatus.CANCELLED_UNCONFIRMED,
        )

    # ── restart recovery ─────────────────────────────────────────────────────

    def recover(self) -> list[dict[str, str]]:
        """Apply the deterministic restart rules (§11.3) to every stored job.

        Returns the list of ``{job_id, from, to}`` transitions applied.  Jobs
        that legitimately keep their state (queued, remote-id running/polling,
        cancel_requested, terminal) are not listed.

        Recovery is deliberately isolated per record: one corrupt/invalid job
        record, one failed state transition, or one failed artifact
        reconciliation never blocks the other valid jobs or the final orphan
        cleanup.  The recovery-only tolerant listing (:meth:`MediaStore.
        list_jobs_for_recovery`) skips unreadable records while the normal
        ``list_jobs``/idempotency/quota paths stay fail-closed; individual
        transition/reconciliation exceptions are logged with only the record id
        and exception type and the pass continues.

        After the state pass, the artifacts of every terminal non-succeeded
        job are reconciled: a crash between the media save and the
        ``succeeded`` transition must never leave a live reference or an
        invisible orphan (``gc_candidate_since == 0``, no reference) behind,
        and those records are armed or cleaned through the grace/GC lifecycle.
        Finally, content-addressed files no artifact record references are
        removed so a crash between the file save and the metadata write cannot
        leak disk space invisibly.
        """
        outcomes: list[dict[str, str]] = []
        for job in self._store.list_jobs_for_recovery():
            target: ImageJobStatus | None = None
            if job.status == ImageJobStatus.QUEUED:
                continue  # remains executable
            elif job.status in (ImageJobStatus.RUNNING, ImageJobStatus.POLLING):
                if not (job.remote_response_id or job.remote_job_id):
                    target = ImageJobStatus.UNKNOWN
                # else: resume reconcile/poll; state unchanged
            elif job.status in (ImageJobStatus.VALIDATING, ImageJobStatus.SAVING):
                target = ImageJobStatus.UNKNOWN
            elif job.status == ImageJobStatus.CANCEL_REQUESTED:
                continue  # only cancel confirmation resumes
            else:
                continue  # terminal states never resume
            if target is None:
                continue
            try:
                self._store.transition_job(job.id, from_status=job.status, to_status=target)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "recovery: could not transition job %s to %s (%s)",
                    job.id,
                    target.value,
                    type(exc).__name__,
                )
                continue
            outcomes.append({"job_id": job.id, "from": job.status.value, "to": target.value})
        for job in self._store.list_jobs_for_recovery():
            if job.status in TERMINAL_JOB_STATUSES and job.status != ImageJobStatus.SUCCEEDED:
                try:
                    self._store.reconcile_artifacts_for_job(job)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "recovery: artifact reconciliation failed for job %s (%s)",
                        job.id,
                        type(exc).__name__,
                    )
        self._store.reconcile_orphaned_files()
        return outcomes

    def run_queued(self, limit: int | None = None) -> list[str]:
        """Synchronously prepare queued jobs for execution (test/worker hook).

        This is intentionally minimal: MED-01 owns persistence and recovery,
        not the async scheduling loop (MED-02/UI wire the event loop).
        """
        queued = [job for job in self._store.list_jobs(status=ImageJobStatus.QUEUED)]
        return [job.id for job in (queued if limit is None else queued[:limit])]


__all__ = ["ImageGenerationJobWorker", "JobExecutor"]
