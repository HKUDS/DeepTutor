from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal
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
    "teaching_strategy",
    "notes",
)


def _source_page_key(source: dict) -> tuple | None:
    """Conservative physical-page identity, shared by native visual/lesson refs."""
    ref = source.get("source_ref") or source.get("ref") or source
    if not isinstance(ref, dict):
        return None
    kb = ref.get("kb_ref") or ref.get("kb_name")
    document = ref.get("document_key") or ref.get("source_path")
    digest = ref.get("source_digest") or ref.get("source_hash")
    page = ref.get("page_index")
    if page is None and type(ref.get("page")) is int:
        page = ref["page"] - 1
    if not kb or not document or not digest or type(page) is not int or page < 0:
        return None
    # Crops do not establish that a nearby printed answer was absent.
    return kb, document, digest, page


def _question_source_pages(question: PendingQuestion) -> set[tuple]:
    sources = question.source_evidence.get("sources", [])
    citations = question.source_evidence.get("assessment_contract", {}).get("citations", [])
    if citations:
        indices = {row.get("index") for row in citations}
        sources = [row for index, row in enumerate(sources) if index in indices]
    return {
        key
        for source in [*sources, *question.visual_context.get("sources", [])]
        if (key := _source_page_key(source)) is not None
    }


def _apply_source_assistance(progress: LearningProgress, question: PendingQuestion) -> None:
    """Attach exposure to this attempt, never to lifelong knowledge of a page.

    Same-turn pre-card display may disclose the question/key. A later receipt
    can assist an already pending question only in its registration session.
    Legacy exposures without native identity are not inferred from history.
    """
    context = question.assistance_context
    session_id, turn_id = context.get("session_id"), context.get("turn_id")
    if not session_id or not turn_id:
        return
    exposed = {
        key
        for source in progress.source_exposures
        if (key := _source_page_key(source)) is not None
        and source.get("session_id") == session_id
        and (source.get("turn_id") == turn_id or source.get("created_at", 0) >= question.created_at)
    }
    pages = _question_source_pages(question)
    # Without a source identity, independence after public source display is
    # unknown. Preserve practice without inventing independent credit.
    if exposed and (not pages or exposed.intersection(pages)):
        question.assistance_used = True


