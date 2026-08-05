"""Model + storage tests for the append-only ModelInvocationRecord (MOD-03).

Covers the §7.8 record shape, default ``unknown`` provider-reported identity,
round-trip serialization, append-only finish semantics, migration of the v2
fixture, and the version-conflict guarantee that a stale writer can never drop
an invocation record another writer already appended.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.learning.models import (
    LearningProgress,
    ModelInvocationPurpose,
    ModelInvocationRecord,
    ModelInvocationStatus,
    ModelInvocationUsage,
)
from deeptutor.learning.storage import (
    InvalidInvocationFinishError,
    InvocationAlreadyFinalizedError,
    LearningStore,
    append_model_invocation,
    find_model_invocation,
    finish_model_invocation,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _record(record_id: str = "inv-1") -> ModelInvocationRecord:
    return ModelInvocationRecord(
        id=record_id,
        purpose=ModelInvocationPurpose.EVALUATION,
        profile_id="p-1",
        profile_revision="r2",
        requested_protocol="auto",
        requested_model="gpt-4o-mini",
        resolved_provider="openai",
        resolved_protocol="openai_responses",
        resolved_model="gpt-4o-mini",
        auto_resolution_reason="auto:default",
    )


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


# ── record defaults / shape ───────────────────────────────────────────────


class TestModelInvocationRecordDefaults:
    def test_pending_status_and_unknown_reported_identity(self):
        record = _record()
        assert record.status == ModelInvocationStatus.PENDING
        # Absent provider-reported identity is the literal ``unknown`` and is
        # never derived from the requested model (§7.6).
        assert record.provider_reported_model == "unknown"
        assert record.provider_model_version == "unknown"
        assert record.requested_model == "gpt-4o-mini"
        assert record.requested_model != record.provider_reported_model
        assert record.strict_protocol is False
        assert record.finished_at is None
        assert record.usage == ModelInvocationUsage()

    def test_purpose_values(self):
        assert ModelInvocationPurpose.CHAT.value == "chat"
        assert ModelInvocationPurpose.TEACHING.value == "teaching"
        assert ModelInvocationPurpose.EVALUATION.value == "evaluation"
        assert ModelInvocationPurpose.KNOWLEDGE_CARD_DRAFT.value == "knowledge_card_draft"

    def test_status_values(self):
        assert ModelInvocationStatus.PENDING.value == "pending"
        assert ModelInvocationStatus.COMPLETED.value == "completed"
        assert ModelInvocationStatus.FAILED.value == "failed"
        assert ModelInvocationStatus.PAUSED.value == "paused"

    def test_extra_fields_ignored(self):
        record = _record().model_copy(update={})
        data = record.model_dump(mode="json")
        assert "api_key" not in data
        assert "extra_headers" not in data


# ── round-trip ────────────────────────────────────────────────────────────


class TestModelInvocationRoundtrip:
    def test_record_roundtrips_losslessly(self):
        record = _record()
        record.provider_reported_model = "gpt-4o-mini"
        record.status = ModelInvocationStatus.COMPLETED
        record.usage = ModelInvocationUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        record.finished_at = 1710000020.0
        data = record.model_dump(mode="json")
        record2 = ModelInvocationRecord.model_validate(data)
        assert record2.model_dump(mode="json") == data
        assert record2.provider_reported_model == "gpt-4o-mini"
        assert record2.status == ModelInvocationStatus.COMPLETED
        assert record2.usage.total_tokens == 15

    def test_learning_progress_defaults(self):
        progress = LearningProgress(book_id="b1")
        assert progress.model_invocations == []
        assert progress.evaluator_profile_id == ""
        assert progress.evaluator_model_id == ""
        assert progress.evaluator_api_protocol == ""
        assert progress.aggregate_versions.model_invocation == 0


# ── append-only finish semantics ──────────────────────────────────────────


class TestAppendOnlyFinish:
    def test_append_then_finish_bumps_aggregate_and_history(self):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        assert len(progress.model_invocations) == 1
        assert progress.aggregate_versions.model_invocation == 1
        assert progress.history[-1].event_type == "model_invocation_started"

        finish_model_invocation(
            progress,
            "inv-1",
            status=ModelInvocationStatus.COMPLETED,
            reported_model="gpt-4o-mini",
        )
        record = find_model_invocation(progress, "inv-1")
        assert record.status == ModelInvocationStatus.COMPLETED
        assert record.provider_reported_model == "gpt-4o-mini"
        assert record.finished_at is not None
        assert progress.aggregate_versions.model_invocation == 2
        assert progress.history[-1].event_type == "model_invocation_finished"
        # Append-only: the pending revision is preserved.
        assert progress.model_invocations[0].status == ModelInvocationStatus.PENDING
        assert len(progress.model_invocations) == 2

    def test_finish_unknown_identity_stored_as_unknown(self):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        finish_model_invocation(progress, "inv-1", status=ModelInvocationStatus.COMPLETED)
        record = find_model_invocation(progress, "inv-1")
        # Even though the requested model was set, the reported field stays the
        # literal ``unknown``.
        assert record.provider_reported_model == "unknown"
        assert record.requested_model == "gpt-4o-mini"

    def test_double_finish_raises_immutable_error(self):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        finish_model_invocation(progress, "inv-1", status=ModelInvocationStatus.COMPLETED)
        with pytest.raises(InvocationAlreadyFinalizedError) as excinfo:
            finish_model_invocation(progress, "inv-1", status=ModelInvocationStatus.FAILED)
        assert excinfo.value.record_id == "inv-1"
        assert excinfo.value.status == ModelInvocationStatus.COMPLETED

    def test_finish_missing_record_raises_keyerror(self):
        progress = LearningProgress(book_id="b1")
        with pytest.raises(KeyError):
            finish_model_invocation(progress, "nope", status=ModelInvocationStatus.COMPLETED)

    def test_find_model_invocation(self):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        assert find_model_invocation(progress, "inv-1") is progress.model_invocations[0]
        assert find_model_invocation(progress, "missing") is None

    def test_finish_targeting_pending_status_is_rejected(self):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        with pytest.raises(InvalidInvocationFinishError) as excinfo:
            finish_model_invocation(progress, "inv-1", status=ModelInvocationStatus.PENDING)
        assert excinfo.value.record_id == "inv-1"
        # Nothing was appended — the pending revision is untouched.
        assert len(progress.model_invocations) == 1
        assert progress.model_invocations[0].status == ModelInvocationStatus.PENDING

    def test_started_at_populated_at_pre_call_start(self):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        record = progress.model_invocations[0]
        assert record.started_at is not None
        assert record.created_at <= record.started_at

    def test_finished_at_is_monotonic(self):
        progress = LearningProgress(book_id="b1")
        record = _record()
        record.started_at = 5000.0
        append_model_invocation(progress, record)
        # A finish timestamp before start is clamped to started_at.
        finished = finish_model_invocation(
            progress, "inv-1", status=ModelInvocationStatus.COMPLETED, now=4000.0
        )
        assert finished.finished_at == 5000.0
        assert finished.finished_at >= finished.started_at

    def test_usage_counters_reject_negative(self):
        with pytest.raises(Exception) as excinfo:
            from deeptutor.learning.models import ModelInvocationUsage

            ModelInvocationUsage(prompt_tokens=-1)
        assert "greater than or equal to 0" in str(excinfo.value) or "ge" in str(excinfo.value)

    def test_terminal_revision_appended_exactly_once(self):
        """After one finish, exactly two revisions exist: the preserved pending
        revision and exactly one terminal revision."""
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        terminal = finish_model_invocation(
            progress, "inv-1", status=ModelInvocationStatus.COMPLETED
        )
        revisions = [r for r in progress.model_invocations if r.id == "inv-1"]
        assert len(revisions) == 2
        assert revisions[0].revision == 1
        assert revisions[0].status == ModelInvocationStatus.PENDING
        assert revisions[1].revision == 2
        assert revisions[1].status == ModelInvocationStatus.COMPLETED
        assert terminal.revision == 2

    def test_terminal_revision_roundtrips_with_history(self):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record("inv-1"))
        finish_model_invocation(
            progress,
            "inv-1",
            status=ModelInvocationStatus.FAILED,
            sanitized_error="upstream boom",
            error_code="upstream",
        )
        data = progress.model_dump(mode="json")
        loaded = LearningProgress.model_validate(data)
        assert loaded.model_dump(mode="json") == data
        assert len(loaded.model_invocations) == 2
        assert loaded.model_invocations[0].status == ModelInvocationStatus.PENDING
        latest = find_model_invocation(loaded, "inv-1")
        assert latest.revision == 2
        assert latest.status == ModelInvocationStatus.FAILED
        assert latest.sanitized_error == "upstream boom"
        assert latest.error_code == "upstream"


# ── persistence + migration ───────────────────────────────────────────────


class TestPersistence:
    def test_pending_record_persists_before_call(self, store):
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record())
        store.save(progress)

        loaded = store.load("b1")
        assert len(loaded.model_invocations) == 1
        assert loaded.model_invocations[0].status == ModelInvocationStatus.PENDING
        assert loaded.model_invocations[0].purpose == ModelInvocationPurpose.EVALUATION

    def test_concurrent_append_version_conflict(self, store):
        left = LearningProgress(book_id="b1")
        append_model_invocation(left, _record("inv-1"))
        store.save(left)

        # ``right`` holds a stale snapshot (version 1).
        right = store.load("b1")

        # ``left`` appends another record and saves, bumping persisted v1 -> v2.
        append_model_invocation(left, _record("inv-2"))
        store.save(left)

        # The stale writer's append+save must be rejected so it cannot drop
        # ``left``'s inv-2 record.
        append_model_invocation(right, _record("inv-3"))
        with pytest.raises(Exception) as excinfo:
            store.save(right)
        assert excinfo.type.__name__ == "VersionConflictError"

        final = store.load("b1")
        assert {r.id for r in final.model_invocations} == {"inv-1", "inv-2"}
        assert final.aggregate_versions.model_invocation == 2

    def test_restart_pending_then_finish_appends_terminal_revision(self, store):
        """A pending record persisted before a crash survives a restart, and
        finishing on the reloaded progress appends exactly one terminal revision
        while the original pending revision is still serialized."""
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record("inv-1"))
        store.save(progress)

        # "Crash" before the provider call: reload simulates a restart.
        reloaded = store.load("b1")
        assert find_model_invocation(reloaded, "inv-1").status == ModelInvocationStatus.PENDING
        pending_dump = reloaded.model_invocations[0].model_dump(mode="json")

        finish_model_invocation(
            reloaded, "inv-1", status=ModelInvocationStatus.COMPLETED, reported_model="gpt-4o-mini"
        )
        store.save(reloaded)

        final = store.load("b1")
        assert len(final.model_invocations) == 2
        # The original pending revision is byte-for-byte unchanged.
        assert final.model_invocations[0].model_dump(mode="json") == pending_dump
        latest = find_model_invocation(final, "inv-1")
        assert latest.revision == 2
        assert latest.status == ModelInvocationStatus.COMPLETED
        assert latest.provider_reported_model == "gpt-4o-mini"

    def test_concurrent_finish_cas_rejects_stale_writer(self, store):
        """Two writers both try to finish the same pending record. The first
        CAS save wins; the stale writer's save is rejected so the terminal
        revision is appended exactly once."""
        progress = LearningProgress(book_id="b1")
        append_model_invocation(progress, _record("inv-1"))
        store.save(progress)

        left = store.load("b1")
        right = store.load("b1")

        finish_model_invocation(left, "inv-1", status=ModelInvocationStatus.COMPLETED)
        store.save(left)  # wins: v1 -> v2

        finish_model_invocation(right, "inv-1", status=ModelInvocationStatus.FAILED)
        with pytest.raises(Exception) as excinfo:
            store.save(right)
        assert excinfo.type.__name__ == "VersionConflictError"

        final = store.load("b1")
        revisions = [r for r in final.model_invocations if r.id == "inv-1"]
        assert len(revisions) == 2
        assert find_model_invocation(final, "inv-1").status == ModelInvocationStatus.COMPLETED

    def test_v2_fixture_roundtrips_losslessly(self):
        data = json.loads((FIXTURES / "feynman_progress_v2.json").read_text(encoding="utf-8"))
        loaded = LearningProgress.model_validate(data)
        assert loaded.model_dump(mode="json") == data
        assert loaded.model_invocations == []
        assert loaded.aggregate_versions.model_invocation == 0
