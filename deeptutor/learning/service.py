from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Literal
import uuid

from deeptutor.learning.grading import classify_error, grade_answer
from deeptutor.learning.mastery import compute_mastery
from deeptutor.learning.models import (
    DeferredObjective,
    ErrorRecord,
    InteractionStatus,
    KnowledgePoint,
    LearnerMasteryOverride,
    LearnerProfile,
    LearningEvidence,
    LearningModule,
    LearningProgress,
    LearningStage,
    MasteryInteraction,
    PendingOption,
    PendingQuestion,
    QuizAttempt,
    RetryAttempt,
    TopicMetadata,
    TopicSource,
)
from deeptutor.learning.objective_relations import (
    ObjectiveRelationError,
    RelationRefs,
    resolve_relation_refs,
    validate_objective_relations,
)
from deeptutor.learning.storage import LearningStore

if TYPE_CHECKING:
    from deeptutor.learning.scheduler import SpacedRepetitionScheduler


# Long enough for a course title, short enough that a list row stays a row.
# Matches the cap module and objective names already use.
_MAX_PATH_NAME_LEN = 200
#: One intake answer. Free text, but a paragraph is an answer and a chapter is
#: a paste — and the whole profile is injected into every turn's status.
_MAX_PROFILE_FIELD_LEN = 600
#: The intake fields a caller may set. Named here so the tool schema, the REST
#: layer and this merge cannot drift apart.
_LEARNER_PROFILE_FIELDS: tuple[str, ...] = (
    "prior_knowledge",
    "target_level",
    "time_budget",
    "preferences",
    "notes",
)


def _objective_fingerprint(kp: KnowledgePoint) -> tuple[str, str]:
    return (str(kp.name or "").strip().casefold(), kp.type.value)


def _unique_fingerprint_map(
    points: list[KnowledgePoint],
) -> dict[tuple[str, str], KnowledgePoint]:
    counts: dict[tuple[str, str], int] = {}
    for kp in points:
        fingerprint = _objective_fingerprint(kp)
        counts[fingerprint] = counts.get(fingerprint, 0) + 1
    return {
        _objective_fingerprint(kp): kp for kp in points if counts[_objective_fingerprint(kp)] == 1
    }


def _reserved_objective_ids(progress: LearningProgress) -> set[str]:
    ids = {kp.id for module in progress.modules for kp in module.knowledge_points}
    ids.update(progress.mastery_levels)
    ids.update(progress.knowledge_types)
    ids.update(progress.qualitative_mastery)
    ids.update(progress.repetition_states)
    ids.update(progress.learner_mastery_overrides)
    ids.update(progress.feynman_retries)
    ids.update(progress.feynman_explanations)
    ids.update(progress.deferred_objectives)
    ids.update(attempt.knowledge_point_id for attempt in progress.quiz_attempts)
    ids.update(record.knowledge_point_id for record in progress.error_records)
    ids.update(task.knowledge_point_id for task in progress.review_queue)
    ids.update(event.knowledge_point_id for event in progress.learning_evidence)
    ids.discard("")
    return ids


def _new_objective_id(module_id: str, reserved: set[str]) -> str:
    prefix = f"{module_id}_kp"
    while True:
        candidate = f"{prefix}_{uuid.uuid4().hex[:12]}"
        if candidate not in reserved:
            reserved.add(candidate)
            return candidate


_QUIZ_EVIDENCE_TYPES = ("quiz", "review")
_QUIZ_EVIDENCE_WINDOW = 2.0


def _quiz_evidence_matches_attempt(event: LearningEvidence, attempt: QuizAttempt) -> bool:
    if (
        event.knowledge_point_id != attempt.knowledge_point_id
        or event.assessment_type not in _QUIZ_EVIDENCE_TYPES
    ):
        return False
    if event.question_id:
        return event.question_id == attempt.question_id
    # Legacy evidence predates question linkage. Keep its narrow timestamp
    # match so old paths remain repairable without risking newer linked rows.
    return abs(event.timestamp - attempt.timestamp) <= _QUIZ_EVIDENCE_WINDOW


