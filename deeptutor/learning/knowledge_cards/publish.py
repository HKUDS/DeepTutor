"""Durable knowledge-card publication (KB-03).

Owns durable, user-confirmed publication of a confirmed knowledge card into a
writable local indexed knowledge base (§7.9.2). Publication is:

* **authorization-bound** — only the card owner may publish/retry/reconcile,
  and the addressed path/card must match (requirement 1);
* **eligibility-gated** — at publish time the card must be a draft / current
  failed publication, ``expected_card_revision`` must match, the bound stable
  assessment must still be the projection's latest valid stable assessment,
  and mastery must still be ``stable_mastery`` (requirement 2);
* **explicit user confirmation** — ``confirmed_at`` is set only through the
  publish operation; generation completion alone never publishes
  (requirement 3);
* **writable-KB enforced** — the reusable
  :func:`deeptutor.knowledge.writable.assert_kb_writable` policy must pass
  (existing ordinary local indexed KB, ``ready``, local raw document set, ready
  provider index, no ``needs_reindex``, not connected/external) (requirement 4);
* **deterministic** — the document is rendered from the confirmed card and
  allowed provenance only, at the fixed relative path
  ``learning_cards/{card_id}-v{revision}.md``, with a persisted SHA-256
  (requirement 6);
* **restart-safe and idempotent** — the per-KB ``card_publish`` lease is
  reused, ``kb_busy`` is recoverable, and a crashed/expired publication cannot
  permit a second mutation until explicit reconciliation (requirements 5/10/12);
* **append-only** — publication records/history are never overwritten while the
  card projects current status (requirement 5).

This service never copies raw conversation, provider prompts/responses,
credentials, base64 or private URLs into the document or any durable record.
On an unambiguous index failure it keeps the card recoverable
(``publish_failed``), retains draft content/provenance, and removes only the
unsuccessful fixed raw file and matching hash entry; when a partial provider
mutation cannot be ruled out it converges to ``reconcile_required``, marks the
KB ``needs_reindex``, and blocks new publication until repaired (requirement 9).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Callable
from uuid import uuid4

from deeptutor.knowledge.add_documents import DocumentAdder, remove_raw_document
from deeptutor.knowledge.kb_types import is_connected_kb
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.writable import (
    KbNotWritableError,
    assert_kb_writable,
    kb_is_ready,
)
from deeptutor.knowledge.write_coordinator import (
    KbBusyError,
    KbLeaseError,
    KbWriteCoordinator,
    LeaseHeartbeat,
    heartbeat_interval_seconds,
)
from deeptutor.learning.knowledge_cards.eligibility import stable_assessment_is_current
from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardEligibilityError,
    KnowledgeCardError,
    KnowledgeCardInputValidationError,
    KnowledgeCardKbNotWritableError,
    KnowledgeCardNotFoundError,
    KnowledgeCardOwnershipError,
    KnowledgeCardPublicationConflictError,
    KnowledgeCardPublicationUnavailableError,
    KnowledgeCardReconcileRequiredError,
    KnowledgeCardStaleVersionError,
    KnowledgeCardStateError,
)
from deeptutor.learning.knowledge_cards.store import require_card
from deeptutor.learning.models import (
    KnowledgeCardPublicationRecord,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    LearningProgress,
    PublicationIntent,
    PublicationStatus,
)
from deeptutor.learning.storage import (
    LearningStore,
    VersionConflictError,
    append_history,
)
from deeptutor.services.file_io import atomic_write_text
from deeptutor.services.media.models import ReferenceOwnerType
from deeptutor.services.media.redaction import redact_text
from deeptutor.services.model_selection.fingerprint import sanitize_error

logger = logging.getLogger(__name__)

#: Fixed relative document path prefix for published knowledge cards (§7.9.2
#: requirement 6). The full path is ``learning_cards/{card_id}-v{revision}.md``
#: and is preserved verbatim under ``<kb>/raw`` — never flattened.
FIXED_CARD_DIRECTORY = "learning_cards"


#: History event types for the publication lifecycle (append-only audit).
_EVENT_PUBLICATION_STARTED = "knowledge_card_publication_started"
_EVENT_PUBLISHED = "knowledge_card_published"
_EVENT_PUBLISH_FAILED = "knowledge_card_publish_failed"
_EVENT_RECONCILE_REQUIRED = "knowledge_card_publish_reconcile_required"
_EVENT_PUBLICATION_RECONCILED = "knowledge_card_publication_reconciled"
_EVENT_STALE_AT_PUBLISH = "knowledge_card_stale_at_publish"

#: Exact error ``DocumentAdder.process_new_documents`` records when the provider
#: returns ``False`` (i.e. deterministically reported *no* mutation). Every
#: other failure string means an exception — a partial provider mutation cannot
#: be ruled out, so the publication converges to ``reconcile_required``.
_PROVIDER_NO_MUTATION_SENTINEL = "Provider returned failure without details."

# ── Markdown privacy / safety (§14) ────────────────────────────────────────

#: Dangerous HTML elements removed entirely (with their inner content) before a
#: rendered card is persisted/published. ``<style>``/``<link>``/``<meta>``/
#: ``<base>`` could pivot page behavior; ``<script>``/``<iframe>``/``<object>``/
#: ``<embed>``/``<form>``/``<input>``/``<button>`` etc. are active or credential
#: -collecting elements that never belong in a knowledge-card document.
_DANGEROUS_ELEMENT_RE = re.compile(
    r"<\s*(script|iframe|object|embed|link|meta|style|base|form|"
    r"input|button|textarea|select|template)\b[^>]*>.*?<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
#: Unpaired/self-closing dangerous elements.
_DANGEROUS_SELF_CLOSING_ELEMENT_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed|link|meta|style|base|input|button|"
    r"textarea|select|template)\b[^>]*/?>",
    re.IGNORECASE,
)
#: Event-handler / style / srcdoc attributes stripped from any retained HTML.
_HTML_EVENT_ATTR_RE = re.compile(
    r"\s+on[a-z][a-z0-9]*\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+)",
    re.IGNORECASE,
)
_HTML_STYLE_ATTR_RE = re.compile(
    r"\s+style\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+)",
    re.IGNORECASE,
)
_HTML_SRCDOC_ATTR_RE = re.compile(
    r"\s+srcdoc\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+)",
    re.IGNORECASE,
)
#: URL schemes that can execute or exfiltrate from a rendered link/image.
_UNSAFE_URL_SCHEME = r"(?:javascript|data|vbscript|file|blob|about)"
_HTML_UNSAFE_URL_ATTR_RE = re.compile(
    rf"\s+(?:href|src|xlink:href|formaction)\s*=\s*"
    rf"(?:\"\s*{_UNSAFE_URL_SCHEME}:(?:[^\"]*)\"|"
    rf"'\s*{_UNSAFE_URL_SCHEME}:(?:[^']*)'|"
    rf"{_UNSAFE_URL_SCHEME}:[^\s\"'=<>`]+)",
    re.IGNORECASE,
)
_DANGEROUS_SCHEME_RE = re.compile(rf"^\s*{_UNSAFE_URL_SCHEME}:", re.IGNORECASE)
#: Markdown link/image destination: ``[label](dest)`` or ``![alt](dest)``.
_MARKDOWN_DEST_RE = re.compile(r"(!?\[[^\]]*\]\()([^\s\)]+)(\))")


def _neutralize_markdown_destination(match: re.Match[str]) -> str:
    prefix, dest, suffix = match.groups()
    if _DANGEROUS_SCHEME_RE.match(dest):
        # Keep the label/prose, drop the dangerous target.
        return f"{prefix}#{suffix}"
    return match.group(0)


def sanitize_markdown_content(text: str) -> str:
    """Sanitize untrusted Markdown before it is published (§14).

    Applies the established :func:`redact_text` redaction (credentials, full
    URLs, base64 payloads), removes dangerous raw HTML elements, strips
    event-handler/style/srcdoc attributes, and neutralizes dangerous link/image
    URL schemes (``javascript:``, ``data:``, ``vbscript:``, ...) in both HTML
    attributes and Markdown links — while preserving ordinary safe learning
    prose and useful Markdown.
    """
    if not text:
        return ""
    safe = redact_text(str(text))
    safe = _DANGEROUS_ELEMENT_RE.sub("", safe)
    safe = _DANGEROUS_SELF_CLOSING_ELEMENT_RE.sub("", safe)
    safe = _HTML_EVENT_ATTR_RE.sub("", safe)
    safe = _HTML_STYLE_ATTR_RE.sub("", safe)
    safe = _HTML_SRCDOC_ATTR_RE.sub("", safe)
    safe = _HTML_UNSAFE_URL_ATTR_RE.sub("", safe)
    safe = _MARKDOWN_DEST_RE.sub(_neutralize_markdown_destination, safe)
    return safe


def _safe_card_id(card_id: str) -> str:
    """Return *card_id* only when it is a safe single document path segment.

    A malformed/legacy card id must never escape ``raw/learning_cards``, so
    separators, traversal, absolute components, NUL and control characters are
    rejected rather than relying on the current UUID generator (§14).
    """
    if not isinstance(card_id, str) or not card_id:
        raise KnowledgeCardInputValidationError("card id is required")
    if any(ch in card_id for ch in ("/", "\\", ":", "\x00", "..")):
        raise KnowledgeCardInputValidationError(
            f"card id {card_id!r} is not a safe document path segment"
        )
    if any(ord(ch) < 32 for ch in card_id):
        raise KnowledgeCardInputValidationError(f"card id {card_id!r} contains control characters")
    return card_id


def fixed_document_rel_path(card_id: str, card_revision: int) -> str:
    """The fixed nested relative path for a published knowledge card.

    The card id is sandboxed to a single safe path segment, so a malformed or
    legacy id can never escape ``raw/learning_cards`` (§14).
    """
    safe_id = _safe_card_id(card_id)
    if not isinstance(card_revision, int) or card_revision < 1:
        raise KnowledgeCardInputValidationError(
            f"card revision must be a positive integer, got {card_revision!r}"
        )
    return f"{FIXED_CARD_DIRECTORY}/{safe_id}-v{card_revision}.md"


def _validate_document_rel_path(rel_path: str) -> str:
    """Return *rel_path* only when it is a safe nested path under ``learning_cards/``.

    Used whenever a persisted ``document_rel_path`` is later joined onto a KB
    raw directory (reconcile/projection), so a malformed or legacy value can
    never escape ``raw/learning_cards``.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise KnowledgeCardInputValidationError("document path is empty")
    parts = rel_path.split("/")
    if len(parts) != 2 or parts[0] != FIXED_CARD_DIRECTORY:
        raise KnowledgeCardInputValidationError(
            f"document path {rel_path!r} escapes {FIXED_CARD_DIRECTORY}/"
        )
    name = parts[1]
    if name in ("", ".", ".."):
        raise KnowledgeCardInputValidationError(
            f"document path {rel_path!r} is not a single nested file"
        )
    if any(ch in name for ch in ("/", "\\", ":", "\x00")) or any(ord(ch) < 32 for ch in name):
        raise KnowledgeCardInputValidationError(
            f"document path {rel_path!r} contains unsafe characters"
        )
    return rel_path


