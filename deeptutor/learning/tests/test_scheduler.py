import time

import pytest

from deeptutor.learning.models import (
    ErrorRecord,
    ErrorType,
    KnowledgeStateProjection,
    KnowledgeType,
    LearningProgress,
    MasteryState,
    RepetitionState,
    ReviewState,
    ReviewTask,
)
from deeptutor.learning.scheduler import (
    FAILED_REVIEW_RETRY_DELAY_DAYS,
    INTERVAL_SEQUENCES,
    PROVISIONAL_RETEACH_DELAY_DAYS,
    STABLE_MAINTENANCE_DELAY_DAYS,
    SpacedRepetitionScheduler,
)
from deeptutor.learning.tests.feynman_builders import START


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
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)
        assert state.interval_index == 1
        assert state.consecutive_correct == 1
        assert state.consecutive_wrong == 0

    def test_two_consecutive_skip(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=1, cc=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=3, cc=0
        assert state.interval_index == 3
        assert state.consecutive_correct == 0


# ── schedule_next: wrong retreats ────────────────────────────────────────


class TestWrongRetreats:
    def test_wrong_decrements(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)  # idx=0
        assert state.interval_index == 0
        assert state.consecutive_wrong == 1
        assert state.consecutive_correct == 0

    def test_two_consecutive_wrong_resets(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, True)  # idx=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)  # idx=0, cw=1
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)  # idx=0, cw resets
        assert state.consecutive_wrong == 0


# ── schedule_next: boundaries ────────────────────────────────────────────


class TestBoundaries:
    def test_cant_go_below_zero(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state = scheduler.schedule_next(state, KnowledgeType.MEMORY, False)
        assert state.interval_index == 0

    def test_cant_exceed_sequence(self, scheduler):
        state = scheduler.get_initial_state(KnowledgeType.MEMORY)
        state.interval_index = 6  # max for MEMORY
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


# ── deterministic time injection (LRN-02 requirement 7) ─────────────────────


class TestDeterministicClock:
    def test_constructor_now_removes_wall_clock_dependence(self):
        a = SpacedRepetitionScheduler(now=123456.0)
        b = SpacedRepetitionScheduler(now=123456.0)
        assert a.get_initial_state(KnowledgeType.MEMORY) == b.get_initial_state(
            KnowledgeType.MEMORY
        )
        assert a.get_initial_state(KnowledgeType.MEMORY).next_review_at == 123456.0

    def test_explicit_now_overrides_constructor_clock(self):
        scheduler = SpacedRepetitionScheduler(now=100.0)
        state = scheduler.schedule_provisional_reteach(KnowledgeType.MEMORY, now=200.0)
        assert state.next_review_at == 200.0 + 86400.0


# ── Feynman scheduling (test-out / delayed-reteach, §6.1/§6.5) ─────────────


class TestFeynmanScheduling:
    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_provisional_reteach_delay_is_type_specific(self, kp_type):
        scheduler = SpacedRepetitionScheduler(now=START)
        state = scheduler.schedule_provisional_reteach(kp_type)
        days = PROVISIONAL_RETEACH_DELAY_DAYS[kp_type]
        assert state.next_review_at == START + days * 86400.0

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_stable_maintenance_delay_is_type_specific(self, kp_type):
        scheduler = SpacedRepetitionScheduler(now=START)
        state = scheduler.schedule_stable_maintenance(kp_type)
        days = STABLE_MAINTENANCE_DELAY_DAYS[kp_type]
        assert state.next_review_at == START + days * 86400.0

    @pytest.mark.parametrize("kp_type", list(KnowledgeType))
    def test_failed_review_retry_delay_is_type_specific(self, kp_type):
        scheduler = SpacedRepetitionScheduler(now=START)
        state = scheduler.schedule_failed_review(kp_type)
        days = FAILED_REVIEW_RETRY_DELAY_DAYS[kp_type]
        assert state.next_review_at == START + days * 86400.0

    def test_test_out_uses_provisional_reteach_scheduling(self):
        """A test-out pass schedules the same delayed reteach as an initial
        pass — never a direct jump to stable."""
        scheduler = SpacedRepetitionScheduler(now=START)
        test_out = scheduler.schedule_provisional_reteach(KnowledgeType.DESIGN)
        initial = scheduler.schedule_provisional_reteach(KnowledgeType.DESIGN)
        assert test_out.next_review_at == initial.next_review_at
        assert test_out.next_review_at > START

    def test_feynman_review_queue_built_from_projections(self):
        scheduler = SpacedRepetitionScheduler(now=START)
        lp = LearningProgress(book_id="b1")
        lp.knowledge_types["kp-mem"] = KnowledgeType.MEMORY
        lp.knowledge_types["kp-con"] = KnowledgeType.CONCEPT
        lp.projections["kp-mem"] = KnowledgeStateProjection(
            knowledge_point_id="kp-mem",
            mastery_state=MasteryState.NEEDS_REVISION,
            review_state=ReviewState.SCHEDULED,
            next_review_at=START + 86400.0,
        )
        lp.projections["kp-con"] = KnowledgeStateProjection(
            knowledge_point_id="kp-con",
            mastery_state=MasteryState.PROVISIONAL_MASTERY,
            review_state=ReviewState.SCHEDULED,
            next_review_at=START + 3 * 86400.0,
        )
        tasks = scheduler.build_feynman_review_queue(lp)
        assert [t.knowledge_point_id for t in tasks] == ["kp-mem", "kp-con"]
        # needs_revision gets the highest priority regardless of type.
        assert tasks[0].priority == 1
        assert tasks[0].due_at == START + 86400.0
        assert tasks[1].knowledge_type == KnowledgeType.CONCEPT
        assert tasks[1].priority == 3

    def test_feynman_review_queue_skips_unscheduled(self):
        scheduler = SpacedRepetitionScheduler(now=START)
        lp = LearningProgress(book_id="b1")
        lp.projections["kp1"] = KnowledgeStateProjection(
            knowledge_point_id="kp1",
            mastery_state=MasteryState.NEW,
            review_state=ReviewState.UNSCHEDULED,
            next_review_at=None,
        )
        assert scheduler.build_feynman_review_queue(lp) == []