def _drop_quiz_evidence_for_attempts(
    progress: LearningProgress, attempts: list[QuizAttempt]
) -> None:
    if not attempts:
        return
    unmatched = list(attempts)
    kept: list[LearningEvidence] = []
    for event in progress.learning_evidence:
        match_index = next(
            (
                index
                for index, attempt in enumerate(unmatched)
                if _quiz_evidence_matches_attempt(event, attempt)
            ),
            None,
        )
        if match_index is not None:
            unmatched.pop(match_index)
            continue
        kept.append(event)
    leftover_by_kp: dict[str, int] = {}
    for attempt in unmatched:
        leftover_by_kp[attempt.knowledge_point_id] = (
            leftover_by_kp.get(attempt.knowledge_point_id, 0) + 1
        )
    if leftover_by_kp:
        rebuilt: list[LearningEvidence] = []
        for event in reversed(kept):
            leftover = leftover_by_kp.get(event.knowledge_point_id, 0)
            if leftover and not event.question_id and event.assessment_type in _QUIZ_EVIDENCE_TYPES:
                leftover_by_kp[event.knowledge_point_id] = leftover - 1
                continue
            rebuilt.append(event)
        kept = list(reversed(rebuilt))
    progress.learning_evidence = kept


def _update_quiz_evidence_for_attempts(
    progress: LearningProgress, attempts: list[QuizAttempt]
) -> None:
    if not attempts:
        return
    unmatched = list(attempts)
    for event in progress.learning_evidence:
        match_index = next(
            (
                index
                for index, attempt in enumerate(unmatched)
                if _quiz_evidence_matches_attempt(event, attempt)
            ),
            None,
        )
        if match_index is None:
            continue
        attempt = unmatched.pop(match_index)
        event.result = "correct" if attempt.is_correct else "incorrect"
        event.quality = 1.0 if attempt.is_correct else 0.0


