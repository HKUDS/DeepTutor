"""Append-only :class:`ModelInvocationRecorder` (§7.8, §9.4).

Used by chat, Teach-Back, evaluation/challenge, and later knowledge-card draft
callers. ``start`` appends a ``pending`` record *before* the provider call;
``finish`` appends a terminal revision (immutable append/revision semantics) so
the ``pending`` revision is preserved and historical records are never
overwritten or dropped. A concurrent stale-writer save is rejected by the
store's version-conflict (CAS) check.

PRODUCTION COVERAGE (narrow hooks wired at real call boundaries)
----------------------------------------------------------------
* ``deeptutor.services.llm.factory.complete()/stream()`` accept an explicit
  ``model_invocation_audit`` context and persist-before-call / finalize-after
  when one is supplied; legacy calls with no context are unchanged.
* ``deeptutor.agents.chat.agent_loop`` audits every LLM round of a turn that
  runs a learning path (``mastery_path_id``) as a ``teaching`` invocation —
  the chat agent loop IS the tutor, so this covers chat-with-learning-path and
  Teach-Back teaching calls.

Deliberately NOT wired yet (documented, not claimed):
* plain chat with no learning path has no ``LearningProgress`` storage
  container for audit records;
* evaluation/challenge finalize boundaries are owned by LRN-03 and are not
  present at this base; knowledge-card-draft invocation is later.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import time
from typing import Any
from uuid import uuid4

from deeptutor.learning.models import (
    EvaluatorSnapshot,
    LearningProgress,
    ModelInvocationPurpose,
    ModelInvocationRecord,
    ModelInvocationStatus,
    ModelInvocationUsage,
    RubricAssessment,
)
from deeptutor.learning.storage import (
    LearningStore,
    append_model_invocation,
    find_model_invocation,
    finish_model_invocation,
)
from deeptutor.services.model_selection.fingerprint import (
    invocation_request_fingerprint,
    invocation_response_fingerprint,
    sanitize_error,
)
from deeptutor.services.model_selection.selector import ResolvedModelSnapshot

logger = logging.getLogger(__name__)


def _coerce_purpose(purpose: ModelInvocationPurpose | str) -> ModelInvocationPurpose:
    if isinstance(purpose, ModelInvocationPurpose):
        return purpose
    return ModelInvocationPurpose(str(purpose))


def _coerce_status(status: ModelInvocationStatus | str) -> ModelInvocationStatus:
    if isinstance(status, ModelInvocationStatus):
        return status
    return ModelInvocationStatus(str(status))


def _coerce_usage(
    usage: ModelInvocationUsage | dict[str, Any] | None,
) -> ModelInvocationUsage | None:
    if usage is None or isinstance(usage, ModelInvocationUsage):
        return usage
    return ModelInvocationUsage(**usage)


class ModelInvocationRecorder:
    """One recorder for every invocation purpose.

    Typical flow::

        recorder = ModelInvocationRecorder()
        record = recorder.start(progress, purpose=purpose, snapshot=snapshot)
        store.save(progress)               # crash here still leaves a pending record
        try:
            result = await provider.complete(...)
        except Exception as exc:
            recorder.finish(progress, record.id, status=FAILED,
                            sanitized_error=str(exc))
        else:
            recorder.finish(progress, record.id, status=COMPLETED,
                            reported_model=result.model,
                            usage=normalized_usage)
        store.save(progress)

    ``finish`` is immutable: a ``pending`` record can only transition once to a
    terminal state, and the record list is never rewritten or reordered.
    """

    def start(
        self,
        progress: LearningProgress,
        *,
        purpose: ModelInvocationPurpose | str,
        snapshot: ResolvedModelSnapshot,
        session_id: str = "",
        turn_id: str = "",
        message_id: str = "",
        tool_call_id: str = "",
        attempt_id: str = "",
        knowledge_card_generation_attempt_id: str = "",
        prompt_version: str | None = None,
        tool_schema_version: str | None = None,
        now: float | None = None,
    ) -> ModelInvocationRecord:
        """Append a ``pending`` invocation record before the provider call."""
        purpose_enum = _coerce_purpose(purpose)
        effective_prompt = prompt_version if prompt_version is not None else snapshot.prompt_version
        effective_tools = (
            tool_schema_version if tool_schema_version is not None else snapshot.tool_schema_version
        )
        record = ModelInvocationRecord(
            id=uuid4().hex,
            purpose=purpose_enum,
            session_id=session_id,
            turn_id=turn_id,
            message_id=message_id,
            tool_call_id=tool_call_id,
            attempt_id=attempt_id,
            knowledge_card_generation_attempt_id=knowledge_card_generation_attempt_id,
            profile_id=snapshot.profile_id,
            profile_revision=snapshot.profile_revision,
            requested_provider=snapshot.requested_provider,
            requested_protocol=snapshot.requested_protocol,
            requested_model=snapshot.requested_model,
            resolved_provider=snapshot.resolved_provider,
            resolved_protocol=snapshot.resolved_protocol,
            resolved_model=snapshot.resolved_model,
            auto_resolution_reason=snapshot.auto_resolution_reason,
            base_url_fingerprint=snapshot.base_url_fingerprint,
            strict_protocol=snapshot.strict_protocol,
            prompt_version=effective_prompt,
            tool_schema_version=effective_tools,
            request_fingerprint=invocation_request_fingerprint(
                purpose=purpose_enum,
                profile_id=snapshot.profile_id,
                profile_revision=snapshot.profile_revision,
                protocol=snapshot.resolved_protocol,
                model=snapshot.resolved_model,
                prompt_version=effective_prompt,
                tool_schema_version=effective_tools,
            ),
            status=ModelInvocationStatus.PENDING,
            created_at=now if now is not None else time.time(),
            started_at=now if now is not None else time.time(),
        )
        return append_model_invocation(progress, record)

    def finish(
        self,
        progress: LearningProgress,
        record_id: str,
        *,
        status: ModelInvocationStatus | str = ModelInvocationStatus.COMPLETED,
        reported_model: str | None = None,
        reported_version: str | None = None,
        usage: ModelInvocationUsage | dict[str, Any] | None = None,
        sanitized_error: str = "",
        error_code: str = "",
        response_fingerprint: str = "",
        now: float | None = None,
    ) -> ModelInvocationRecord:
        """Finalize a pending record (immutable terminal transition)."""
        status_enum = _coerce_status(status)
        usage_model = _coerce_usage(usage)
        if not response_fingerprint:
            response_fingerprint = invocation_response_fingerprint(
                status=status_enum,
                reported_model=reported_model,
                error_code=error_code,
            )
        return finish_model_invocation(
            progress,
            record_id,
            status=status_enum,
            reported_model=reported_model,
            reported_version=reported_version,
            usage=usage_model,
            sanitized_error=sanitize_error(sanitized_error),
            error_code=error_code,
            response_fingerprint=response_fingerprint,
            now=now,
        )


def attach_evaluation_identity(
    assessment: RubricAssessment,
    *,
    snapshot: EvaluatorSnapshot | None,
    invocation_id: str,
) -> RubricAssessment:
    """Attach the frozen evaluator snapshot + invocation id to an assessment.

    Called at evaluation completion so the appended :class:`RubricAssessment`
    carries both the frozen snapshot and the exact invocation it was graded by
    (§7.3, §7.6). Provider-reported model/version stays on the invocation
    record only.
    """
    assessment.evaluator_snapshot = snapshot
    assessment.model_invocation_id = invocation_id
    return assessment


def to_audit_view(progress: LearningProgress, record_id: str) -> dict[str, Any]:
    """A serializable, secret-free audit view for API consumers (§9.4).

    Deterministically projects the *latest* revision of ``record_id`` (see
    :func:`~deeptutor.learning.storage.find_model_invocation`) so the API never
    exposes a stale pending revision while historical revisions stay stored.
    Records only ever persist fingerprints and sanitized data, so this view
    never contains an API key, auth header, private URL, raw prompt/response,
    or base64 media.
    """
    record = find_model_invocation(progress, record_id)
    if record is None:
        raise KeyError(f"model invocation {record_id!r} not found")
    return record.model_dump(mode="json")


@dataclass(frozen=True, slots=True)
class EvaluatorUnavailableResult:
    """Stable paused result when the evaluator is unavailable at finalize (§9.3).

    The frozen profile/model is NOT switched: finalize is paused and the user
    can explicitly migrate the evaluator later. No fallback call is recorded.
    """

    status: str = "paused"
    reason: str = "evaluator_unavailable"
    invocation_id: str = ""
    sanitized_error: str = ""


def finalize_evaluator_unavailable(
    progress: LearningProgress,
    record_id: str,
    *,
    sanitized_error: str = "",
    error_code: str = "",
    now: float | None = None,
) -> EvaluatorUnavailableResult:
    """Finish a pending evaluation invocation as paused / evaluator unavailable.

    Returns the stable :class:`EvaluatorUnavailableResult` so the caller can
    return a deterministic paused verdict to the learner without inventing a
    new evaluator selection.
    """
    finish_model_invocation(
        progress,
        record_id,
        status=ModelInvocationStatus.PAUSED,
        sanitized_error=sanitize_error(sanitized_error),
        error_code=error_code,
        now=now,
    )
    return EvaluatorUnavailableResult(
        invocation_id=record_id,
        sanitized_error=sanitize_error(sanitized_error),
    )


@dataclass(frozen=True, slots=True)
class ModelInvocationAuditContext:
    """Explicit audit context passed by a production caller to the shared
    LLM boundary (``deeptutor.services.llm.factory``) or the chat loop.

    When a caller can resolve purpose/learning context it supplies this; the
    boundary then guarantees a ``pending`` record is persisted *before* the
    provider request and finalized after success/failure. ``store`` may be
    ``None`` or ``book_id`` empty — in that case no audit happens and legacy
    provider behavior is unchanged (nothing is persisted, nothing is raised).
    """

    purpose: ModelInvocationPurpose | str
    #: LearningProgress storage key (``book_id``) the audit record lives in.
    book_id: str
    store: LearningStore | None
    #: Pre-resolved selection snapshot; required for the boundary to audit.
    snapshot: ResolvedModelSnapshot | None = None
    session_id: str = ""
    turn_id: str = ""
    message_id: str = ""
    tool_call_id: str = ""
    attempt_id: str = ""
    prompt_version: str = ""
    tool_schema_version: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.store is not None and self.book_id and self.snapshot is not None)


def _load_audit_progress(ctx: ModelInvocationAuditContext) -> LearningProgress:
    """Load (or create) the LearningProgress the audit record appends to.

    Reloaded on every start/finish so the audit never races a concurrent
    mastery-tool writer: each append is a fresh CAS save against the latest
    persisted document instead of mutating a stale in-memory snapshot.
    """
    progress = ctx.store.load(ctx.book_id)
    if progress is None:
        progress = LearningProgress(book_id=ctx.book_id)
    return progress


def start_audited_invocation(
    ctx: ModelInvocationAuditContext,
    snapshot: ResolvedModelSnapshot | None = None,
    *,
    now: float | None = None,
) -> str | None:
    """Persist a ``pending`` invocation record *before* the provider request.

    Returns the record id, or ``None`` when the audit context is not enabled
    (no store / book_id / snapshot) — the caller must then proceed with legacy
    behaviour and never create a record. Persist-before-call is guaranteed by
    the save inside this function: a crash between here and the provider call
    still leaves the ``pending`` record on disk.
    """
    if ctx is None or not ctx.enabled:
        return None
    snapshot = snapshot or ctx.snapshot
    if snapshot is None:
        return None
    progress = _load_audit_progress(ctx)
    recorder = ModelInvocationRecorder()
    record = recorder.start(
        progress,
        purpose=ctx.purpose,
        snapshot=snapshot,
        session_id=ctx.session_id,
        turn_id=ctx.turn_id,
        message_id=ctx.message_id,
        tool_call_id=ctx.tool_call_id,
        attempt_id=ctx.attempt_id,
        prompt_version=ctx.prompt_version,
        tool_schema_version=ctx.tool_schema_version,
        now=now,
    )
    ctx.store.save(progress)
    return record.id


def finish_audited_invocation(
    ctx: ModelInvocationAuditContext,
    record_id: str,
    *,
    status: ModelInvocationStatus | str,
    reported_model: str | None = None,
    reported_version: str | None = None,
    usage: ModelInvocationUsage | dict[str, Any] | None = None,
    sanitized_error: str = "",
    error_code: str = "",
    now: float | None = None,
) -> str | None:
    """Finalize an audited invocation (append terminal revision + save).

    Returns the latest record id (same ``record_id``) or ``None`` when the
    audit context is disabled. Reloads the latest progress so the terminal
    revision always appends to the newest persisted document.
    """
    if ctx is None or not ctx.enabled or not record_id:
        return None
    progress = _load_audit_progress(ctx)
    recorder = ModelInvocationRecorder()
    recorder.finish(
        progress,
        record_id,
        status=status,
        reported_model=reported_model,
        reported_version=reported_version,
        usage=usage,
        sanitized_error=sanitize_error(sanitized_error),
        error_code=error_code,
        now=now,
    )
    ctx.store.save(progress)
    return record_id


def _error_code_from_exception(exc: BaseException) -> str:
    """A stable, useful error code from an arbitrary provider exception."""
    name = type(exc).__name__
    if name.endswith("Error"):
        name = name[: -len("Error")]
    return (name or "unknown").lower()


async def run_audited_completion(
    ctx: ModelInvocationAuditContext,
    provider_fn: Callable[..., Awaitable[Any]],
    *,
    snapshot: ResolvedModelSnapshot | None = None,
    reported_model: Callable[[Any], str | None] | None = None,
    usage_of: Callable[[Any], dict[str, Any] | None] | None = None,
) -> Any:
    """Run ``provider_fn`` inside an audit envelope (persist-before-call).

    * ``start_audited_invocation`` persists a ``pending`` record before
      ``provider_fn`` is awaited;
    * on success the record is finalized ``completed`` (optionally extracting
      the provider-reported model/usage via the supplied callables);
    * on failure it is finalized ``failed`` with a sanitized error and a stable
      error code, then re-raised.

    ``ctx`` is optional: passing ``None`` (or a disabled context) runs
    ``provider_fn`` with legacy behaviour and no audit record.
    """
    if ctx is None or not ctx.enabled:
        return await provider_fn()
    record_id = start_audited_invocation(ctx, snapshot)
    if record_id is None:
        return await provider_fn()
    try:
        result = await provider_fn()
    except BaseException as exc:
        finish_audited_invocation(
            ctx,
            record_id,
            status=ModelInvocationStatus.FAILED,
            sanitized_error=str(exc),
            error_code=_error_code_from_exception(exc),
        )
        raise
    finish_audited_invocation(
        ctx,
        record_id,
        status=ModelInvocationStatus.COMPLETED,
        reported_model=reported_model(result) if reported_model is not None else None,
        usage=usage_of(result) if usage_of is not None else None,
    )
    return result


__all__ = [
    "EvaluatorUnavailableResult",
    "ModelInvocationAuditContext",
    "ModelInvocationRecorder",
    "attach_evaluation_identity",
    "finalize_evaluator_unavailable",
    "finish_audited_invocation",
    "run_audited_completion",
    "start_audited_invocation",
    "to_audit_view",
]
