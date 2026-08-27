from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING
import uuid

from deeptutor.learning.grading import classify_error, grade_answer
from deeptutor.learning.mastery import compute_mastery
from deeptutor.learning.models import (
    ErrorRecord,
    InteractionStatus,
    LearningModule,
    LearningProgress,
    LearningStage,
    MasteryInteraction,
    PendingQuestion,
    QuizAttempt,
    RetryAttempt,
)
from deeptutor.learning.storage import LearningStore

if TYPE_CHECKING:
    from deeptutor.learning.scheduler import SpacedRepetitionScheduler


# Long enough for a course title, short enough that a list row stays a row.
# Matches the cap module and objective names already use.
_MAX_PATH_NAME_LEN = 200


class MasteryInteractionError(RuntimeError):
    """Base error for invalid durable question lifecycle transitions."""


class NoPendingInteractionError(MasteryInteractionError):
    """Raised when grading or resuming without an outstanding question."""


class StaleInteractionError(MasteryInteractionError):
    """Raised when a caller submits an answer for a superseded question."""

    def __init__(self, submitted_id: str, current_id: str) -> None:
        self.submitted_id = submitted_id
        self.current_id = current_id
        super().__init__(
            f"Question {submitted_id!r} is no longer pending; answer {current_id!r} instead"
        )