def publication_key(user_id: str, card_id: str, card_revision: int, target_kb_name: str) -> str:
    """Deterministic publication key (§7.9.2 requirement 5)."""
    return f"kb3:{user_id}|{card_id}|{card_revision}|{target_kb_name}"


def render_card_markdown(card: KnowledgeCardRecord, progress: LearningProgress) -> str:
    """Deterministic UTF-8 Markdown from the confirmed card + allowed provenance.

    Only the confirmed title/body and identity-level provenance participate:
    knowledge-point/assessment ids, source titles + citation anchors, and
    evidence/artifact ids. Raw conversation, provider prompts/responses,
    credentials, base64, private URLs and arbitrary unowned references are never
    copied into the document (§7.9.2 requirement 6). The same card + progress
    always renders the same bytes, so the persisted SHA-256 is stable.
    """
    title = sanitize_markdown_content(
        (card.title or "").replace("\n", " ").replace("\r", " ").strip()
    )
    lines: list[str] = [f"# {title}", ""]
    body = sanitize_markdown_content((card.body or "").strip())
    if body:
        lines.append(body)
        lines.append("")
    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Knowledge point: `{card.knowledge_point_id}`")
    lines.append(
        f"- Stable assessment: `{card.stable_assessment_id}` "
        f"(sequence {card.stable_assessment_sequence})"
    )
    source_by_id = {snapshot.id: snapshot for snapshot in progress.source_snapshots}
    for sid in card.source_snapshot_ids:
        source = source_by_id.get(sid)
        if source is None:
            continue
        # Source titles/anchors are sanitized exactly like card content so a
        # private URL, credential, base64 payload or dangerous HTML/link
        # protocol can never leak into the published document (§14).
        source_title = sanitize_markdown_content(
            (source.title or sid).replace("\n", " ").replace("\r", " ").strip() or sid
        )
        anchors = [
            sanitize_markdown_content(str(anchor).strip())
            for anchor in (source.citation_anchors or [])
            if str(anchor).strip()
        ]
        suffix = f" ({', '.join(anchors)})" if anchors else ""
        lines.append(f"- Source: {source_title}{suffix}")
    if card.evidence_ids:
        lines.append(f"- Evidence: {', '.join(sorted(card.evidence_ids))}")
    if card.artifact_ids:
        lines.append(f"- Artifacts: {', '.join(sorted(card.artifact_ids))}")
    lines.append("")
    return "\n".join(lines) + "\n"