def assign_objective_identities(
    progress: LearningProgress,
    modules: list[LearningModule],
    *,
    identity_mode: str,
) -> dict[str, list[str] | str]:
    """Rewrite *modules* in place so IDs never inherit unrelated evidence.

    ``semantic`` (full replace) preserves an ID only when ``(name, type)`` is
    unique in both maps. ``explicit`` (targeted revise / topic edits) keeps
    caller-supplied IDs unless the same ID now names different content.
    """
    mode = "semantic" if identity_mode == "semantic" else "explicit"
    old_points = [kp for module in progress.modules for kp in module.knowledge_points]
    old_by_id = {kp.id: kp for kp in old_points}
    old_ids = set(old_by_id)
    reserved = _reserved_objective_ids(progress)
    preserved: list[str] = []
    minted: list[str] = []
    used_old_ids: set[str] = set()

    if mode == "semantic" and old_points:
        old_unique = _unique_fingerprint_map(old_points)
        new_unique = _unique_fingerprint_map(
            [kp for module in modules for kp in module.knowledge_points]
        )
        for module in modules:
            for kp in module.knowledge_points:
                fingerprint = _objective_fingerprint(kp)
                matched = None
                if fingerprint in new_unique and fingerprint in old_unique:
                    candidate = old_unique[fingerprint]
                    if candidate.id not in used_old_ids:
                        matched = candidate
                if matched is not None:
                    kp.id = matched.id
                    used_old_ids.add(matched.id)
                    preserved.append(kp.id)
                elif kp.id not in reserved:
                    reserved.add(kp.id)
                    minted.append(kp.id)
                else:
                    kp.id = _new_objective_id(module.id, reserved)
                    minted.append(kp.id)
                kp.module_id = module.id
    else:
        for module in modules:
            for kp in module.knowledge_points:
                old = old_by_id.get(kp.id)
                if old is not None and _objective_fingerprint(old) == _objective_fingerprint(kp):
                    preserved.append(kp.id)
                    reserved.add(kp.id)
                elif kp.id in reserved:
                    kp.id = _new_objective_id(module.id, reserved)
                    minted.append(kp.id)
                else:
                    reserved.add(kp.id)
                    minted.append(kp.id)
                kp.module_id = module.id

    new_ids = {kp.id for module in modules for kp in module.knowledge_points}
    return {
        "mode": mode,
        "preserved": preserved,
        "minted": minted,
        "dropped": sorted(old_ids - new_ids),
    }


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

    @staticmethod
    def _resolve_final_relations(
        applied: list[LearningModule],
        submitted: list[LearningModule],
        relation_refs: dict[str, RelationRefs],
        source_aliases: dict[str, str],
        sources: list[TopicSource],
        *,
        existing_modules: list[LearningModule] | None = None,
    ) -> None:
        """Resolve request references after durable objective IDs have been assigned."""
        aliases = {
            point.id: point.id
            for module in existing_modules or []
            for point in module.knowledge_points
        }
        final_refs: dict[str, RelationRefs] = {}
        for submitted_module, final_module in zip(submitted, applied, strict=True):
            for submitted_point, final_point in zip(
                submitted_module.knowledge_points, final_module.knowledge_points, strict=True
            ):
                # An append request may reuse a provisional ID that already belongs
                # to an existing objective. Its client_ref disambiguates the new one.
                if submitted_point.id not in aliases:
                    aliases[submitted_point.id] = final_point.id
                aliases[final_point.id] = final_point.id
                specs = relation_refs.get(submitted_point.id)
                if specs is not None:
                    final_refs[final_point.id] = specs

        for final_id, specs in final_refs.items():
            alias = specs.client_ref.strip()
            if not alias:
                continue
            if alias in aliases and aliases[alias] != final_id:
                raise ObjectiveRelationError(f"Objective reference {alias!r} is ambiguous")
            aliases[alias] = final_id

        resolve_relation_refs(
            applied,
            final_refs,
            prerequisite_aliases=aliases,
            source_aliases=source_aliases,
            sources=sources,
        )

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
        for key in list(progress.learner_mastery_overrides.keys()):
            if key not in new_kp_ids:
                del progress.learner_mastery_overrides[key]
        for key in list(progress.deferred_objectives.keys()):
            if key not in new_kp_ids:
                del progress.deferred_objectives[key]
        progress.error_records = [
            r for r in progress.error_records if r.knowledge_point_id in new_kp_ids
        ]
        progress.quiz_attempts = [
            attempt
            for attempt in progress.quiz_attempts
            if attempt.knowledge_point_id in new_kp_ids
        ]
        progress.learning_evidence = [
            event for event in progress.learning_evidence if event.knowledge_point_id in new_kp_ids
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
            a.is_correct
            for a in progress.quiz_attempts
            if a.knowledge_point_id == kp_id and not a.voided
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
        session_id: str = "",
        turn_id: str = "",
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
            session_id=session_id,
            turn_id=turn_id,
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
        session_id: str = "",
        turn_id: str = "",
    ) -> bool:
        """Mutate one aggregate with a grade without performing I/O."""
        is_correct = bool(expected_answer) and grade_answer(
            user_answer, expected_answer, question_type
        )
        # Capture the active retry before recording this answer graduates it.
        # Past retries on this or another question must not weaken later reviews.
        retrying = any(
            rec.question_id == question_id
            and rec.knowledge_point_id == knowledge_point_id
            and rec.status in ("active", "retrying")
            for rec in progress.error_records
        )
        already_scheduled = knowledge_point_id in progress.repetition_states
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
        evidence = None
        if knowledge_point_id:
            progress.deferred_objectives.pop(knowledge_point_id, None)
            evidence = self._record_quiz_evidence(
                progress,
                knowledge_point_id,
                question_id=question_id,
                is_correct=is_correct,
                retrying=retrying,
                session_id=session_id,
                turn_id=turn_id,
                assessment_type="review" if already_scheduled else "quiz",
            )
            self.update_mastery(
                progress, knowledge_point_id, self.calculate_mastery(progress, knowledge_point_id)
            )
            kp_type = progress.knowledge_types.get(knowledge_point_id)
            if kp_type is not None and scheduler is not None:
                state = progress.repetition_states.get(
                    knowledge_point_id
                ) or scheduler.get_initial_state(
                    kp_type, desired_retention=progress.desired_retention
                )
                progress.repetition_states[knowledge_point_id] = state
                scheduler.schedule_review(state, kp_type, evidence)
                progress.review_queue = scheduler.build_review_queue(progress)
        return is_correct

    def _record_quiz_evidence(
        self,
        progress: LearningProgress,
        kp_id: str,
        *,
        question_id: str = "",
        is_correct: bool,
        retrying: bool = False,
        session_id: str = "",
        turn_id: str = "",
        assessment_type: Literal["quiz", "qualitative", "review"] = "quiz",
    ) -> LearningEvidence:
        attempt_count = sum(
            1
            for attempt in progress.quiz_attempts
            if attempt.knowledge_point_id == kp_id and not attempt.voided
        )
        evidence = LearningEvidence(
            question_id=question_id,
            knowledge_point_id=kp_id,
            assessment_type=assessment_type,
            result="correct" if is_correct else "incorrect",
            quality=(0.6 if retrying else 1.0) if is_correct else 0.0,
            attempt_count=max(1, attempt_count),
            session_id=session_id,
            turn_id=turn_id,
        )
        progress.learning_evidence.append(evidence)
        return evidence

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
            tx.progress.deferred_objectives.pop(pending.knowledge_point_id, None)
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
                option_map = interaction.question.choice_map
                if not is_readable_choice_answer(stored, option_map) and is_readable_choice_answer(
                    incoming, option_map
                ):
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
                        resolve_choice_submission,
                    )

                    option_map = pending.choice_map
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
                # Bodies recovered for a legacy question (see the tool
                # adapter): store them in the structured form so nothing has
                # to recover them again.
                pending.options = [
                    PendingOption(label=label, body=body)
                    for label, body in resolved_choice_options.items()
                ]
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
                session_id=session_id,
                turn_id=turn_id,
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
            if tx.progress.learning_evidence:
                latest = tx.progress.learning_evidence[-1]
                if latest.knowledge_point_id == pending.knowledge_point_id:
                    tx.emit(
                        "evidence.recorded",
                        {
                            "knowledge_point_id": latest.knowledge_point_id,
                            "assessment_type": latest.assessment_type,
                            "result": latest.result,
                            "quality": latest.quality,
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
        identity_mode: str = "explicit",
        relation_refs: dict[str, RelationRefs] | None = None,
        source_aliases: dict[str, str] | None = None,
        topic_sources: list[TopicSource] | None = None,
        fresh_identity: bool = False,
    ) -> LearningProgress:
        """Install a module set, optionally naming a path that has no name yet.

        ``name`` is applied only when the path is still unnamed, in the same
        transaction as the modules so a built path is never briefly nameless.
        Replacing the map deliberately does NOT rename: the map is what the
        path teaches, the name is which path it is — deriving one from the
        other is what made a rebuild look like a different course.

        ``identity_mode`` is ``semantic`` for a full outline replace (unique
        ``(name, type)`` mapping) and ``explicit`` for targeted revise / topic
        edits that already carry durable IDs. Position never establishes identity.
        """

        def replace(tx):
            if name.strip() and not tx.progress.name.strip():
                tx.progress.name = name.strip()[:_MAX_PATH_NAME_LEN]
            applied_modules = [module.model_copy(deep=True) for module in modules]
            identity_map: dict[str, list[str] | str] = {
                "mode": "append" if append else ("fresh" if fresh_identity else identity_mode),
                "preserved": [],
                "minted": [],
                "dropped": [],
            }
            if append:
                reserved = _reserved_objective_ids(tx.progress)
                offset = len(tx.progress.modules)
                minted: list[str] = []
                for index, module in enumerate(applied_modules, start=offset):
                    module.id = f"{book_id}_m{index}"
                    module.order = index
                    for kp_index, kp in enumerate(module.knowledge_points):
                        kp.module_id = module.id
                        candidate = f"{module.id}_kp{kp_index}"
                        if candidate in reserved:
                            kp.id = _new_objective_id(module.id, reserved)
                        else:
                            kp.id = candidate
                            reserved.add(candidate)
                        tx.progress.knowledge_types[kp.id] = kp.type
                        minted.append(kp.id)
                identity_map["minted"] = minted
                existing_modules = tx.progress.modules
                self._resolve_final_relations(
                    applied_modules,
                    modules,
                    relation_refs or {},
                    source_aliases or {},
                    tx.topic_sources() if topic_sources is None else topic_sources,
                    existing_modules=existing_modules,
                )
                validate_objective_relations(
                    [*existing_modules, *applied_modules],
                    tx.topic_sources() if topic_sources is None else topic_sources,
                )
                tx.progress.modules.extend(applied_modules)
                if not tx.progress.current_module_id and applied_modules:
                    tx.progress.current_module_id = applied_modules[0].id
                    tx.progress.current_kp_index = 0
            else:
                current_kp_id = ""
                for current_module in tx.progress.modules:
                    if current_module.id != tx.progress.current_module_id:
                        continue
                    if 0 <= tx.progress.current_kp_index < len(current_module.knowledge_points):
                        current_kp_id = current_module.knowledge_points[
                            tx.progress.current_kp_index
                        ].id
                    break
                pending_kp_id = (
                    tx.progress.pending_question.knowledge_point_id
                    if tx.progress.pending_question is not None
                    else ""
                )
                active_interaction = tx.active_interaction()
                active_kp_id = (
                    active_interaction.question.knowledge_point_id
                    if active_interaction is not None
                    else ""
                )

                if fresh_identity:
                    reserved = _reserved_objective_ids(tx.progress)
                    for module in applied_modules:
                        for kp in module.knowledge_points:
                            kp.id = _new_objective_id(module.id, reserved)
                            kp.module_id = module.id
                    identity_map["minted"] = [
                        kp.id for module in applied_modules for kp in module.knowledge_points
                    ]
                    identity_map["dropped"] = sorted(
                        {kp.id for module in tx.progress.modules for kp in module.knowledge_points}
                    )
                else:
                    identity_map = assign_objective_identities(
                        tx.progress,
                        applied_modules,
                        identity_mode=identity_mode,
                    )
                sources = tx.topic_sources() if topic_sources is None else topic_sources
                self._resolve_final_relations(
                    applied_modules,
                    modules,
                    relation_refs or {},
                    source_aliases or {},
                    sources,
                )
                validate_objective_relations(applied_modules, sources)
                self.replace_modules(tx.progress, applied_modules)
                objective_locations = {
                    kp.id: (module.id, kp_index)
                    for module in applied_modules
                    for kp_index, kp in enumerate(module.knowledge_points)
                }

                if current_kp_id in objective_locations:
                    (
                        tx.progress.current_module_id,
                        tx.progress.current_kp_index,
                    ) = objective_locations[current_kp_id]
                elif applied_modules:
                    tx.progress.current_module_id = applied_modules[0].id
                    tx.progress.current_kp_index = 0
                else:
                    tx.progress.current_module_id = ""
                    tx.progress.current_kp_index = 0

                if tx.progress.pending_question is not None:
                    if pending_kp_id not in objective_locations:
                        tx.progress.pending_question = None
                    else:
                        pending_module_id, _ = objective_locations[pending_kp_id]
                        tx.progress.pending_question.module_id = pending_module_id

                if active_interaction is not None:
                    if active_kp_id not in objective_locations:
                        tx.abandon_active_interactions()
                    else:
                        active_module_id, _ = objective_locations[active_kp_id]
                        if active_interaction.question.module_id != active_module_id:
                            active_interaction.question.module_id = active_module_id
                            tx.put_interaction(active_interaction)
            tx.touch()
            tx.emit(
                event_type,
                {
                    "mode": "append" if append else "replace",
                    "identity_map": identity_map,
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

    def create_topic(
        self,
        book_id: str,
        *,
        name: str,
        modules: list[LearningModule],
        metadata: TopicMetadata,
        sources: list[TopicSource],
        relation_refs: dict[str, RelationRefs] | None = None,
        source_aliases: dict[str, str] | None = None,
    ) -> LearningProgress:
        """Create a confirmed topic, sources, and route in one transaction."""

        if self._store.exists(book_id):
            raise ValueError(f"Mastery topic {book_id!r} already exists")

        def create(tx):
            tx.progress.name = str(name or "").strip()[:_MAX_PATH_NAME_LEN]
            tx.put_topic(metadata, sources)
            applied_modules = [module.model_copy(deep=True) for module in modules]
            self._resolve_final_relations(
                applied_modules,
                modules,
                relation_refs or {},
                source_aliases or {},
                sources,
            )
            validate_objective_relations(applied_modules, sources)
            self.replace_modules(tx.progress, applied_modules)
            tx.progress.current_module_id = applied_modules[0].id if applied_modules else ""
            tx.progress.current_kp_index = 0
            tx.touch()
            tx.emit(
                "topic.created",
                {
                    "module_count": len(modules),
                    "knowledge_point_count": sum(
                        len(module.knowledge_points) for module in modules
                    ),
                    "source_count": len(sources),
                },
            )

        progress, _ = self._store.mutate(book_id, create, create=True)
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

    def record_learner_profile(
        self,
        book_id: str,
        *,
        fields: dict[str, str],
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[LearningProgress, list[str]]:
        """Merge intake answers into this goal's learner profile.

        Merge, never replace: intake is not a single moment. The first session
        asks four questions, and months later "我时间变少了" has to be able to
        change one of them without wiping the other three. Only fields the
        caller actually names are touched, so an omitted field keeps whatever
        the learner said about it before.

        Returns the progress and the names of the fields that really changed,
        so the caller can tell the learner what it recorded rather than
        claiming to have recorded everything it was handed.
        """
        cleaned = {
            key: str(value or "").strip()[:_MAX_PROFILE_FIELD_LEN]
            for key, value in fields.items()
            if key in _LEARNER_PROFILE_FIELDS and value is not None
        }

        def record(tx):
            profile = tx.progress.learner_profile or LearnerProfile()
            changed = [key for key, value in cleaned.items() if getattr(profile, key) != value]
            if not changed:
                return []
            updated = profile.model_copy(update={**cleaned, "updated_at": time.time()})
            tx.progress.learner_profile = updated
            tx.touch()
            tx.emit(
                "path.learner_profile_recorded",
                {"fields": changed},
                session_id=session_id,
                turn_id=turn_id,
            )
            return changed

        return self._store.mutate(book_id, record, create=True)

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
            progress.learning_evidence = []
            progress.repetition_states = {}
            progress.review_queue = []
            progress.learner_mastery_overrides = {}
            progress.deferred_objectives = {}
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

    def set_learner_mastery_override(
        self,
        book_id: str,
        kp_id: str,
        *,
        mastered: bool,
        note: str = "",
    ) -> LearningProgress:
        """Set or clear an explicit learner claim without changing evidence."""

        def update(tx):
            from deeptutor.learning.policy import find_knowledge_point

            kp, _, _ = find_knowledge_point(tx.progress, kp_id)
            if kp is None:
                raise MasteryInteractionError(f"Unknown objective {kp_id!r}")
            if mastered:
                tx.progress.learner_mastery_overrides[kp_id] = LearnerMasteryOverride(
                    knowledge_point_id=kp_id,
                    note=str(note or "").strip()[:500],
                )
                tx.progress.deferred_objectives.pop(kp_id, None)
                event_type = "mastery.overridden"
            else:
                if kp_id not in tx.progress.learner_mastery_overrides:
                    return
                tx.progress.learner_mastery_overrides.pop(kp_id, None)
                event_type = "mastery.override_cleared"
            tx.touch()
            tx.emit(
                event_type,
                {"knowledge_point_id": kp_id, "mastered": bool(mastered)},
            )

        progress, _ = self._store.mutate(book_id, update)
        return progress

    def _recompute_objective_state(
        self,
        progress: LearningProgress,
        kp_id: str,
        scheduler: SpacedRepetitionScheduler | None,
    ) -> None:
        if not kp_id:
            return
        self.update_mastery(progress, kp_id, self.calculate_mastery(progress, kp_id))
        if scheduler is None:
            return
        kp_type = progress.knowledge_types.get(kp_id)
        attempts = [
            attempt
            for attempt in progress.quiz_attempts
            if attempt.knowledge_point_id == kp_id and not attempt.voided
        ]
        events = [
            event for event in progress.learning_evidence if event.knowledge_point_id == kp_id
        ]
        if kp_type is None or (not attempts and not events):
            progress.repetition_states.pop(kp_id, None)
        elif events:
            progress.repetition_states[kp_id] = scheduler.replay(
                kp_type,
                # Live transitions follow durable append order. A linked
                # assessment can arrive after a newer one with an older source
                # timestamp; sorting it here would make repair diverge (#1541).
                events,
                desired_retention=progress.desired_retention,
            )
        else:
            synthesized = [
                LearningEvidence(
                    question_id=attempt.question_id,
                    knowledge_point_id=kp_id,
                    timestamp=attempt.timestamp,
                    assessment_type="quiz",
                    result="correct" if attempt.is_correct else "incorrect",
                    quality=1.0 if attempt.is_correct else 0.0,
                    attempt_count=index,
                )
                for index, attempt in enumerate(
                    sorted(attempts, key=lambda item: item.timestamp),
                    start=1,
                )
            ]
            progress.repetition_states[kp_id] = scheduler.replay(
                kp_type, synthesized, desired_retention=progress.desired_retention
            )
        progress.review_queue = scheduler.build_review_queue(progress)

    def repair_question(
        self,
        book_id: str,
        question_id: str = "",
        *,
        action: str,
        expected_answer: str = "",
        reason: str = "",
        scheduler: SpacedRepetitionScheduler | None = None,
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[LearningProgress, dict]:
        """Void or re-key one question and rebuild that objective's evidence."""

        action_name = str(action or "").strip().lower()
        if action_name not in {"void", "correct"}:
            raise MasteryInteractionError("action must be 'void' or 'correct'")
        note = str(reason or "").strip()[:500]
        if not note:
            raise MasteryInteractionError("A reason is required so the repair can be audited")
        if action_name == "correct" and not str(expected_answer or "").strip():
            raise MasteryInteractionError("correcting a question requires the new expected_answer")

        def repair(tx):
            requested_id = str(question_id or "").strip()
            interaction = tx.get_interaction(requested_id) if requested_id else None
            if interaction is None and not requested_id:
                interaction = tx.active_interaction()
            pending = tx.progress.pending_question
            if interaction is not None:
                resolved_id = interaction.interaction_id
            elif requested_id:
                resolved_id = requested_id
            elif pending is not None:
                resolved_id = pending.question_id
            else:
                latest = next(
                    (
                        attempt.question_id
                        for attempt in reversed(tx.progress.quiz_attempts)
                        if not attempt.voided
                    ),
                    "",
                )
                resolved_id = latest
            if not resolved_id:
                raise NoPendingInteractionError("No question is available to repair")
            if interaction is None:
                interaction = tx.get_interaction(resolved_id)
            if pending is not None and pending.question_id != resolved_id:
                pending = None
            elif (
                pending is None
                and tx.progress.pending_question is not None
                and tx.progress.pending_question.question_id == resolved_id
            ):
                pending = tx.progress.pending_question

            attempts = [
                attempt
                for attempt in tx.progress.quiz_attempts
                if attempt.question_id == resolved_id
            ]
            question = interaction.question if interaction is not None else pending
            kp_id = (question.knowledge_point_id if question is not None else "") or (
                attempts[0].knowledge_point_id if attempts else ""
            )
            module_id = (question.module_id if question is not None else "") or (
                attempts[0].module_id if attempts else ""
            )
            question_type = question.question_type if question is not None else "short"
            previous_expected = question.expected_answer if question is not None else ""
            previous_is_correct = attempts[0].is_correct if attempts else None
            user_answer = (interaction.user_answer if interaction is not None else "") or (
                str(attempts[0].user_answer or "") if attempts else ""
            )

            repaired_correct: bool | None = previous_is_correct
            new_expected = previous_expected
            if action_name == "void":
                for attempt in attempts:
                    attempt.voided = True
                    attempt.void_reason = note
                tx.progress.error_records = [
                    record
                    for record in tx.progress.error_records
                    if record.question_id != resolved_id
                ]
                if pending is not None:
                    tx.progress.pending_question = None
                active = tx.active_interaction()
                if active is not None and active.interaction_id == resolved_id:
                    tx.abandon_active_interactions()
                elif interaction is not None and interaction.status != InteractionStatus.ABANDONED:
                    interaction.result = {
                        **dict(interaction.result or {}),
                        "voided": True,
                        "reason": note,
                    }
                    tx.put_interaction(interaction)
                _drop_quiz_evidence_for_attempts(tx.progress, attempts)
                repaired_correct = None
            else:
                new_expected = str(expected_answer or "").strip()
                if question is not None:
                    question.expected_answer = new_expected
                if interaction is not None:
                    interaction.question.expected_answer = new_expected
                if (
                    tx.progress.pending_question is not None
                    and tx.progress.pending_question.question_id == resolved_id
                ):
                    tx.progress.pending_question.expected_answer = new_expected
                if attempts:
                    for attempt in attempts:
                        if attempt.voided:
                            continue
                        is_correct = bool(new_expected) and grade_answer(
                            str(attempt.user_answer or ""),
                            new_expected,
                            question_type,
                        )
                        attempt.is_correct = is_correct
                        attempt.error_type = (
                            None if is_correct else classify_error(str(attempt.user_answer or ""))
                        )
                        repaired_correct = is_correct
                        if is_correct:
                            for record in tx.progress.error_records:
                                if record.question_id == resolved_id:
                                    record.status = "graduated"
                        elif not any(
                            record.question_id == resolved_id
                            for record in tx.progress.error_records
                        ):
                            tx.progress.error_records.append(
                                ErrorRecord(
                                    id=uuid.uuid4().hex,
                                    question_id=resolved_id,
                                    knowledge_point_id=kp_id,
                                    module_id=module_id,
                                    error_type=attempt.error_type
                                    or classify_error(str(attempt.user_answer or "")),
                                    status="active",
                                )
                            )
                if interaction is not None:
                    interaction.result = {
                        **dict(interaction.result or {}),
                        "is_correct": repaired_correct,
                        "corrected": True,
                        "reason": note,
                    }
                    tx.put_interaction(interaction)
                _update_quiz_evidence_for_attempts(
                    tx.progress,
                    [attempt for attempt in attempts if not attempt.voided],
                )

            self._recompute_objective_state(tx.progress, kp_id, scheduler)
            tx.touch()
            tx.emit(
                "assessment.voided" if action_name == "void" else "assessment.corrected",
                {
                    "question_id": resolved_id,
                    "knowledge_point_id": kp_id,
                    "reason": note,
                    "previous_expected": previous_expected,
                    "expected_answer": new_expected,
                    "previous_is_correct": previous_is_correct,
                    "is_correct": repaired_correct,
                },
                session_id=session_id or (interaction.session_id if interaction else ""),
                turn_id=turn_id or (interaction.turn_id if interaction else ""),
            )
            return {
                "action": action_name,
                "question_id": resolved_id,
                "knowledge_point_id": kp_id,
                "module_id": module_id,
                "reason": note,
                "previous_expected": previous_expected,
                "expected_answer": new_expected,
                "previous_is_correct": previous_is_correct,
                "is_correct": repaired_correct,
                "user_answer": user_answer,
                "question_type": question_type,
                "prompt": question.prompt if question is not None else "",
                "options": question.choice_map if question is not None else {},
                "explanation": question.explanation if question is not None else "",
                "difficulty": question.difficulty if question is not None else "",
                "session_id": session_id or (interaction.session_id if interaction else ""),
                "turn_id": turn_id or (interaction.turn_id if interaction else ""),
            }

        progress, details = self._store.mutate(book_id, repair)
        return progress, details

    def defer_objective(
        self,
        book_id: str,
        kp_id: str = "",
        *,
        note: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[LearningProgress, dict]:
        """Skip this objective for now without recording mastery."""

        def defer(tx):
            from deeptutor.learning.policy import find_knowledge_point, is_mastered, next_objective

            target_id = str(kp_id or "").strip()
            if not target_id:
                pending = tx.progress.pending_question
                if pending is not None:
                    target_id = pending.knowledge_point_id
                else:
                    target_id = next_objective(tx.progress).knowledge_point_id
            kp, _, _ = find_knowledge_point(tx.progress, target_id)
            if kp is None:
                raise MasteryInteractionError(f"Unknown objective {target_id!r}")
            if is_mastered(tx.progress, kp):
                raise MasteryInteractionError(
                    f"{kp.name!r} is already mastered, so there is nothing to defer"
                )
            abandoned = False
            pending = tx.progress.pending_question
            if pending is not None and pending.knowledge_point_id == target_id:
                tx.progress.pending_question = None
                abandoned = True
            active = tx.active_interaction()
            if active is not None and active.question.knowledge_point_id == target_id:
                tx.abandon_active_interactions()
                abandoned = True
            tx.progress.deferred_objectives[target_id] = DeferredObjective(
                knowledge_point_id=target_id,
                note=str(note or "").strip()[:500],
            )
            tx.touch()
            tx.emit(
                "objective.deferred",
                {
                    "knowledge_point_id": target_id,
                    "note": str(note or "").strip()[:500],
                    "abandoned_question": abandoned,
                },
                session_id=session_id,
                turn_id=turn_id,
            )
            return {"knowledge_point_id": target_id, "abandoned_question": abandoned}

        return self._store.mutate(book_id, defer)

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

        Every assessment applies the same retention transition that evidence
        replay uses. This keeps the persisted state reproducible and lets an
        initial failure schedule the prompt repair it demonstrably needs.
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
            applied = self.record_qualitative_in_memory(
                tx.progress,
                kp_id,
                passed=passed,
                evidence=evidence,
                scheduler=scheduler,
                session_id=session_id,
                turn_id=turn_id,
            )
            if not applied:
                return
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
            if tx.progress.learning_evidence:
                latest = tx.progress.learning_evidence[-1]
                if latest.knowledge_point_id == kp_id:
                    tx.emit(
                        "evidence.recorded",
                        {
                            "knowledge_point_id": latest.knowledge_point_id,
                            "assessment_type": latest.assessment_type,
                            "result": latest.result,
                            "quality": latest.quality,
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
        session_id: str = "",
        turn_id: str = "",
    ) -> bool:
        evidence_id = ""
        if session_id or turn_id:
            evidence_id = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"deeptutor:qualitative:{session_id}:{turn_id}:{kp_id}",
            ).hex
            if any(item.evidence_id == evidence_id for item in progress.learning_evidence):
                return False
        progress.qualitative_mastery[kp_id] = bool(passed)
        progress.deferred_objectives.pop(kp_id, None)
        current = progress.mastery_levels.get(kp_id, 0.0)
        progress.mastery_levels[kp_id] = max(current, 1.0) if passed else min(current, 0.4)
        if evidence:
            progress.feynman_explanations[kp_id] = evidence
        moment = time.time()
        review_evidence = LearningEvidence(
            evidence_id=evidence_id,
            knowledge_point_id=kp_id,
            timestamp=moment,
            assessment_type="qualitative",
            result="correct" if passed else "partial",
            quality=(1.0 if evidence else 0.9) if passed else 0.2,
            attempt_count=1,
            session_id=session_id,
            turn_id=turn_id,
        )
        progress.learning_evidence.append(review_evidence)
        kp_type = progress.knowledge_types.get(kp_id)
        if kp_type is not None and scheduler is not None:
            state = progress.repetition_states.get(kp_id) or scheduler.get_initial_state(
                kp_type,
                now=review_evidence.timestamp,
                desired_retention=progress.desired_retention,
            )
            progress.repetition_states[kp_id] = state
            scheduler.schedule_review(
                state,
                kp_type,
                review_evidence,
                now=review_evidence.timestamp,
            )
            progress.review_queue = scheduler.build_review_queue(progress)
        progress.updated_at = moment
        return True

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
