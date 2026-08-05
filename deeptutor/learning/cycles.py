"""LRN-03 Feynman cycle orchestration.

This module is the LRN-03-owned seam between the mastery tools/API and the
append-only aggregates built by LRN-01 plus the evidence gate and mastery/
review projection from LRN-02. It owns the attempt lifecycle
(``mastery_cycle_start`` / ``mastery_record_evidence`` / ``mastery_finalize``),
challenge/resume actions, versioned map edit/confirm, and conflict
resolve/reopen. It never calls an LLM and never reaches the network.

Design contract (spec §6-§8, §17.2):

* Server-injected identity — path/session/turn/message/user — is the only
  identity ever bound to evidence; model-supplied values are ignored.
* Evidence is append-only and idempotent: the same ``event_id`` with the same
  payload replays the prior result, the same key with a different payload is a
  stable conflict, and a stale ``expected_attempt_version`` is a recoverable
  version conflict (never an overwrite).
* ``mastery_finalize`` never accepts ``passed`` — the LRN-02 server gate is
  the only path to a pass.
* Conflict resolve/reopen are owner-only, preserve both source sides, and only
  select a snapshot already listed on the conflict.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
import uuid

from deeptutor.learning.grading import (
    REQUIRED_EVIDENCE_KINDS,
    record_server_gate,
    rotate_chain_for_full_explanation,
    validate_evidence_chain,
)
from deeptutor.learning.models import (
    AttemptCycleType,
    AttemptStatus,
    ChallengeMode,
    ChallengeRecord,
    ChallengeStatus,
    ConflictStatus,
    EvaluatorSnapshot,
    EvidenceItem,
    EvidenceKind,
    FeynmanAttempt,
    GapRecord,
    GapStatus,
    HelpLevel,
    InputMode,
    KnowledgeMapVersion,
    MasteryState,
    RubricAssessment,
    RubricScores,
    SourceCitation,
    SourceConflict,
)
from deeptutor.learning.policy import find_knowledge_point, next_objective, project_all
from deeptutor.learning.scheduler import SpacedRepetitionScheduler
from deeptutor.learning.storage import (
    LearningStore,
    VersionConflictError,
    append_history,
    apply_map_version,
    bump_aggregate_version,
    next_assessment_sequence,
)

#: Attempt statuses that may still collect evidence / be finalised.
_LIVE_ATTEMPT_STATUSES = frozenset(
    {
        AttemptStatus.DRAFT,
        AttemptStatus.COLLECTING,
        AttemptStatus.READY_TO_ASSESS,
    }
)

#: Evidence kinds produced by the learner (voice transcripts must confirm).
_LEARNER_EVIDENCE_KINDS = frozenset(
    {
        EvidenceKind.EXPLANATION,
        EvidenceKind.PROBE_ANSWER,
        EvidenceKind.TRANSFER_ANSWER,
    }
)

_ALLOWED_CYCLE_TYPES: frozenset[str] = frozenset(
    {cycle.value for cycle in AttemptCycleType if cycle != AttemptCycleType.LEGACY_IMPORT}
)


class FeynmanError(Exception):
    """Base for recoverable LRN-03 domain errors."""


class OwnershipError(FeynmanError):
    """A non-owner tried to mutate a path (resolve/reopen/map edit)."""


class InvalidAttemptStateError(FeynmanError):
    """An attempt is not in a state that permits the requested operation."""


class EvidenceOrderError(FeynmanError):
    """An evidence item violates the Feynman chain ordering."""


class EvidenceConflictError(FeynmanError):
    """The same evidence event id was reused with a different payload."""


class IdempotencyConflictError(FeynmanError):
    """The same idempotency key was reused with a different payload.

    Applied to map edit/confirm, conflict resolve/reopen, finalize and
    challenge creation: the same key plus the same full payload replays the
    exact prior result, while the same key plus a different payload is a stable
    conflict (spec §8.3).
    """


class StaleVersionError(FeynmanError):
    """The caller holds a stale expected version (recoverable, never overwrite)."""


class ConflictResolutionError(FeynmanError):
    """A conflict resolution is invalid (e.g. snapshot not listed on conflict)."""


class UnknownAttemptError(FeynmanError):
    """The referenced attempt does not exist."""


class UnknownConflictError(FeynmanError):
    """The referenced conflict does not exist."""


def _content_hash(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _fingerprint(payload: dict[str, Any]) -> str:
    """Canonical SHA-256 of a request payload for idempotency replay.

    Server-generated timestamps/ids are excluded by construction: callers only
    pass request fields. ``sort_keys`` keeps the digest stable regardless of
    dict insertion order.
    """
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _citation_payload(citations: list[SourceCitation]) -> list[dict[str, str]]:
    """Stable serialization of source citations for fingerprinting."""
    return sorted(
        ({"source_snapshot_id": c.source_snapshot_id, "anchor": c.anchor} for c in citations),
        key=lambda c: (c["source_snapshot_id"], c["anchor"]),
    )


def _latest_map_version(progress) -> KnowledgeMapVersion | None:
    if not progress.map_versions:
        return None
    return max(progress.map_versions, key=lambda version: (version.version, version.confirmed_at))


def _current_conflict(progress: object, conflict_id: str) -> SourceConflict | None:
    """The newest revision of ``conflict_id`` (SourceConflict is versioned)."""
    revisions = [c for c in progress.source_conflicts if c.id == conflict_id]
    if not revisions:
        return None
    return max(revisions, key=lambda conflict: conflict.version)


def _latest_assessment_for_attempt(progress, attempt_id: str) -> RubricAssessment | None:
    assessments = [a for a in progress.rubric_assessments if a.attempt_id == attempt_id]
    if not assessments:
        return None
    return max(
        assessments,
        key=lambda assessment: (
            assessment.assessment_sequence,
            assessment.created_at,
            assessment.id,
        ),
    )


def _path_owner(progress) -> str:
    """Owner recorded when the path was first claimed, or ``""`` if unclaimed."""
    for event in progress.history:
        if event.event_type == "path_owner":
            return str(event.payload.get("owner_id") or "")
    return ""


def _require_owner(progress, actor_id: str) -> None:
    """Claim the path for *actor_id* if unclaimed, else require they own it.

    Paths are per-user workspaces; a path with no recorded owner is claimed by
    the first actor who mutates it. Once claimed, only that owner may resolve/
    reopen conflicts or edit/confirm the map.
    """
    owner = _path_owner(progress)
    if not owner:
        if actor_id:
            append_history(
                progress,
                "path_owner",
                summary="path owner claimed",
                payload={"owner_id": actor_id},
            )
        return
    if actor_id and owner != actor_id:
        raise OwnershipError(f"path is owned by {owner!r}; {actor_id!r} is not the owner")


class EvaluatorResolutionError(FeynmanError):
    """No valid configured evaluator could be resolved at attempt start (§9.3).

    The production resolver fails closed: it never fabricates a nonempty
    snapshot and never falls back to another model. Raising this from
    ``start_cycle``/``create_challenge`` is the stable sanitized outcome the
    tool/API surface maps onto a recoverable error.
    """


class FeynmanCycleService:
    """Attempt/evidence/finalize + map/conflict orchestration over the store."""

    def __init__(
        self,
        store: LearningStore | None = None,
        *,
        evaluator_resolver: Any = None,
    ) -> None:
        self._store = store or LearningStore()
        #: ``resolver(progress, *, now) -> EvaluatorSnapshot`` freezes the real
        #: evaluator at attempt start. ``None`` keeps the legacy empty snapshot
        #: (historical data stays loadable); the production wiring always passes
        #: :func:`production_evaluator_resolver`.
        self._evaluator_resolver = evaluator_resolver

    def load(self, path_id: str):
        return self._store.load(path_id)

    def save(self, progress) -> None:
        """Persist, translating a stale-snapshot write into a recoverable error.

        The store's CAS never clobbers append-only history; LRN-03 surfaces the
        same boundary as a recoverable :class:`StaleVersionError` so callers can
        return the current version instead of overwriting.
        """
        try:
            self._store.save(progress)
        except VersionConflictError as exc:
            raise StaleVersionError(
                f"stale save rejected: expected {exc.expected_version}, "
                f"persisted {exc.persisted_version}"
            ) from exc

    # ── attempt lifecycle ──────────────────────────────────────────────────

    def start_cycle(
        self,
        progress,
        *,
        knowledge_point_id: str,
        cycle_type: str,
        session_id: str = "",
        turn_id: str = "",
        supersedes_attempt_id: str = "",
        now: float | None = None,
    ) -> FeynmanAttempt:
        """Idempotently create or resume a valid attempt (§8.1, requirement 2).

        A live (draft/collecting/ready-to-assess) attempt for the knowledge
        point is resumed as-is. Otherwise a fresh attempt is created that freezes
        the latest confirmed map version's source bindings. Invalidated or
        closed attempts are never reused — their evidence stays read-only.
        """
        moment = now if now is not None else time.time()
        cycle_value = str(cycle_type or "initial")
        if cycle_value not in _ALLOWED_CYCLE_TYPES:
            raise FeynmanError(f"unsupported cycle_type: {cycle_value!r}")
        cycle = AttemptCycleType(cycle_value)

        # The knowledge point must exist on the path before an attempt binds it.
        kp, _, _ = find_knowledge_point(progress, knowledge_point_id)
        if kp is None:
            raise FeynmanError(f"knowledge_point_id {knowledge_point_id!r} is not on the path")

        live = next(
            (
                attempt
                for attempt in progress.attempts
                if attempt.knowledge_point_id == knowledge_point_id
                and attempt.status in _LIVE_ATTEMPT_STATUSES
            ),
            None,
        )
        if live is not None:
            return live
        return self._create_attempt(
            progress,
            knowledge_point_id=knowledge_point_id,
            cycle=cycle,
            session_id=session_id,
            turn_id=turn_id,
            supersedes_attempt_id=supersedes_attempt_id,
            now=moment,
        )

    def _create_attempt(
        self,
        progress,
        *,
        knowledge_point_id: str,
        cycle: AttemptCycleType,
        session_id: str,
        turn_id: str,
        supersedes_attempt_id: str,
        now: float,
    ) -> FeynmanAttempt:
        """Build and append a fresh attempt freezing current map/source bindings."""
        map_version = _latest_map_version(progress)
        if map_version is None:
            # Do not create an unbound attempt that would later inherit a
            # different map through the grading fallback (§7.7, finding 9).
            raise FeynmanError(
                "no confirmed map/source basis exists; confirm the map and its "
                "source snapshots before starting an attempt"
            )
        attempt_id = uuid.uuid4().hex
        attempt = FeynmanAttempt(
            id=attempt_id,
            knowledge_point_id=knowledge_point_id,
            cycle_type=cycle,
            status=AttemptStatus.COLLECTING,
            knowledge_point_version=map_version.version if map_version else 0,
            map_version_id=map_version.id if map_version else "",
            source_snapshot_ids=list(map_version.source_snapshot_ids) if map_version else [],
            supersedes_attempt_id=supersedes_attempt_id,
            session_id=session_id,
            started_turn_id=turn_id,
            active_chain_id=f"{attempt_id}:chain:1",
            max_help_level=HelpLevel.QUESTION,
            evaluator_snapshot=self._resolve_evaluator_snapshot(progress, now=now),
            created_at=now,
            updated_at=now,
        )
        progress.attempts.append(attempt)
        append_history(
            progress,
            "attempt_started",
            aggregate="attempt",
            summary=f"{cycle.value} attempt {attempt_id} for {knowledge_point_id}",
            payload={
                "attempt_id": attempt_id,
                "knowledge_point_id": knowledge_point_id,
                "cycle_type": cycle.value,
                "map_version_id": attempt.map_version_id,
                "supersedes_attempt_id": supersedes_attempt_id,
            },
        )
        return attempt

    def _resolve_evaluator_snapshot(self, progress, *, now: float) -> EvaluatorSnapshot:
        """Freeze the evaluator configuration at attempt start (§7.6/§9.3).

        The production resolver (``evaluator_resolver``) resolves the learning
        path's configured evaluator — or the active LLM profile default — and
        freezes the non-secret snapshot. No LLM call is made. A service built
        without a resolver keeps the legacy empty snapshot so historical
        attempts stay loadable.
        """
        if self._evaluator_resolver is None:
            return EvaluatorSnapshot(created_at=now)
        snapshot = self._evaluator_resolver(progress, now=now)
        return snapshot if snapshot is not None else EvaluatorSnapshot(created_at=now)

    def record_evidence(
        self,
        progress,
        *,
        attempt_id: str,
        kind: str,
        event_id: str,
        content: str,
        identity: dict[str, str],
        question_evidence_id: str = "",
        source_citations: list[SourceCitation] | None = None,
        input_mode: str = "text",
        transcript_confirmed: bool = False,
        help_level: str | None = None,
        expected_attempt_version: int | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Append one evidence item bound to trusted server identity (§8.1).

        Returns a result dict; on an idempotent replay it returns the prior
        item's result, and on an event-key reuse with a different payload it
        raises :class:`EvidenceConflictError`.
        """
        moment = now if now is not None else time.time()
        if not str(event_id or "").strip():
            raise FeynmanError(
                "mastery_record_evidence requires a nonblank event_id idempotency key"
            )
        if expected_attempt_version is None:
            raise FeynmanError("mastery_record_evidence requires a real expected_attempt_version")
        attempt = self._attempt(progress, attempt_id)
        if attempt.status not in _LIVE_ATTEMPT_STATUSES:
            raise InvalidAttemptStateError(
                f"attempt {attempt_id} is {attempt.status.value}; evidence is read-only"
            )

        kind_value = str(kind)
        if kind_value not in {item.value for item in EvidenceKind}:
            raise FeynmanError(f"unsupported evidence kind: {kind_value!r}")
        kind_enum = EvidenceKind(kind_value)
        input_value = str(input_mode or "text")
        if input_value not in {item.value for item in InputMode}:
            raise FeynmanError(f"unsupported input_mode: {input_value!r}")
        input_enum = InputMode(input_value)
        if help_level:
            help_value = str(help_level)
            if help_value not in {item.value for item in HelpLevel}:
                raise FeynmanError(f"unsupported help_level: {help_value!r}")
        help = HelpLevel(str(help_level)) if help_level else None
        if (
            kind_enum in _LEARNER_EVIDENCE_KINDS
            and input_enum == InputMode.VOICE_TRANSCRIPT
            and not transcript_confirmed
        ):
            raise InvalidAttemptStateError(
                "voice-transcript learner evidence requires transcript_confirmed=true"
            )
        if not str(content or "").strip():
            raise FeynmanError(f"evidence content for {kind_value!r} must not be blank/whitespace")
        if kind_enum == EvidenceKind.SOURCE_REFERENCE:
            self._validate_frozen_citations(progress, attempt, list(source_citations or []))

        evidence_id = f"{attempt_id}:ev:{event_id}"
        new_hash = _content_hash(content)
        citations = list(source_citations or [])
        fingerprint = _fingerprint(
            {
                "attempt_id": attempt_id,
                "event_id": event_id,
                "kind": kind_enum.value,
                "content": content,
                "question_evidence_id": question_evidence_id,
                "source_citations": _citation_payload(citations),
                "input_mode": input_enum.value,
                "transcript_confirmed": transcript_confirmed,
                "help_level": help.value if help else None,
                "session_id": identity.get("session_id"),
                "turn_id": identity.get("turn_id"),
                "message_id": identity.get("message_id"),
                "user_id": identity.get("user_id"),
            }
        )

        # Idempotency lookup happens before the expected-version guard so a
        # committed retry (same key + same full payload) replays the prior
        # result even when the caller passes a stale expected version (§8.3).
        existing = next((e for e in progress.evidence_items if e.id == evidence_id), None)
        if existing is not None:
            prior = self._history_payload(progress, "evidence_recorded", "evidence_id", evidence_id)
            stored_fp = (prior or {}).get("request_fingerprint")
            if stored_fp is None:
                # Fail closed on a missing fingerprint: without the persisted
                # full-request fingerprint we can never prove the same payload,
                # so a pre-fingerprint row can neither replay nor be extended
                # under the same key — content-only equality is never used
                # (finding 2).
                raise EvidenceConflictError(
                    f"event_id {event_id!r} already recorded without a request "
                    f"fingerprint on attempt {attempt_id}; refusing to replay"
                )
            if stored_fp == fingerprint:
                return self._evidence_result(progress, existing, replay=True)
            raise EvidenceConflictError(
                f"event_id {event_id!r} reused with a different payload on attempt {attempt_id}"
            )

        if expected_attempt_version != progress.aggregate_versions.attempt:
            raise StaleVersionError(
                f"expected attempt version {expected_attempt_version}, "
                f"current is {progress.aggregate_versions.attempt}"
            )

        self._check_evidence_order(progress, attempt, kind_enum, question_evidence_id, help=help)

        session_id = str(identity.get("session_id") or "")
        turn_id = str(identity.get("turn_id") or "")
        event_seq = self._next_event_seq(progress, session_id, turn_id)
        item = EvidenceItem(
            id=evidence_id,
            attempt_id=attempt_id,
            chain_id=attempt.active_chain_id,
            kind=kind_enum,
            session_id=session_id,
            turn_id=turn_id,
            message_id=str(identity.get("message_id") or ""),
            event_seq=event_seq,
            input_mode=input_enum,
            transcript_confirmed=transcript_confirmed,
            content_snapshot=content,
            content_hash=new_hash,
            question_evidence_id=question_evidence_id,
            source_citations=list(source_citations or []),
            help_level=help,
            created_at=moment,
        )
        progress.evidence_items.append(item)
        append_history(
            progress,
            "evidence_recorded",
            aggregate="evidence",
            summary=f"{kind_enum.value} evidence {item.id}",
            payload={
                "evidence_id": item.id,
                "attempt_id": attempt_id,
                "chain_id": item.chain_id,
                "kind": kind_enum.value,
                "event_seq": event_seq,
                "input_mode": input_enum.value,
                "transcript_confirmed": transcript_confirmed,
                "content_hash": new_hash,
                "request_fingerprint": fingerprint,
            },
        )
        if help == HelpLevel.FULL_EXPLANATION:
            # A full explanation closes the current chain; a fresh reteach
            # chain must be built before the attempt can be finalised (§6.3).
            rotate_chain_for_full_explanation(progress, attempt, now=moment)
        # Advance the concurrency token returned to the caller so a stale token
        # from before this mutation can never be reused for a different event
        # (§8.3). A committed retry still replays: the idempotency lookup above
        # runs before this version guard.
        bump_aggregate_version(progress, "attempt")
        attempt.updated_at = moment
        return self._evidence_result(progress, item, replay=False)

    def _attempt(self, progress, attempt_id: str) -> FeynmanAttempt:
        attempt = next((a for a in progress.attempts if a.id == attempt_id), None)
        if attempt is None:
            raise UnknownAttemptError(f"attempt {attempt_id!r} not found")
        return attempt

    @staticmethod
    def _history_payload(progress, event_type: str, key: str, value: str) -> dict[str, Any] | None:
        """The first append-only history payload matching ``event_type``/key."""
        for event in progress.history:
            if event.event_type == event_type and event.payload.get(key) == value:
                return event.payload
        return None

    @staticmethod
    def _finalize_prior(progress, attempt_id: str, event_id: str) -> dict[str, Any] | None:
        """The committed finalize history payload for ``(attempt_id, event_id)``."""
        for event in progress.history:
            if (
                event.event_type == "assessment_created"
                and event.payload.get("event_id") == event_id
                and event.payload.get("attempt_id") == attempt_id
            ):
                return event.payload
        return None

    def _validate_frozen_citations(
        self,
        progress,
        attempt: FeynmanAttempt,
        citations: list[SourceCitation],
    ) -> None:
        """A source reference may only cite snapshots frozen on the attempt."""
        frozen = set(attempt.source_snapshot_ids)
        materialized = {s.id for s in progress.source_snapshots}
        for citation in citations:
            if citation.source_snapshot_id not in frozen:
                raise EvidenceOrderError(
                    f"source_reference cites snapshot {citation.source_snapshot_id!r} "
                    "which is not frozen on the attempt"
                )
            if citation.source_snapshot_id not in materialized:
                raise EvidenceOrderError(
                    f"source_reference cites snapshot {citation.source_snapshot_id!r} "
                    "which is not a materialized source snapshot"
                )

    @staticmethod
    def _next_event_seq(progress, session_id: str, turn_id: str) -> int:
        """Monotonic ``(session_id, turn_id, event_seq)`` reference (§7.2)."""
        seqs = [
            e.event_seq
            for e in progress.evidence_items
            if e.session_id == session_id and e.turn_id == turn_id
        ]
        return (max(seqs) + 1) if seqs else 1

    def _evidence_result(self, progress, item: EvidenceItem, *, replay: bool) -> dict[str, Any]:
        attempt = next((a for a in progress.attempts if a.id == item.attempt_id), None)
        return {
            "recorded": True,
            "replay": replay,
            "evidence_id": item.id,
            "attempt_id": item.attempt_id,
            "chain_id": item.chain_id,
            "kind": item.kind.value,
            "event_seq": item.event_seq,
            "input_mode": item.input_mode.value,
            "transcript_confirmed": item.transcript_confirmed,
            "content_hash": item.content_hash,
            "attempt_version": progress.aggregate_versions.attempt,
            "next_required_steps": self._missing_steps(progress, attempt),
        }

    @staticmethod
    def _missing_steps(progress, attempt: FeynmanAttempt | None) -> list[str]:
        if attempt is None:
            return list(REQUIRED_EVIDENCE_KINDS)
        chain = validate_evidence_chain(progress, attempt)
        if chain.valid:
            return []
        return list(chain.missing_evidence_kinds)

    def _check_evidence_order(
        self,
        progress,
        attempt: FeynmanAttempt,
        kind: EvidenceKind,
        question_evidence_id: str,
        help: HelpLevel | None = None,
    ) -> None:
        """Enforce the Feynman chain progression (§6.1, requirement 3)."""
        if kind == EvidenceKind.SOURCE_REFERENCE:
            return
        chain = [
            item
            for item in progress.evidence_items
            if item.attempt_id == attempt.id and item.chain_id == attempt.active_chain_id
        ]
        explanations = [
            item for item in chain if item.kind in (EvidenceKind.EXPLANATION, EvidenceKind.RETEACH)
        ]
        transfer_started = any(
            item.kind in (EvidenceKind.TRANSFER_QUESTION, EvidenceKind.TRANSFER_ANSWER)
            for item in chain
        )
        # A ``reteach`` at the ``full_explanation`` help level is the chain
        # reset action (§6.3): it is allowed after transfer because it closes
        # the current chain (and a fresh reteach chain starts afterwards).
        is_chain_reset = kind == EvidenceKind.RETEACH and help == HelpLevel.FULL_EXPLANATION

        if kind in (EvidenceKind.EXPLANATION, EvidenceKind.RETEACH):
            if transfer_started and not is_chain_reset:
                raise EvidenceOrderError(
                    f"{kind.value} cannot follow transfer evidence; the chain is "
                    "already in transfer"
                )
            return  # a chain starts with (re)teaching
        if not explanations:
            raise EvidenceOrderError(f"{kind.value} requires a confirmed explanation first")
        if kind in (EvidenceKind.PROBE_QUESTION, EvidenceKind.PROBE_ANSWER):
            if transfer_started:
                raise EvidenceOrderError(
                    f"{kind.value} cannot follow transfer evidence; the chain is "
                    "already in transfer"
                )
            if kind == EvidenceKind.PROBE_QUESTION:
                return
            if not question_evidence_id:
                raise EvidenceOrderError("probe_answer requires question_evidence_id")
            question = next((e for e in chain if e.id == question_evidence_id), None)
            if question is None or question.kind != EvidenceKind.PROBE_QUESTION:
                raise EvidenceOrderError(
                    "probe_answer must bind to a probe_question in the active chain"
                )
            return
        if kind == EvidenceKind.TRANSFER_QUESTION:
            bound = self._bound_probe_pairs(chain)
            if len(bound) < 2:
                raise EvidenceOrderError(
                    "transfer_question requires at least two bound probe pairs"
                )
            return
        if kind == EvidenceKind.TRANSFER_ANSWER:
            if not question_evidence_id:
                raise EvidenceOrderError("transfer_answer requires question_evidence_id")
            question = next((e for e in chain if e.id == question_evidence_id), None)
            if question is None or question.kind != EvidenceKind.TRANSFER_QUESTION:
                raise EvidenceOrderError(
                    "transfer_answer must bind to a transfer_question in the active chain"
                )
            return

    @staticmethod
    def _bound_probe_pairs(chain: list[EvidenceItem]) -> list[tuple[str, str]]:
        """Distinct ``(question_id, answer_id)`` probe pairs in chain order."""
        questions = {q.id: q for q in chain if q.kind == EvidenceKind.PROBE_QUESTION}
        pairs: dict[str, tuple[str, str]] = {}
        for answer in chain:
            if answer.kind != EvidenceKind.PROBE_ANSWER:
                continue
            question = questions.get(answer.question_evidence_id)
            if question is None:
                continue
            if (answer.created_at, answer.event_seq) < (
                question.created_at,
                question.event_seq,
            ):
                continue
            if answer.question_evidence_id not in pairs:
                pairs[answer.question_evidence_id] = (question.id, answer.id)
        return sorted(pairs.values())

    # ── finalize / challenge ───────────────────────────────────────────────

    def find_finalize_replay(
        self,
        progress,
        *,
        attempt_id: str,
        event_id: str,
        client_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """The committed finalize result for ``(attempt_id, event_id)``, if any.

        The tool calls this *before* running the evaluator so a retry of a
        committed finalize replays the stored result without repeating a
        provider call (§8.3, requirement 2). When ``client_payload`` is
        supplied, the same key reused with a *different* payload is a stable
        conflict; the same payload replays the stored result.
        """
        prior = self._finalize_prior(progress, attempt_id, event_id)
        if prior is None:
            return None
        if client_payload is not None:
            stored_fp = prior.get("client_request_fingerprint")
            client_fp = _fingerprint(client_payload)
            if stored_fp is not None and stored_fp != client_fp:
                raise IdempotencyConflictError(
                    f"finalize event_id {event_id!r} reused with a different payload "
                    f"on attempt {attempt_id}"
                )
        result = prior.get("result")
        if isinstance(result, dict):
            return {**result, "replayed": True}
        raise FeynmanError(f"finalize replay missing stored result for event_id {event_id!r}")

    def finalize(
        self,
        progress,
        *,
        attempt_id: str,
        rubric: RubricScores,
        critical_errors: list[str],
        strengths: list[str],
        gap_candidates: list[dict[str, str]],
        evidence_ids: list[str],
        source_citations: list[SourceCitation],
        model_invocation_id: str = "",
        challenge_id: str = "",
        client_request_fingerprint: str = "",
        expected_attempt_version: int | None = None,
        event_id: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Server-computed finalize: gate, assessment, gaps, projection (§8.1).

        ``passed`` is never accepted — the LRN-02 gate computes it. A challenge
        reassessment appends a later revision to the same attempt; otherwise a
        closed/invalidated attempt cannot be finalised.

        ``event_id`` is the required finalize idempotency key (``attempt_id +
        event_id``, §8.3): a committed retry with the same full payload replays
        the stored result — never creating a second assessment — while the same
        key with a different payload is a stable conflict.
        """
        moment = now if now is not None else time.time()
        if not str(event_id or "").strip():
            raise FeynmanError("mastery_finalize requires a nonblank event_id idempotency key")
        if expected_attempt_version is None:
            raise FeynmanError("mastery_finalize requires a real expected_attempt_version")
        attempt = self._attempt(progress, attempt_id)

        # The invocation id is an audit detail, not assessment content: it is
        # deliberately excluded from the idempotency fingerprint so a committed
        # finalize replays on retry even though the evaluator produces a fresh
        # invocation id each run (§8.3, requirement 2).
        fingerprint = _fingerprint(
            {
                "attempt_id": attempt_id,
                "event_id": event_id,
                "rubric": rubric.model_dump(),
                "critical_errors": list(critical_errors),
                "strengths": list(strengths),
                "gap_candidates": sorted(
                    (dict(g) for g in gap_candidates),
                    key=lambda g: str(g.get("label") or "") + str(g.get("description") or ""),
                ),
                "evidence_ids": list(evidence_ids),
                "source_citations": _citation_payload(source_citations),
                "challenge_id": challenge_id,
            }
        )
        prior = self._finalize_prior(progress, attempt_id, event_id)
        if prior is not None:
            stored_fp = prior.get("request_fingerprint")
            if stored_fp is not None and stored_fp == fingerprint:
                result = prior.get("result")
                if isinstance(result, dict):
                    return {**result, "replayed": True}
                raise FeynmanError(
                    f"finalize replay missing stored result for event_id {event_id!r}"
                )
            raise IdempotencyConflictError(
                f"finalize event_id {event_id!r} reused with a different payload "
                f"on attempt {attempt_id}"
            )

        if expected_attempt_version != progress.aggregate_versions.attempt:
            raise StaleVersionError(
                f"expected attempt version {expected_attempt_version}, "
                f"current is {progress.aggregate_versions.attempt}"
            )
        challenge = self._resolve_challenge(progress, challenge_id, attempt_id)

        if attempt.status not in _LIVE_ATTEMPT_STATUSES:
            if challenge is None:
                raise InvalidAttemptStateError(
                    f"attempt {attempt_id} is {attempt.status.value}; cannot finalise"
                )
            # A challenge reassessment (reassess_existing) finalises the source
            # attempt again — it reuses frozen evidence and appends a revision.
            # collect_new_evidence finalises its fresh result attempt (live).

        # A reassess_existing challenge appends a revision to the *same*
        # attempt; a collect_new_evidence challenge finalises a fresh attempt
        # that has no prior assessment to supersede.
        supersedes = ""
        if challenge is not None and challenge.source_attempt_id == attempt_id:
            prior = _latest_assessment_for_attempt(progress, attempt_id)
            if prior is not None:
                supersedes = prior.id
        effective_challenge_id = challenge.id if challenge is not None else ""
        assessment = self._build_assessment(
            progress,
            attempt=attempt,
            rubric=rubric,
            critical_errors=critical_errors,
            strengths=strengths,
            gap_candidates=gap_candidates,
            evidence_ids=evidence_ids,
            source_citations=source_citations,
            model_invocation_id=model_invocation_id,
            challenge_id=effective_challenge_id,
            supersedes_assessment_id=supersedes,
        )
        record_server_gate(progress, attempt, assessment, now=moment)
        progress.rubric_assessments.append(assessment)

        # The attempt itself is terminal once assessed.
        attempt.status = AttemptStatus.ASSESSED
        attempt.closed_at = attempt.closed_at or moment
        attempt.updated_at = moment

        # Rebuild the orthogonal mastery/review projections and the unified
        # review queue (Feynman projection tasks merged over legacy repetition
        # tasks so memory/procedure quiz reviews are never dropped).
        projections = project_all(progress, now=moment)
        progress.projections = projections
        progress.review_queue = self._unified_review_queue(progress, now=moment)

        projection = projections.get(attempt.knowledge_point_id)
        # Advance the concurrency token on an accepted finalize so the version
        # the caller receives can never be reused for a different mutation;
        # a committed retry replays the stored result before this guard (§8.3).
        bump_aggregate_version(progress, "attempt")
        result = {
            "assessment_id": assessment.id,
            "attempt_id": attempt_id,
            "assessment_sequence": assessment.assessment_sequence,
            "revision": assessment.revision,
            "server_gate": assessment.server_gate_result.model_dump(),
            "passed": assessment.server_gate_result.passed,
            "mastery_state": projection.mastery_state.value if projection else "",
            "review_state": projection.review_state.value if projection else "",
            "next_review_at": projection.next_review_at if projection else None,
            "attempt_version": progress.aggregate_versions.attempt,
        }
        append_history(
            progress,
            "assessment_created",
            aggregate="assessment",
            summary=f"assessment {assessment.id} for attempt {attempt_id}",
            payload={
                "assessment_id": assessment.id,
                "attempt_id": attempt_id,
                "assessment_sequence": assessment.assessment_sequence,
                "revision": assessment.revision,
                "passed": assessment.server_gate_result.passed,
                "challenge_id": effective_challenge_id,
                "event_id": event_id,
                "request_fingerprint": fingerprint,
                "client_request_fingerprint": client_request_fingerprint,
                "result": result,
            },
        )

        if challenge is not None:
            self._complete_challenge(
                progress, challenge, result_assessment_id=assessment.id, now=moment
            )

        return result

    def _build_assessment(
        self,
        progress,
        *,
        attempt: FeynmanAttempt,
        rubric: RubricScores,
        critical_errors: list[str],
        strengths: list[str],
        gap_candidates: list[dict[str, str]],
        evidence_ids: list[str],
        source_citations: list[SourceCitation],
        model_invocation_id: str,
        challenge_id: str,
        supersedes_assessment_id: str,
    ) -> RubricAssessment:
        existing = [a for a in progress.rubric_assessments if a.attempt_id == attempt.id]
        gap_ids = [self._gap_for(progress, attempt, candidate).id for candidate in gap_candidates]
        return RubricAssessment(
            id=uuid.uuid4().hex,
            attempt_id=attempt.id,
            revision=len(existing) + 1,
            assessment_sequence=next_assessment_sequence(progress, attempt.knowledge_point_id),
            rubric=rubric,
            critical_errors=list(critical_errors),
            strengths=list(strengths),
            gap_ids=gap_ids,
            evidence_ids=list(evidence_ids),
            source_citations=list(source_citations),
            evaluator_snapshot=attempt.evaluator_snapshot,
            model_invocation_id=model_invocation_id,
            supersedes_assessment_id=supersedes_assessment_id,
            challenge_id=challenge_id,
        )

    def _gap_for(self, progress, attempt: FeynmanAttempt, candidate: dict[str, str]) -> GapRecord:
        label = str(candidate.get("label") or "").strip()
        description = str(candidate.get("description") or "").strip()
        existing = next(
            (
                gap
                for gap in progress.gaps
                if gap.knowledge_point_id == attempt.knowledge_point_id
                and gap.label == label
                and gap.status in (GapStatus.ACTIVE, GapStatus.IMPROVING, GapStatus.REOPENED)
            ),
            None,
        )
        if existing is not None:
            if description:
                existing.description = description
            return existing
        gap = GapRecord(
            id=uuid.uuid4().hex,
            knowledge_point_id=attempt.knowledge_point_id,
            label=label or description or "gap",
            description=description,
            priority=1,
        )
        progress.gaps.append(gap)
        return gap

    def _pending_challenge(self, progress, challenge_id: str) -> ChallengeRecord | None:
        if not challenge_id:
            return None
        return next(
            (
                c
                for c in progress.challenge_records
                if c.id == challenge_id and c.status == ChallengeStatus.PENDING
            ),
            None,
        )

    @staticmethod
    def _pending_challenge_for_result(progress, result_attempt_id: str) -> ChallengeRecord | None:
        """A pending collect_new_evidence challenge awaiting this result attempt."""
        return next(
            (
                c
                for c in progress.challenge_records
                if c.status == ChallengeStatus.PENDING and c.result_attempt_id == result_attempt_id
            ),
            None,
        )

    def _resolve_challenge(
        self, progress, challenge_id: str, attempt_id: str
    ) -> ChallengeRecord | None:
        """Resolve the challenge being finalised, validating attempt linkage.

        A supplied ``challenge_id`` must match the finalized attempt according
        to its mode (§7.3.1, finding 6): ``reassess_existing`` targets its
        ``source_attempt_id``, ``collect_new_evidence`` targets its
        ``result_attempt_id``. Without a supplied id, a pending
        ``collect_new_evidence`` challenge awaiting this result attempt is
        discovered so the assessment records the effective challenge id.
        """
        if challenge_id:
            challenge = self._pending_challenge(progress, challenge_id)
            if challenge is None:
                raise InvalidAttemptStateError(f"challenge {challenge_id!r} is not pending")
            if challenge.mode == ChallengeMode.REASSESS_EXISTING:
                if challenge.source_attempt_id != attempt_id:
                    raise InvalidAttemptStateError(
                        f"reassess_existing challenge {challenge_id} targets source "
                        f"attempt {challenge.source_attempt_id}, not {attempt_id}"
                    )
            else:  # COLLECT_NEW_EVIDENCE
                if challenge.result_attempt_id != attempt_id:
                    raise InvalidAttemptStateError(
                        f"collect_new_evidence challenge {challenge_id} targets result "
                        f"attempt {challenge.result_attempt_id}, not {attempt_id}"
                    )
            return challenge
        return self._pending_challenge_for_result(progress, attempt_id)

    def _complete_challenge(
        self,
        progress,
        challenge: ChallengeRecord,
        *,
        result_assessment_id: str,
        now: float | None = None,
    ) -> None:
        challenge.status = ChallengeStatus.COMPLETED
        challenge.result_assessment_id = result_assessment_id
        challenge.completed_at = challenge.completed_at or (now if now is not None else time.time())
        append_history(
            progress,
            "challenge_completed",
            aggregate="challenge",
            summary=f"challenge {challenge.id} completed",
            payload={
                "challenge_id": challenge.id,
                "result_assessment_id": result_assessment_id,
            },
        )

    def create_challenge(
        self,
        progress,
        *,
        attempt_id: str,
        mode: str,
        reason: str = "",
        requested_evaluator_snapshot: EvaluatorSnapshot | None = None,
        request_id: str = "",
        expected_attempt_version: int | None = None,
        now: float | None = None,
    ) -> ChallengeRecord:
        """Create a challenge; never writes a pass directly (§7.3.1).

        ``reassess_existing`` reuses the source attempt's frozen evidence and
        appends a later assessment revision. ``collect_new_evidence`` creates a
        linked reevaluation attempt (``supersedes_attempt_id``) that collects a
        fresh chain. Creation is idempotent under ``request_id`` (same key +
        same payload replays the existing challenge; same key + different
        payload conflicts). A pending challenge is never duplicated, and
        ``reassess_existing`` requires a prior source assessment. An accepted
        creation advances the attempt concurrency token returned to the caller.
        """
        moment = now if now is not None else time.time()
        if not str(request_id or "").strip():
            raise FeynmanError("challenge creation requires a nonblank request_id idempotency key")
        if expected_attempt_version is None:
            raise FeynmanError("challenge creation requires a real expected_attempt_version")
        attempt = self._attempt(progress, attempt_id)
        mode_value = str(mode or "")
        if mode_value not in {item.value for item in ChallengeMode}:
            raise FeynmanError(f"unsupported challenge mode: {mode_value!r}")
        mode_enum = ChallengeMode(mode_value)

        fingerprint = _fingerprint(
            {
                "attempt_id": attempt_id,
                "mode": mode_enum.value,
                "reason": reason,
                "requested_evaluator_snapshot": (
                    requested_evaluator_snapshot.model_dump()
                    if requested_evaluator_snapshot is not None
                    else None
                ),
            }
        )
        prior = self._history_payload(progress, "challenge_created", "request_id", request_id)
        if prior is not None:
            stored_fp = prior.get("request_fingerprint")
            if stored_fp is not None and stored_fp == fingerprint:
                existing = next(
                    (c for c in progress.challenge_records if c.id == prior.get("challenge_id")),
                    None,
                )
                if existing is not None:
                    return existing
                raise FeynmanError(
                    f"challenge replay missing persisted record for request_id {request_id!r}"
                )
            raise IdempotencyConflictError(
                f"challenge request_id {request_id!r} reused with a different payload"
            )

        if expected_attempt_version != progress.aggregate_versions.attempt:
            raise StaleVersionError(
                f"expected attempt version {expected_attempt_version}, "
                f"current is {progress.aggregate_versions.attempt}"
            )

        source_assessment = _latest_assessment_for_attempt(progress, attempt_id)
        if mode_enum == ChallengeMode.REASSESS_EXISTING and source_assessment is None:
            raise InvalidAttemptStateError(
                "reassess_existing requires a prior assessment on the source attempt"
            )
        duplicate = next(
            (
                c
                for c in progress.challenge_records
                if c.source_attempt_id == attempt_id and c.status == ChallengeStatus.PENDING
            ),
            None,
        )
        if duplicate is not None:
            raise IdempotencyConflictError(
                f"a pending challenge already exists for attempt {attempt_id}"
            )

        challenge = ChallengeRecord(
            id=uuid.uuid4().hex,
            knowledge_point_id=attempt.knowledge_point_id,
            source_attempt_id=attempt_id,
            source_assessment_id=source_assessment.id if source_assessment else "",
            mode=mode_enum,
            requested_evaluator_snapshot=requested_evaluator_snapshot,
            status=ChallengeStatus.PENDING,
            reason=reason,
            created_at=moment,
        )
        progress.challenge_records.append(challenge)
        if mode_enum == ChallengeMode.COLLECT_NEW_EVIDENCE:
            new_attempt = self._create_attempt(
                progress,
                knowledge_point_id=attempt.knowledge_point_id,
                cycle=AttemptCycleType.REEVALUATION,
                session_id=attempt.session_id,
                turn_id=attempt.started_turn_id,
                supersedes_attempt_id=attempt_id,
                now=moment,
            )
            challenge.result_attempt_id = new_attempt.id
        append_history(
            progress,
            "challenge_created",
            aggregate="challenge",
            summary=f"{mode_enum.value} challenge {challenge.id} on attempt {attempt_id}",
            payload={
                "challenge_id": challenge.id,
                "source_attempt_id": attempt_id,
                "mode": mode_enum.value,
                "result_attempt_id": challenge.result_attempt_id,
                "request_id": request_id,
                "request_fingerprint": fingerprint,
            },
        )
        # An accepted challenge mutation advances the attempt concurrency token
        # so a stale token cannot be reused for a different mutation (§8.3).
        bump_aggregate_version(progress, "attempt")
        return challenge

    def resume_attempt(self, progress, *, attempt_id: str) -> dict[str, Any]:
        """Resume a draft/interrupted attempt (§8.3).

        An invalidated attempt is never resumed: it returns a stable
        ``requires_restart`` with the current map version so the client can
        start a fresh chain bound to the new sources.
        """
        attempt = self._attempt(progress, attempt_id)
        if attempt.status == AttemptStatus.INVALIDATED:
            map_version = _latest_map_version(progress)
            return {
                "status": "requires_restart",
                "attempt_id": attempt_id,
                "invalidated_reason": attempt.invalidated_reason,
                "map_version_id": map_version.id if map_version else "",
                "map_version": map_version.version if map_version else 0,
            }
        if attempt.status in (AttemptStatus.CLOSED, AttemptStatus.ASSESSED):
            return {
                "status": "closed",
                "attempt_id": attempt_id,
                "cycle_type": attempt.cycle_type.value,
            }
        return {
            "status": "resumed",
            "attempt_id": attempt_id,
            "chain_id": attempt.active_chain_id,
            "cycle_type": attempt.cycle_type.value,
            "knowledge_point_id": attempt.knowledge_point_id,
            "max_help_level": attempt.max_help_level.value,
            "attempt_version": progress.aggregate_versions.attempt,
            "next_required_steps": self._missing_steps(progress, attempt),
        }

    # ── map edit / confirm / conflict resolve / reopen ─────────────────────

    def edit_map(
        self,
        progress,
        *,
        nodes: list[str],
        edges: list[dict[str, Any]],
        priorities: dict[str, int],
        expected_map_version: int,
        request_id: str = "",
        actor_id: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Versioned map edit (§8.2). Creates a new map version with the
        expected-version concurrency contract; incompatible active attempts are
        atomically invalidated. Idempotent under ``request_id``: same key +
        same payload replays the full prior result, different payload conflicts."""
        moment = now if now is not None else time.time()
        if not str(request_id or "").strip():
            raise FeynmanError("map edit requires a nonblank request_id idempotency key")
        _require_owner(progress, actor_id)
        fingerprint = _fingerprint(
            {
                "nodes": list(nodes),
                "edges": list(edges),
                "priorities": dict(priorities),
            }
        )
        replayed = self._replay_or_conflict_result(progress, "map_edited", request_id, fingerprint)
        if replayed is not None:
            return replayed
        latest = _latest_map_version(progress)
        current_version = latest.version if latest else 0
        if expected_map_version != current_version:
            raise StaleVersionError(
                f"expected map version {expected_map_version}, current is {current_version}"
            )
        new_version = KnowledgeMapVersion(
            id=f"{progress.book_id}:map:{current_version + 1}",
            path_id=progress.book_id,
            version=current_version + 1,
            nodes=list(nodes),
            edges=list(edges),
            priorities=dict(priorities),
            source_snapshot_ids=list(latest.source_snapshot_ids) if latest else [],
            confirmed_at=moment,
        )
        # Only the attempts invalidated by THIS operation are reported — never
        # every historically invalidated attempt (finding 4).
        invalidated = apply_map_version(progress, new_version)
        result = self._map_payload(progress, new_version)
        result["invalidated_attempt_ids"] = invalidated
        append_history(
            progress,
            "map_edited",
            summary=f"map {progress.book_id} edited to v{new_version.version}",
            payload={
                "request_id": request_id,
                "version_id": new_version.id,
                "version": new_version.version,
                "request_fingerprint": fingerprint,
                "result": result,
                "invalidated_attempt_ids": result["invalidated_attempt_ids"],
            },
        )
        return result

    def confirm_map(
        self,
        progress,
        *,
        expected_map_version: int,
        request_id: str = "",
        source_snapshot_ids: list[str] | None = None,
        actor_id: str = "",
        now: float | None = None,
    ) -> dict[str, Any]:
        """Idempotently confirm the current map version and its sources (§8.2).

        Map versions are append-only: a confirmation that changes the source
        set appends a new confirmed revision (never mutating a historical
        ``KnowledgeMapVersion``), validates every selected snapshot exists, and
        atomically invalidates incompatible active attempts.
        """
        moment = now if now is not None else time.time()
        if not str(request_id or "").strip():
            raise FeynmanError("map confirm requires a nonblank request_id idempotency key")
        _require_owner(progress, actor_id)
        # ``None`` (preserve the current source set) and ``[]`` (explicitly
        # clear it, appending/invalidating) are semantically different payloads;
        # the fingerprint must not collapse them onto one digest.
        fingerprint = _fingerprint(
            {
                "source_snapshot_ids": (
                    None if source_snapshot_ids is None else sorted(source_snapshot_ids)
                ),
            }
        )
        replayed = self._replay_or_conflict_result(
            progress, "map_confirmed", request_id, fingerprint
        )
        if replayed is not None:
            return replayed
        latest = _latest_map_version(progress)
        if latest is None:
            # Nothing to confirm — a stable domain error instead of
            # dereferencing ``None`` in the history summary (finding 4).
            raise FeynmanError(
                "no confirmed map exists to confirm; build and confirm a map "
                "before starting an attempt"
            )
        current_version = latest.version
        if expected_map_version != current_version:
            raise StaleVersionError(
                f"expected map version {expected_map_version}, current is {current_version}"
            )

        invalidated: list[str] = []
        confirmed_version = latest
        if source_snapshot_ids is not None:
            self._validate_snapshots_exist(progress, source_snapshot_ids)
            if set(source_snapshot_ids) != set(latest.source_snapshot_ids):
                confirmed_version = KnowledgeMapVersion(
                    id=f"{progress.book_id}:map:{current_version + 1}",
                    path_id=progress.book_id,
                    version=current_version + 1,
                    nodes=list(latest.nodes),
                    edges=list(latest.edges),
                    priorities=dict(latest.priorities),
                    source_snapshot_ids=list(source_snapshot_ids),
                    confirmed_at=moment,
                )
                invalidated = apply_map_version(progress, confirmed_version)
        result = self._map_payload(progress, confirmed_version)
        result["invalidated_attempt_ids"] = invalidated
        append_history(
            progress,
            "map_confirmed",
            aggregate="map",
            summary=f"map {progress.book_id} v{confirmed_version.version} confirmed",
            payload={
                "request_id": request_id,
                "version_id": confirmed_version.id if confirmed_version else "",
                "version": confirmed_version.version if confirmed_version else 0,
                "request_fingerprint": fingerprint,
                "result": result,
                "invalidated_attempt_ids": invalidated,
            },
        )
        return result

    def _replay_or_conflict_result(
        self,
        progress,
        event_type: str,
        request_id: str,
        fingerprint: str,
    ) -> dict[str, Any] | None:
        """Full-result idempotency for map/conflict mutations (§8.3).

        ``None`` means the key is new (caller should execute). Otherwise the
        stored full result is returned for a same-payload replay, or a stable
        conflict is raised for a different payload. Never returns the truncated
        ``{replayed, request_id}`` shape.
        """
        if not request_id:
            return None
        prior = self._history_payload(progress, event_type, "request_id", request_id)
        if prior is None:
            return None
        stored_fp = prior.get("request_fingerprint")
        if stored_fp is not None and stored_fp == fingerprint:
            result = prior.get("result")
            if isinstance(result, dict):
                return {**result, "replayed": True}
            raise FeynmanError(
                f"{event_type} replay missing stored result for request_id {request_id!r}"
            )
        raise IdempotencyConflictError(f"request_id {request_id!r} reused with a different payload")

    def _validate_snapshots_exist(self, progress, snapshot_ids: list[str]) -> None:
        """Every selected snapshot must be a materialized SourceSnapshot."""
        materialized = {s.id for s in progress.source_snapshots}
        missing = [sid for sid in snapshot_ids if sid not in materialized]
        if missing:
            raise ConflictResolutionError(f"unknown source snapshots: {', '.join(missing)}")

    @staticmethod
    def _map_payload(progress, version: KnowledgeMapVersion | None) -> dict[str, Any]:
        latest = version or _latest_map_version(progress)
        return {
            "map_version": latest.version if latest else 0,
            "map_version_id": latest.id if latest else "",
            "confirmed_at": latest.confirmed_at if latest else None,
            "nodes": list(latest.nodes) if latest else [],
            "source_snapshot_ids": list(latest.source_snapshot_ids) if latest else [],
        }

    def resolve_conflict(
        self,
        progress,
        *,
        conflict_id: str,
        accepted_snapshot_id: str,
        resolution_note: str,
        actor_id: str,
        request_id: str = "",
        expected_conflict_version: int | None = None,
        expected_map_version: int | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Owner-only conflict resolution (§7.7, §8.2).

        Selects only a snapshot already listed on the conflict, requires a
        resolution note, creates a new conflict revision and a new map version,
        and atomically invalidates incompatible active attempts. Resolution
        requires the newest revision to be OPEN and the caller's expected
        conflict/map versions to match. Idempotent under ``request_id``.
        """
        moment = now if now is not None else time.time()
        if not str(request_id or "").strip():
            raise FeynmanError("conflict resolve requires a nonblank request_id idempotency key")
        if expected_conflict_version is None:
            raise FeynmanError("conflict resolve requires a real expected_conflict_version")
        if expected_map_version is None:
            raise FeynmanError("conflict resolve requires a real expected_map_version")
        _require_owner(progress, actor_id)
        conflict = _current_conflict(progress, conflict_id)
        if conflict is None:
            raise UnknownConflictError(f"conflict {conflict_id!r} not found")
        fingerprint = _fingerprint(
            {
                "conflict_id": conflict_id,
                "accepted_snapshot_id": accepted_snapshot_id,
                "resolution_note": resolution_note,
            }
        )
        replayed = self._replay_or_conflict_result(
            progress, "conflict_resolved", request_id, fingerprint
        )
        if replayed is not None:
            return replayed

        if conflict.status != ConflictStatus.OPEN:
            raise ConflictResolutionError(
                f"conflict {conflict_id} is {conflict.status.value}; only an OPEN "
                "conflict can be resolved"
            )
        if accepted_snapshot_id not in conflict.source_snapshot_ids:
            raise ConflictResolutionError(
                f"accepted_snapshot_id {accepted_snapshot_id!r} is not listed on conflict "
                f"{conflict_id} ({', '.join(conflict.source_snapshot_ids)})"
            )
        # Accepted/listed snapshot ids must resolve to materialized sources.
        self._validate_snapshots_exist(progress, conflict.source_snapshot_ids)
        self._validate_snapshots_exist(progress, [accepted_snapshot_id])
        if not (resolution_note or "").strip():
            raise ConflictResolutionError("a resolution note is required")
        if expected_conflict_version != conflict.version:
            raise StaleVersionError(
                f"expected conflict version {expected_conflict_version}, "
                f"current is {conflict.version}"
            )
        latest = _latest_map_version(progress)
        current_map_version = latest.version if latest else 0
        if expected_map_version != current_map_version:
            raise StaleVersionError(
                f"expected map version {expected_map_version}, current is {current_map_version}"
            )

        new_conflict = SourceConflict(
            id=conflict.id,
            path_id=conflict.path_id,
            knowledge_point_ids=list(conflict.knowledge_point_ids),
            claim=conflict.claim,
            source_snapshot_ids=list(conflict.source_snapshot_ids),
            citation_anchors=list(conflict.citation_anchors),
            version=conflict.version + 1,
            status=ConflictStatus.RESOLVED,
            accepted_snapshot_id=accepted_snapshot_id,
            resolution_note=resolution_note.strip(),
            resolved_at=moment,
            resolved_by=actor_id,
        )
        progress.source_conflicts.append(new_conflict)

        next_version = (latest.version + 1) if latest else 1
        map_version = KnowledgeMapVersion(
            id=f"{progress.book_id}:map:{next_version}",
            path_id=progress.book_id,
            version=next_version,
            nodes=list(latest.nodes) if latest else [],
            edges=list(latest.edges) if latest else [],
            priorities=dict(latest.priorities) if latest else {},
            source_snapshot_ids=list(latest.source_snapshot_ids) if latest else [],
            confirmed_at=moment,
        )
        invalidated = apply_map_version(progress, map_version)
        result = {
            "status": "resolved",
            "conflict_id": conflict_id,
            "conflict_version": new_conflict.version,
            "accepted_snapshot_id": accepted_snapshot_id,
            "map_version": map_version.version,
            "map_version_id": map_version.id,
            "invalidated_attempt_ids": invalidated,
        }
        append_history(
            progress,
            "conflict_resolved",
            aggregate="conflict",
            summary=f"conflict {conflict_id} resolved to {accepted_snapshot_id}",
            payload={
                "conflict_id": conflict_id,
                "request_id": request_id,
                "version": new_conflict.version,
                "accepted_snapshot_id": accepted_snapshot_id,
                "request_fingerprint": fingerprint,
                "result": result,
            },
        )
        return result

    def reopen_conflict(
        self,
        progress,
        *,
        conflict_id: str,
        actor_id: str,
        request_id: str = "",
        expected_conflict_version: int | None = None,
        expected_map_version: int | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Owner-only reopen: immediately restores the correctness block (§7.7).

        Reopen requires the newest revision to be RESOLVED and the caller's
        expected conflict/map versions to match. Idempotent under ``request_id``.
        """
        moment = now if now is not None else time.time()
        if not str(request_id or "").strip():
            raise FeynmanError("conflict reopen requires a nonblank request_id idempotency key")
        if expected_conflict_version is None:
            raise FeynmanError("conflict reopen requires a real expected_conflict_version")
        if expected_map_version is None:
            raise FeynmanError("conflict reopen requires a real expected_map_version")
        _require_owner(progress, actor_id)
        conflict = _current_conflict(progress, conflict_id)
        if conflict is None:
            raise UnknownConflictError(f"conflict {conflict_id!r} not found")
        fingerprint = _fingerprint({"conflict_id": conflict_id})
        replayed = self._replay_or_conflict_result(
            progress, "conflict_reopened", request_id, fingerprint
        )
        if replayed is not None:
            return replayed

        if conflict.status != ConflictStatus.RESOLVED:
            raise ConflictResolutionError(
                f"conflict {conflict_id} is {conflict.status.value}; only a RESOLVED "
                "conflict can be reopened"
            )
        if expected_conflict_version != conflict.version:
            raise StaleVersionError(
                f"expected conflict version {expected_conflict_version}, "
                f"current is {conflict.version}"
            )
        latest = _latest_map_version(progress)
        current_map_version = latest.version if latest else 0
        if expected_map_version != current_map_version:
            raise StaleVersionError(
                f"expected map version {expected_map_version}, current is {current_map_version}"
            )

        new_conflict = SourceConflict(
            id=conflict.id,
            path_id=conflict.path_id,
            knowledge_point_ids=list(conflict.knowledge_point_ids),
            claim=conflict.claim,
            source_snapshot_ids=list(conflict.source_snapshot_ids),
            citation_anchors=list(conflict.citation_anchors),
            version=conflict.version + 1,
            status=ConflictStatus.OPEN,
            resolved_at=None,
            resolved_by="",
        )
        progress.source_conflicts.append(new_conflict)
        result = {
            "status": "open",
            "conflict_id": conflict_id,
            "conflict_version": new_conflict.version,
            "blocking": True,
        }
        append_history(
            progress,
            "conflict_reopened",
            aggregate="conflict",
            summary=f"conflict {conflict_id} reopened",
            payload={
                "conflict_id": conflict_id,
                "request_id": request_id,
                "version": new_conflict.version,
                "request_fingerprint": fingerprint,
                "result": result,
            },
        )
        return result

    def _unified_review_queue(self, progress, *, now: float | None = None):
        """Merge Feynman projection reviews over the legacy repetition queue.

        Every knowledge type is reviewed from the same queue (§13.2): a kp
        with a Feynman projection review (next_review_at set) uses it; a kp
        with only a legacy repetition state (memory/procedure quiz mastery)
        keeps its legacy review task. Feynman tasks win where both exist.
        """
        scheduler = SpacedRepetitionScheduler()
        feynman = {
            task.knowledge_point_id: task
            for task in scheduler.build_feynman_review_queue(progress, now=now)
        }
        legacy = {task.knowledge_point_id: task for task in scheduler.build_review_queue(progress)}
        merged: dict[str, Any] = dict(legacy)
        merged.update(feynman)
        tasks = list(merged.values())
        tasks.sort(key=lambda task: (task.priority, task.due_at))
        return tasks

    # ── read helpers ───────────────────────────────────────────────────────

    def map_read_payload(self, progress, *, now: float | None = None) -> dict[str, Any]:
        moment = now if now is not None else time.time()
        projections = project_all(progress, now=moment)
        active_attempts: dict[str, dict[str, Any]] = {}
        evidence_summary: dict[str, dict[str, Any]] = {}
        for kp_id, projection in projections.items():
            if projection.active_attempt_id:
                attempt = self._attempt(progress, projection.active_attempt_id)
                active_attempts[kp_id] = {
                    "attempt_id": attempt.id,
                    "status": attempt.status.value,
                    "cycle_type": attempt.cycle_type.value,
                    "chain_id": attempt.active_chain_id,
                    "map_version_id": attempt.map_version_id,
                }
                chain = [
                    e
                    for e in progress.evidence_items
                    if e.attempt_id == attempt.id and e.chain_id == attempt.active_chain_id
                ]
                evidence_summary[kp_id] = {
                    "count": len(chain),
                    "kinds": [e.kind.value for e in chain],
                }
        latest = _latest_map_version(progress)
        return {
            "book_id": progress.book_id,
            "next": next_objective(progress, now=moment).to_dict(),
            "projections": {kp: p.model_dump() for kp, p in projections.items()},
            "active_attempts": active_attempts,
            "evidence_summary": evidence_summary,
            "map_version": latest.version if latest else 0,
            "map_version_id": latest.id if latest else "",
            "source_snapshots": [s.model_dump() for s in progress.source_snapshots],
            "map_versions": [v.model_dump() for v in progress.map_versions],
            "conflicts": [c.model_dump() for c in self._current_conflicts(progress)],
            "updated_at": moment,
        }

    def attempt_read_payload(self, progress, *, attempt_id: str) -> dict[str, Any]:
        attempt = self._attempt(progress, attempt_id)
        evidence = [e.model_dump() for e in progress.evidence_items if e.attempt_id == attempt_id]
        assessments = sorted(
            (a.model_dump() for a in progress.rubric_assessments if a.attempt_id == attempt_id),
            key=lambda a: (a["assessment_sequence"], a["created_at"]),
        )
        gap_ids = sorted({gid for a in assessments for gid in a["gap_ids"]})
        gaps = [
            g.model_dump()
            for g in progress.gaps
            if g.id in gap_ids or g.knowledge_point_id == attempt.knowledge_point_id
        ]
        challenges = [
            c.model_dump()
            for c in progress.challenge_records
            if c.source_attempt_id == attempt_id or c.result_attempt_id == attempt_id
        ]
        audit = [
            {"seq": e.seq, "event_type": e.event_type, "summary": e.summary, "at": e.at}
            for e in progress.history
            if attempt_id in (e.payload or {}).get("attempt_id", "")
            or attempt_id in (e.payload or {}).get("evidence_id", "")
            or attempt_id in (e.payload or {}).get("result_attempt_id", "")
            or attempt_id in json.dumps(e.payload, default=str)
        ]
        return {
            "attempt": attempt.model_dump(),
            "evidence": evidence,
            "assessments": assessments,
            "gaps": gaps,
            "challenges": challenges,
            "audit": audit[-20:],
            "projection": progress.projections.get(attempt.knowledge_point_id).model_dump()
            if progress.projections.get(attempt.knowledge_point_id)
            else None,
        }

    def reviews_read_payload(self, progress, *, now: float | None = None) -> dict[str, Any]:
        moment = now if now is not None else time.time()
        projections = project_all(progress, now=moment)
        tasks = self._unified_review_queue(progress, now=moment)
        due = [t for t in tasks if t.due_at <= moment]
        return {
            "reviews": [t.model_dump() for t in tasks],
            "due_reviews": [t.model_dump() for t in due],
            "due_count": len(due),
            "needs_revision": [
                kp_id
                for kp_id, projection in projections.items()
                if projection.mastery_state == MasteryState.NEEDS_REVISION
            ],
            "updated_at": moment,
        }

    @staticmethod
    def _current_conflicts(progress) -> list[SourceConflict]:
        """One revision per conflict id — the newest — preserving both sides."""
        by_id: dict[str, SourceConflict] = {}
        for conflict in progress.source_conflicts:
            current = by_id.get(conflict.id)
            if current is None or conflict.version > current.version:
                by_id[conflict.id] = conflict
        return sorted(by_id.values(), key=lambda c: c.id)


def is_configured_evaluator_snapshot(
    snapshot: EvaluatorSnapshot, catalog: Any | None = None
) -> bool:
    """True when ``snapshot`` is a *complete* server-canonical evaluator identity.

    Used to reject a challenge's requested alternative evaluator (or any
    client-supplied snapshot). Every required frozen field must be present
    (omission is never tolerated) and verified exactly against the currently
    configured profile: the profile id and exact profile revision, the resolved
    model, the resolved API protocol after auto-resolution, the strict-protocol
    flag (including an explicit ``false`` rather than omission), and the exact
    non-secret base-URL fingerprint. A request that merely names a configured
    profile/model but omits or forges any of the rest fails closed here and
    again at the evaluation boundary (§7.3.1/§9.3).
    """
    if snapshot is None or not snapshot.profile_id or not snapshot.resolved_model:
        return False
    if catalog is not None:
        loaded = catalog
    else:
        from deeptutor.services.config import get_model_catalog_service

        loaded = get_model_catalog_service().load()
    if not _configured_model_exists(loaded, snapshot):
        return False
    from deeptutor.services.config.provider_runtime import resolve_api_protocol
    from deeptutor.services.model_selection.fingerprint import (
        base_url_fingerprint,
        profile_revision,
    )

    service = (loaded or {}).get("services", {}).get("llm", {})
    profile = next(
        (
            profile
            for profile in service.get("profiles", []) or []
            if isinstance(profile, dict) and profile.get("id") == snapshot.profile_id
        ),
        None,
    )
    if profile is None:
        return False
    expected_protocol, _ = resolve_api_protocol(
        str(profile.get("binding") or ""), str(profile.get("api_protocol") or "auto")
    )
    # Every identity field is required and must match exactly — an omitted
    # field never falls back to a catalog default and never skips a check.
    if not str(snapshot.resolved_api_protocol or ""):
        return False
    if snapshot.resolved_api_protocol != expected_protocol:
        return False
    if "strict_protocol" not in snapshot.model_fields_set:
        return False
    configured_strict = bool(profile.get("strict_protocol"))
    if bool(snapshot.strict_protocol) != configured_strict:
        return False
    if not str(snapshot.profile_revision or ""):
        return False
    if str(snapshot.profile_revision) != profile_revision(profile):
        return False
    if not str(snapshot.base_url_fingerprint or ""):
        return False
    if snapshot.base_url_fingerprint != base_url_fingerprint(str(profile.get("base_url") or "")):
        return False
    return True


def finalize_client_fingerprint(client_payload: dict[str, Any]) -> str:
    """Canonical idempotency fingerprint for the caller's finalize request.

    The client (tool) payload is the model-supplied proposal; the fingerprint
    lets a retry distinguish replay (same payload) from conflict (different
    payload) *before* the evaluator is invoked (§8.3).
    """
    return _fingerprint(client_payload)


# ── production evaluator resolution (MOD-03 → ASM-01) ────────────────────

#: Rubric contract version stamped into every frozen evaluator snapshot.
EVALUATOR_RUBRIC_VERSION = "feynman-rubric-v1"
#: Prompt contract version stamped into every frozen evaluator snapshot.
EVALUATOR_PROMPT_VERSION = "feynman-eval-v1"


def _configured_model_exists(catalog: Any, snapshot: EvaluatorSnapshot) -> bool:
    """True when ``snapshot``'s profile/model is actually configured.

    Guards against the hard-coded ``gpt-4o-mini`` fallback inside
    ``resolve_llm_runtime_config``: a profile with no configured model must not
    produce a fake nonempty snapshot (§9.3).
    """
    service = (catalog or {}).get("services", {}).get("llm", {})
    for profile in service.get("profiles", []) or []:
        if not isinstance(profile, dict) or profile.get("id") != snapshot.profile_id:
            continue
        return any(
            isinstance(model, dict)
            and model.get("model")
            and model.get("model") == snapshot.resolved_model
            for model in profile.get("models", []) or []
        )
    return False


def production_evaluator_resolver(*, catalog: Any | None = None):
    """Build the production evaluator resolver used by the tool/API wiring.

    The returned ``resolver(progress, *, now)`` resolves the learning path's
    configured evaluator (or the active LLM profile default, §9.3) and freezes
    the non-secret snapshot — no LLM call. When no valid configured evaluator
    can be resolved it raises :class:`EvaluatorResolutionError` instead of
    fabricating a snapshot or falling back to another model.
    """

    def resolver(progress, *, now: float | None = None) -> EvaluatorSnapshot:
        from deeptutor.learning.knowledge_cards.eligibility import (
            is_frozen_evaluator_snapshot,
        )
        from deeptutor.services.config import get_model_catalog_service
        from deeptutor.services.model_selection import (
            ModelSelector,
            evaluator_selection_from_progress,
        )

        moment = now if now is not None else time.time()
        loaded = catalog if catalog is not None else get_model_catalog_service().load()
        selection = evaluator_selection_from_progress(progress)
        try:
            resolved = ModelSelector(catalog=loaded).resolve_evaluator(selection)
        except Exception as exc:  # noqa: BLE001 - invalid selection surfaces as unavailable
            raise EvaluatorResolutionError(
                "no valid configured evaluator: selection could not be resolved "
                f"({type(exc).__name__})"
            ) from exc
        snapshot = resolved.to_evaluator_snapshot(
            rubric_version=EVALUATOR_RUBRIC_VERSION,
            prompt_version=EVALUATOR_PROMPT_VERSION,
            now=moment,
        )
        if not is_frozen_evaluator_snapshot(snapshot) or not _configured_model_exists(
            loaded, snapshot
        ):
            raise EvaluatorResolutionError(
                "no valid configured evaluator: the learning path has no "
                "evaluator profile/model configured and no active LLM profile "
                "with a real model is available"
            )
        return snapshot

    return resolver


__all__ = [
    "EVALUATOR_PROMPT_VERSION",
    "EVALUATOR_RUBRIC_VERSION",
    "EvaluatorResolutionError",
    "FeynmanError",
    "OwnershipError",
    "InvalidAttemptStateError",
    "EvidenceOrderError",
    "EvidenceConflictError",
    "IdempotencyConflictError",
    "StaleVersionError",
    "ConflictResolutionError",
    "UnknownAttemptError",
    "UnknownConflictError",
    "FeynmanCycleService",
    "finalize_client_fingerprint",
    "is_configured_evaluator_snapshot",
    "production_evaluator_resolver",
]
