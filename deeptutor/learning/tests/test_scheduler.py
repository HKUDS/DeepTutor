import math
import time

import pytest

from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgeType,
    LearningEvidence,
    LearningProgress,
    RepetitionState,
    ReviewTask,
)
from deeptutor.learning.scheduler import INTERVAL_SEQUENCES, SpacedRepetitionScheduler


@pytest.fixture
def scheduler():
    return SpacedRepetitionScheduler()


# ── interval sequences ───────────────────────────────────────────────────


class TestIntervalSequences:
    def test_memory_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.MEMORY] == [0, 1, 3, 7, 14, 30, 60]

    def test_concept_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.CONCEPT] == [3, 7, 14, 30]

    def test_procedure_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.PROCEDURE] == [3, 7, 14]

    def test_design_sequence(self):
        assert INTERVAL_SEQUENCES[KnowledgeType.DESIGN] == [14, 28]


# ── get_initial_state ────────────────────────────────────────────────────


class TestInitialState:
    def test_memory_initial(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        assert state.interval_index == 0
        assert state.consecutive_correct == 0
        assert state.consecutive_wrong == 0
        assert abs(state.next_review_at - time.time()) < 5

    def test_design_initial(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.DESIGN)
        assert state.interval_index == 0
        assert abs(state.next_review_at - time.time() - 14 * 86400) < 5


# ── schedule_next: correct advances ──────────────────────────────────────


class TestCorrectAdvances:
    def test_first_correct(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        initial_stability = state.stability
        before = state.next_review_at
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        assert state.consecutive_correct == 1
        assert state.consecutive_wrong == 0
        assert state.review_count == 1
        assert state.stability > initial_stability
        assert state.next_review_at > before
        assert state.last_review_at is not None

    def test_same_session_success_does_not_extend_due_time(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        after_one = state.stability
        due_after_one = state.next_review_at
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        assert state.consecutive_correct == 1
        assert state.stability == after_one
        assert state.next_review_at == due_after_one
        assert state.review_count == 2
        assert state.lapse_count == 0

    def test_success_at_due_time_extends_interval(self, scheduler):
        start = 1_700_000_000.0
        state = scheduler.get_initial_state(KnowledgeType.MEMORY, now=start)
        scheduler.schedule_review(state, KnowledgeType.MEMORY, _evidence(quality=1.0, ts=start))
        first_stability = state.stability
        due = state.next_review_at
        scheduler.schedule_review(state, KnowledgeType.MEMORY, _evidence(quality=1.0, ts=due))
        assert state.stability > first_stability
        assert state.next_review_at > due


# ── schedule_next: wrong retreats ────────────────────────────────────────


class TestWrongRetreats:
    def test_wrong_shortens_stability_and_interval(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        after_success = state.stability
        due_after_success = state.next_review_at - state.last_review_at
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)
        assert state.consecutive_wrong == 1
        assert state.consecutive_correct == 0
        assert state.lapse_count == 1
        assert state.stability < after_success
        assert (state.next_review_at - state.last_review_at) < due_after_success

    def test_two_consecutive_wrong_resets(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)
        assert state.consecutive_wrong == 0
        assert state.lapse_count == 2


# ── schedule_next: boundaries ────────────────────────────────────────────


class TestBoundaries:
    def test_cant_go_below_zero(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)
        assert state.interval_index == 0
        assert state.stability > 0
        assert state.next_review_at > time.time() - 1

    def test_cant_exceed_sequence(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state.interval_index = 6  # max for MEMORY
        state.stability = 0.0
        scheduler.hydrate(state, KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        assert state.interval_index == 6


# ── different types ──────────────────────────────────────────────────────


class TestDifferentTypes:
    def test_design_first_correct(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.DESIGN)
        state = scheduler.schedule_next(state, KnowledgeType.DESIGN, True)
        assert state.interval_index == 1

    def test_concept_sequence(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.CONCEPT)
        state = scheduler.schedule_next(state, KnowledgeType.CONCEPT, True)
        assert state.interval_index == 1


# ── get_due_tasks ────────────────────────────────────────────────────────


class TestGetDueTasks:
    def test_returns_due_only(self, scheduler):
        now = time.time()
        state = RepetitionState(next_review_at=now - 10)
        task = ReviewTask(
            id="r1",
            knowledge_point_id="kp1",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=now - 10,
            priority=1,
            state=state,
        )
        lp = LearningProgress(book_id="b1", review_queue=[task])
        due = scheduler.get_due_tasks(lp)
        assert len(due) == 1

    def test_skips_future(self, scheduler):
        now = time.time()
        state = RepetitionState(next_review_at=now + 86400)
        task = ReviewTask(
            id="r1",
            knowledge_point_id="kp1",
            knowledge_type=KnowledgeType.MEMORY,
            due_at=now + 86400,
            priority=1,
            state=state,
        )
        lp = LearningProgress(book_id="b1", review_queue=[task])
        due = scheduler.get_due_tasks(lp)
        assert len(due) == 0

    def test_sorted_by_priority(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.review_queue = [
            ReviewTask(
                id="r_low",
                knowledge_point_id="kp_low",
                knowledge_type=KnowledgeType.MEMORY,
                due_at=now - 10,
                priority=5,
                state=RepetitionState(next_review_at=now - 10),
            ),
            ReviewTask(
                id="r_high",
                knowledge_point_id="kp_high",
                knowledge_type=KnowledgeType.MEMORY,
                due_at=now - 10,
                priority=1,
                state=RepetitionState(next_review_at=now - 10),
            ),
        ]
        due = scheduler.get_due_tasks(lp)
        assert [t.id for t in due] == ["r_high", "r_low"]

    def test_respects_max_tasks(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.review_queue = [
            ReviewTask(
                id=f"r{i}",
                knowledge_point_id=f"kp{i}",
                knowledge_type=KnowledgeType.MEMORY,
                due_at=now - 10,
                priority=i,
                state=RepetitionState(next_review_at=now - 10),
            )
            for i in range(8)
        ]
        due = scheduler.get_due_tasks(lp, max_tasks=3)
        assert len(due) == 3


# ── build_review_queue ───────────────────────────────────────────────────


class TestBuildReviewQueue:
    def test_error_records_get_priority_1(self, scheduler):
        now = time.time()
        state = RepetitionState(next_review_at=now)
        lp = LearningProgress(book_id="b1")
        lp.repetition_states["kp1"] = state
        lp.knowledge_types["kp1"] = KnowledgeType.MEMORY
        lp.error_records = [
            ErrorRecord(
                id="e1",
                question_id="q1",
                knowledge_point_id="kp1",
                module_id="m1",
                error_type=ErrorType.APPLICATION_ERROR,
            )
        ]
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        assert tasks[0].priority == 1

    def test_non_error_kp_uses_type_priority(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.repetition_states["kp_design"] = RepetitionState(next_review_at=now)
        lp.knowledge_types["kp_design"] = KnowledgeType.DESIGN
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        # DESIGN has the lowest urgency -> largest priority number, never 1.
        assert tasks[0].priority == 5
        assert tasks[0].knowledge_type == KnowledgeType.DESIGN

    def test_graduated_error_does_not_promote_priority(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now)
        lp.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        # Only active/retrying error records boost priority to 1.
        lp.error_records = [
            ErrorRecord(
                id="e1",
                question_id="q1",
                knowledge_point_id="kp1",
                module_id="m1",
                error_type=ErrorType.APPLICATION_ERROR,
                status="graduated",
            )
        ]
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        assert tasks[0].priority == 3  # CONCEPT type priority, not 1

    def test_retrying_error_promotes_priority(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now)
        lp.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        lp.error_records = [
            ErrorRecord(
                id="e1",
                question_id="q1",
                knowledge_point_id="kp1",
                module_id="m1",
                error_type=ErrorType.APPLICATION_ERROR,
                status="retrying",
            )
        ]
        tasks = scheduler.build_review_queue(lp)
        assert tasks[0].priority == 1

    def test_defaults_missing_type_to_memory(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.repetition_states["kp1"] = RepetitionState(next_review_at=now)
        # No entry in knowledge_types -> defaults to MEMORY (priority 2).
        tasks = scheduler.build_review_queue(lp)
        assert len(tasks) == 1
        assert tasks[0].knowledge_type == KnowledgeType.MEMORY
        assert tasks[0].priority == 2
        assert tasks[0].reason
        assert 0.0 <= tasks[0].forgetting_risk <= 1.0

    def test_review_explains_latest_linked_assessment_source(self, scheduler):
        now = 1_700_000_000.0
        progress = LearningProgress(book_id="b1")
        progress.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        progress.repetition_states["kp1"] = scheduler.get_initial_state(
            KnowledgeType.CONCEPT, now=now
        )
        progress.learning_evidence = [
            LearningEvidence(
                evidence_id="older-book-attempt",
                knowledge_point_id="kp1",
                timestamp=now - 86400,
                source="book",
                result="incorrect",
            ),
            LearningEvidence(
                evidence_id="reading-attempt-42",
                knowledge_point_id="kp1",
                timestamp=now - 2 * 86400,
                source="immersive_reading",
                result="correct",
            ),
        ]

        task = scheduler.build_review_queue(progress, now=now)[0]
        assert task.evidence_source == "immersive_reading"
        assert task.evidence_id == "reading-attempt-42"
        assert "latest Reading assessment: correct" in task.reason
        assert "reading-attempt-42" not in task.reason


# ── adaptive retention baseline ──────────────────────────────────────────


def _evidence(
    *, quality: float, result: str = "correct", ts: float | None = None
) -> LearningEvidence:
    return LearningEvidence(
        knowledge_point_id="kp1",
        timestamp=time.time() if ts is None else ts,
        assessment_type="quiz",
        result="correct" if result == "correct" else "incorrect",
        quality=quality,
    )


class TestRetentionBaseline:
    def test_quality_differentiates_correct_updates(self, scheduler):
        easy = scheduler.get_initial_state(KnowledgeType.MEMORY)
        hard = scheduler.get_initial_state(KnowledgeType.MEMORY)
        now = time.time()
        scheduler.schedule_review(
            easy, KnowledgeType.MEMORY, _evidence(quality=1.0, ts=now), now=now
        )
        scheduler.schedule_review(
            hard, KnowledgeType.MEMORY, _evidence(quality=0.6, ts=now), now=now
        )
        assert easy.stability > hard.stability
        assert easy.next_review_at > hard.next_review_at

    def test_delayed_success_grows_stability_more_than_immediate_repetition(self, scheduler):
        start = 1_700_000_000.0
        immediate = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=start)
        delayed = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=start)
        first = _evidence(quality=1.0, ts=start)
        scheduler.schedule_review(immediate, KnowledgeType.CONCEPT, first, now=start)
        scheduler.schedule_review(delayed, KnowledgeType.CONCEPT, first, now=start)

        scheduler.schedule_review(
            immediate,
            KnowledgeType.CONCEPT,
            _evidence(quality=1.0, ts=start + 60),
            now=start + 60,
        )
        scheduler.schedule_review(
            delayed,
            KnowledgeType.CONCEPT,
            _evidence(quality=1.0, ts=start + 7 * 86400),
            now=start + 7 * 86400,
        )

        assert delayed.stability > immediate.stability
        assert delayed.difficulty < immediate.difficulty

    def test_six_one_minute_reviews_do_not_turn_into_a_long_interval(self, scheduler):
        start = 1_700_000_000.0
        state = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=start)
        scheduler.schedule_review(state, KnowledgeType.CONCEPT, _evidence(quality=1.0, ts=start))
        first_stability = state.stability
        first_due = state.next_review_at
        for index in range(1, 6):
            scheduler.schedule_review(
                state,
                KnowledgeType.CONCEPT,
                _evidence(quality=1.0, ts=start + index * 60),
            )
        assert state.stability == first_stability
        assert state.next_review_at == first_due
        assert state.review_count == 6

    def test_live_transition_equals_replay_with_path_retention_and_mixed_assessments(
        self, scheduler
    ):
        start = 1_700_000_000.0
        events = [
            LearningEvidence(
                knowledge_point_id="kp1",
                timestamp=start,
                assessment_type="qualitative",
                result="correct",
                quality=0.9,
            ),
            _evidence(quality=1.0, ts=start + 60),  # not yet due
            _evidence(quality=0.0, result="incorrect", ts=start + 86400),
            _evidence(quality=1.0, ts=start + 86460),
            _evidence(quality=1.0, ts=start + 8 * 86400),
        ]
        live = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=start, desired_retention=0.82)
        for event in events:
            scheduler.schedule_review(live, KnowledgeType.CONCEPT, event)
        replayed = scheduler.replay(KnowledgeType.CONCEPT, events, desired_retention=0.82)
        assert replayed.model_dump() == live.model_dump()

    def test_replay_from_legacy_starting_state_is_non_mutating(self, scheduler):
        baseline = RepetitionState(
            interval_index=2, next_review_at=1_700_000_000.0, desired_retention=0.85
        )
        event = _evidence(quality=1.0, ts=1_700_000_000.0 + 86400)
        live = baseline.model_copy(deep=True)
        scheduler.schedule_review(live, KnowledgeType.MEMORY, event)
        replayed = scheduler.replay(KnowledgeType.MEMORY, [event], initial_state=baseline)
        assert replayed.model_dump() == live.model_dump()
        assert baseline.stability == 0.0
        assert scheduler.replay(KnowledgeType.MEMORY, [], initial_state=baseline) == baseline

    def test_changing_retention_rescales_existing_due_without_new_review(self, scheduler):
        start = 1_700_000_000.0
        progress = LearningProgress(book_id="b1")
        progress.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        state = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=start)
        scheduler.schedule_review(state, KnowledgeType.CONCEPT, _evidence(quality=1.0, ts=start))
        progress.repetition_states["kp1"] = state
        old_due = state.next_review_at
        review_count = state.review_count
        scheduler.set_desired_retention(progress, 0.97, now=start)
        high_target_due = state.next_review_at
        assert high_target_due < old_due
        scheduler.set_desired_retention(progress, 0.7, now=start)
        assert state.next_review_at > old_due
        assert state.review_count == review_count
        assert progress.desired_retention == state.desired_retention == 0.7
        assert progress.review_queue[0].due_at == state.next_review_at

    def test_replay_matches_live_after_retention_change(self, scheduler):
        start = 1_700_000_000.0
        events = [
            _evidence(quality=1.0, ts=start),
            _evidence(quality=1.0, ts=start + 7 * 86400),
        ]
        progress = LearningProgress(book_id="changed-target")
        progress.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        live = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=start)
        for event in events:
            scheduler.schedule_review(live, KnowledgeType.CONCEPT, event)
        progress.repetition_states["kp1"] = live
        stability_before = live.stability

        scheduler.set_desired_retention(progress, 0.97, now=events[-1].timestamp)
        replayed = scheduler.replay(KnowledgeType.CONCEPT, events, desired_retention=0.97)

        assert live.stability == stability_before
        assert replayed.model_dump() == live.model_dump()

    def test_late_evidence_after_target_change_replays_in_append_order(self, scheduler):
        start = 1_700_000_000.0
        events = [
            _evidence(quality=1.0, ts=start),
            _evidence(quality=0.0, result="incorrect", ts=start + 7 * 86400),
        ]
        progress = LearningProgress(book_id="late-evidence")
        progress.knowledge_types["kp1"] = KnowledgeType.CONCEPT
        live = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=start)
        for event in events:
            scheduler.schedule_review(live, KnowledgeType.CONCEPT, event)
        progress.repetition_states["kp1"] = live
        scheduler.set_desired_retention(progress, 0.97, now=events[-1].timestamp)
        due_after_failure = live.next_review_at

        late = _evidence(quality=1.0, ts=start + 86400)
        events.append(late)
        scheduler.schedule_review(live, KnowledgeType.CONCEPT, late)
        assert live.last_review_at == start + 7 * 86400
        assert live.next_review_at == due_after_failure
        replayed = scheduler.replay(KnowledgeType.CONCEPT, events, desired_retention=0.97)
        assert replayed.model_dump() == live.model_dump()

    @pytest.mark.parametrize("invalid", [0.5, 1.0, float("nan"), float("inf")])
    def test_invalid_retention_is_rejected(self, scheduler, invalid):
        with pytest.raises(ValueError):
            scheduler.get_initial_state(KnowledgeType.MEMORY, desired_retention=invalid)

    def test_replay_matches_stepwise_updates(self, scheduler):
        now = 1_700_000_000.0
        events = [
            _evidence(quality=1.0, ts=now),
            _evidence(quality=0.0, result="incorrect", ts=now + 86400),
            _evidence(quality=1.0, ts=now + 2 * 86400),
        ]
        replayed = scheduler.replay(KnowledgeType.CONCEPT, events)
        stepwise = scheduler.get_initial_state(KnowledgeType.CONCEPT, now=events[0].timestamp)
        for event in events:
            scheduler.schedule_review(stepwise, KnowledgeType.CONCEPT, event, now=event.timestamp)
        assert replayed.stability == pytest.approx(stepwise.stability)
        assert replayed.next_review_at == pytest.approx(stepwise.next_review_at)
        assert replayed.lapse_count == stepwise.lapse_count == 1
        assert replayed.review_count == 3

    def test_hydrates_legacy_interval_index_without_changing_due(self, scheduler):
        due = 1_700_000_000.0 + 3 * 86400
        state = RepetitionState(interval_index=2, consecutive_correct=1, next_review_at=due)
        assert state.stability == 0.0
        scheduler.hydrate(state, KnowledgeType.MEMORY)
        assert state.stability == pytest.approx(
            INTERVAL_SEQUENCES[KnowledgeType.MEMORY][2] / -math.log(0.9)
        )
        assert state.next_review_at == due
        assert state.difficulty > 0

    def test_queue_orders_by_forgetting_risk_then_overdue(self, scheduler):
        now = time.time()
        lp = LearningProgress(book_id="b1")
        lp.knowledge_types["kp_risk"] = KnowledgeType.MEMORY
        lp.knowledge_types["kp_safe"] = KnowledgeType.MEMORY
        risky = scheduler.get_initial_state(KnowledgeType.MEMORY, now=now - 10 * 86400)
        risky.last_review_at = now - 10 * 86400
        risky.next_review_at = now - 5 * 86400
        risky.stability = 2.0
        risky.lapse_count = 2
        safe = scheduler.get_initial_state(KnowledgeType.MEMORY, now=now)
        safe.last_review_at = now
        safe.next_review_at = now - 10
        safe.stability = 30.0
        lp.repetition_states["kp_risk"] = risky
        lp.repetition_states["kp_safe"] = safe
        tasks = scheduler.build_review_queue(lp, now=now)
        assert [task.knowledge_point_id for task in tasks] == ["kp_risk", "kp_safe"]
        assert tasks[0].forgetting_risk > tasks[1].forgetting_risk
        assert "retrievability" in tasks[0].reason