class KnowledgeCardPublicationService:
    """Durable publish / retry-publish / reconcile-publication for one card."""

    def __init__(
        self,
        store: LearningStore | None = None,
        *,
        kb_base_dir: str | Path | None = None,
        manager: KnowledgeBaseManager | None = None,
        media_store: Any | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._store = store or LearningStore()
        self._kb_base_dir = Path(kb_base_dir) if kb_base_dir is not None else None
        self._manager = manager
        self._media_store = media_store
        self._now = now or time.time

    @property
    def store(self) -> LearningStore:
        return self._store

    @property
    def media_store(self) -> Any:
        """The media store used to revalidate artifact references at publish."""
        if self._media_store is None:
            from deeptutor.services.media.store import MediaStore

            self._media_store = MediaStore()
        return self._media_store

    @property
    def kb_base_dir(self) -> Path:
        if self._kb_base_dir is not None:
            return self._kb_base_dir
        if self._manager is not None:
            return Path(self._manager.base_dir)
        from deeptutor.multi_user.knowledge_access import current_kb_base_dir

        return current_kb_base_dir()

    def _get_manager(self) -> KnowledgeBaseManager:
        if self._manager is not None:
            return self._manager
        if self._kb_base_dir is not None:
            return KnowledgeBaseManager(base_dir=str(self._kb_base_dir))
        from deeptutor.multi_user.knowledge_access import current_kb_manager

        return current_kb_manager()

    def _load(self, path_id: str) -> LearningProgress:
        progress = self._store.load(path_id)
        if progress is None:
            raise KnowledgeCardNotFoundError(f"progress for path {path_id!r} not found")
        return progress

    def save(self, progress: LearningProgress) -> None:
        try:
            self._store.save(progress)
        except VersionConflictError as exc:
            raise KnowledgeCardStaleVersionError(
                f"stale save rejected for {exc.book_id!r}: caller holds "
                f"{exc.expected_version}, persisted {exc.persisted_version}; "
                "reload before saving so append-only history is never overwritten"
            ) from exc

    # ── ownership / path / writable policy ──────────────────────────────────

    def _require_ownership_and_path(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord,
        user_id: str,
    ) -> None:
        if not user_id:
            raise KnowledgeCardOwnershipError("actor user id is required")
        if card.user_id and card.user_id != user_id:
            raise KnowledgeCardOwnershipError(
                f"card {card.id!r} belongs to user {card.user_id!r}, not {user_id!r}"
            )
        if card.path_id and card.path_id != progress.book_id:
            raise KnowledgeCardInputValidationError(
                f"card {card.id!r} belongs to path {card.path_id!r}, not "
                f"{progress.book_id!r}; cross-path publication fails closed"
            )

    def _assert_kb_writable(self, kb_name: str) -> dict[str, Any]:
        manager = self._get_manager()
        try:
            return assert_kb_writable(manager, kb_name)
        except KbNotWritableError as exc:
            raise KnowledgeCardKbNotWritableError(str(exc)) from exc

    def _revalidate_publication_references(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord,
        *,
        user_id: str,
    ) -> None:
        """Revalidate frozen source/evidence/artifact references at publish time.

        Uses the KB-02 validation patterns (§6.6): every evidence id must exist
        and belong to the card's stable attempt; every source snapshot id must
        be materialized and frozen on that attempt; every artifact must exist
        and be owned by the acting user/card. Fails closed — before lease
        acquisition or KB mutation — on a deleted, unowned or cross-path
        reference (§7.9.2 requirement 2 / §14).
        """
        assessment = next(
            (item for item in progress.rubric_assessments if item.id == card.stable_assessment_id),
            None,
        )
        attempt = next(
            (item for item in progress.attempts if item.id == card.stable_attempt_id),
            None,
        )
        if assessment is None or attempt is None:
            raise KnowledgeCardEligibilityError(
                f"card {card.id!r} no longer resolves to a stable assessment/attempt"
            )
        evidence_by_id = {item.id: item for item in progress.evidence_items}
        for evidence_id in card.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                raise KnowledgeCardInputValidationError(
                    f"evidence {evidence_id!r} referenced by card {card.id!r} does not exist"
                )
            if item.attempt_id != attempt.id:
                raise KnowledgeCardInputValidationError(
                    f"evidence {evidence_id!r} belongs to attempt "
                    f"{item.attempt_id!r}, not the stable attempt {attempt.id!r}"
                )
        source_by_id = {snapshot.id: snapshot for snapshot in progress.source_snapshots}
        frozen = set(attempt.source_snapshot_ids)
        for sid in card.source_snapshot_ids:
            if sid not in source_by_id:
                raise KnowledgeCardInputValidationError(
                    f"source snapshot {sid!r} referenced by card {card.id!r} is not materialized"
                )
            if sid not in frozen:
                raise KnowledgeCardInputValidationError(
                    f"source snapshot {sid!r} referenced by card {card.id!r} "
                    "is not frozen on the stable attempt"
                )
        for artifact_id in card.artifact_ids:
            artifact = self.media_store.load_artifact(artifact_id)
            if artifact is None:
                raise KnowledgeCardInputValidationError(
                    f"artifact {artifact_id!r} referenced by card {card.id!r} does not exist"
                )
            if artifact.user_id != user_id:
                raise KnowledgeCardInputValidationError(
                    f"artifact {artifact_id!r} belongs to user "
                    f"{artifact.user_id!r}, not {user_id!r}"
                )
            # The frozen design binds each artifact to exactly this card by a
            # *live* KNOWLEDGE_CARD reference with owner_id=card.id. A same-user
            # artifact referenced by another card/context — or a soft-deleted
            # card reference — fails closed before lease acquisition / KB
            # mutation, so a published document can never claim an artifact the
            # card does not durably own (§7.9.2 requirement 2 / §10.5).
            reference = self.media_store.find_live_reference(
                artifact_id=artifact_id,
                user_id=user_id,
                owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
                owner_id=card.id,
            )
            if reference is None:
                raise KnowledgeCardInputValidationError(
                    f"artifact {artifact_id!r} referenced by card {card.id!r} "
                    "is not bound to this card by a live knowledge-card "
                    "reference; publish fails closed"
                )

    # ── publication record lookups ──────────────────────────────────────────

    @staticmethod
    def _latest_publication(
        progress: LearningProgress, pub_key: str
    ) -> KnowledgeCardPublicationRecord | None:
        for record in reversed(progress.knowledge_card_publication_records):
            if record.publication_key == pub_key:
                return record
        return None

    @staticmethod
    def _records_for_card(
        progress: LearningProgress, card_id: str
    ) -> list[KnowledgeCardPublicationRecord]:
        """The current publication projection: one record per logical publication.

        Publication records are append-only revision history; the projection
        deterministically selects the latest revision per logical record id so a
        client observes current state while the durable list keeps every prior
        revision.
        """
        latest_by_id: dict[str, KnowledgeCardPublicationRecord] = {}
        for record in progress.knowledge_card_publication_records:
            if record.card_id == card_id:
                latest_by_id[record.id] = record
        return list(latest_by_id.values())

    # ── result / projection helpers ─────────────────────────────────────────

    def _card_result(
        self, progress: LearningProgress, card: KnowledgeCardRecord, *, replayed: bool
    ) -> dict[str, Any]:
        return {
            "card_id": card.id,
            "status": card.status.value,
            "replayed": replayed,
            "revision": card.revision,
            "target_kb_name": card.target_kb_name,
            "document_rel_path": card.document_rel_path,
            "document_sha256": card.document_sha256,
            "publication_key": card.publication_key,
            "confirmed_at": card.confirmed_at,
            "published_at": card.published_at,
            "error_code": card.error_code,
            "sanitized_error": card.sanitized_error,
        }

    def _reload_result(self, path_id: str, card_id: str, *, replayed: bool) -> dict[str, Any]:
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        return self._card_result(progress, card, replayed=replayed)

    def publication_projection(self, path_id: str, *, card_id: str, user_id: str) -> dict[str, Any]:
        """A read projection so a client can observe publication state after reload."""
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)
        records = self._records_for_card(progress, card_id)
        return {
            **self._card_result(progress, card, replayed=False),
            "publication_records": [record.model_dump(mode="json") for record in records],
        }

    # ── publish / retry-publish ─────────────────────────────────────────────

    async def publish(
        self,
        path_id: str,
        *,
        card_id: str,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        target_kb_name: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """User-confirmed publication; allows a draft or a failed publication."""
        moment = now if now is not None else self._now()
        return await self._publish_impl(
            path_id,
            card_id=card_id,
            user_id=user_id,
            request_id=request_id,
            expected_card_revision=expected_card_revision,
            target_kb_name=target_kb_name,
            allow_draft=True,
            now=moment,
        )

    async def retry_publish(
        self,
        path_id: str,
        *,
        card_id: str,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        target_kb_name: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Retry a confirmed-failed publication, reusing the original key/path/hash.

        ``target_kb_name`` defaults to (and must match) the original target the
        failed publication used, so a retry can never migrate a publication to a
        different KB or create a second raw document/record/index entry.
        """
        moment = now if now is not None else self._now()
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)
        if target_kb_name is None:
            target_kb_name = card.target_kb_name
        elif card.target_kb_name and card.target_kb_name != target_kb_name:
            raise KnowledgeCardInputValidationError(
                f"retry-publish must reuse the original target knowledge base "
                f"{card.target_kb_name!r}, not {target_kb_name!r}"
            )
        if not target_kb_name:
            raise KnowledgeCardInputValidationError(
                "the original target knowledge base is unknown; call publish with "
                "target_kb_name instead"
            )
        return await self._publish_impl(
            path_id,
            card_id=card_id,
            user_id=user_id,
            request_id=request_id,
            expected_card_revision=expected_card_revision,
            target_kb_name=target_kb_name,
            allow_draft=False,
            now=moment,
        )

    async def _publish_impl(
        self,
        path_id: str,
        *,
        card_id: str,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        target_kb_name: str,
        allow_draft: bool,
        now: float,
    ) -> dict[str, Any]:
        if not user_id:
            raise KnowledgeCardOwnershipError("actor user id is required")
        if not request_id:
            raise KnowledgeCardInputValidationError("request_id is required")
        if not target_kb_name:
            raise KnowledgeCardInputValidationError("target_kb_name is required")

        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)

        rel_path = fixed_document_rel_path(card.id, card.revision)
        document = render_card_markdown(card, progress)
        document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
        pub_key = publication_key(user_id, card.id, card.revision, target_kb_name)

        # Idempotency + start-state resolution (same key + same content replays).
        basis = self._resolve_publication_basis(progress, card, pub_key, document_sha)
        if basis == "replay":
            return self._card_result(progress, card, replayed=True)

        if expected_card_revision != card.revision:
            raise KnowledgeCardStaleVersionError(
                f"card {card_id!r} revision conflict: expected "
                f"{expected_card_revision}, current {card.revision}"
            )
        if card.status == KnowledgeCardStatus.DRAFT and not allow_draft:
            raise KnowledgeCardStateError(
                f"retry-publish requires a publish_failed card; {card_id!r} is a draft"
            )
        if card.status not in (
            KnowledgeCardStatus.DRAFT,
            KnowledgeCardStatus.PUBLISH_FAILED,
        ):
            raise KnowledgeCardStateError(
                f"card {card_id!r} is {card.status.value}; only a draft or a failed "
                "publication can be published"
            )
        if not stable_assessment_is_current(progress, card):
            self._persist_stale_evidence(
                path_id,
                card_id,
                user_id=user_id,
                moment=now,
                reason="stable assessment no longer current at publish",
            )
            raise KnowledgeCardEligibilityError(
                f"card {card_id!r} is no longer backed by the current latest valid "
                "stable assessment; its evidence was marked stale and the KB was "
                "not touched"
            )

        # Revalidate frozen source/evidence/artifact references at the publish
        # boundary — fails closed before lease acquisition / KB mutation on a
        # deleted, unowned or cross-path reference (requirement 2 / §14).
        self._revalidate_publication_references(progress, card, user_id=user_id)

        # Writable-KB policy (before any KB mutation).
        self._assert_kb_writable(target_kb_name)
        kb_dir = self._get_manager().get_knowledge_base_path(target_kb_name)
        raw_root = (kb_dir / "raw").resolve()
        raw_path = (raw_root / rel_path).resolve()
        if not raw_path.is_relative_to(raw_root):
            raise KnowledgeCardInputValidationError(
                f"document path {rel_path!r} escapes the KB raw directory"
            )

        # Durable publication intent (phase 1) — persisted *before* lease
        # acquisition so a crash at every boundary leaves a recoverable
        # two-phase record (target/key/path/hash/request identity).
        self._persist_publication_intent(
            path_id,
            card_id,
            user_id=user_id,
            request_id=request_id,
            expected_card_revision=expected_card_revision,
            target_kb_name=target_kb_name,
            pub_key=pub_key,
            rel_path=rel_path,
            document_sha=document_sha,
            now=now,
        )

        # Per-KB durable lease (``card_publish``).
        coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
        owner = f"publish:{uuid4().hex[:12]}"
        try:
            op = coordinator.acquire(
                target_kb_name,
                "card_publish",
                owner=owner,
                request_id=request_id,
                subject_id=card_id,
                user_id=user_id,
            )
        except KbBusyError as exc:
            # The publication never started; drop the staged intent so a fresh
            # draft does not carry stale intent.
            self._clear_publication_intent(path_id, card_id, user_id, now)
            raise KnowledgeCardPublicationUnavailableError(
                f"target knowledge base {target_kb_name!r} is busy (kb_busy): a "
                f"{exc.operation_type} operation is {exc.status}; retry after it "
                "completes or is reconciled"
            ) from exc

        # Lease heartbeat: renews during the potentially long staging/indexing
        # phase and aborts (fail-closed) as soon as ownership is lost or the
        # lease state becomes unknown, so a stale writer never keeps mutating
        # under a newer holder.
        heartbeat = LeaseHeartbeat(
            coordinator,
            target_kb_name,
            op.id,
            owner=owner,
            interval=heartbeat_interval_seconds(coordinator),
        )
        heartbeat.start()

        def _lease_check() -> None:
            heartbeat.check()
            coordinator.verify_lease(target_kb_name, op.id, owner=owner)

        try:
            try:
                progress, _card, _record = self._begin_publication(
                    path_id,
                    card_id,
                    user_id=user_id,
                    request_id=request_id,
                    expected_card_revision=expected_card_revision,
                    target_kb_name=target_kb_name,
                    pub_key=pub_key,
                    rel_path=rel_path,
                    document_sha=document_sha,
                    now=now,
                    op_id=op.id,
                )
            except KnowledgeCardError:
                self._clear_publication_intent(path_id, card_id, user_id, now)
                self._release_lease(
                    coordinator,
                    target_kb_name,
                    op.id,
                    owner,
                    error_code="publication_did_not_start",
                    error="publication eligibility check failed",
                )
                raise

            try:
                # Stage/write the fixed raw document safely, then integrate
                # through the existing DocumentAdder + RAGService path. Staging
                # runs in a worker thread with a cooperative per-file lease
                # checkpoint; indexing is heartbeat-guarded so a long index
                # aborts on ownership loss instead of continuing.
                _lease_check()
                self._write_raw_document(raw_path, document)
                adder = DocumentAdder(kb_name=target_kb_name, base_dir=str(self.kb_base_dir))
                new_files = await asyncio.to_thread(
                    adder.add_documents,
                    [str(raw_path)],
                    allow_duplicates=True,
                    lease_check=_lease_check,
                )
                heartbeat.check()
                if not any(str(Path(f).resolve()) == str(raw_path.resolve()) for f in new_files):
                    outcome, err = (
                        "unambiguous_failure",
                        ("staged document was not accepted for indexing"),
                    )
                else:
                    try:
                        index_result = await heartbeat.run_guarded(
                            adder.process_new_documents(new_files)
                        )
                    except Exception as exc:  # noqa: BLE001 - failure classification
                        outcome, err = "ambiguous_failure", sanitize_error(str(exc))
                    else:
                        outcome, err = self._classify_index_result(index_result, raw_path)
            except KbLeaseError:
                # Lease lost or unknown during staging/indexing: never mark the
                # card published and never resolve another holder's operation.
                # Converge conservatively to a recoverable reconcile state with
                # no further KB mutation (no cleanup, no mark_needs_reindex).
                self._finalize(
                    path_id,
                    card_id,
                    status=KnowledgeCardStatus.RECONCILE_REQUIRED,
                    coordinator=coordinator,
                    kb_name=target_kb_name,
                    op_id=op.id,
                    owner=owner,
                    rel_path=rel_path,
                    document_sha=document_sha,
                    expected_revision=expected_card_revision,
                    now=now,
                    error_code="kb_lease_lost",
                    sanitized_error="publication lease was lost or unknown; reconcile required",
                    lease_check=None,
                    resolve=False,
                )
                return self._reload_result(path_id, card_id, replayed=False)

            if outcome == "processed":
                # Mark published only when the index result explicitly includes
                # the fixed file AND the KB is confirmably ready (requirement 8),
                # and only while we still provably own the lease.
                _lease_check()
                if not kb_is_ready(self._get_manager(), target_kb_name, kb_dir):
                    try:
                        self._get_manager().mark_needs_reindex(
                            target_kb_name,
                            reason=("knowledge-card publication left the KB not confirmably ready"),
                        )
                    except Exception as exc:  # noqa: BLE001 - failure-of-failure
                        logger.warning(
                            "could not mark KB '%s' needs_reindex: %s",
                            target_kb_name,
                            exc,
                        )
                    self._finalize(
                        path_id,
                        card_id,
                        status=KnowledgeCardStatus.RECONCILE_REQUIRED,
                        coordinator=coordinator,
                        kb_name=target_kb_name,
                        op_id=op.id,
                        owner=owner,
                        rel_path=rel_path,
                        document_sha=document_sha,
                        expected_revision=expected_card_revision,
                        now=now,
                        error_code="kb_not_ready_after_index",
                        sanitized_error=("the KB is not confirmably ready after the index write"),
                        lease_check=_lease_check,
                    )
                else:
                    self._finalize(
                        path_id,
                        card_id,
                        status=KnowledgeCardStatus.PUBLISHED,
                        coordinator=coordinator,
                        kb_name=target_kb_name,
                        op_id=op.id,
                        owner=owner,
                        rel_path=rel_path,
                        document_sha=document_sha,
                        expected_revision=expected_card_revision,
                        now=now,
                        error_code="",
                        sanitized_error="",
                        lease_check=_lease_check,
                    )
                return self._reload_result(path_id, card_id, replayed=False)

            if outcome == "unambiguous_failure":
                _lease_check()
                self._cleanup_raw_file(kb_dir, raw_path)
                self._finalize(
                    path_id,
                    card_id,
                    status=KnowledgeCardStatus.PUBLISH_FAILED,
                    coordinator=coordinator,
                    kb_name=target_kb_name,
                    op_id=op.id,
                    owner=owner,
                    rel_path=rel_path,
                    document_sha=document_sha,
                    expected_revision=expected_card_revision,
                    now=now,
                    error_code="index_failed",
                    sanitized_error=err,
                    lease_check=_lease_check,
                )
                return self._reload_result(path_id, card_id, replayed=False)

            # Ambiguous partial provider mutation — conservative
            # reconcile_required; mark the KB needs_reindex (best-effort).
            _lease_check()
            try:
                self._get_manager().mark_needs_reindex(
                    target_kb_name,
                    reason="knowledge-card publication has an ambiguous provider mutation",
                )
            except Exception as exc:  # noqa: BLE001 - failure-of-failure
                logger.warning("could not mark KB '%s' needs_reindex: %s", target_kb_name, exc)
            self._finalize(
                path_id,
                card_id,
                status=KnowledgeCardStatus.RECONCILE_REQUIRED,
                coordinator=coordinator,
                kb_name=target_kb_name,
                op_id=op.id,
                owner=owner,
                rel_path=rel_path,
                document_sha=document_sha,
                expected_revision=expected_card_revision,
                now=now,
                error_code="index_failed",
                sanitized_error=err,
                lease_check=_lease_check,
            )
            return self._reload_result(path_id, card_id, replayed=False)
        except KbLeaseError:
            # A later lease checkpoint (e.g. the finalization gate) failed
            # closed: never mark the card published and never resolve another
            # holder's operation. Converge conservatively to a recoverable
            # reconcile state with no further KB mutation.
            self._finalize(
                path_id,
                card_id,
                status=KnowledgeCardStatus.RECONCILE_REQUIRED,
                coordinator=coordinator,
                kb_name=target_kb_name,
                op_id=op.id,
                owner=owner,
                rel_path=rel_path,
                document_sha=document_sha,
                expected_revision=expected_card_revision,
                now=now,
                error_code="kb_lease_lost",
                sanitized_error="publication lease was lost or unknown; reconcile required",
                lease_check=None,
                resolve=False,
            )
            return self._reload_result(path_id, card_id, replayed=False)
        finally:
            await heartbeat.stop()

    def _resolve_publication_basis(
        self,
        progress: LearningProgress,
        card: KnowledgeCardRecord,
        pub_key: str,
        document_sha: str,
    ) -> str | KnowledgeCardPublicationRecord | None:
        """Resolve the idempotency start-state.

        Returns ``"replay"`` (already published, same content), a prior
        publication record to reuse (failed retry), or ``None`` (new
        publication). Raises on a content conflict or a non-actionable state.
        """
        prior = self._latest_publication(progress, pub_key)
        if prior is not None and prior.document_sha256 != document_sha:
            raise KnowledgeCardPublicationConflictError(
                f"publication key {pub_key!r} was reused with different content on "
                f"card {card.id!r}; publish a new revision instead"
            )
        if card.status == KnowledgeCardStatus.PUBLISHED:
            # An already-published card replays only when the requested
            # publication key/target/hash matches the published record. A
            # different target (a key with no record) is a stable conflict, not
            # an idempotent success for that target.
            if card.publication_key and card.publication_key == pub_key:
                return "replay"
            if prior is not None and prior.status == PublicationStatus.PUBLISHED:
                return "replay"
            raise KnowledgeCardPublicationConflictError(
                f"card {card.id!r} is already published; request key {pub_key!r} "
                f"does not match the published record {card.publication_key!r}"
            )
        if card.status in (
            KnowledgeCardStatus.PUBLISHING,
            KnowledgeCardStatus.RECONCILE_REQUIRED,
        ):
            raise KnowledgeCardReconcileRequiredError(
                f"card {card.id!r} is {card.status.value}; reconcile it before "
                "publishing (interrupted publications cannot be re-mutated)"
            )
        if card.status == KnowledgeCardStatus.PUBLISH_FAILED:
            if prior is None:
                raise KnowledgeCardStateError(
                    f"card {card.id!r} is publish_failed but has no publication record"
                )
            return prior
        if card.status == KnowledgeCardStatus.DRAFT:
            if prior is not None:
                raise KnowledgeCardStateError(
                    f"card {card.id!r} is a draft but already has a publication "
                    f"record for key {pub_key!r}"
                )
            return None
        raise KnowledgeCardStateError(
            f"card {card.id!r} is {card.status.value}; only a draft or a failed "
            "publication can be published"
        )

    def _begin_publication(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        target_kb_name: str,
        pub_key: str,
        rel_path: str,
        document_sha: str,
        now: float,
        op_id: str,
    ) -> tuple[LearningProgress, KnowledgeCardRecord, KnowledgeCardPublicationRecord]:
        """Durably transition the card to ``publishing`` and set ``confirmed_at``.

        Runs under the store CAS: a conflicting save reloads and re-applies so a
        concurrent writer can never be overwritten. The prior publication record
        is re-resolved by durable key on every CAS retry — a stale object from
        an older :class:`LearningProgress` instance is never carried across a
        reload (CAS retry correctness).
        """
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if card.status not in (
                KnowledgeCardStatus.DRAFT,
                KnowledgeCardStatus.PUBLISH_FAILED,
            ):
                raise KnowledgeCardStateError(
                    f"card {card_id!r} is {card.status.value}; publish requires a "
                    "draft or a failed publication"
                )
            if card.revision != expected_card_revision:
                raise KnowledgeCardStaleVersionError(
                    f"card {card_id!r} revision conflict: expected "
                    f"{expected_card_revision}, current {card.revision}"
                )
            if not stable_assessment_is_current(progress, card):
                self._persist_stale_evidence(
                    path_id,
                    card_id,
                    user_id=user_id,
                    moment=now,
                    reason="stable assessment no longer current at publish",
                )
                raise KnowledgeCardEligibilityError(
                    f"card {card_id!r} is no longer backed by current stable evidence"
                )

            card.status = KnowledgeCardStatus.PUBLISHING
            card.confirmed_at = card.confirmed_at or now
            card.target_kb_name = target_kb_name
            card.document_rel_path = rel_path
            card.document_sha256 = document_sha
            card.publication_key = pub_key
            card.publication_operation_id = op_id
            if card.publication_intent is not None:
                card.publication_intent.operation_id = op_id
            card.error_code = ""
            card.sanitized_error = ""
            card.updated_at = now
            card.version += 1

            # Re-resolve the prior publication record by durable key on every
            # CAS retry instead of carrying an object from a stale snapshot.
            prior_record = self._latest_publication(progress, pub_key)
            if prior_record is None:
                record = KnowledgeCardPublicationRecord(
                    id=uuid4().hex,
                    revision=1,
                    card_id=card.id,
                    publication_key=pub_key,
                    card_revision=card.revision,
                    target_kb_name=target_kb_name,
                    document_rel_path=rel_path,
                    document_sha256=document_sha,
                    status=PublicationStatus.PUBLISHING,
                    request_id=request_id,
                    created_at=now,
                    updated_at=now,
                )
                progress.knowledge_card_publication_records.append(record)
            else:
                # Append the next immutable revision of the same logical record:
                # the original failure/request/timestamp is preserved, never
                # overwritten (append-only publication history).
                record = prior_record.model_copy(
                    update={
                        "revision": prior_record.revision + 1,
                        "card_revision": card.revision,
                        "target_kb_name": target_kb_name,
                        "document_rel_path": rel_path,
                        "document_sha256": document_sha,
                        "status": PublicationStatus.PUBLISHING,
                        "request_id": request_id,
                        "error_code": "",
                        "sanitized_error": "",
                        "updated_at": now,
                        "published_at": None,
                    }
                )
                progress.knowledge_card_publication_records.append(record)

            append_history(
                progress,
                _EVENT_PUBLICATION_STARTED,
                aggregate="",
                summary=f"card {card.id} publication to {target_kb_name!r} started",
                payload={
                    "card_id": card.id,
                    "publication_key": pub_key,
                    "target_kb_name": target_kb_name,
                    "document_rel_path": rel_path,
                    "document_sha256": document_sha,
                    "record_id": record.id,
                    "operation_id": op_id,
                    "request_id": request_id,
                    "user_id": user_id,
                },
            )
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return progress, card, record

    def _persist_stale_evidence(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        moment: float,
        reason: str,
    ) -> None:
        """Durably mark an unpublished occupying card ``stale_evidence``."""
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if card.status == KnowledgeCardStatus.STALE_EVIDENCE:
                return
            card.status = KnowledgeCardStatus.STALE_EVIDENCE
            card.stale_at = card.stale_at or moment
            card.updated_at = moment
            card.version += 1
            append_history(
                progress,
                _EVENT_STALE_AT_PUBLISH,
                aggregate="",
                summary=f"card {card_id} staled at publish because {reason}",
                payload={"card_id": card_id, "reason": reason},
            )
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return

    # ── durable publication intent (crash-safe two-phase protocol) ─────────

    def _persist_publication_intent(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        request_id: str,
        expected_card_revision: int,
        target_kb_name: str,
        pub_key: str,
        rel_path: str,
        document_sha: str,
        now: float,
    ) -> None:
        """Durably record the publication intent *before* lease acquisition.

        Closes the crash window between ``coordinator.acquire`` and the durable
        ``publishing`` transition: if the process dies after this save but
        before operation-id attachment, ``reconcile-publication`` can still
        locate the exact orphan ``card_publish`` operation from the intent's
        durable target + subject + request identity.
        """
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if card.status not in (
                KnowledgeCardStatus.DRAFT,
                KnowledgeCardStatus.PUBLISH_FAILED,
            ):
                raise KnowledgeCardStateError(
                    f"card {card_id!r} is {card.status.value}; publish requires a "
                    "draft or a failed publication"
                )
            if card.revision != expected_card_revision:
                raise KnowledgeCardStaleVersionError(
                    f"card {card_id!r} revision conflict: expected "
                    f"{expected_card_revision}, current {card.revision}"
                )
            card.publication_intent = PublicationIntent(
                target_kb_name=target_kb_name,
                publication_key=pub_key,
                document_rel_path=rel_path,
                document_sha256=document_sha,
                request_id=request_id,
                expected_card_revision=expected_card_revision,
                created_at=now,
            )
            card.updated_at = now
            card.version += 1
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return

    def _clear_publication_intent(
        self,
        path_id: str,
        card_id: str,
        user_id: str,
        now: float,
    ) -> None:
        """Durably clear a staged/orphaned publication intent (CAS-safe)."""
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if card.publication_intent is None:
                return
            card.publication_intent = None
            card.updated_at = now
            card.version += 1
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return

    @staticmethod
    def _matching_orphan_operation(
        coordinator: KbWriteCoordinator,
        intent: PublicationIntent,
        card_id: str,
    ) -> Any:
        """Locate the exact orphan ``card_publish`` operation for *intent*.

        Returns ``None`` when there is no operation, the current operation is a
        different type/subject/request, or it is already terminal (not
        ``reconcile_required``) — the caller must never guess or release
        another card's operation.
        """
        if not intent.target_kb_name:
            return None
        op = coordinator.current_operation(intent.target_kb_name)
        if op is None:
            return None
        if op.operation_type != "card_publish":
            return None
        # The operation must be durably bound to this card — never another
        # card's operation, even when the ledger op lacks a subject id.
        if not op.subject_id or op.subject_id != card_id:
            return None
        # Request identity must be present *and* exactly equal on both sides.
        # A missing/mismatched request id is never this orphan — releasing it
        # could unblock the KB under a different, unrelated operation.
        if not op.request_id or not intent.request_id:
            return None
        if op.request_id != intent.request_id:
            return None
        if op.status in ("succeeded", "failed"):
            return None
        return op

    # ── KB volume staging / indexing ────────────────────────────────────────

    @staticmethod
    def _write_raw_document(raw_path: Path, document: str) -> None:
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(raw_path, document)

    @staticmethod
    def _cleanup_raw_file(kb_dir: Path, raw_path: Path) -> None:
        """Remove only the unsuccessful fixed raw file and its hash entry."""
        try:
            remove_raw_document(kb_dir, raw_path)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            logger.warning("could not remove staged publication document %s", raw_path)

    @staticmethod
    def _classify_index_result(result: Any, raw_path: Path) -> tuple[str, str]:
        """Classify a ``DocumentIndexResult`` for the fixed file.

        ``processed`` only when the result explicitly includes the fixed file.
        A clean provider ``False`` (the documented sentinel) is an unambiguous
        failure; anything else is a potentially partial mutation.
        """
        processed = {Path(p).resolve() for p in result.processed_files}
        if raw_path.resolve() in processed:
            return "processed", ""
        failures = [
            failure
            for failure in result.failures
            if Path(failure.file_path).resolve() == raw_path.resolve()
        ]
        if failures and all(
            failure.error == _PROVIDER_NO_MUTATION_SENTINEL for failure in failures
        ):
            return "unambiguous_failure", failures[0].error
        if failures:
            return "ambiguous_failure", failures[0].error
        return "ambiguous_failure", "the fixed document was not confirmed processed"

    def _finalize(
        self,
        path_id: str,
        card_id: str,
        *,
        status: KnowledgeCardStatus,
        coordinator: KbWriteCoordinator,
        kb_name: str,
        op_id: str,
        owner: str,
        rel_path: str,
        document_sha: str,
        expected_revision: int,
        now: float,
        error_code: str,
        sanitized_error: str,
        lease_check: Callable[[], None] | None = None,
        resolve: bool = True,
    ) -> None:
        """Apply a terminal publication state under the store CAS.

        Before the terminal card write, ``lease_check`` (when provided) proves
        the exact operation is still current and owned — a newer
        upload/delete/reindex or a lost/unknown lease therefore prevents a stale
        ``published`` finalization. Never lowers mastery, never mutates a
        published snapshot, and only ever touches the exact write operation this
        publication acquired. The per-KB lease is released (or left for
        reconcile) after the card state is durable.
        """
        if lease_check is not None:
            lease_check()

        applied = False
        try:
            while True:
                progress = self._load(path_id)
                card = require_card(progress, card_id)
                if card.status == KnowledgeCardStatus.PUBLISHED:
                    break  # immutable snapshot; nothing to do
                if card.publication_operation_id and card.publication_operation_id != op_id:
                    break  # a newer publication owns the operation
                if card.status != KnowledgeCardStatus.PUBLISHING:
                    break  # the card left publishing; don't clobber a concurrent decision
                if card.revision != expected_revision:
                    status = KnowledgeCardStatus.RECONCILE_REQUIRED
                    error_code = error_code or "card_revision_changed_during_publish"
                    sanitized_error = sanitized_error or (
                        "card revision changed during publication"
                    )
                card.status = status
                card.error_code = error_code
                card.sanitized_error = sanitized_error
                card.updated_at = now
                card.version += 1
                if status == KnowledgeCardStatus.PUBLISHED:
                    card.published_at = card.published_at or now
                    card.document_rel_path = rel_path
                    card.document_sha256 = document_sha
                # A terminal outcome clears the staged intent; a draft never
                # carries stale intent afterward.
                if status != KnowledgeCardStatus.RECONCILE_REQUIRED:
                    card.publication_intent = None
                self._append_publication_revision(
                    progress,
                    card,
                    status=status,
                    error_code=error_code,
                    sanitized_error=sanitized_error,
                    now=now,
                )
                append_history(
                    progress,
                    self._event_type_for(status),
                    aggregate="",
                    summary=self._summary_for(status, card, kb_name),
                    payload={
                        "card_id": card.id,
                        "publication_key": card.publication_key,
                        "target_kb_name": kb_name,
                        "document_rel_path": rel_path,
                        "document_sha256": document_sha,
                        "operation_id": op_id,
                        "error_code": error_code,
                        "sanitized_error": sanitized_error,
                    },
                )
                try:
                    self.save(progress)
                except KnowledgeCardStaleVersionError:
                    continue
                applied = True
                break
        except Exception as exc:  # noqa: BLE001 - failure-of-failure
            # The proof write failed — never claim published. Resolve the
            # operation to a durable recoverable state so the KB is not
            # permanently blocked, then re-raise for the caller.
            logger.error(
                "could not finalize card %s publication (error_code=%s): %s",
                card_id,
                error_code,
                sanitize_error(str(exc)),
            )
            try:
                coordinator.resolve_manual(
                    kb_name,
                    op_id,
                    "reconcile_required",
                    error_code=error_code or "finalize_failed",
                    error=sanitize_error(str(exc)),
                    owner=owner,
                )
            except Exception:  # noqa: BLE001 - best-effort recoverable resolve
                logger.warning(
                    "could not resolve card_publish operation %s for KB '%s'",
                    op_id,
                    kb_name,
                )
            raise

        if applied and resolve:
            terminal = (
                "succeeded"
                if status == KnowledgeCardStatus.PUBLISHED
                else "failed"
                if status == KnowledgeCardStatus.PUBLISH_FAILED
                else "reconcile_required"
            )
            try:
                coordinator.resolve_manual(
                    kb_name,
                    op_id,
                    terminal,
                    error_code=error_code or None,
                    error=sanitized_error or None,
                    owner=owner,
                )
            except Exception:  # noqa: BLE001 - best-effort lease release
                logger.warning(
                    "could not resolve card_publish operation %s for KB '%s'",
                    op_id,
                    kb_name,
                )

    @staticmethod
    def _append_publication_revision(
        progress: LearningProgress,
        card: KnowledgeCardRecord,
        *,
        status: KnowledgeCardStatus,
        error_code: str,
        sanitized_error: str,
        now: float,
    ) -> None:
        """Append the next immutable publication revision for *card* (append-only).

        Never mutates a prior revision: the original failure/request/timestamp
        stays serialized while the current projection is the latest revision.
        Idempotent — a terminal status already recorded for the logical record
        is not re-appended.
        """
        record = KnowledgeCardPublicationService._latest_publication(progress, card.publication_key)
        if record is None:
            return
        target_status = KnowledgeCardPublicationService._record_status_for(status)
        if record.status == target_status:
            return
        revision = record.model_copy(
            update={
                "revision": record.revision + 1,
                "card_revision": card.revision,
                "target_kb_name": card.target_kb_name or record.target_kb_name,
                "document_rel_path": card.document_rel_path or record.document_rel_path,
                "document_sha256": card.document_sha256 or record.document_sha256,
                "status": target_status,
                "error_code": error_code,
                "sanitized_error": sanitized_error,
                "updated_at": now,
                "published_at": record.published_at
                or (now if status == KnowledgeCardStatus.PUBLISHED else None),
            }
        )
        progress.knowledge_card_publication_records.append(revision)

    @staticmethod
    def _record_status_for(status: KnowledgeCardStatus) -> PublicationStatus:
        return {
            KnowledgeCardStatus.PUBLISHING: PublicationStatus.PUBLISHING,
            KnowledgeCardStatus.PUBLISHED: PublicationStatus.PUBLISHED,
            KnowledgeCardStatus.PUBLISH_FAILED: PublicationStatus.PUBLISH_FAILED,
            KnowledgeCardStatus.RECONCILE_REQUIRED: PublicationStatus.RECONCILE_REQUIRED,
        }[status]

    @staticmethod
    def _event_type_for(status: KnowledgeCardStatus) -> str:
        return {
            KnowledgeCardStatus.PUBLISHED: _EVENT_PUBLISHED,
            KnowledgeCardStatus.PUBLISH_FAILED: _EVENT_PUBLISH_FAILED,
            KnowledgeCardStatus.RECONCILE_REQUIRED: _EVENT_RECONCILE_REQUIRED,
        }[status]

    @staticmethod
    def _summary_for(status: KnowledgeCardStatus, card: KnowledgeCardRecord, kb_name: str) -> str:
        verb = {
            KnowledgeCardStatus.PUBLISHED: "published",
            KnowledgeCardStatus.PUBLISH_FAILED: "publish failed",
            KnowledgeCardStatus.RECONCILE_REQUIRED: "publication needs reconcile",
        }[status]
        return f"card {card.id} {verb} to {kb_name!r}"

    def _release_lease(
        self,
        coordinator: KbWriteCoordinator,
        kb_name: str,
        op_id: str,
        owner: str,
        *,
        error_code: str,
        error: str,
    ) -> None:
        try:
            coordinator.complete(
                kb_name,
                op_id,
                "failed",
                owner=owner,
                error_code=error_code,
                error=error,
            )
        except Exception:  # noqa: BLE001 - best-effort lease release
            logger.warning(
                "could not release card_publish operation %s for KB '%s'",
                op_id,
                kb_name,
            )

    # ── reconcile-publication (read-only wrt raw/index submission) ──────────

    def _converge_published_operation(
        self,
        card: KnowledgeCardRecord,
        *,
        user_id: str,
    ) -> None:
        """Converge the exact stranded ``card_publish`` operation of a published card.

        ``_finalize`` durably saves the ``published`` card *before* it releases
        the per-KB lease. A crash, ``None`` return or exception on that release
        leaves the exact ``card_publish`` operation active or
        ``reconcile_required`` while the KB is blocked. The immutable published
        card is durable proof that publication finalization passed, so an
        explicit reconcile converges that exact operation to ``succeeded``.

        Conservative by construction: it only ever touches the operation whose
        id matches ``card.publication_operation_id`` (never another operation,
        even for the same KB), never resolves a *live* active operation without
        matching lease ownership, and never demotes or mutates the published
        snapshot.
        """
        target_kb_name = card.target_kb_name
        op_id = card.publication_operation_id
        if not target_kb_name or not op_id:
            return
        coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
        op = coordinator.current_operation(target_kb_name)
        if op is None or op.id != op_id:
            # A different operation now owns the KB; never resolve it.
            return
        if op.operation_type != "card_publish":
            return
        if op.status in ("succeeded", "failed"):
            # Already terminal; nothing to converge.
            return
        if op.user_id and op.user_id != user_id:
            # The operation was acquired by a different actor; fail closed.
            return
        if coordinator.is_lease_live(target_kb_name, op_id):
            # A live active operation belongs to its lease holder and must not
            # be resolved without matching ownership. A later explicit reconcile
            # (after the lease expires) can converge it.
            return
        try:
            coordinator.resolve_manual(
                target_kb_name,
                op_id,
                "succeeded",
                error_code="",
                error="",
                owner=None,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort convergence
            logger.warning(
                "could not converge card_publish operation %s for published card %s on KB '%s': %s",
                op_id,
                card.id,
                target_kb_name,
                sanitize_error(str(exc)),
            )

    def reconcile_publication(
        self,
        path_id: str,
        *,
        card_id: str,
        user_id: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        """Inspect existing evidence only and converge the card conservatively.

        Never creates/copies/resubmits a file. Converges to ``published`` only
        when the fixed raw file exists with a matching SHA-256, the KB metadata
        ``file_hashes`` registry confirms the index write, and the KB is ready;
        to ``publish_failed`` only when nothing was written/indexed (a confirmed
        failed submission, hence retryable); otherwise to ``reconcile_required``.

        Only a card in a publication lifecycle state — ``publishing``,
        ``publish_failed``, ``reconcile_required``, or a draft carrying a
        durable publication intent — may be reconciled. A fresh draft,
        ``stale_evidence``, ``discarded``, ``retracted`` or other unrelated
        state is returned unchanged (never corrupted into a stuck state). A
        crash at every boundary is recoverable: the exact orphan operation is
        located by durable target + subject + request identity and converged
        without guessing or releasing another card's operation.
        """
        moment = now if now is not None else self._now()
        progress = self._load(path_id)
        card = require_card(progress, card_id)
        self._require_ownership_and_path(progress, card, user_id)

        if card.status == KnowledgeCardStatus.PUBLISHED:
            # The immutable published snapshot is durable proof that publication
            # finalization passed. If the exact card_publish operation is still
            # active / reconcile-required (crash, None return or exception after
            # the published save but before the lease release), converge it so the
            # KB is never permanently blocked. Never resolves another operation or
            # a live operation without matching ownership, and never demotes or
            # mutates the published snapshot.
            self._converge_published_operation(card, user_id=user_id)
            return self._card_result(progress, card, replayed=True)

        intent = card.publication_intent
        in_lifecycle = card.status in (
            KnowledgeCardStatus.PUBLISHING,
            KnowledgeCardStatus.PUBLISH_FAILED,
            KnowledgeCardStatus.RECONCILE_REQUIRED,
        ) or (card.status == KnowledgeCardStatus.DRAFT and intent is not None)
        if not in_lifecycle:
            # Unrelated card states must never change on reconcile (a fresh
            # draft misuse stays editable/publishable).
            return self._card_result(progress, card, replayed=False)

        coordinator = KbWriteCoordinator(base_dir=self.kb_base_dir)
        target_kb_name = card.target_kb_name or (intent.target_kb_name if intent else "")
        rel_path = (
            card.document_rel_path
            or (intent.document_rel_path if intent else "")
            or fixed_document_rel_path(card.id, card.revision)
        )
        expected_sha = card.document_sha256 or (intent.document_sha256 if intent else "")
        # Sandbox the persisted path before it is joined onto a KB raw dir so a
        # malformed/legacy value can never escape ``raw/learning_cards`` (§14).
        rel_path = _validate_document_rel_path(rel_path)

        op = None
        if target_kb_name and card.publication_operation_id:
            op = coordinator.current_operation(target_kb_name)
            if op is None or op.id != card.publication_operation_id:
                op = None
        elif target_kb_name and intent is not None:
            # Crash before operation-id attachment: locate the exact orphan op
            # by durable target + subject + request identity.
            op = self._matching_orphan_operation(coordinator, intent, card.id)

        # A genuinely in-flight publication with a live lease is left alone.
        if (
            card.status == KnowledgeCardStatus.PUBLISHING
            and op is not None
            and coordinator.is_lease_live(target_kb_name, op.id)
        ):
            return self._card_result(progress, card, replayed=False)

        # Read-only evidence gathering.
        manager = self._get_manager()
        entry = manager.get_kb_entry(target_kb_name) if target_kb_name else None
        kb_dir: Path | None = None
        file_present = False
        file_hash_matches = False
        index_evidence_sha: str | None = None
        kb_ready = False
        if isinstance(entry, dict):
            kb_ready = str(entry.get("status") or "") == "ready" and not bool(
                entry.get("needs_reindex", False)
            )
            if not is_connected_kb(entry):
                try:
                    kb_dir = manager.get_knowledge_base_path(target_kb_name)
                except Exception:  # noqa: BLE001 - KB directory may be gone
                    kb_dir = None
                if kb_dir is not None:
                    raw_file = kb_dir / "raw" / rel_path
                    if raw_file.is_file():
                        file_present = True
                        try:
                            file_hash_matches = (
                                hashlib.sha256(raw_file.read_bytes()).hexdigest() == expected_sha
                            )
                        except OSError:
                            file_hash_matches = False
                    index_evidence_sha = self._index_evidence(kb_dir, rel_path)

        # A draft carrying a staged intent is a publication that never durably
        # transitioned to ``publishing``. If its orphan op is gone (or was never
        # created), the publication never started: clear the intent and keep the
        # card a usable draft. If nothing was staged, resolve the orphan op and
        # keep the draft. Only when the document is actually present does it
        # fall through to the evidence-based convergence below.
        if card.status == KnowledgeCardStatus.DRAFT:
            if op is None:
                self._clear_publication_intent(path_id, card_id, user_id, moment)
                return self._reload_result(path_id, card_id, replayed=False)
            if coordinator.is_lease_live(target_kb_name, op.id):
                return self._card_result(progress, card, replayed=False)
            if not file_present and index_evidence_sha is None:
                # No durable KB mutation — the interrupted publication never
                # started. Converge the exact orphan op to a terminal state and
                # only *then* clear the intent, so a failure to converge never
                # destroys the only durable identity of the orphan. On None /
                # exception the intent is retained and a later explicit reconcile
                # retries.
                resolved: Any = None
                try:
                    resolved = coordinator.resolve_manual(
                        target_kb_name,
                        op.id,
                        "failed",
                        error_code="interrupted",
                        error=(
                            "publication interrupted before the card intent was durably attached"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - failure-of-failure
                    logger.warning(
                        "could not resolve orphan card_publish operation %s for KB '%s': %s",
                        op.id,
                        target_kb_name,
                        sanitize_error(str(exc)),
                    )
                if resolved is None:
                    # The operation was not durably converged (replaced or still
                    # live under a lease we cannot prove we own). Keep the intent
                    # so the orphan remains discoverable on a later reconcile.
                    return self._card_result(progress, card, replayed=False)
                self._clear_publication_intent(path_id, card_id, user_id, moment)
                return self._reload_result(path_id, card_id, replayed=False)

        if file_present and file_hash_matches and index_evidence_sha == expected_sha and kb_ready:
            new_status = KnowledgeCardStatus.PUBLISHED
            error_code, err = "", ""
        elif not file_present and index_evidence_sha is None:
            new_status = KnowledgeCardStatus.PUBLISH_FAILED
            error_code, err = (
                "interrupted",
                ("publication was interrupted before any durable KB mutation"),
            )
        else:
            new_status = KnowledgeCardStatus.RECONCILE_REQUIRED
            error_code, err = (
                "ambiguous_state",
                ("publication state is ambiguous; manual inspection of the KB index is required"),
            )

        progress, card = self._apply_reconcile(
            path_id,
            card_id,
            user_id=user_id,
            status=new_status,
            target_kb_name=target_kb_name,
            rel_path=rel_path,
            document_sha=expected_sha,
            now=moment,
            error_code=error_code,
            sanitized_error=err,
            operation_id=op.id if op is not None else "",
        )

        if op is not None:
            terminal = (
                "succeeded"
                if new_status == KnowledgeCardStatus.PUBLISHED
                else "failed"
                if new_status == KnowledgeCardStatus.PUBLISH_FAILED
                else "reconcile_required"
            )
            try:
                coordinator.resolve_manual(
                    target_kb_name,
                    op.id,
                    terminal,
                    error_code=error_code or None,
                    error=err or None,
                )
            except Exception:  # noqa: BLE001 - best-effort lease release
                logger.warning(
                    "could not resolve interrupted card_publish operation %s for KB '%s'",
                    op.id,
                    target_kb_name,
                )

        return self._card_result(progress, card, replayed=False)

    @staticmethod
    def _index_evidence(kb_dir: Path, rel_path: str) -> str | None:
        """The recorded SHA in the KB ``metadata.json`` ``file_hashes`` registry.

        ``process_new_documents`` records a successful index write there, so it
        is the existing index evidence reconcile inspects — never the provider's
        private store.
        """
        metadata_file = kb_dir / "metadata.json"
        if not metadata_file.exists():
            return None
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - unreadable metadata is absent evidence
            return None
        if not isinstance(metadata, dict):
            return None
        hashes = metadata.get("file_hashes")
        if not isinstance(hashes, dict):
            return None
        value = hashes.get(rel_path)
        return str(value) if value else None

    def _apply_reconcile(
        self,
        path_id: str,
        card_id: str,
        *,
        user_id: str,
        status: KnowledgeCardStatus,
        target_kb_name: str,
        rel_path: str,
        document_sha: str,
        now: float,
        error_code: str,
        sanitized_error: str,
        operation_id: str = "",
    ) -> tuple[LearningProgress, KnowledgeCardRecord]:
        """Persist the converged reconcile state under the store CAS.

        Appends an immutable publication revision (never mutates a prior one)
        and clears the staged intent once the state is terminal. When this
        reconcile started from a draft-with-intent orphan, the exact
        ``publication_operation_id`` is durably attached *before* the intent is
        cleared, so a later failed operation convergence can still locate and
        converge the operation from the card's durable operation linkage.
        """
        while True:
            progress = self._load(path_id)
            card = require_card(progress, card_id)
            self._require_ownership_and_path(progress, card, user_id)
            if card.status == KnowledgeCardStatus.PUBLISHED:
                return progress, card
            card.status = status
            card.error_code = error_code
            card.sanitized_error = sanitized_error
            card.updated_at = now
            card.version += 1
            if status == KnowledgeCardStatus.PUBLISHED:
                card.published_at = card.published_at or now
                card.document_rel_path = rel_path or card.document_rel_path
                card.document_sha256 = document_sha or card.document_sha256
            # Derive durable identity from the staged intent when the card was
            # never durably transitioned (draft-with-intent orphan). Attach the
            # exact operation id *before* the intent is cleared so a later
            # reconcile can always locate and converge the operation from the
            # card's durable operation linkage, even if this operation's own
            # terminal resolution subsequently fails.
            if operation_id:
                card.publication_operation_id = operation_id
            if card.publication_intent is not None:
                intent = card.publication_intent
                card.publication_key = card.publication_key or intent.publication_key
                card.target_kb_name = card.target_kb_name or intent.target_kb_name
                card.document_rel_path = card.document_rel_path or intent.document_rel_path
                card.document_sha256 = card.document_sha256 or intent.document_sha256
            if status != KnowledgeCardStatus.RECONCILE_REQUIRED:
                card.publication_intent = None
            record = self._latest_publication(progress, card.publication_key)
            if record is not None:
                self._append_publication_revision(
                    progress,
                    card,
                    status=status,
                    error_code=error_code,
                    sanitized_error=sanitized_error,
                    now=now,
                )
            elif card.publication_key:
                # Safety net for the draft-with-intent orphan that converged
                # with the document already present: materialize the logical
                # publication record from the final evidence.
                progress.knowledge_card_publication_records.append(
                    KnowledgeCardPublicationRecord(
                        id=uuid4().hex,
                        revision=1,
                        card_id=card.id,
                        publication_key=card.publication_key,
                        card_revision=card.revision,
                        target_kb_name=card.target_kb_name or target_kb_name,
                        document_rel_path=rel_path,
                        document_sha256=document_sha,
                        status=self._record_status_for(status),
                        error_code=error_code,
                        sanitized_error=sanitized_error,
                        created_at=now,
                        updated_at=now,
                        published_at=(now if status == KnowledgeCardStatus.PUBLISHED else None),
                    )
                )
            append_history(
                progress,
                _EVENT_PUBLICATION_RECONCILED,
                aggregate="",
                summary=f"card {card.id} publication reconciled to {status.value}",
                payload={
                    "card_id": card.id,
                    "publication_key": card.publication_key,
                    "target_kb_name": target_kb_name,
                    "document_rel_path": rel_path,
                    "document_sha256": document_sha,
                    "status": status.value,
                    "error_code": error_code,
                    "sanitized_error": sanitized_error,
                },
            )
            try:
                self.save(progress)
            except KnowledgeCardStaleVersionError:
                continue
            return progress, card


__all__ = [
    "KnowledgeCardPublicationService",
    "fixed_document_rel_path",
    "publication_key",
    "render_card_markdown",
    "sanitize_markdown_content",
]