def _question_independent(question: PendingQuestion) -> bool:
    return not (question.assistance_used or question.visual_context.get("hints_used"))


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
    ids.update(progress.explained_objectives)
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
        event.result = attempt.result or ("correct" if attempt.is_correct else "incorrect")
        event.quality = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[event.result]
        if event.hints_used and attempt.is_correct:
            event.quality = min(event.quality, 0.6)


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
        for key in list(progress.explained_objectives):
            if key not in new_kp_ids:
                del progress.explained_objectives[key]
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
            0.5 if a.result == "partial" else a.is_correct
            for a in progress.quiz_attempts
            if a.knowledge_point_id == kp_id and not a.voided and a.independent
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
        visual_context: dict[str, Any] | None = None,
        assistance_used: bool = False,
        verdict: dict[str, Any] | None = None,
    ) -> bool:
        """Mutate one aggregate with a grade without performing I/O."""
        is_correct = (
            verdict["result"] == "correct"
            if verdict
            else bool(expected_answer) and grade_answer(user_answer, expected_answer, question_type)
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
                result=verdict["result"] if verdict else ("correct" if is_correct else "incorrect"),
                user_answer=user_answer,
                self_attribution=self_attribution,
                error_type=None
                if is_correct or verdict and verdict["result"] == "partial"
                else classify_error(user_answer),
                independent=not assistance_used and not (visual_context or {}).get("hints_used"),
                visual_context=visual_context or {},
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
            evidence.visual_context = visual_context or {}
            evidence.hints_used = max(
                int((visual_context or {}).get("hints_used") or 0), int(assistance_used)
            )
            if evidence.hints_used and is_correct:
                evidence.quality = min(evidence.quality or 1.0, 0.6)
            if verdict:
                evidence.result = verdict["result"]
                evidence.quality = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[
                    verdict["result"]
                ]
                evidence.confidence = verdict.get("confidence")
                evidence.learner_answer = user_answer
                evidence.feedback = verdict.get("feedback", "")
                if evidence.hints_used and is_correct:
                    evidence.quality = min(evidence.quality, 0.6)
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
        for question in pending.questions or [pending]:
            _apply_source_assistance(progress, question)
        progress.pending_question = pending
        progress.updated_at = time.time()
        self.save(progress)

    def clear_pending_question(self, progress: LearningProgress) -> None:
        progress.pending_question = None
        progress.updated_at = time.time()
        self.save(progress)

    def present_sources(
        self,
        book_id: str,
        sources: list[dict],
        purpose: str,
        *,
        session_id: str = "",
        turn_id: str = "",
    ) -> list[dict]:
        """Authorize explicit page display and persist assistance before delivery.

        Called only by the trusted runtime after exact-source retrieval. A
        failed delivery may conservatively leave a receipt; it cannot grant
        independent credit after a possibly delivered answer-bearing page.
        """
        from deeptutor.services.rag.source_pages import SourceRef, public_source, resolve_source

        if purpose not in {"teaching", "reveal"} or not 1 <= len(sources) <= 6:
            raise MasteryInteractionError("Presentation needs one to six exact source pages")
        refs = []
        for source in sources:
            try:
                ref = SourceRef.model_validate(source.get("source_ref"))
            except ValueError as exc:
                raise MasteryInteractionError(
                    "Presentation requires an exact verified source page"
                ) from exc
            resolve_source(ref)
            refs.append(ref)
        rows = [public_source(ref) for ref in refs]
        for row in rows:
            # A full-file link bypasses a page/crop presentation boundary.
            row.pop("url", None)
        pages = {_source_page_key(row) for row in rows}

        def present(tx):
            active = tx.active_interaction() or self._interaction_from_legacy_pending(tx.progress)
            if active:
                final_ids = {
                    row["question_id"]
                    for row in active.result.get("results", [])
                    if row.get("final", True)
                }
                unresolved = [
                    q
                    for q in active.question.questions or [active.question]
                    if q.question_id not in final_ids
                ]
                if purpose == "reveal" and unresolved:
                    raise MasteryInteractionError(
                        "Answer every pending question before revealing source pages"
                    )
                if any(
                    not _question_source_pages(q) or pages.intersection(_question_source_pages(q))
                    for q in unresolved
                ):
                    raise MasteryInteractionError(
                        "This source may disclose a pending answer; resolve the question before presentation"
                    )
            known = {
                (_source_page_key(row), row.get("session_id"), row.get("turn_id"))
                for row in tx.progress.source_exposures
            }
            for row in rows:
                key = (_source_page_key(row), session_id, turn_id)
                if key not in known:
                    tx.progress.source_exposures.append(
                        {
                            "source_ref": row["source_ref"],
                            "purpose": purpose,
                            "session_id": session_id,
                            "turn_id": turn_id,
                            "created_at": time.time(),
                        }
                    )
                    known.add(key)
                    tx.touch()
            return rows

        _, authorized = self._store.mutate(book_id, present)
        return authorized

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
        pending: PendingQuestion | None,
        *,
        pending_action: str = "retain",
        replace_question_id: str = "",
        resume_question_id: str = "",
        session_id: str = "",
        turn_id: str = "",
    ) -> tuple[LearningProgress, MasteryInteraction, bool]:
        """Atomically register one outstanding question.

        Retrying ``mastery_quiz`` while a question is active returns the
        existing interaction instead of overwriting its expected answer.
        """

        if pending_action not in {"retain", "replace", "resume"}:
            raise MasteryInteractionError("pending_action must be retain, replace or resume")
        if pending_action == "resume":
            if pending is not None or replace_question_id or not resume_question_id:
                raise MasteryInteractionError(
                    "Resume needs only the exact pending parent question_id"
                )
        elif pending is None or resume_question_id:
            raise MasteryInteractionError(
                "A new question contract cannot include resume_question_id"
            )

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
            if pending_action == "resume":
                if active is None or active.interaction_id != resume_question_id:
                    raise StaleInteractionError(
                        resume_question_id, active.interaction_id if active else ""
                    )
                if active.status not in {
                    InteractionStatus.REGISTERED,
                    InteractionStatus.AWAITING_INPUT,
                    InteractionStatus.ANSWERED,
                }:
                    raise MasteryInteractionError(
                        "This question is no longer awaiting input; refresh mastery_status"
                    )
                from deeptutor.learning.lesson_evidence import LessonUnavailable

                graded_ids = {
                    result["question_id"]
                    for result in (active.result or {}).get("results", [])
                    if result.get("final", True)
                }
                reviewed_ids = {
                    result["question_id"] for result in (active.result or {}).get("results", [])
                }
                if set(active.answers) - reviewed_ids:
                    raise MasteryInteractionError(
                        "Grade the committed answers before re-presenting the remaining card"
                    )
                known_ids = {
                    kp.id for module in tx.progress.modules for kp in module.knowledge_points
                }
                try:
                    for question in active.question.questions or [active.question]:
                        if question.question_id in graded_ids:
                            continue
                        if question.knowledge_point_id not in known_ids:
                            raise MasteryInteractionError(
                                "The pending objective changed; refresh mastery_status"
                            )
                        from deeptutor.learning.semantic_assessment import validate_question

                        validate_question(self._store, tx.progress, question)
                except LessonUnavailable as exc:
                    raise MasteryInteractionError(str(exc)) from exc
                return active, False
            if active is not None and pending_action == "retain":
                if bool(pending.questions) != bool(active.question.questions):
                    raise MasteryInteractionError(
                        "An incompatible question is already pending; retain it or explicitly "
                        "replace its question_id before creating a group"
                    )
                if pending.questions and self._group_contract(pending) != self._group_contract(
                    active.question
                ):
                    raise MasteryInteractionError(
                        "A different group is already pending; explicitly replace its question_id"
                    )
                return active, False
            if pending_action == "replace" and (
                active is None or active.interaction_id != replace_question_id
            ):
                raise StaleInteractionError(
                    replace_question_id, active.interaction_id if active else ""
                )

            leaves = pending.questions or [pending]
            known_ids = {kp.id for module in tx.progress.modules for kp in module.knowledge_points}
            for question in leaves:
                if question.knowledge_point_id not in known_ids:
                    raise MasteryInteractionError(
                        f"Unknown objective {question.knowledge_point_id!r}; refresh mastery_status"
                    )
            from deeptutor.learning.lesson_evidence import LessonUnavailable, question_snapshot

            try:
                for question in leaves:
                    if question.source_evidence.get("assessment_contract"):
                        from deeptutor.learning.semantic_assessment import validate_question

                        validate_question(self._store, tx.progress, question)
                    else:
                        question.source_evidence = question_snapshot(
                            self._store, tx.progress, question.knowledge_point_id
                        )
                    question.assistance_context = {"session_id": session_id, "turn_id": turn_id}
                    question.created_at = time.time()
                    _apply_source_assistance(tx.progress, question)
            except LessonUnavailable as exc:
                raise MasteryInteractionError(str(exc)) from exc
            if active is not None:
                active.status = InteractionStatus.ABANDONED
                tx.put_interaction(active)
                tx.emit(
                    "interaction.abandoned",
                    {
                        "interaction_id": active.interaction_id,
                        "reason": "explicit_replacement",
                        "replacement_id": pending.question_id,
                    },
                    session_id=session_id,
                    turn_id=turn_id,
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
            for question in leaves:
                tx.progress.deferred_objectives.pop(question.knowledge_point_id, None)
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
        answers: dict[str, str] | None = None,
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
            if interaction.question.questions:
                if interaction.status == InteractionStatus.ABANDONED:
                    raise NoPendingInteractionError("The question was abandoned")
                submitted = self._merge_group_answers(interaction, answers)
                if submitted == interaction.answers:
                    return interaction
                interaction.answers = submitted
                complete = len(submitted) == len(interaction.question.questions)
                interaction.status = (
                    InteractionStatus.ANSWERED if complete else InteractionStatus.AWAITING_INPUT
                )
                interaction.session_id = session_id or interaction.session_id
                interaction.turn_id = turn_id or interaction.turn_id
                tx.put_interaction(interaction)
                tx.emit(
                    "interaction.answered" if complete else "interaction.answers_recorded",
                    {"interaction_id": interaction.interaction_id, "complete": complete},
                    session_id=interaction.session_id,
                    turn_id=interaction.turn_id,
                )
                return interaction
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
                and interaction.result.get("final") is False
            ):
                tx.emit(
                    "assessment.revised",
                    {
                        "question_id": interaction.interaction_id,
                        "previous_answer": interaction.user_answer,
                        "previous_result": interaction.result,
                    },
                    session_id=session_id,
                    turn_id=turn_id,
                )
                interaction.user_answer = str(answer or "")
                interaction.session_id = session_id or interaction.session_id
                interaction.turn_id = turn_id or interaction.turn_id
                tx.put_interaction(interaction)
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
        answers: dict[str, str] | None = None,
        answer_for_grading: str | None = None,
        expected_answer: str | None = None,
        resolved_choice_options: dict[str, str] | None = None,
        scheduler: SpacedRepetitionScheduler | None = None,
        session_id: str = "",
        turn_id: str = "",
        _assessment: dict | None = None,
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
                if interaction.question.questions and answers is not None:
                    self._merge_group_answers(interaction, answers)
                return interaction, True
            if interaction.status == InteractionStatus.ABANDONED:
                raise NoPendingInteractionError("The question was abandoned")
            if _assessment:
                from deeptutor.learning.lesson_evidence import objective_fingerprint
                from deeptutor.learning.semantic_assessment import fingerprint

                if fingerprint(interaction.model_dump()) != _assessment["state"] or any(
                    objective_fingerprint(tx.progress, key) != value
                    for key, value in _assessment["objectives"].items()
                ):
                    raise MasteryInteractionError(
                        "The question, answer or objective changed during assessment; retry."
                    )
                for question in interaction.question.questions or [interaction.question]:
                    if question.question_id in _assessment.get("sources", {}):
                        question.source_evidence = _assessment["sources"][question.question_id]

            if interaction.question.questions:
                return self._grade_group(
                    tx,
                    interaction,
                    answers=answers,
                    scheduler=scheduler,
                    session_id=session_id,
                    turn_id=turn_id,
                    verdicts=_assessment["verdicts"] if _assessment else None,
                )

            from deeptutor.learning.lesson_evidence import LessonUnavailable

            try:
                from deeptutor.learning.semantic_assessment import validate_question

                validate_question(self._store, tx.progress, interaction.question)
            except LessonUnavailable as exc:
                raise MasteryInteractionError(str(exc)) from exc

            raw_answer, is_correct, visual_result, visual_diagnosis = self._evaluate_question(
                tx,
                interaction,
                answer=answer,
                answer_for_grading=answer_for_grading,
                expected_answer=expected_answer,
                resolved_choice_options=resolved_choice_options,
                scheduler=scheduler,
                session_id=session_id,
                turn_id=turn_id,
                verdict=(_assessment or {})
                .get("verdicts", {})
                .get(interaction.question.question_id),
            )
            pending = interaction.question
            receipt = (_assessment or {}).get("verdicts", {}).get(pending.question_id, {})
            if visual_result == "ungraded" and not receipt:
                receipt = {
                    "result": "ungraded",
                    "final": False,
                    "needs_clarification": True,
                    "feedback": visual_diagnosis,
                    "confidence": None,
                    "is_correct": None,
                }
            if (
                tx.progress.pending_question is not None
                and tx.progress.pending_question.question_id == pending.question_id
                and receipt.get("final", True)
            ):
                tx.progress.pending_question = None
            interaction.status = (
                InteractionStatus.GRADED
                if receipt.get("final", True)
                else InteractionStatus.ANSWERED
            )
            interaction.user_answer = raw_answer
            interaction.session_id = session_id or interaction.session_id
            interaction.turn_id = turn_id or interaction.turn_id
            interaction.result = {
                "is_correct": is_correct,
                "knowledge_point_id": pending.knowledge_point_id,
                **receipt,
                "independent": _question_independent(pending),
            }
            if pending.visual_context:
                interaction.result.update(
                    {
                        "result": visual_result,
                        "diagnosis": visual_diagnosis,
                        "visual_context": pending.visual_context,
                        "independent": _question_independent(pending),
                    }
                )
            tx.put_interaction(interaction)
            tx.emit(
                "practice.ungraded" if visual_result == "ungraded" else "attempt.recorded",
                {
                    "interaction_id": interaction.interaction_id,
                    "knowledge_point_id": pending.knowledge_point_id,
                    "is_correct": is_correct,
                },
                session_id=interaction.session_id,
                turn_id=interaction.turn_id,
            )
            if visual_result != "ungraded" and tx.progress.learning_evidence:
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

    @staticmethod
    def _group_contract(pending: PendingQuestion) -> list[tuple]:
        # Choice shuffling changes labels, not the answer contract. Ignore new
        # generated ids when a duplicate tool call re-presents the same group.
        return [
            (
                q.knowledge_point_id,
                q.prompt,
                q.question_type,
                tuple(sorted(q.choice_map.values())),
                q.choice_map.get(q.expected_answer, q.expected_answer),
                q.explanation,
                q.difficulty,
                q.visual_context,
            )
            for q in pending.questions
        ]

    @staticmethod
    def _validate_group_answers(pending: PendingQuestion, answers: Any) -> dict[str, str]:
        ids = {question.question_id for question in pending.questions}
        if (
            not isinstance(answers, dict)
            or not answers
            or not set(answers).issubset(ids)
            or any(
                not isinstance(value, str) or not value.strip() or len(value) > 10000
                for value in answers.values()
            )
        ):
            raise MasteryInteractionError(
                "Supply at least one actual answer using its exact group question_id"
            )
        from deeptutor.learning.pending import resolve_choice_submission

        for question in pending.questions:
            if (
                question.question_id in answers
                and question.question_type == "choice"
                and not resolve_choice_submission(
                    answers[question.question_id], question.choice_map
                )
            ):
                raise MasteryInteractionError(
                    "Choose one unambiguous option for each choice question"
                )
        return {key: value.strip() for key, value in answers.items()}

    def _merge_group_answers(self, interaction: MasteryInteraction, answers: Any) -> dict[str, str]:
        submitted = self._validate_group_answers(
            interaction.question, interaction.answers if answers is None else answers
        )
        revisable = {
            row["question_id"]
            for row in interaction.result.get("results", [])
            if row.get("final") is False
        }
        if any(
            key in interaction.answers
            and interaction.answers[key] != value
            and key not in revisable
            for key, value in submitted.items()
        ):
            raise MasteryInteractionError("This group already has a different committed answer")
        return {**interaction.answers, **submitted}

    @staticmethod
    def _group_result(pending: PendingQuestion, results: list[dict]) -> dict:
        values = [result["is_correct"] for result in results]
        graded_ids = {result["question_id"] for result in results if result.get("final", True)}
        remaining = [q.question_id for q in pending.questions if q.question_id not in graded_ids]
        complete = not remaining
        outcomes = {
            row.get("result") or ("correct" if row["is_correct"] else "incorrect")
            for row in results
        }
        return {
            "question_id": pending.question_id,
            "question_type": "group",
            "results": results,
            "complete": complete,
            "final": complete,
            "needs_clarification": any(row.get("needs_clarification", False) for row in results),
            "remaining_question_ids": remaining,
            "is_correct": None if not complete or None in values else all(values),
            "result": "ungraded"
            if not complete
            else next(iter(outcomes))
            if len(outcomes) == 1
            else "mixed",
        }

    def _grade_group(
        self,
        tx,
        interaction: MasteryInteraction,
        *,
        answers,
        scheduler=None,
        session_id="",
        turn_id="",
        verdicts=None,
    ) -> tuple[MasteryInteraction, bool]:
        """Commit new replies once; unanswered siblings remain awaiting input."""
        pending = interaction.question
        submitted = self._merge_group_answers(interaction, answers)
        known_ids = {kp.id for module in tx.progress.modules for kp in module.knowledge_points}
        if any(q.knowledge_point_id not in known_ids for q in pending.questions):
            raise MasteryInteractionError("An objective changed; refresh the question group")
        from deeptutor.learning.lesson_evidence import LessonUnavailable
        from deeptutor.learning.question_card import build_grade_result

        leaves = []
        for question in pending.questions:
            if question.question_id not in submitted:
                continue
            stored = tx.get_interaction(question.question_id)
            if stored is not None and (
                stored.result.get("group_question_id") != pending.question_id
                or stored.question.knowledge_point_id != question.knowledge_point_id
                or stored.user_answer != submitted[question.question_id]
                and stored.result.get("final", True)
            ):
                raise MasteryInteractionError("This child belongs to another interaction or reply")
            if (
                stored is None
                or stored.status != InteractionStatus.GRADED
                or not stored.result.get("final", True)
            ):
                try:
                    from deeptutor.learning.semantic_assessment import validate_question

                    validate_question(self._store, tx.progress, question)
                except LessonUnavailable as exc:
                    raise MasteryInteractionError(str(exc)) from exc
            leaves.append((question, stored))

        results = []
        new_results = False
        for question, stored in leaves:
            if (
                stored is not None
                and stored.status == InteractionStatus.GRADED
                and stored.result.get("final", True)
            ):
                results.append(self._group_leaf_result(stored))
                continue
            new_results = True
            if stored:
                tx.emit(
                    "assessment.revised",
                    {
                        "question_id": question.question_id,
                        "previous_answer": stored.user_answer,
                        "previous_result": stored.result,
                    },
                    session_id=session_id,
                    turn_id=turn_id,
                )
            leaf = MasteryInteraction(
                interaction_id=question.question_id,
                path_id=interaction.path_id,
                question=question,
                status=InteractionStatus.ANSWERED,
                user_answer=submitted[question.question_id],
            )
            raw, correct, visual_result, diagnosis = self._evaluate_question(
                tx,
                leaf,
                answer=submitted[question.question_id],
                scheduler=scheduler,
                session_id=session_id,
                turn_id=turn_id,
                verdict=(verdicts or {}).get(question.question_id),
            )
            result = build_grade_result(
                question_id=question.question_id,
                is_correct=bool(correct),
                learner_answer=raw,
                correct_label=question.expected_answer if correct is not None else "",
                choice_options=question.choice_map,
                explanation=question.explanation if correct is not None else diagnosis,
                result=visual_result,
                final=correct is not None,
                needs_clarification=correct is None,
                feedback=diagnosis,
                independent=_question_independent(question),
            )
            result["is_correct"] = correct
            result.update((verdicts or {}).get(question.question_id, {}))
            result["knowledge_point_id"] = question.knowledge_point_id
            if diagnosis:
                result["diagnosis"] = diagnosis
            results.append(result)
            leaf.session_id = session_id or interaction.session_id
            leaf.turn_id = turn_id or interaction.turn_id
            leaf.status = InteractionStatus.GRADED
            leaf.result = {**result, "group_question_id": pending.question_id}
            tx.put_interaction(leaf)
            tx.emit(
                "practice.ungraded" if correct is None else "attempt.recorded",
                {
                    "interaction_id": interaction.interaction_id,
                    "question_id": question.question_id,
                    "knowledge_point_id": question.knowledge_point_id,
                    "is_correct": correct,
                },
                session_id=session_id,
                turn_id=turn_id,
            )
            if correct is not None or result.get("result") == "partial":
                evidence = tx.progress.learning_evidence[-1]
                tx.emit(
                    "evidence.recorded",
                    {
                        "knowledge_point_id": evidence.knowledge_point_id,
                        "assessment_type": evidence.assessment_type,
                        "result": evidence.result,
                        "quality": evidence.quality,
                    },
                    session_id=session_id,
                    turn_id=turn_id,
                )
        if not new_results:
            return interaction, True
        interaction.result = self._group_result(pending, results)
        complete = interaction.result["complete"]
        interaction.status = (
            InteractionStatus.GRADED
            if complete
            else InteractionStatus.ANSWERED
            if interaction.status == InteractionStatus.ANSWERED
            else InteractionStatus.AWAITING_INPUT
        )
        interaction.answers = submitted
        interaction.session_id = session_id or interaction.session_id
        interaction.turn_id = turn_id or interaction.turn_id
        if complete:
            tx.progress.pending_question = None
        tx.put_interaction(interaction)
        tx.emit(
            "interaction.graded" if complete else "interaction.partially_graded",
            dict(interaction.result),
            session_id=interaction.session_id,
            turn_id=interaction.turn_id,
        )
        return interaction, False

    def _evaluate_question(
        self,
        tx,
        interaction: MasteryInteraction,
        *,
        answer: str,
        answer_for_grading: str | None = None,
        expected_answer: str | None = None,
        resolved_choice_options: dict[str, str] | None = None,
        scheduler: SpacedRepetitionScheduler | None = None,
        session_id: str = "",
        turn_id: str = "",
        verdict: dict | None = None,
    ) -> tuple[str, bool | None, str, str]:
        """Shared leaf grader: never creates a parent attempt or commits separately."""
        pending = interaction.question
        _apply_source_assistance(tx.progress, pending)
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
                    graded_answer = resolve_choice_submission(raw_answer, option_map) or raw_answer
                else:
                    # Legacy questions may need option bodies recovered by
                    # the trusted tool adapter from the original turn.
                    graded_answer = raw_answer if answer_for_grading is None else answer_for_grading
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
        visual_result = ""
        visual_diagnosis = ""
        if pending.visual_context:
            from deeptutor.learning.visual_practice import (
                account_for_recent_assistance,
                evaluate_visual,
            )

            pending.visual_context = account_for_recent_assistance(
                pending.visual_context, tx.progress.quiz_attempts, pending.knowledge_point_id
            )
            visual_result, visual_diagnosis = evaluate_visual(pending, raw_answer)
            if (
                tx.progress.explained_objectives.get(pending.knowledge_point_id, {}).get(
                    "timestamp", 0
                )
                > pending.created_at
            ):
                pending.visual_context["hints_used"] = max(
                    1, pending.visual_context.get("hints_used", 0)
                )
                pending.visual_context["teaching_after_question"] = True
            if visual_result == "correct":
                graded_answer = authoritative_answer
            if verdict and verdict["final"]:
                from deeptutor.learning.visual_practice import verified_visual_images

                try:
                    verified_visual_images(pending)
                except ValueError as exc:
                    raise MasteryInteractionError(str(exc)) from exc
                visual_result = verdict["result"]
        is_correct = (
            None
            if visual_result == "ungraded" or verdict and not verdict["final"]
            else self._apply_grade(
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
                visual_context=pending.visual_context,
                assistance_used=pending.assistance_used,
                verdict=verdict,
            )
        )
        if verdict:
            is_correct = verdict["is_correct"]
            visual_result = verdict["result"]
            visual_diagnosis = verdict["feedback"]
        return raw_answer, is_correct, visual_result, visual_diagnosis

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

        progress, _ = self._store.mutate(
            book_id,
            lambda tx: self._replace_module_set(
                tx,
                modules,
                append=append,
                name=name,
                event_type=event_type,
                session_id=session_id,
                turn_id=turn_id,
                identity_mode=identity_mode,
                relation_refs=relation_refs,
                source_aliases=source_aliases,
                topic_sources=topic_sources,
                fresh_identity=fresh_identity,
            ),
            create=True,
        )
        return progress

    def _replace_module_set(
        self,
        tx,
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
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Shared identity, relation and question effects for preview and save."""
        active_interaction_removed = False
        book_id = tx.progress.book_id
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
                    current_kp_id = current_module.knowledge_points[tx.progress.current_kp_index].id
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
                pending_leaves = tx.progress.pending_question.questions or [
                    tx.progress.pending_question
                ]
                if pending_kp_id not in objective_locations or any(
                    q.knowledge_point_id not in objective_locations for q in pending_leaves
                ):
                    tx.progress.pending_question = None
                else:
                    tx.progress.pending_question.module_id = objective_locations[pending_kp_id][0]
                    for question in pending_leaves:
                        question.module_id = objective_locations[question.knowledge_point_id][0]

            if active_interaction is not None:
                active_leaves = active_interaction.question.questions or [
                    active_interaction.question
                ]
                active_interaction_removed = active_kp_id not in objective_locations or any(
                    q.knowledge_point_id not in objective_locations for q in active_leaves
                )
                if active_interaction_removed:
                    if not dry_run:
                        tx.abandon_active_interactions()
                else:
                    active_module_id = objective_locations[active_kp_id][0]
                    active_changed = (
                        active_interaction.question.module_id != active_module_id
                        or any(
                            question.module_id
                            != objective_locations[question.knowledge_point_id][0]
                            for question in active_leaves
                        )
                    )
                    active_interaction.question.module_id = active_module_id
                    for question in active_leaves:
                        question.module_id = objective_locations[question.knowledge_point_id][0]
                    if active_changed and not dry_run:
                        tx.put_interaction(active_interaction)
        if not dry_run:
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
        return {
            "identity_map": identity_map,
            "active_interaction_removed": active_interaction_removed,
        }

    def preview_module_revision(
        self,
        book_id: str,
        modules: list[LearningModule],
        *,
        expected_revision: int,
        session_id: str,
        request_id: str = "",
    ) -> tuple[dict[str, Any], LearningProgress]:
        """Run the real replacement engine on a copy, then record the reviewed draft."""
        from deeptutor.learning.outline_revision import exact_diff, state_digest
        from deeptutor.learning.storage import LearningConflictError

        with self._store.transaction(book_id) as tx:
            if tx.base_revision != expected_revision:
                raise LearningConflictError(book_id, expected_revision, tx.base_revision)
            original = tx.progress
            tx.progress = original.model_copy(deep=True)
            try:
                effects = self._replace_module_set(tx, modules, dry_run=True)
                proposed = tx.progress.model_copy(deep=True)
            finally:
                tx.progress = original
            # Save-time bookkeeping is not a curriculum change or progress reset.
            exclude = {"version", "updated_at"}
            changes = exact_diff(
                original.model_dump(mode="json", exclude=exclude),
                proposed.model_dump(mode="json", exclude=exclude),
            )
            if not changes:
                raise ValueError("This plan changes nothing. Leave the current outline in place.")
            payload = {
                "base_revision": expected_revision,
                "request_id": request_id,
                "before_digest": state_digest(original),
                "after_digest": state_digest(proposed),
                "modules": [module.model_dump(mode="json") for module in proposed.modules],
                "changes": changes,
                "effects": effects,
                "before_module_order": [module.id for module in original.modules],
                "proposed_module_order": [module.id for module in proposed.modules],
            }
            preview_id = tx.record_module_preview(payload, session_id=session_id)
        return {
            "preview_id": preview_id,
            "base_revision": expected_revision,
            "changes": changes,
            "effects": effects,
            "before_module_order": payload["before_module_order"],
            "proposed_module_order": payload["proposed_module_order"],
            "module_order_changed": (
                payload["before_module_order"] != payload["proposed_module_order"]
            ),
        }, proposed

    def commit_module_revision(
        self,
        book_id: str,
        preview_id: int,
        *,
        session_id: str,
        turn_id: str = "",
        request_id: str = "",
    ) -> tuple[LearningProgress, dict[str, Any]]:
        """Apply only the persisted draft; stale state rolls back instead of overwriting."""
        from deeptutor.learning.outline_revision import state_digest
        from deeptutor.learning.storage import LearningConflictError

        with self._store.transaction(book_id) as tx:
            draft = tx.module_preview(preview_id, session_id=session_id)
            replayed = draft["committed_revision"] is not None
            if not replayed:
                if draft.get("request_id") and (
                    not request_id or request_id == draft["request_id"]
                ):
                    raise ValueError(
                        "Inspect this preview in a later model round before committing it."
                    )
                expected = int(draft["base_revision"])
                if expected != tx.base_revision:
                    raise LearningConflictError(book_id, expected, tx.base_revision)
                if state_digest(tx.progress) != draft["before_digest"]:
                    raise ValueError(
                        "The outline state changed. Create and review a fresh preview."
                    )
                self._replace_module_set(
                    tx,
                    [LearningModule.model_validate(m) for m in draft["modules"]],
                    session_id=session_id,
                    turn_id=turn_id,
                )
                if state_digest(tx.progress) != draft["after_digest"]:
                    raise ValueError(
                        "The preview no longer matches the engine result. Nothing was saved."
                    )
                tx.emit(
                    "path.modules_revision_committed",
                    {"preview_id": preview_id},
                    session_id=session_id,
                    turn_id=turn_id,
                )
            receipt = {
                "preview_id": preview_id,
                "replayed": replayed,
                "applied_revision": draft["committed_revision"]
                if replayed
                else tx.base_revision + 1,
                "applied_module_order": [module["id"] for module in draft["modules"]],
            }
        return tx.progress, receipt

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
        teaching_updates: list[dict] | None = None,
        expected_revision: int | None = None,
        learner_message: str = "",
        clear_fields: list[str] | None = None,
        clear_request: str = "",
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
            if key in _LEARNER_PROFILE_FIELDS and value is not None and str(value).strip()
        }
        # Optional schema placeholders are not learner-authored deletions.
        # Deletion has its own explicit, quoted, revision-fenced operation.
        if clear_fields is not None and (
            not isinstance(clear_fields, list)
            or any(
                not isinstance(key, str)
                or key not in _LEARNER_PROFILE_FIELDS
                or key == "teaching_strategy"
                for key in clear_fields
            )
        ):
            raise ValueError("clear_fields must name intake text fields")
        if clear_fields:
            if (
                not isinstance(clear_request, str)
                or not clear_request.strip()
                or clear_request not in learner_message
            ):
                raise ValueError(
                    "clear_request must be a literal quote from the current learner message"
                )
            if any(key in cleaned for key in clear_fields):
                raise ValueError("Cannot update and clear the same profile field")
            if type(expected_revision) is not int or expected_revision < 0:
                raise ValueError("clear_fields requires the current path revision")
            cleaned.update({key: "" for key in clear_fields})
        from deeptutor.learning.teaching import apply_teaching_updates, parse_teaching_updates

        updates = (
            parse_teaching_updates(teaching_updates, learner_message)
            if teaching_updates is not None
            else []
        )
        if updates and (type(expected_revision) is not int or expected_revision < 0):
            raise ValueError("teaching_updates requires the current path revision")
        if "teaching_strategy" in cleaned and cleaned["teaching_strategy"] not in {
            "probe_first",
            "teach_first",
        }:
            raise ValueError("teaching_strategy must be probe_first or teach_first")

        def record(tx):
            profile = tx.progress.learner_profile or LearnerProfile()
            teaching_fields = (
                apply_teaching_updates(
                    profile,
                    updates,
                    {kp.id for module in tx.progress.modules for kp in module.knowledge_points},
                    session_id=session_id,
                    turn_id=turn_id,
                )
                if updates
                else {}
            )
            changed = [key for key, value in cleaned.items() if getattr(profile, key) != value]
            changed.extend(teaching_fields)
            if not changed:
                return []
            if (updates or clear_fields) and tx.progress.version != expected_revision:
                from deeptutor.learning.storage import LearningConflictError

                raise LearningConflictError(book_id, expected_revision, tx.progress.version)
            updated = profile.model_copy(
                update={**cleaned, **teaching_fields, "updated_at": time.time()}
            )
            tx.progress.learner_profile = updated
            tx.touch()
            tx.emit(
                "path.learner_profile_recorded",
                {"fields": changed},
                session_id=session_id,
                turn_id=turn_id,
            )
            return changed

        return self._store.mutate(book_id, record, create=not bool(updates or clear_fields))

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
            progress.explained_objectives = {}
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
        _assessment: dict | None = None,
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
            original_expected = question.expected_answer if question is not None else ""
            previous_result = dict(interaction.result) if interaction else {}
            if (
                action_name == "correct"
                and previous_result.get("confidence") is not None
                and not _assessment
            ):
                raise MasteryInteractionError(
                    "A semantic verdict requires semantic re-evaluation; use repair_question_semantic."
                )
            if _assessment:
                from deeptutor.learning.lesson_evidence import (
                    LessonUnavailable,
                    objective_fingerprint,
                )
                from deeptutor.learning.semantic_assessment import fingerprint, validate_question

                if (
                    interaction is None
                    or fingerprint(interaction.model_dump()) != _assessment["state"]
                    or objective_fingerprint(tx.progress, question.knowledge_point_id)
                    != _assessment["objective"]
                ):
                    raise MasteryInteractionError(
                        "Question or answer changed during correction; retry."
                    )
                question = _assessment["question"].model_copy(deep=True)
                try:
                    validate_question(self._store, tx.progress, question)
                except LessonUnavailable as exc:
                    raise MasteryInteractionError(str(exc)) from exc
                interaction.question = question
            if question is not None and question.questions:
                raise MasteryInteractionError(
                    "A group has no aggregate answer key; review or challenge an individual child question_id"
                )
            kp_id = (question.knowledge_point_id if question is not None else "") or (
                attempts[0].knowledge_point_id if attempts else ""
            )
            module_id = (question.module_id if question is not None else "") or (
                attempts[0].module_id if attempts else ""
            )
            question_type = question.question_type if question is not None else "short"
            previous_expected = original_expected
            previous_is_correct = attempts[0].is_correct if attempts else None
            if action_name == "correct" and question is not None and question.visual_context:
                from deeptutor.learning.visual_practice import prepare_visual

                candidate_answer = str(expected_answer or question.expected_answer)
                if not question.visual_context.get("pixels_inspected"):
                    raise MasteryInteractionError(
                        "This visual practice had no verified pixel inspection. Void it and pose a supported replacement; a challenge cannot create mastery evidence."
                    )
                try:
                    corrected_visual, corrected_aliases = prepare_visual(
                        {
                            **question.visual_context,
                            "accepted_answers": [],
                            "key_status": "verified",
                        },
                        expected_answer=candidate_answer,
                        options=question.choice_map,
                    )
                except (OSError, ValueError, TypeError) as exc:
                    raise MasteryInteractionError(
                        "Visual correction lacks current source support; void the assessment and pose a supported replacement."
                    ) from exc
                if corrected_visual["key_status"] != "verified":
                    raise MasteryInteractionError(
                        "Visual correction lacks a source-supported key; void the assessment instead of granting unsupported mastery."
                    )
                question.accepted_answers = corrected_aliases
                question.visual_context = corrected_visual
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
                from deeptutor.learning.lesson_evidence import LessonUnavailable, validate_evidence

                try:
                    if _assessment:
                        validate_question(self._store, tx.progress, question)
                    else:
                        validate_evidence(
                            self._store,
                            tx.progress,
                            kp_id,
                            question.source_evidence if question else {},
                        )
                except LessonUnavailable as exc:
                    raise MasteryInteractionError(str(exc)) from exc
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
                        receipt = _assessment.get("receipt") if _assessment else None
                        is_correct = (
                            receipt["result"] == "correct"
                            if receipt
                            else bool(new_expected)
                            and grade_answer(
                                str(attempt.user_answer or ""),
                                new_expected,
                                question_type,
                            )
                        )
                        attempt.is_correct = is_correct
                        attempt.result = (
                            receipt["result"]
                            if receipt
                            else ("correct" if is_correct else "incorrect")
                        )
                        attempt.error_type = (
                            None
                            if is_correct or attempt.result == "partial"
                            else classify_error(str(attempt.user_answer or ""))
                        )
                        repaired_correct = is_correct
                        if is_correct:
                            for record in tx.progress.error_records:
                                if record.question_id == resolved_id:
                                    record.status = "graduated"
                        elif attempt.result == "partial":
                            tx.progress.error_records = [
                                record
                                for record in tx.progress.error_records
                                if record.question_id != resolved_id
                            ]
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
                    repair_receipt = (_assessment or {}).get("receipt") or {
                        "result": "correct" if repaired_correct else "incorrect",
                        "final": True,
                        "needs_clarification": False,
                        "feedback": note,
                        "confidence": None,
                    }
                    if _assessment and _assessment.get("receipt"):
                        repaired_correct = repair_receipt["is_correct"]
                    interaction.result = {
                        **dict(interaction.result or {}),
                        "is_correct": repaired_correct,
                        "corrected": True,
                        "reason": note,
                        **repair_receipt,
                    }
                    tx.put_interaction(interaction)
                _update_quiz_evidence_for_attempts(
                    tx.progress,
                    [attempt for attempt in attempts if not attempt.voided],
                )

            self._recompute_objective_state(tx.progress, kp_id, scheduler)
            if interaction is not None and interaction.result.get("group_question_id"):
                self._refresh_group_result(tx, interaction)
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
                    "previous_result": previous_result,
                    "learner_answer": user_answer,
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
                "result": interaction.result.get("result", "") if interaction else "",
                "feedback": interaction.result.get("feedback", "") if interaction else "",
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

    @staticmethod
    def _group_leaf_result(stored: MasteryInteraction) -> dict:
        """Project a committed leaf, including later repairs, without regrading."""
        from deeptutor.learning.question_card import build_grade_result

        correct = None if stored.result.get("voided") else stored.result.get("is_correct")
        result = build_grade_result(
            question_id=stored.interaction_id,
            is_correct=bool(correct),
            learner_answer=stored.user_answer,
            correct_label=stored.question.expected_answer if correct is not None else "",
            choice_options=stored.question.choice_map,
            explanation=stored.question.explanation
            if correct is not None
            else str(stored.result.get("reason") or stored.result.get("diagnosis") or ""),
            result="ungraded" if correct is None else "",
            independent=stored.result.get("independent", _question_independent(stored.question)),
        )
        result.update(
            {"is_correct": correct, "knowledge_point_id": stored.question.knowledge_point_id}
        )
        result.update(
            {
                key: stored.result[key]
                for key in ("result", "final", "needs_clarification", "feedback", "confidence")
                if key in stored.result
            }
        )
        if stored.result.get("diagnosis"):
            result["diagnosis"] = stored.result["diagnosis"]
        return result

    def _refresh_group_result(self, tx, leaf: MasteryInteraction) -> None:
        """Keep a complete or partial parent consistent after a native leaf repair."""
        parent = tx.get_interaction(leaf.result["group_question_id"])
        if parent is None:
            return
        results = []
        questions = []
        for question in parent.question.questions:
            stored = tx.get_interaction(question.question_id)
            if stored is None or stored.result.get("group_question_id") != parent.interaction_id:
                questions.append(question)
                continue
            questions.append(stored.question)
            results.append(self._group_leaf_result(stored))
        parent.question.questions = questions
        parent.result = self._group_result(parent.question, results)
        if (
            tx.progress.pending_question is not None
            and tx.progress.pending_question.question_id == parent.interaction_id
        ):
            tx.progress.pending_question = parent.question
        tx.put_interaction(parent)

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
            if pending is not None and any(
                q.knowledge_point_id == target_id for q in pending.questions or [pending]
            ):
                tx.progress.pending_question = None
                abandoned = True
            active = tx.active_interaction()
            if active is not None and any(
                q.knowledge_point_id == target_id
                for q in active.question.questions or [active.question]
            ):
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
        _assessment: dict | None = None,
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
            from deeptutor.learning.lesson_evidence import LessonUnavailable, validate_evidence

            try:
                validate_evidence(
                    self._store, tx.progress, kp_id, tx.progress.lesson_evidence.get(kp_id, {})
                )
                if _assessment:
                    from deeptutor.learning.lesson_evidence import objective_fingerprint
                    from deeptutor.learning.semantic_assessment import fingerprint

                    if (
                        objective_fingerprint(tx.progress, kp_id) != _assessment["objective"]
                        or fingerprint(tx.progress.lesson_evidence.get(kp_id, {}))
                        != _assessment["source"]
                    ):
                        raise MasteryInteractionError(
                            "Objective or source changed during assessment; retry."
                        )
            except LessonUnavailable as exc:
                raise MasteryInteractionError(str(exc)) from exc
            applied = self.record_qualitative_in_memory(
                tx.progress,
                kp_id,
                passed=passed,
                evidence=evidence,
                scheduler=scheduler,
                session_id=session_id,
                turn_id=turn_id,
                verdict=_assessment["receipt"] if _assessment else None,
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
        verdict: dict | None = None,
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
            result=verdict["result"] if verdict else ("correct" if passed else "partial"),
            quality={"correct": 1.0, "partial": 0.5, "incorrect": 0.0}[verdict["result"]]
            if verdict
            else ((1.0 if evidence else 0.9) if passed else 0.2),
            confidence=verdict.get("confidence") if verdict else None,
            learner_answer=evidence,
            feedback=verdict.get("feedback", "") if verdict else "",
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

    async def assess_qualitative_semantic(
        self, book_id, kp_id, *, learner_answer, config=None, **kwargs
    ):
        from deeptutor.learning import semantic_assessment as semantic
        from deeptutor.learning.lesson_evidence import (
            LessonUnavailable,
            objective_fingerprint,
            validate_evidence,
        )
        from deeptutor.learning.policy import find_knowledge_point

        answer = str(learner_answer or "").strip()
        if not answer or len(answer) > 10000:
            raise MasteryInteractionError(
                "Assessment needs the actual learner explanation, at most 10000 characters."
            )
        progress = self._store.load(book_id)
        kp, module_id, _ = find_knowledge_point(progress, kp_id)
        if kp is None:
            raise MasteryInteractionError("Unknown objective")
        session_id, turn_id = kwargs.get("session_id", ""), kwargs.get("turn_id", "")
        if session_id or turn_id:
            evidence_id = uuid.uuid5(
                uuid.NAMESPACE_URL, f"deeptutor:qualitative:{session_id}:{turn_id}:{kp_id}"
            ).hex
            existing = next(
                (item for item in progress.learning_evidence if item.evidence_id == evidence_id),
                None,
            )
            if existing:
                return progress, semantic.Verdict(
                    result=existing.result,
                    confidence=existing.confidence if existing.confidence is not None else 1.0,
                    feedback=existing.feedback or "Previously saved assessment.",
                ).receipt()
        evidence = progress.lesson_evidence.get(kp_id, {})
        try:
            validate_evidence(self._store, progress, kp_id, evidence)
            objective = objective_fingerprint(progress, kp_id)
            decisions = await semantic.judge_answers(
                config,
                [
                    {
                        "question_id": kp_id,
                        "prompt": "Explain this objective in your own words: " + kp.name,
                        "expected_answer": "A complete, accurate explanation of the objective and its relationships; do not infer mastery from acknowledgements or requests.",
                        "objective": kp.model_dump(),
                        "module_id": module_id,
                        "answer": answer,
                        "source_evidence": evidence,
                    }
                ],
            )
        except (semantic.AssessmentUnavailable, LessonUnavailable) as exc:
            raise MasteryInteractionError(str(exc)) from exc
        receipt = decisions[kp_id].receipt()
        if not receipt["final"]:
            return progress, receipt
        progress = self.record_qualitative_for_path(
            book_id,
            kp_id,
            passed=receipt["result"] == "correct",
            evidence=answer,
            _assessment={
                "objective": objective,
                "source": semantic.fingerprint(evidence),
                "receipt": receipt,
            },
            **kwargs,
        )
        return progress, receipt

    async def grade_interaction_semantic(self, book_id: str, *, config=None, **kwargs):
        """Evaluate outside the transaction, then fence every input at commit."""
        from deeptutor.learning import semantic_assessment as semantic
        from deeptutor.learning.lesson_evidence import LessonUnavailable, objective_fingerprint

        question_id = kwargs.get("question_id", "")
        interaction = (
            self._store.get_interaction(book_id, question_id)
            if question_id
            else self._store.get_active_interaction(book_id)
        )
        if interaction is None:
            legacy_progress = self._store.load(book_id)
            legacy = legacy_progress.pending_question if legacy_progress else None
            if legacy is not None and (not question_id or legacy.question_id == question_id):
                interaction = self.record_question_answer(
                    book_id,
                    kwargs.get("answer", ""),
                    answers=kwargs.get("answers"),
                    interaction_id=question_id,
                    session_id=kwargs.get("session_id", ""),
                    turn_id=kwargs.get("turn_id", ""),
                )
        if interaction is None or interaction.status in {
            InteractionStatus.GRADED,
            InteractionStatus.ABANDONED,
        }:
            return self.grade_interaction(book_id, **kwargs)
        progress = self._store.load(book_id)
        state = semantic.fingerprint(interaction.model_dump())
        pending = interaction.question
        answers = (
            self._merge_group_answers(interaction, kwargs.get("answers"))
            if pending.questions
            else {
                pending.question_id: interaction.user_answer
                if interaction.status == InteractionStatus.ANSWERED
                else kwargs.get("answer", "")
            }
        )
        if not pending.questions and pending.question_type == "choice":
            from deeptutor.learning.pending import is_readable_choice_answer

            if not is_readable_choice_answer(answers[pending.question_id], pending.choice_map):
                answers[pending.question_id] = kwargs.get("answer", "")
        verdicts, items, objectives, source_updates = {}, [], {}, {}
        try:
            for question in pending.questions or [pending]:
                if question.question_id not in answers:
                    continue
                if len(answers[question.question_id]) > 10000:
                    raise MasteryInteractionError(
                        "An assessment answer must be at most 10000 characters."
                    )
                stored = (
                    self._store.get_interaction(book_id, question.question_id)
                    if pending.questions
                    else None
                )
                if (
                    stored
                    and stored.status == InteractionStatus.GRADED
                    and stored.result.get("final", True)
                ):
                    continue
                if question.source_evidence and not question.source_evidence.get(
                    "assessment_contract"
                ):
                    await semantic.bind_question(self._store, progress, question, config)
                    source_updates[question.question_id] = question.source_evidence
                semantic.validate_question(self._store, progress, question)
                objectives[question.knowledge_point_id] = objective_fingerprint(
                    progress, question.knowledge_point_id
                )
                if question.visual_context:
                    from deeptutor.learning.visual_practice import (
                        evaluate_visual,
                        verified_visual_images,
                    )

                    visual_result, diagnosis = evaluate_visual(
                        question, answers[question.question_id]
                    )
                    if visual_result in {"correct", "incorrect"}:
                        continue
                    try:
                        images = verified_visual_images(question)
                    except ValueError:
                        # A failed source/key/pixel check remains ungraded; a
                        # semantic model cannot promote missing authority.
                        verdicts[question.question_id] = semantic.Verdict(
                            result="ungraded", confidence=0, feedback=diagnosis
                        ).receipt()
                        continue
                    if question.question_type == "choice":
                        verdicts[question.question_id] = semantic.Verdict(
                            result="ungraded", confidence=0, feedback=diagnosis
                        ).receipt()
                        continue
                    items.append(
                        {
                            **semantic.question_contract(question),
                            "answer": answers[question.question_id],
                            "source_evidence": {},
                            "_visual_images": images,
                        }
                    )
                    continue
                exact = semantic.exact_verdict(question, answers[question.question_id])
                if exact:
                    verdicts[question.question_id] = exact.receipt()
                else:
                    items.append(
                        {
                            **semantic.question_contract(question),
                            "answer": answers[question.question_id],
                            "source_evidence": question.source_evidence,
                        }
                    )
            if items:
                decisions = await semantic.judge_answers(config, items)
                verdicts.update({key: value.receipt() for key, value in decisions.items()})
        except (semantic.AssessmentUnavailable, LessonUnavailable) as exc:
            raise MasteryInteractionError(str(exc)) from exc
        return self.grade_interaction(
            book_id,
            _assessment={
                "state": state,
                "objectives": objectives,
                "verdicts": verdicts,
                "sources": source_updates,
            },
            **kwargs,
        )

    async def repair_question_semantic(self, book_id, question_id="", *, config=None, **kwargs):
        """A challenged grade is corrected durably, with the same source/answer fences."""
        if kwargs.get("action") != "correct":
            return self.repair_question(book_id, question_id, **kwargs)
        from deeptutor.learning import semantic_assessment as semantic
        from deeptutor.learning.lesson_evidence import LessonUnavailable, objective_fingerprint

        progress = self._store.load(book_id)
        interaction = (
            self._store.get_interaction(book_id, question_id)
            if question_id
            else self._store.get_active_interaction(book_id)
        )
        if interaction is None and not question_id and progress.quiz_attempts:
            interaction = self._store.get_interaction(
                book_id, progress.quiz_attempts[-1].question_id
            )
        if interaction is None or interaction.question.questions:
            raise MasteryInteractionError(
                "Correct an exact stored leaf question_id; otherwise void the unsupported record."
            )
        question = interaction.question.model_copy(deep=True)
        question.expected_answer = str(kwargs.get("expected_answer") or "").strip()
        if question.expected_answer != interaction.question.expected_answer:
            question.accepted_answers = []
        if not question.expected_answer:
            raise MasteryInteractionError("Correcting a question requires its answer key.")
        if question.question_type == "choice" and question.choice_map:
            from deeptutor.learning.pending import resolve_choice_submission

            corrected_label = resolve_choice_submission(
                question.expected_answer, question.choice_map
            )
            if not corrected_label:
                raise MasteryInteractionError("The corrected key must identify one stored option.")
            question.expected_answer = corrected_label
            kwargs["expected_answer"] = corrected_label
        answers = {
            str(a.user_answer or "")
            for a in progress.quiz_attempts
            if a.question_id == interaction.interaction_id and not a.voided
        }
        if len(answers) > 1:
            raise MasteryInteractionError(
                "This legacy question has multiple distinct attempts; void it rather than overwriting their independent decisions."
            )
        answer = next(iter(answers), interaction.user_answer)
        receipt = None
        try:
            if question.visual_context:
                from deeptutor.learning.visual_practice import (
                    prepare_visual,
                    verified_visual_images,
                )

                question.visual_context, question.accepted_answers = prepare_visual(
                    {**question.visual_context, "accepted_answers": [], "key_status": "verified"},
                    expected_answer=question.expected_answer,
                    options=question.choice_map,
                )
                images = verified_visual_images(question)
            else:
                images = []
            await semantic.bind_question(self._store, progress, question, config)
            if answer:
                exact = semantic.exact_verdict(question, answer)
                if exact:
                    receipt = exact.receipt()
                else:
                    decisions = await semantic.judge_answers(
                        config,
                        [
                            {
                                **semantic.question_contract(question),
                                "answer": answer,
                                "source_evidence": question.source_evidence,
                                "_visual_images": images,
                            }
                        ],
                    )
                    receipt = decisions[question.question_id].receipt()
                if not receipt["final"]:
                    raise MasteryInteractionError(
                        "The challenged grade remains uncertain; clarify or void it. No correction was saved."
                    )
        except (semantic.AssessmentUnavailable, LessonUnavailable, ValueError) as exc:
            raise MasteryInteractionError(str(exc)) from exc
        return self.repair_question(
            book_id,
            interaction.interaction_id,
            _assessment={
                "state": semantic.fingerprint(interaction.model_dump()),
                "objective": objective_fingerprint(progress, question.knowledge_point_id),
                "question": question,
                "receipt": receipt,
            },
            **kwargs,
        )


__all__ = [
    "LearningService",
    "MasteryInteractionError",
    "NoPendingInteractionError",
    "StaleInteractionError",
]