class LearningService:
    def __init__(self, store: LearningStore | None = None) -> None:
        self._store = store or LearningStore()

    @property
    def store(self) -> LearningStore:
        """Expose the persistence boundary for read-only interaction queries."""
        return self._store

    def get_or_create(self, book_id: str) -> LearningProgress:
        # The store serializes creation under BEGIN IMMEDIATE, so two callers
        # cannot both manufacture revision 1 and race to overwrite one another.
        with self._store.transaction(book_id, create=True) as tx:
            return tx.progress

    def init_modules(self, progress: LearningProgress, modules: list[LearningModule]) -> None:
        """Initialize the runnable module set (replace semantics)."""
        self.replace_modules(progress, modules)

    def replace_modules(self, progress: LearningProgress, modules: list[LearningModule]) -> None:
        """Replace all modules and clean stale KP state."""
        new_kp_ids = {kp.id for m in modules for kp in m.knowledge_points}

        # Clean stale KP state
        for key in list(progress.mastery_levels.keys()):
            if key not in new_kp_ids:
                del progress.mastery_levels[key]
        for key in list(progress.knowledge_types.keys()):
            if key not in new_kp_ids:
                del progress.knowledge_types[key]
        for key in list(progress.qualitative_mastery.keys()):
            if key not in new_kp_ids:
                del progress.qualitative_mastery[key]
        for key in list(progress.repetition_states.keys()):
            if key not in new_kp_ids:
                del progress.repetition_states[key]
        progress.error_records = [
            r for r in progress.error_records if r.knowledge_point_id in new_kp_ids
        ]
        progress.quiz_attempts = [
            attempt
            for attempt in progress.quiz_attempts
            if attempt.knowledge_point_id in new_kp_ids
        ]
        progress.feynman_retries = {
            k: v for k, v in progress.feynman_retries.items() if k in new_kp_ids
        }
        progress.feynman_explanations = {
            k: v for k, v in progress.feynman_explanations.items() if k in new_kp_ids
        }
        progress.review_queue = [
            t for t in progress.review_queue if t.knowledge_point_id in new_kp_ids
        ]
        # Clear global stage failure records — different modules should not share failure counts
        progress.stage_failure_counts = {}
        progress.stage_failure_notes = {}

        # Set new modules
        progress.modules = list(modules)
        for mod in modules:
            for kp in mod.knowledge_points:
                progress.knowledge_types[kp.id] = kp.type

    def advance_stage(self, progress: LearningProgress, next_stage: LearningStage) -> None:
        progress.current_stage = next_stage
        progress.updated_at = time.time()

    def switch_module(self, progress: LearningProgress, module_id: str) -> bool:
        """Point the session at ``module_id`` and reset it to that module's
        first teaching stage (EXPLAIN). Mutates ``progress`` in place and returns
        whether the module exists. The caller is responsible for persisting
        (``save``) — typically *after* cancelling any in-flight turn so the
        turn's teardown cannot overwrite the switch with stale progress.
        """
        found = any(m.id == module_id for m in progress.modules)
        if found:
            progress.current_module_id = module_id
            progress.current_kp_index = 0
            progress.current_stage = LearningStage.EXPLAIN
            progress.updated_at = time.time()
        return found

    def record_quiz_attempt(self, progress: LearningProgress, attempt: QuizAttempt) -> None:
        if not attempt.is_correct and attempt.error_type is not None:
            # Find existing error record for this question + knowledge point.
            existing = None
            for rec in progress.error_records:
                if (
                    rec.question_id == attempt.question_id
                    and rec.knowledge_point_id == attempt.knowledge_point_id
                ):
                    existing = rec
                    break

            if existing is not None:
                existing.retry_history.append(
                    RetryAttempt(
                        timestamp=time.time(),
                        is_correct=False,
                        attempt_number=len(existing.retry_history) + 1,
                    )
                )
                existing.status = "retrying"
            else:
                record = ErrorRecord(
                    id=uuid.uuid4().hex,
                    question_id=attempt.question_id,
                    knowledge_point_id=attempt.knowledge_point_id,
                    module_id=attempt.module_id,
                    error_type=attempt.error_type,
                    self_attribution=attempt.self_attribution,
                    status="active",
                )
                progress.error_records.append(record)

        elif attempt.is_correct:
            # Graduate any active error record for this question + knowledge point.
            for rec in progress.error_records:
                if (
                    rec.question_id == attempt.question_id
                    and rec.knowledge_point_id == attempt.knowledge_point_id
                    and rec.status in ("active", "retrying")
                ):
                    rec.retry_history.append(
                        RetryAttempt(
                            timestamp=time.time(),
                            is_correct=True,
                            attempt_number=len(rec.retry_history) + 1,
                        )
                    )
                    rec.status = "graduated"
                    break

        progress.quiz_attempts.append(attempt)
        progress.updated_at = time.time()

    def calculate_mastery(self, progress: LearningProgress, kp_id: str) -> float:
        """Mastery 0..1 for *kp_id* from its attempt history (policy in mastery.py)."""
        correctness = [
            a.is_correct for a in progress.quiz_attempts if a.knowledge_point_id == kp_id
        ]
        return compute_mastery(correctness)

    def update_mastery(self, progress: LearningProgress, kp_id: str, level: float) -> None:
        progress.mastery_levels[kp_id] = level
        progress.updated_at = time.time()

    def grade_and_record(
        self,
        progress: LearningProgress,
        *,
        question_id: str,
        knowledge_point_id: str,
        module_id: str,
        user_answer: str,
        expected_answer: str,
        question_type: str = "short",
        self_attribution: str = "",
        scheduler: SpacedRepetitionScheduler | None = None,
    ) -> bool:
        """Grade one answer and fold it through the full post-answer pipeline.

        record attempt -> recompute mastery -> advance the spaced-repetition
        state -> rebuild the review queue -> persist. This is the single source
        of truth for what happens when a student answers, shared by every
        interactive stage. Grading is fail-closed: with no stored expected
        answer the attempt is recorded wrong, never right.
        """
        is_correct = self._apply_grade(
            progress,
            question_id=question_id,
            knowledge_point_id=knowledge_point_id,
            module_id=module_id,
            user_answer=user_answer,
            expected_answer=expected_answer,
            question_type=question_type,
            self_attribution=self_attribution,
            scheduler=scheduler,
        )
        self.save(progress)
        return is_correct

    def _apply_grade(
        self,
        progress: LearningProgress,
        *,
        question_id: str,
        knowledge_point_id: str,
        module_id: str,
        user_answer: str,
        expected_answer: str,
        question_type: str,
        self_attribution: str = "",
        scheduler: SpacedRepetitionScheduler | None = None,
    ) -> bool:
        """Mutate one aggregate with a grade without performing I/O."""
        is_correct = bool(expected_answer) and grade_answer(
            user_answer, expected_answer, question_type
        )
        self.record_quiz_attempt(
            progress,
            QuizAttempt(
                question_id=question_id,
                knowledge_point_id=knowledge_point_id,
                module_id=module_id,
                is_correct=is_correct,
                user_answer=user_answer,
                self_attribution=self_attribution,
                error_type=None if is_correct else classify_error(user_answer),
            ),
        )
        if knowledge_point_id:
            self.update_mastery(
                progress, knowledge_point_id, self.calculate_mastery(progress, knowledge_point_id)
            )
            kp_type = progress.knowledge_types.get(knowledge_point_id)
            if kp_type is not None and scheduler is not None:
                state = progress.repetition_states.get(
                    knowledge_point_id
                ) or scheduler.get_initial_state(kp_type)
                progress.repetition_states[knowledge_point_id] = state
                scheduler.schedule_next(state, kp_type, is_correct)
                progress.review_queue = scheduler.build_review_queue(progress)
        return is_correct

    # ── Loop-driven tutoring helpers ─────────────────────────────────────

    def set_pending_question(self, progress: LearningProgress, pending: PendingQuestion) -> None:
        """Store the question the tutor just posed so its expected answer can
        be graded deterministically on a later turn (never via the model)."""
        progress.pending_question = pending
        progress.updated_at = time.time()
        self.save(progress)

    def clear_pending_question(self, progress: LearningProgress) -> None:
        progress.pending_question = None
        progress.updated_at = time.time()
        self.save(progress)

    @staticmethod
    def _interaction_from_legacy_pending(
        progress: LearningProgress,
        *,
        session_id: str = "",
        turn_id: str = "",
    ) -> MasteryInteraction | None:
        pending = progress.pending_question
        if pending is None:
            return None
        return MasteryInteraction(
            interaction_id=pending.question_id,
            path_id=progress.book_id,
            question=pending,
            status=InteractionStatus.REGISTERED,
            session_id=session_id,
            turn_id=turn_id,
        )

    def register_question(
        self,
        book_id: str,
        pending: PendingQuestion,
        *,
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[LearningProgress, MasteryInteraction, bool]:
        """Atomically register one outstanding question.

        Retrying ``mastery_quiz`` while a question is active returns the
        existing interaction instead of overwriting its expected answer.
        """

        def register(tx):
            active = tx.active_interaction()
            if active is None:
                active = self._interaction_from_legacy_pending(
                    tx.progress, session_id=session_id, turn_id=turn_id
                )
                if active is not None:
                    persisted = tx.get_interaction(active.interaction_id)
                    if persisted is not None and persisted.status in {
                        InteractionStatus.GRADED,
                        InteractionStatus.ABANDONED,
                    }:
                        # Repair a legacy aggregate whose compatibility field
                        # survived after the durable interaction completed.
                        tx.progress.pending_question = None
                        tx.touch()
                        active = None
                    elif persisted is not None:
                        active = persisted
                    else:
                        tx.put_interaction(active)
            if active is not None:
                return active, False

            known_kp = next(
                (
                    kp
                    for module in tx.progress.modules
                    for kp in module.knowledge_points
                    if kp.id == pending.knowledge_point_id
                ),
                None,
            )
            if known_kp is None:
                raise MasteryInteractionError(
                    f"Unknown objective {pending.knowledge_point_id!r}; refresh mastery_status"
                )

            interaction = MasteryInteraction(
                interaction_id=pending.question_id,
                path_id=book_id,
                question=pending,
                status=InteractionStatus.REGISTERED,
                session_id=session_id,
                turn_id=turn_id,
            )
            tx.progress.pending_question = pending
            tx.put_interaction(interaction)
            from deeptutor.learning.pending import public_pending_question

            tx.emit(
                "interaction.registered",
                {
                    "interaction_id": interaction.interaction_id,
                    "knowledge_point_id": pending.knowledge_point_id,
                    "question": public_pending_question(pending).to_dict(),
                },
                session_id=session_id,
                turn_id=turn_id,
            )
            return interaction, True

        progress, result = self._store.mutate(book_id, register)
        interaction, created = result
        return progress, interaction, created

    def mark_question_awaiting(
        self,
        book_id: str,
        *,
        interaction_id: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> MasteryInteraction | None:
        """Persist that an interaction card has been presented to the learner."""

        def mark(tx):
            interaction = (
                tx.get_interaction(interaction_id) if interaction_id else tx.active_interaction()
            )
            if interaction is None:
                active = tx.active_interaction()
                if active is not None and interaction_id:
                    raise StaleInteractionError(interaction_id, active.interaction_id)
                interaction = self._interaction_from_legacy_pending(
                    tx.progress, session_id=session_id, turn_id=turn_id
                )
                if interaction is None:
                    return None
                if interaction_id and interaction.interaction_id != interaction_id:
                    raise StaleInteractionError(interaction_id, interaction.interaction_id)
            if interaction.status == InteractionStatus.REGISTERED:
                interaction.status = InteractionStatus.AWAITING_INPUT
                interaction.session_id = session_id or interaction.session_id
                interaction.turn_id = turn_id or interaction.turn_id
                tx.put_interaction(interaction)
                tx.emit(
                    "interaction.awaiting_input",
                    {"interaction_id": interaction.interaction_id},
                    session_id=interaction.session_id,
                    turn_id=interaction.turn_id,
                )
            return interaction

        _, interaction = self._store.mutate(book_id, mark)
        return interaction

    def record_question_answer(
        self,
        book_id: str,
        answer: str,
        *,
        interaction_id: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> MasteryInteraction | None:
        """Durably record a reply before the LLM gets another reasoning round."""

        def record(tx):
            interaction = (
                tx.get_interaction(interaction_id) if interaction_id else tx.active_interaction()
            )
            if interaction is None:
                active = tx.active_interaction()
                if active is not None and interaction_id:
                    raise StaleInteractionError(interaction_id, active.interaction_id)
                interaction = self._interaction_from_legacy_pending(
                    tx.progress, session_id=session_id, turn_id=turn_id
                )
            if interaction is None:
                return None
            if interaction_id and interaction.interaction_id != interaction_id:
                raise StaleInteractionError(interaction_id, interaction.interaction_id)
            if interaction.status in {
                InteractionStatus.REGISTERED,
                InteractionStatus.AWAITING_INPUT,
            }:
                interaction.status = InteractionStatus.ANSWERED
                interaction.user_answer = str(answer or "")
                interaction.session_id = session_id or interaction.session_id
                interaction.turn_id = turn_id or interaction.turn_id
                tx.put_interaction(interaction)
                tx.emit(
                    "interaction.answered",
                    {"interaction_id": interaction.interaction_id},
                    session_id=interaction.session_id,
                    turn_id=interaction.turn_id,
                )
            elif (
                interaction.status == InteractionStatus.ANSWERED
                and interaction.question.question_type == "choice"
            ):
                # Recover from a prior unreadable composer commit (#1004): allow
                # a later readable pick to replace the stalled user_answer.
                from deeptutor.learning.pending import is_readable_choice_answer

                stored = str(interaction.user_answer or "")
                incoming = str(answer or "")
                if not is_readable_choice_answer(
                    stored, interaction.question.options
                ) and is_readable_choice_answer(incoming, interaction.question.options):
                    interaction.user_answer = incoming
                    interaction.session_id = session_id or interaction.session_id
                    interaction.turn_id = turn_id or interaction.turn_id
                    tx.put_interaction(interaction)
                    tx.emit(
                        "interaction.answered",
                        {"interaction_id": interaction.interaction_id},
                        session_id=interaction.session_id,
                        turn_id=interaction.turn_id,
                    )
            return interaction

        _, interaction = self._store.mutate(book_id, record)
        return interaction

    def grade_interaction(
        self,
        book_id: str,
        *,
        answer: str,
        question_id: str = "",
        answer_for_grading: str | None = None,
        expected_answer: str | None = None,
        resolved_choice_options: dict[str, str] | None = None,
        scheduler: SpacedRepetitionScheduler | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[LearningProgress, MasteryInteraction, bool]:
        """Grade and resolve an interaction in one idempotent transaction.

        Returns ``(progress, interaction, replayed)``.  A retry carrying the
        same ``question_id`` returns the stored result and never appends a
        second attempt.
        """

        def grade(tx):
            interaction = tx.get_interaction(question_id) if question_id else None
            if interaction is None and not question_id:
                interaction = tx.active_interaction()
            if interaction is None:
                legacy = self._interaction_from_legacy_pending(
                    tx.progress, session_id=session_id, turn_id=turn_id
                )
                if legacy is not None and (not question_id or legacy.interaction_id == question_id):
                    interaction = legacy
                    tx.put_interaction(interaction)
            if interaction is None:
                active = tx.active_interaction()
                if active is not None and question_id:
                    raise StaleInteractionError(question_id, active.interaction_id)
                raise NoPendingInteractionError("No question is awaiting an answer")
            if question_id and interaction.interaction_id != question_id:
                raise StaleInteractionError(question_id, interaction.interaction_id)
            if interaction.status == InteractionStatus.GRADED:
                return interaction, True
            if interaction.status == InteractionStatus.ABANDONED:
                raise NoPendingInteractionError("The question was abandoned")

            pending = interaction.question
            raw_answer = str(answer or "")
            if interaction.status == InteractionStatus.ANSWERED:
                stored = str(interaction.user_answer or "")
                if pending.question_type == "choice":
                    from deeptutor.learning.pending import (
                        has_option_bodies,
                        is_readable_choice_answer,
                        parse_options,
                        resolve_choice_submission,
                    )

                    option_map = parse_options(pending.options)
                    if is_readable_choice_answer(stored, option_map):
                        raw_answer = stored
                    elif is_readable_choice_answer(raw_answer, option_map):
                        # Prior commit was unreadable clarifying text (#1004) —
                        # accept the fresh readable answer and rewrite storage.
                        interaction.user_answer = raw_answer
                    else:
                        raw_answer = stored
                    if has_option_bodies(option_map):
                        graded_answer = (
                            resolve_choice_submission(raw_answer, option_map) or raw_answer
                        )
                    else:
                        # Legacy questions may need option bodies recovered by
                        # the trusted tool adapter from the original turn.
                        graded_answer = (
                            raw_answer if answer_for_grading is None else answer_for_grading
                        )
                else:
                    raw_answer = stored
                    graded_answer = raw_answer
            else:
                graded_answer = raw_answer if answer_for_grading is None else answer_for_grading
            authoritative_answer = (
                pending.expected_answer if expected_answer is None else expected_answer
            )
            if pending.question_type == "choice" and resolved_choice_options:
                from deeptutor.learning.pending import format_options

                pending.options = format_options(resolved_choice_options)
                pending.expected_answer = authoritative_answer
                interaction.question = pending
            is_correct = self._apply_grade(
                tx.progress,
                question_id=pending.question_id,
                knowledge_point_id=pending.knowledge_point_id,
                module_id=pending.module_id,
                user_answer=graded_answer,
                expected_answer=authoritative_answer,
                question_type=pending.question_type,
                scheduler=scheduler,
            )
            if (
                tx.progress.pending_question is not None
                and tx.progress.pending_question.question_id == pending.question_id
            ):
                tx.progress.pending_question = None
            interaction.status = InteractionStatus.GRADED
            interaction.user_answer = raw_answer
            interaction.session_id = session_id or interaction.session_id
            interaction.turn_id = turn_id or interaction.turn_id
            interaction.result = {
                "is_correct": is_correct,
                "knowledge_point_id": pending.knowledge_point_id,
            }
            tx.put_interaction(interaction)
            tx.emit(
                "attempt.recorded",
                {
                    "interaction_id": interaction.interaction_id,
                    "knowledge_point_id": pending.knowledge_point_id,
                    "is_correct": is_correct,
                },
                session_id=interaction.session_id,
                turn_id=interaction.turn_id,
            )
            tx.emit(
                "interaction.graded",
                dict(interaction.result),
                session_id=interaction.session_id,
                turn_id=interaction.turn_id,
            )
            return interaction, False

        progress, result = self._store.mutate(book_id, grade)
        interaction, replayed = result
        return progress, interaction, replayed

    def replace_modules_for_path(
        self,
        book_id: str,
        modules: list[LearningModule],
        *,
        append: bool = False,
        name: str = "",
        event_type: str = "path.modules_replaced",
        session_id: str = "",
        turn_id: str = "",
    ) -> LearningProgress:
        """Install a module set, optionally naming a path that has no name yet.

        ``name`` is applied only when the path is still unnamed, in the same
        transaction as the modules so a built path is never briefly nameless.
        Replacing the map deliberately does NOT rename: the map is what the
        path teaches, the name is which path it is — deriving one from the
        other is what made a rebuild look like a different course.
        """

        def replace(tx):
            if name.strip() and not tx.progress.name.strip():
                tx.progress.name = name.strip()[:_MAX_PATH_NAME_LEN]
            applied_modules = [module.model_copy(deep=True) for module in modules]
            if append:
                offset = len(tx.progress.modules)
                for index, module in enumerate(applied_modules, start=offset):
                    module.id = f"{book_id}_m{index}"
                    module.order = index
                    for kp_index, kp in enumerate(module.knowledge_points):
                        kp.module_id = module.id
                        kp.id = f"{module.id}_kp{kp_index}"
                        tx.progress.knowledge_types[kp.id] = kp.type
                tx.progress.modules.extend(applied_modules)
                if not tx.progress.current_module_id and applied_modules:
                    tx.progress.current_module_id = applied_modules[0].id
                    tx.progress.current_kp_index = 0
            else:
                self.replace_modules(tx.progress, applied_modules)
                tx.progress.pending_question = None
                tx.abandon_active_interactions()
                if applied_modules:
                    tx.progress.current_module_id = applied_modules[0].id
                    tx.progress.current_kp_index = 0
            tx.touch()
            tx.emit(
                event_type,
                {
                    "mode": "append" if append else "replace",
                    "module_count": len(applied_modules),
                    "knowledge_point_count": sum(
                        len(module.knowledge_points) for module in applied_modules
                    ),
                },
                session_id=session_id,
                turn_id=turn_id,
            )

        progress, _ = self._store.mutate(book_id, replace, create=True)
        return progress

    def rename_path(self, book_id: str, name: str) -> LearningProgress:
        """Set (or clear) the learner-facing name of a path.

        Clearing it is meaningful, not a no-op: an empty name hands the path
        back to the derived display name, which is the only way to undo a
        rename without inventing a second "auto" flag.
        """
        cleaned = str(name or "").strip()[:_MAX_PATH_NAME_LEN]

        def rename(tx):
            if tx.progress.name == cleaned:
                return cleaned
            tx.progress.name = cleaned
            tx.touch()
            tx.emit("path.renamed", {"name": cleaned})
            return cleaned

        progress, _ = self._store.mutate(book_id, rename)
        return progress

    def abandon_active_question(self, book_id: str) -> tuple[LearningProgress, bool]:
        """Drop the outstanding question so the path can move on.

        A posed question outranks everything in ``policy.next_objective`` and
        blocks ``register_question`` from posing another, which is what keeps
        the gate honest — but it also means a question the learner can no
        longer answer (its conversation is gone, the card was never shown)
        would stall the path with no way out short of resetting all progress.
        Abandoning is deliberately explicit rather than automatic: an
        unanswered question is normally resumable across turns, so only the
        learner can say this one is not.

        Returns the progress and whether anything was outstanding.
        """

        def abandon(tx):
            interaction = tx.active_interaction()
            abandoned = tx.abandon_active_interactions() > 0
            if tx.progress.pending_question is not None:
                tx.progress.pending_question = None
                abandoned = True
            if not abandoned:
                return False
            tx.touch()
            tx.emit(
                "interaction.abandoned",
                {"interaction_id": interaction.interaction_id if interaction else ""},
            )
            return True

        return self._store.mutate(book_id, abandon)

    def reset_path(self, book_id: str) -> LearningProgress:
        def reset(tx):
            progress = tx.progress
            progress.current_stage = LearningStage.DIAGNOSTIC
            progress.mastery_levels = {}
            progress.qualitative_mastery = {}
            progress.quiz_attempts = []
            progress.error_records = []
            progress.repetition_states = {}
            progress.review_queue = []
            progress.pending_question = None
            progress.feynman_retries = {}
            progress.feynman_explanations = {}
            progress.stage_failure_counts = {}
            progress.stage_failure_notes = {}
            progress.diagnostic = None
            progress.current_kp_index = 0
            progress.current_module_id = progress.modules[0].id if progress.modules else ""
            tx.abandon_active_interactions()
            tx.touch()
            tx.emit("path.reset", {})

        progress, _ = self._store.mutate(book_id, reset)
        return progress

    def record_qualitative(
        self,
        progress: LearningProgress,
        kp_id: str,
        *,
        passed: bool,
        evidence: str = "",
        scheduler: SpacedRepetitionScheduler | None = None,
    ) -> None:
        """Record the qualitative (CONCEPT / DESIGN) gate outcome.

        The boolean is the gate of record; ``mastery_levels`` is nudged only so
        the map's colour matches the gate (full on pass, capped on fail).

        A first pass starts spaced repetition at the type's first configured
        interval. Later assessments advance or shorten that existing schedule.
        An initial failure is not reviewable mastery, so it creates no state.
        """
        self.record_qualitative_in_memory(
            progress,
            kp_id,
            passed=passed,
            evidence=evidence,
            scheduler=scheduler,
        )
        self.save(progress)

    def record_qualitative_for_path(
        self,
        book_id: str,
        kp_id: str,
        *,
        passed: bool,
        evidence: str = "",
        scheduler: SpacedRepetitionScheduler | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> LearningProgress:
        def record(tx):
            from deeptutor.learning.policy import QUALITATIVE_TYPES, find_knowledge_point

            kp, _, _ = find_knowledge_point(tx.progress, kp_id)
            if kp is None:
                raise MasteryInteractionError(
                    f"Unknown objective {kp_id!r}; refresh mastery_status"
                )
            if kp.type not in QUALITATIVE_TYPES:
                raise MasteryInteractionError(
                    f"Objective {kp.name!r} must be graded with mastery_quiz + mastery_grade"
                )
            self.record_qualitative_in_memory(
                tx.progress,
                kp_id,
                passed=passed,
                evidence=evidence,
                scheduler=scheduler,
            )
            tx.touch()
            tx.emit(
                "mastery.assessed",
                {
                    "knowledge_point_id": kp_id,
                    "passed": bool(passed),
                },
                session_id=session_id,
                turn_id=turn_id,
            )

        progress, _ = self._store.mutate(book_id, record)
        return progress

    @staticmethod
    def record_qualitative_in_memory(
        progress: LearningProgress,
        kp_id: str,
        *,
        passed: bool,
        evidence: str = "",
        scheduler: SpacedRepetitionScheduler | None = None,
    ) -> None:
        progress.qualitative_mastery[kp_id] = bool(passed)
        current = progress.mastery_levels.get(kp_id, 0.0)
        progress.mastery_levels[kp_id] = max(current, 1.0) if passed else min(current, 0.4)
        if evidence:
            progress.feynman_explanations[kp_id] = evidence
        kp_type = progress.knowledge_types.get(kp_id)
        if kp_type is not None and scheduler is not None:
            state = progress.repetition_states.get(kp_id)
            if state is not None and state.next_review_at <= time.time():
                scheduler.schedule_next(state, kp_type, passed)
            elif state is None and passed:
                progress.repetition_states[kp_id] = scheduler.get_initial_state(kp_type)
            progress.review_queue = scheduler.build_review_queue(progress)
        progress.updated_at = time.time()

    def list_path_overviews(self) -> list[dict]:
        """Gate-accurate one-line state for every path the learner owns.

        ``list_progress`` reports an *average* mastery percentage, which is the
        right number for a progress bar and the wrong one for deciding what is
        finished: mastery is a per-objective gate, so "3 of 4 cleared" is the
        fact, and an average can sit at 75% with nothing actually mastered.
        This reports the counts the gate itself produces.
        """
        from deeptutor.learning import policy

        overviews: list[dict] = []
        for path_id in self._store.list_all():
            try:
                progress = self._store.load(path_id)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Failed to load mastery path %s for overview", path_id, exc_info=True
                )
                continue
            if progress is None:
                continue
            summary = policy.map_summary(progress)
            counts = summary["counts"]
            overviews.append(
                {
                    "path_id": progress.book_id,
                    "name": policy.path_display_name(progress),
                    "objectives": counts["total"],
                    "mastered": counts["mastered"],
                    "learning": counts["learning"],
                    "not_started": counts["new"],
                    "due_reviews": summary["due_reviews"],
                    "complete": summary["complete"],
                    "open_question": progress.pending_question is not None,
                    "updated_at": progress.updated_at,
                }
            )
        overviews.sort(key=lambda overview: overview["updated_at"], reverse=True)
        return overviews

    def list_progress(self) -> dict:
        """Return summary of all book progress with per-book error info."""
        from deeptutor.learning import policy

        logger = logging.getLogger(__name__)

        book_ids = self._store.list_all()
        summaries = []
        errors = []
        for bid in book_ids:
            try:
                progress = self._store.load(bid)
                if progress is None:
                    continue
                # Only count KPs from current modules (exclude stale IDs)
                current_kp_ids = {kp.id for m in progress.modules for kp in m.knowledge_points}
                total_kps = len(current_kp_ids)
                total_mastery = sum(
                    progress.mastery_levels.get(kp_id, 0) for kp_id in current_kp_ids
                )
                summaries.append(
                    {
                        "book_id": progress.book_id,
                        "name": policy.path_display_name(progress),
                        "modules_count": len(progress.modules),
                        "kp_count": total_kps,
                        "current_stage": progress.current_stage.value
                        if progress.current_stage
                        else "",
                        # Average mastery across current KPs (not the % of KPs mastered).
                        "avg_mastery_pct": round(total_mastery / total_kps * 100)
                        if total_kps
                        else 0,
                        "updated_at": progress.updated_at,
                    }
                )
            except Exception:
                logger.warning("Failed to load progress for book %s, skipping", bid, exc_info=True)
                errors.append({"book_id": bid, "error": "Failed to load"})
                continue
        return {"summaries": summaries, "errors": errors}

    def save(self, progress: LearningProgress) -> None:
        self._store.save(progress)


__all__ = [
    "LearningService",
    "MasteryInteractionError",
    "NoPendingInteractionError",
    "StaleInteractionError",
]
