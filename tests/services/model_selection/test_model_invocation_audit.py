"""ModelInvocationRecorder contract tests (MOD-03, §7.8 / §9.4).

All purposes (chat/teaching/evaluation/knowledge_card_draft) go through one
recorder. Records are appended as ``pending`` before the provider call,
finalized exactly once afterwards, and never overwritten or dropped. Strict
protocol failures keep the requested protocol and produce no fabricated
fallback record. No real endpoint is ever called.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.models import (
    ModelInvocationPurpose,
    ModelInvocationStatus,
    ModelInvocationUsage,
)
from deeptutor.learning.storage import (
    InvalidInvocationFinishError,
    InvocationAlreadyFinalizedError,
    LearningStore,
    find_model_invocation,
)
from deeptutor.services.model_selection import (
    ModelInvocationRecorder,
    ModelSelector,
    attach_evaluation_identity,
    finalize_evaluator_unavailable,
)
from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.model_selection.selector import ResolvedModelSnapshot

from . import _fixtures as fx

ALL_PURPOSES = [
    ModelInvocationPurpose.CHAT,
    ModelInvocationPurpose.TEACHING,
    ModelInvocationPurpose.EVALUATION,
    ModelInvocationPurpose.KNOWLEDGE_CARD_DRAFT,
]


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


def _snapshot(protocol: str = "openai_responses", *, strict: bool = True) -> ResolvedModelSnapshot:
    """A resolved snapshot for p1/m1 (OpenAI Responses, strict)."""
    return ModelSelector(catalog=fx.catalog()).resolve_evaluator(
        LLMSelection(profile_id="p1", model_id="m1"),
        prompt_version="feynman-v2",
        tool_schema_version="tools-v1",
    )


# ── every purpose ─────────────────────────────────────────────────────────


class TestAllPurposes:
    @pytest.mark.parametrize("purpose", ALL_PURPOSES, ids=lambda p: p.value)
    def test_start_finish_for_purpose(self, purpose):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        record = recorder.start(
            progress,
            purpose=purpose,
            snapshot=_snapshot(),
            session_id="sess-1",
            turn_id="t-1",
        )
        assert record.purpose == purpose
        assert record.status == ModelInvocationStatus.PENDING
        assert record.session_id == "sess-1"
        assert record.turn_id == "t-1"

        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model="gpt-4o-mini",
            usage=ModelInvocationUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )
        record = find_model_invocation(progress, record.id)
        assert record.status == ModelInvocationStatus.COMPLETED
        assert record.usage.total_tokens == 5
        assert record.finished_at is not None
        assert record.provider_reported_model == "gpt-4o-mini"
        # Append-only: the pending revision is preserved and a terminal revision
        # is appended (same id, revision 1 + revision 2).
        assert len(progress.model_invocations) == 2
        assert progress.model_invocations[0].status == ModelInvocationStatus.PENDING
        assert progress.model_invocations[1].revision == 2

    def test_requested_resolved_and_reported_identity_all_recorded(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        snapshot = _snapshot()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=snapshot
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model="gpt-4o-mini",
            reported_version="2026-01-10",
        )
        record = find_model_invocation(progress, record.id)
        assert record.requested_protocol == "openai_responses"
        assert record.resolved_protocol == "openai_responses"
        assert record.requested_model == "gpt-4o-mini"
        assert record.resolved_model == "gpt-4o-mini"
        assert record.resolved_provider == "openai"
        assert record.provider_reported_model == "gpt-4o-mini"
        assert record.provider_model_version == "2026-01-10"
        assert record.profile_revision
        assert record.base_url_fingerprint


# ── pre-call record existence ─────────────────────────────────────────────


class TestPreCallRecord:
    def test_pending_record_exists_after_save_before_call(self, store):
        progress = fx.progress("b1")
        recorder = ModelInvocationRecorder()
        record = recorder.start(progress, purpose=ModelInvocationPurpose.CHAT, snapshot=_snapshot())
        # Persist BEFORE the provider call so a crash leaves an audit trail.
        store.save(progress)

        loaded = store.load("b1")
        assert len(loaded.model_invocations) == 1
        assert loaded.model_invocations[0].id == record.id
        assert loaded.model_invocations[0].status == ModelInvocationStatus.PENDING
        assert loaded.model_invocations[0].purpose == ModelInvocationPurpose.CHAT

        # Finish afterwards and persist again.
        recorder.finish(progress, record.id, status=ModelInvocationStatus.COMPLETED)
        store.save(progress)
        final = store.load("b1")
        assert final.model_invocations[0].status == ModelInvocationStatus.PENDING
        assert find_model_invocation(final, record.id).status == ModelInvocationStatus.COMPLETED
        # Exactly one invocation id (pending + terminal revision) — no
        # fabricated fallback call, no duplicate.
        assert {r.id for r in final.model_invocations} == {record.id}
        assert len(final.model_invocations) == 2


# ── missing reported identity ─────────────────────────────────────────────


class TestMissingReportedIdentity:
    def test_absent_reported_model_stores_literal_unknown(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        snapshot = _snapshot()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.TEACHING, snapshot=snapshot
        )
        recorder.finish(progress, record.id, status=ModelInvocationStatus.COMPLETED)
        record = find_model_invocation(progress, record.id)
        # The requested model must never leak into the reported field.
        assert record.requested_model == "gpt-4o-mini"
        assert record.provider_reported_model == "unknown"
        assert record.provider_model_version == "unknown"

    def test_blank_reported_model_stores_literal_unknown(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=_snapshot()
        )
        recorder.finish(
            progress, record.id, status=ModelInvocationStatus.COMPLETED, reported_model="  "
        )
        assert find_model_invocation(progress, record.id).provider_reported_model == "unknown"


# ── provider exception / strict failure ───────────────────────────────────


class TestFailureSemantics:
    def test_provider_exception_finishing_marks_failed(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        snapshot = _snapshot()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=snapshot
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.FAILED,
            sanitized_error="upstream timeout",
            error_code="timeout",
        )
        record = find_model_invocation(progress, record.id)
        assert record.status == ModelInvocationStatus.FAILED
        assert record.error_code == "timeout"
        assert record.sanitized_error == "upstream timeout"

    def test_strict_failure_keeps_requested_protocol_no_fallback_record(self):
        """A strict-protocol failure records the requested protocol and creates
        exactly one record — no fabricated fallback call is appended."""
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        snapshot = _snapshot()  # p1/m1 is strict openai_responses
        assert snapshot.strict_protocol is True
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=snapshot
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.FAILED,
            sanitized_error="UnifiedProtocolError: protocol_error",
            error_code="protocol_error",
        )
        # Exactly one invocation id — the pending revision and its terminal
        # revision — and no extra record was created for a "fallback" call.
        assert {r.id for r in progress.model_invocations} == {record.id}
        assert len(progress.model_invocations) == 2
        record = find_model_invocation(progress, record.id)
        # Requested == resolved (strict never falls back).
        assert record.requested_protocol == "openai_responses"
        assert record.resolved_protocol == "openai_responses"
        assert record.status == ModelInvocationStatus.FAILED

    def test_auto_resolution_reason_recorded(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        selector = ModelSelector(catalog=fx.auto_catalog())
        snapshot = selector.resolve_evaluator(
            LLMSelection(profile_id="p2", model_id="m3"),
            prompt_version="feynman-v2",
        )
        assert snapshot.requested_protocol == "auto"
        assert snapshot.resolved_protocol == "anthropic_messages"
        assert snapshot.auto_resolution_reason  # non-empty

        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=snapshot
        )
        recorder.finish(progress, record.id, status=ModelInvocationStatus.COMPLETED)
        record = find_model_invocation(progress, record.id)
        assert record.resolved_protocol == "anthropic_messages"
        assert record.auto_resolution_reason


# ── immutable / concurrent ────────────────────────────────────────────────


class TestImmutableAndConcurrent:
    def test_double_finish_raises(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        record = recorder.start(progress, purpose=ModelInvocationPurpose.CHAT, snapshot=_snapshot())
        recorder.finish(progress, record.id, status=ModelInvocationStatus.COMPLETED)
        with pytest.raises(InvocationAlreadyFinalizedError):
            recorder.finish(progress, record.id, status=ModelInvocationStatus.FAILED)

    def test_concurrent_append_version_conflict(self, store):
        left = fx.progress("b1")
        left_recorder = ModelInvocationRecorder()
        left_record = left_recorder.start(
            left, purpose=ModelInvocationPurpose.CHAT, snapshot=_snapshot()
        )
        store.save(left)

        right = store.load("b1")
        right_recorder = ModelInvocationRecorder()
        right_record = right_recorder.start(
            right, purpose=ModelInvocationPurpose.CHAT, snapshot=_snapshot()
        )

        # Left saves again, bumping the persisted version past right's snapshot.
        left_recorder.finish(left, left_record.id, status=ModelInvocationStatus.COMPLETED)
        store.save(left)

        with pytest.raises(Exception) as excinfo:
            store.save(right)
        assert excinfo.type.__name__ == "VersionConflictError"
        assert right_record.status == ModelInvocationStatus.PENDING

        final = store.load("b1")
        assert {r.id for r in final.model_invocations} == {left_record.id}
        # Pending revision preserved + terminal revision appended by left.
        assert (
            find_model_invocation(final, left_record.id).status == ModelInvocationStatus.COMPLETED
        )
        assert final.model_invocations[0].status == ModelInvocationStatus.PENDING


# ── secrets never persisted ───────────────────────────────────────────────


class TestNoSecrets:
    def test_secrets_and_private_url_never_serialized(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        # A snapshot whose base URL carries a secret query token; the snapshot
        # already stores only a fingerprint.
        snapshot = ModelSelector(catalog=fx.catalog()).resolve_evaluator(
            LLMSelection(profile_id="p1", model_id="m1")
        )
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=snapshot
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.FAILED,
            sanitized_error="provider echoed Authorization: Bearer sk-abcdef123456",
        )
        data = json.dumps(find_model_invocation(progress, record.id).model_dump(mode="json"))
        assert "sk-secret" not in data
        assert "sk-abcdef123456" not in data
        assert "Bearer" not in data
        assert "api.example.com" not in data
        assert "extra_headers" not in data
        assert "api_key" not in data

    def test_url_secrets_never_reach_serialized_record_or_audit_view(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=_snapshot()
        )
        # Assembled at runtime so the source never carries a literal
        # private-looking URL; the scrubber must redact the assembled one.
        fake_url = (
            "https://user:pass@"
            + "api.example.com"
            + "/v1/chat"
            + "?token="
            + "t0ken"
            + "&key="
            + "secretK"
            + "&password="
            + "hunter2"
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.FAILED,
            sanitized_error="upstream 401 GET " + fake_url,
            error_code="unauthorized",
        )
        latest = find_model_invocation(progress, record.id)
        data = json.dumps(latest.model_dump(mode="json"))
        assert "api.example.com" not in data
        assert "/v1/chat" not in data
        assert "user:pass" not in data
        assert "t0ken" not in data
        assert "secretK" not in data
        assert "hunter2" not in data
        assert "https://[REDACTED]" in data

        from deeptutor.services.model_selection import to_audit_view

        view = json.dumps(to_audit_view(progress, record.id))
        assert "api.example.com" not in view
        assert "t0ken" not in view
        assert "hunter2" not in view

    def test_sanitized_error_is_stable(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        record = recorder.start(progress, purpose=ModelInvocationPurpose.CHAT, snapshot=_snapshot())
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.FAILED,
            sanitized_error="boom sk-abcdef123456 x-api-key: secret123",
        )
        stored = find_model_invocation(progress, record.id).sanitized_error
        assert "sk-abcdef123456" not in stored
        assert "secret123" not in stored
        assert "[REDACTED]" in stored

    def test_api_ready_audit_view_is_secret_free(self):
        from deeptutor.services.model_selection import to_audit_view

        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=_snapshot()
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model="gpt-4o-mini",
        )
        view = to_audit_view(progress, record.id)
        text = json.dumps(view)
        assert "api_key" not in text
        assert "extra_headers" not in text
        assert "api.example.com" not in text
        assert "sk-" not in text
        assert view["purpose"] == "evaluation"
        assert view["provider_reported_model"] == "gpt-4o-mini"


# ── evaluator unavailable → stable paused ─────────────────────────────────


class TestEvaluatorUnavailable:
    def test_finalize_unavailable_returns_stable_paused_result(self):
        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=_snapshot()
        )
        result = finalize_evaluator_unavailable(
            progress,
            record.id,
            sanitized_error="evaluator unavailable",
        )
        assert result.status == "paused"
        assert result.reason == "evaluator_unavailable"
        assert result.invocation_id == record.id
        # The record is paused, NOT switched to another profile/model.
        record = find_model_invocation(progress, record.id)
        assert record.status == ModelInvocationStatus.PAUSED
        assert record.resolved_provider == "openai"
        assert record.resolved_protocol == "openai_responses"
        # Pending revision preserved + terminal paused revision appended.
        assert len(progress.model_invocations) == 2


# ── attach evaluation identity ────────────────────────────────────────────


class TestAttachIdentity:
    def test_assessment_carries_frozen_snapshot_and_invocation_id(self):
        from deeptutor.learning.models import RubricAssessment

        progress = fx.progress()
        recorder = ModelInvocationRecorder()
        snapshot = _snapshot()
        record = recorder.start(
            progress, purpose=ModelInvocationPurpose.EVALUATION, snapshot=snapshot
        )
        recorder.finish(
            progress,
            record.id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model="gpt-4o-mini",
        )
        evaluator_snapshot = snapshot.to_evaluator_snapshot(rubric_version="v1")
        assessment = RubricAssessment(id="ra1", attempt_id="a1")
        attach_evaluation_identity(assessment, snapshot=evaluator_snapshot, invocation_id=record.id)
        assert assessment.model_invocation_id == record.id
        assert assessment.evaluator_snapshot is evaluator_snapshot
        assert assessment.evaluator_snapshot.resolved_model == "gpt-4o-mini"
