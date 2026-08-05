"""Service/model/migration tests for durable knowledge-card retraction (KB-04).

Covers §7.11 / §8.5 requirements 1-11: success with exact quarantine and
excluding-index proof, idempotent replay and conflicting request reuse,
fail-closed preconditions before KB mutation, busy/live/lost/expired leases and
a different current operation, every crash boundary, definite failure with fully
confirmed rollback to ``published``, ambiguous deletion/rollback to
``retract_reconcile_required`` + ``needs_reindex``, observational reconcile to
each provable terminal state and no-op/fail-closed unrelated states, append-only
CAS retry correctness, media-reference retention/release including
release-failure retry, no duplicate quarantine/reindex/move/delete on retries or
reconcile, failure-of-failure paths, and backward-compatible schema/migration.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.knowledge.write_coordinator import (
    KbOwnershipLostError,
    KbWriteCoordinator,
    KbWriteOperation,
)
from deeptutor.learning.knowledge_cards import retraction as retraction_module
from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardInputValidationError,
    KnowledgeCardKbNotWritableError,
    KnowledgeCardOwnershipError,
    KnowledgeCardReconcileRequiredError,
    KnowledgeCardRetractionConflictError,
    KnowledgeCardRetractionUnavailableError,
    KnowledgeCardStaleVersionError,
    KnowledgeCardStateError,
)
from deeptutor.learning.knowledge_cards.publish import (
    fixed_document_rel_path,
    publication_key,
    render_card_markdown,
)
from deeptutor.learning.knowledge_cards.retraction import (
    KnowledgeCardRetractionService,
    fixed_quarantine_rel_path,
    retraction_fingerprint,
)
from deeptutor.learning.knowledge_cards.store import content_hash
from deeptutor.learning.models import (
    KnowledgeCardPublicationRecord,
    KnowledgeCardRecord,
    KnowledgeCardRetractionRecord,
    KnowledgeCardStatus,
    LearningProgress,
    PublicationStatus,
    RetractionIntent,
    RetractionStatus,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.knowledge_card_builders import (
    media_store_with_artifact,
    stable_mastery_progress,
)
from deeptutor.services.media.models import (
    ArtifactReference,
    GeneratedArtifact,
    ReferenceOwnerType,
)
from deeptutor.services.media.store import MediaStore
from deeptutor.services.rag import service as rag_module


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def _write_provider_index(kb_dir: Path) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )


def _make_kb(
    base: Path,
    name: str = "kb1",
    *,
    status: str = "ready",
    needs_reindex: bool = False,
    connected: bool = False,
) -> None:
    if connected:
        vault = base / "vault"
        vault.mkdir(parents=True, exist_ok=True)
        entry = {"path": name, "type": "obsidian", "vault_path": str(vault), "status": status}
    else:
        kb_dir = base / name
        (kb_dir / "raw").mkdir(parents=True)
        _write_provider_index(kb_dir)
        entry = {
            "path": name,
            "rag_provider": "llamaindex",
            "status": status,
            "needs_reindex": needs_reindex,
        }
    (base / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {name: entry}}), encoding="utf-8"
    )


def _published_progress(
    book_id: str = "b1",
    *,
    user_id: str = "owner",
    card_id: str = "card1",
    kp_id: str = "kp1",
    target_kb_name: str = "kb1",
) -> tuple[LearningProgress, KnowledgeCardRecord, str, str, str, str]:
    """A PUBLISHED card with a durable PUBLISHED publication record.

    Returns ``(progress, card, document, document_sha, rel_path, key)``.
    """
    progress, attempt, assessment = stable_mastery_progress(book_id=book_id, kp_id=kp_id)
    card = KnowledgeCardRecord(
        id=card_id,
        user_id=user_id,
        path_id=book_id,
        knowledge_point_id=kp_id,
        stable_attempt_id=attempt.id,
        stable_assessment_id=assessment.id,
        stable_assessment_sequence=assessment.assessment_sequence,
        status=KnowledgeCardStatus.PUBLISHED,
        revision=1,
        title="The Feynman Technique",
        body="Explain it simply, then trace the gap.",
        content_hash=content_hash(
            "The Feynman Technique", "Explain it simply, then trace the gap."
        ),
        source_snapshot_ids=["s1"],
        evidence_ids=["ev1"],
        confirmed_at=1000.0,
        published_at=1000.0,
    )
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key(user_id, card.id, card.revision, target_kb_name)
    card.target_kb_name = target_kb_name
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    progress.knowledge_card_publication_records.append(
        KnowledgeCardPublicationRecord(
            id="rec1",
            card_id=card.id,
            publication_key=key,
            card_revision=card.revision,
            target_kb_name=target_kb_name,
            document_rel_path=rel_path,
            document_sha256=document_sha,
            status=PublicationStatus.PUBLISHED,
            published_at=1000.0,
        )
    )
    progress.knowledge_cards.append(card)
    return progress, card, document, document_sha, rel_path, key


def _save(base: Path, progress: LearningProgress) -> None:
    LearningStore(root=base).save(progress)


def _load(base: Path, book_id: str = "b1") -> LearningProgress:
    return LearningStore(root=base).load(book_id)


def _card_of(progress: LearningProgress, card_id: str) -> KnowledgeCardRecord:
    return next(card for card in progress.knowledge_cards if card.id == card_id)


def _write_raw_document(base: Path, rel_path: str, document: str) -> Path:
    kb_dir = base / "kb1"
    raw_file = kb_dir / "raw" / rel_path
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(document, encoding="utf-8")
    return raw_file


def _write_index_evidence(base: Path, rel_path: str, sha: str) -> None:
    kb_dir = base / "kb1"
    metadata_file = kb_dir / "metadata.json"
    metadata = {}
    if metadata_file.exists():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata.setdefault("file_hashes", {})[rel_path] = sha
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")


def _write_second_raw_doc(base: Path) -> Path:
    """A second ordinary raw document so the excluding reindex set is nonempty."""
    kb_dir = base / "kb1"
    other = kb_dir / "raw" / "notes" / "intro.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("# Intro\n\nOrdinary notes that stay in the KB.", encoding="utf-8")
    return other


def _setup_published_kb(
    base: Path,
    *,
    book_id: str = "b1",
    with_second_doc: bool = True,
) -> tuple[LearningProgress, KnowledgeCardRecord, str, str, str, str]:
    """A ready KB + published card with its raw file and index evidence on disk."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, key = _published_progress(book_id=book_id)
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    if with_second_doc:
        _write_second_raw_doc(base)
    return progress, card, document, document_sha, rel_path, key


def _write_expired_op(
    base: Path,
    *,
    op_id: str = "op1",
    status: str = "running",
    operation_type: str = "card_retract",
    subject_id: str = "card1",
    request_id: str = "req1",
    user_id: str = "owner",
) -> None:
    coordinator = KbWriteCoordinator(base_dir=base)
    coordinator._save(
        {
            "kb1": KbWriteOperation.from_dict(
                {
                    "id": op_id,
                    "kb_name": "kb1",
                    "user_id": user_id,
                    "operation_type": operation_type,
                    "subject_id": subject_id,
                    "request_id": request_id,
                    "status": status,
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                    "lease_owner": "crash-owner",
                    "lease_expires_at": "2026-08-04T12:00:00Z",
                }
            )
        }
    )


def _kb_bytes_snapshot(base: Path) -> dict[str, bytes]:
    """Raw tree, quarantine tree, and index-evidence metadata bytes (KB bytes).

    ``reconcile_retraction`` must never change these on any outcome.
    """
    kb_dir = base / "kb1"
    snapshot: dict[str, bytes] = {}
    for rel in ("raw", "quarantine"):
        root = kb_dir / rel
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    snapshot[f"{rel}/{path.relative_to(root)}"] = path.read_bytes()
    metadata = kb_dir / "metadata.json"
    if metadata.exists():
        snapshot["metadata.json"] = metadata.read_bytes()
    return snapshot


def _latest_retraction_record(
    progress: LearningProgress, card_id: str
) -> KnowledgeCardRetractionRecord:
    records = [
        record for record in progress.knowledge_card_retraction_records if record.card_id == card_id
    ]
    return max(records, key=lambda record: (record.created_at, record.id))


def _setup_reconcile_retracted(base: Path) -> None:
    """An already-retracted card with a surviving quarantine copy (no ledger)."""
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.RETRACTED,
            original_rel_path=rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
            finished_at=901.0,
        )
    )
    _save(base, progress)
    quarantine_path = base / "kb1" / fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(document, encoding="utf-8")
    _write_second_raw_doc(base)


def _setup_reconcile_exclusion(base: Path) -> None:
    """A RETRACTING card with full exclusion evidence (quarantine present, no
    index evidence, reindex confirmed, KB ready)."""
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.REINDEXING,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            index_task_id="task-1",
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    quarantine_path = base / "kb1" / card.quarantine_rel_path
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(document, encoding="utf-8")
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")


def _setup_reconcile_restoration(base: Path) -> None:
    """A RETRACT_RECONCILE_REQUIRED card with full restoration evidence (raw +
    index evidence present, no quarantine, KB ready)."""
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.RECONCILE_REQUIRED,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
            finished_at=901.0,
        )
    )
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")


def _setup_reconcile_ambiguous(base: Path) -> None:
    """A RETRACTING card with ambiguous evidence (quarantine present but no
    reindex marker, no restoration)."""
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.QUARANTINING,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    quarantine_path = base / "kb1" / card.quarantine_rel_path
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(document, encoding="utf-8")
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")


def _setup_reconcile_published_intent(base: Path) -> None:
    """A PUBLISHED card carrying a staged retraction intent with a fully intact
    no-mutation KB (no operation)."""
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)


def _artifact_bound_to_card(
    base: Path,
    *,
    card_id: str = "card1",
    user_id: str = "owner",
    artifact_id: str = "art1",
    owner_id: str | None = None,
    owner_type: ReferenceOwnerType = ReferenceOwnerType.KNOWLEDGE_CARD,
    soft_deleted: bool = False,
) -> tuple[MediaStore, GeneratedArtifact, ArtifactReference]:
    media_store, artifact = media_store_with_artifact(
        base, user_id=user_id, artifact_id=artifact_id
    )
    reference = media_store.create_reference(
        artifact_id=artifact_id,
        user_id=user_id,
        owner_type=owner_type,
        owner_id=owner_id if owner_id is not None else card_id,
    )
    if soft_deleted:
        media_store.delete_reference(reference.id, user_id=user_id)
    return media_store, artifact, reference


@pytest.fixture
def base(tmp_path: Path) -> Path:
    return Path(tmp_path)


@pytest.fixture
def service(base: Path) -> KnowledgeCardRetractionService:
    return KnowledgeCardRetractionService(LearningStore(root=base), kb_base_dir=base)


@pytest.fixture
def manager(base: Path) -> KnowledgeBaseManager:
    return KnowledgeBaseManager(base_dir=str(base))


@pytest.fixture
def mock_reindex(monkeypatch):
    """Patch ``RAGService.initialize`` with a per-file-set handler.

    ``handler`` receives the full ``file_paths`` list and returns ``True`` on
    success, ``False`` on a truthy-but-failed provider response, or raises.
    """

    def _patch(handler):
        async def _init(self, kb_name, file_paths, **kwargs):
            result = handler(list(file_paths))
            if asyncio.iscoroutine(result):
                return await result
            return result

        monkeypatch.setattr(rag_module.RAGService, "initialize", _init)

    return _patch


def _card_rel_path(base: Path) -> str:
    return "learning_cards/card1-v1.md"


# ── deterministic quarantine path / fingerprint ────────────────────────────


def test_fixed_quarantine_path_and_fingerprint() -> None:
    sha = "a" * 64
    assert (
        fixed_quarantine_rel_path("card1", 1, sha)
        == f"quarantine/learning_cards/card1-v1-{sha[:16]}.md"
    )
    with pytest.raises(KnowledgeCardInputValidationError):
        fixed_quarantine_rel_path("../../etc", 1, sha)
    with pytest.raises(KnowledgeCardInputValidationError):
        fixed_quarantine_rel_path("card1", 0, sha)
    with pytest.raises(KnowledgeCardInputValidationError):
        fixed_quarantine_rel_path("card1", 1, "")
    fp = retraction_fingerprint(1, "kb1", "learning_cards/card1-v1.md", sha)
    assert fp == retraction_fingerprint(1, "kb1", "learning_cards/card1-v1.md", sha)
    assert fp != retraction_fingerprint(1, "kb2", "learning_cards/card1-v1.md", sha)


# ── success: exact quarantine + excluding-index proof ──────────────────────


def test_retract_success_quarantines_and_proves_exclusion(
    base, service, manager, mock_reindex
) -> None:
    progress, card, document, document_sha, rel_path, _ = _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )

    assert result["status"] == "retracted"
    assert result["replayed"] is False
    assert result["retracted_at"] is not None
    assert result["quarantine_rel_path"] == fixed_quarantine_rel_path(
        card.id, card.revision, document_sha
    )

    # Exact quarantine: the original raw file is gone. The quarantine copy held
    # the exact bytes at the deterministic same-volume path, but the quarantine
    # lifecycle is completed only after the excluding index is confirmed and the
    # card is durably retracted — the matching copy is deleted (KB-04 P0
    # correction 5).
    raw_file = base / "kb1" / "raw" / rel_path
    assert not raw_file.exists()
    quarantine_file = base / "kb1" / result["quarantine_rel_path"]
    assert not quarantine_file.exists()

    # Excluding-index proof: the document hash/path is absent from the index
    # evidence, the KB is ready, and the reindex was explicitly confirmed.
    metadata = json.loads((base / "kb1" / "metadata.json").read_text(encoding="utf-8"))
    assert rel_path not in metadata.get("file_hashes", {})
    assert manager.get_kb_entry("kb1")["status"] == "ready"
    assert manager.get_kb_entry("kb1")["needs_reindex"] in (False, None)

    # Durable retraction record: append-only history, latest is RETRACTED.
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACTED
    records = [r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"]
    assert records, "a retraction record must exist"
    latest = max(records, key=lambda r: (r.created_at, r.id))
    assert latest.status == RetractionStatus.RETRACTED
    assert latest.request_id == "req1"
    assert latest.index_task_id, "the excluding reindex must be durably recorded"
    assert card.retraction_intent is None
    assert card.retraction_request_id == "req1"
    assert card.retraction_operation_id

    # The card_retract operation succeeded and the KB is unblocked.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["operation_type"] == "card_retract"
    assert ledger["operations"]["kb1"]["status"] == "succeeded"

    # Mastery is never lowered; immutable publication facts are preserved.
    assert reloaded.projections["kp1"].mastery_state.value == "stable_mastery"
    assert card.published_at == 1000.0
    assert card.document_rel_path == rel_path
    assert card.document_sha256 == document_sha


def test_retract_success_releases_media_references_after_durable_retraction(
    base, mock_reindex
) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id=card.id)
    card.artifact_ids = [artifact.id]
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    mock_reindex(lambda file_paths: True)

    svc = KnowledgeCardRetractionService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    result = _run(
        svc.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retracted"

    # The live KNOWLEDGE_CARD reference was released only after retracted; the
    # retained audit artifact id is unchanged.
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is None
    )
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").artifact_ids == [artifact.id]


# ── same-request replay / conflicting reuse ────────────────────────────────


def test_retract_replays_same_request_without_duplicate(base, service, mock_reindex) -> None:
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    first = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert first["status"] == "retracted"

    restarted = KnowledgeCardRetractionService(LearningStore(root=base), kb_base_dir=base)
    second = _run(
        restarted.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert second["status"] == "retracted"
    assert second["replayed"] is True

    # No duplicate quarantine/reindex/record: the quarantine copy was cleaned up
    # only after durable retraction (so there is none left), exactly one
    # retraction record, and the raw file stays absent.
    reloaded = _load(base)
    records = reloaded.knowledge_card_retraction_records
    assert len([r for r in records if r.card_id == "card1"]) == 1
    quarantine_files = list((base / "kb1" / "quarantine").rglob("*.md"))
    assert len(quarantine_files) == 0
    assert not (base / "kb1" / "raw" / "learning_cards" / "card1-v1.md").exists()


def test_retract_conflicts_on_same_request_different_facts(base, service) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    # A prior retraction record with the SAME request id but DIFFERENT facts
    # (different document hash) — a stable conflict, never an idempotent replay.
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.RETRACTED,
            original_rel_path=rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, "0" * 64),
            document_sha256="0" * 64,
            created_at=900.0,
            updated_at=901.0,
            finished_at=901.0,
        )
    )
    _save(base, progress)
    with pytest.raises(KnowledgeCardRetractionConflictError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )


def test_retract_rejects_already_retracted_with_different_request(base, service) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req-old",
            status=RetractionStatus.RETRACTED,
            original_rel_path=rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
            finished_at=901.0,
        )
    )
    _save(base, progress)
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req-new",
                expected_card_revision=1,
            )
        )


# ── fail-closed preconditions before mutation ──────────────────────────────


def test_retract_rejects_unauthorized_owner(base, service) -> None:
    _setup_published_kb(base)
    with pytest.raises(KnowledgeCardOwnershipError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="intruder",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    assert not (base / "kb_write_operations.json").exists()


def test_retract_rejects_cross_path(base, service) -> None:
    _make_kb(base)
    progress, card, _, _, _, _ = _published_progress()
    card.path_id = "other-path"
    _save(base, progress)
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )


def test_retract_rejects_stale_revision(base, service) -> None:
    _setup_published_kb(base)
    with pytest.raises(KnowledgeCardStaleVersionError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=2,
            )
        )


def test_retract_rejects_non_published_state(base, service) -> None:
    _make_kb(base)
    progress, card, _, _, _, _ = _published_progress()
    card.status = KnowledgeCardStatus.DRAFT
    _save(base, progress)
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )


@pytest.mark.parametrize(
    "kb_kwargs",
    [
        {"connected": True},
        {"needs_reindex": True},
        {"status": "processing"},
    ],
)
def test_retract_rejects_non_writable_kb_before_mutation(base, service, kb_kwargs) -> None:
    _make_kb(base, **kb_kwargs)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    with pytest.raises(KnowledgeCardKbNotWritableError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISHED
    assert not (base / "kb_write_operations.json").exists()


def test_retract_rejects_missing_kb_before_mutation(base, service) -> None:
    _setup_published_kb(base)
    # Re-point the card at a KB that is not registered.
    reloaded = _load(base)
    _card_of(reloaded, "card1").target_kb_name = "missing-kb"
    LearningStore(root=base).save(reloaded)
    with pytest.raises(KnowledgeCardKbNotWritableError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISHED


def test_retract_rejects_hash_mismatch_before_mutation(base, service) -> None:
    _setup_published_kb(base)
    # Overwrite the raw bytes so they no longer match the published SHA.
    raw_file = base / "kb1" / "raw" / "learning_cards" / "card1-v1.md"
    raw_file.write_text("# Tampered", encoding="utf-8")
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISHED
    assert _card_of(reloaded, "card1").retraction_intent is None
    assert not (base / "kb_write_operations.json").exists()


def test_retract_rejects_missing_raw_file_before_mutation(base, service) -> None:
    _setup_published_kb(base)
    (base / "kb1" / "raw" / "learning_cards" / "card1-v1.md").unlink()
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    assert not (base / "kb_write_operations.json").exists()


def test_retract_rejects_path_containment_escape(base, service) -> None:
    _setup_published_kb(base)
    reloaded = _load(base)
    _card_of(reloaded, "card1").document_rel_path = "learning_cards/../../evil.md"
    LearningStore(root=base).save(reloaded)
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    assert not (base / "kb_write_operations.json").exists()


def test_retract_rejects_internally_inconsistent_publication(base, service) -> None:
    _setup_published_kb(base)
    reloaded = _load(base)
    # Break internal consistency: the publication record's hash disagrees.
    record = reloaded.knowledge_card_publication_records[0]
    record.document_sha256 = "f" * 64
    LearningStore(root=base).save(reloaded)
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    assert not (base / "kb_write_operations.json").exists()


# ── lease contention / live / lost / different current operation ───────────


def test_retract_refused_when_kb_lease_held(base, service) -> None:
    _setup_published_kb(base)
    coordinator = KbWriteCoordinator(base_dir=base)
    coordinator.acquire("kb1", "card_publish", owner="other-writer")
    with pytest.raises(KnowledgeCardRetractionUnavailableError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None  # staged intent cleared on busy


def test_retract_aborts_on_lost_lease_during_reindex(
    base, service, mock_reindex, monkeypatch
) -> None:
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    calls = {"n": 0}
    original_verify = KbWriteCoordinator.verify_lease

    def _flaky_verify(self, kb_name, operation_id, *, owner=None):
        calls["n"] += 1
        if calls["n"] > 2:
            raise KbOwnershipLostError(kb_name, operation_id)
        return original_verify(self, kb_name, operation_id, owner=owner)

    monkeypatch.setattr(KbWriteCoordinator, "verify_lease", _flaky_verify)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retract_reconcile_required"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    assert card.retraction_operation_id
    # The stale writer did not resolve the operation.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


def test_retract_refused_when_card_has_active_retraction(base, service) -> None:
    _setup_published_kb(base)
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op-live"
    card.retraction_request_id = "req-other"
    reloaded.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req-other",
            status=RetractionStatus.QUARANTINING,
            original_rel_path=card.document_rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(
                card.id, card.revision, card.document_sha256
            ),
            document_sha256=card.document_sha256,
            created_at=900.0,
            updated_at=901.0,
        )
    )
    LearningStore(root=base).save(reloaded)
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req-new",
                expected_card_revision=1,
            )
        )


# ── crash boundaries ───────────────────────────────────────────────────────


def test_reconcile_published_without_intent_is_noop(base, service) -> None:
    _setup_published_kb(base)
    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    assert result["replayed"] is False
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None


def test_reconcile_published_with_intent_no_op_clears_intent(base, service) -> None:
    """Crash after the intent was persisted but before lease acquisition: the
    published KB is fully intact (raw + index evidence + ready), so the
    retraction never mutated anything — reconcile clears the staged intent and
    keeps the card a usable published snapshot."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    # A real published card: raw file present with the exact hash, matching
    # index evidence, and a ready KB. No KB mutation happened.
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None
    assert not (base / "kb_write_operations.json").exists()


def test_reconcile_published_with_intent_resolves_orphan_op(base, service) -> None:
    """Crash after the intent was persisted and the lease acquired, before any KB
    mutation: the published KB is fully intact, so reconcile durably resolves the
    exact expired orphan operation failed and only then clears the intent."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(
        base,
        op_id="op-orphan",
        request_id="req-crash",
        status="running",
        subject_id="card1",
    )

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None
    # The exact orphan operation was durably resolved failed and the card keeps
    # the exact operation linkage.
    assert card.retraction_operation_id == "op-orphan"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_reconcile_after_attachment_before_quarantine_converges_published(base, service) -> None:
    """Crash after the card entered ``retracting`` but before quarantine: no
    durable KB mutation exists, so reconcile converges back to ``published``."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.QUARANTINING,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_reconcile_after_quarantine_before_reindex_locks_reconcile_required(base, service) -> None:
    """Crash after quarantine but before the excluding reindex is confirmed:
    exclusion cannot be proven (no reindex marker) and restoration cannot be
    proven (raw absent) → the card locks ``retract_reconcile_required`` and all
    durable identities are retained."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.QUARANTINING,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    # The raw file is in quarantine; the index evidence was already dropped but
    # NO excluding reindex has been durably recorded yet.
    quarantine_path = base / "kb1" / card.quarantine_rel_path
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(document, encoding="utf-8")
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retract_reconcile_required"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    # Durable identities are retained for a later explicit recovery.
    assert card.quarantine_rel_path
    assert card.document_sha256 == document_sha
    assert card.retraction_operation_id == "op1"
    assert card.retraction_request_id == "req1"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "reconcile_required"


def test_reconcile_after_reindex_before_finalize_converges_retracted(base, service) -> None:
    """Crash after the excluding reindex is confirmed but before the card
    finalize: exclusion is fully proven → reconcile converges to ``retracted``."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.REINDEXING,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            index_task_id="task-xyz",
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    quarantine_path = base / "kb1" / card.quarantine_rel_path
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(document, encoding="utf-8")
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACTED
    assert card.retracted_at is not None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"


def test_reconcile_retracted_card_converges_stranded_operation(base, service) -> None:
    """Crash after the retracted card save but before the operation resolve: the
    immutable retracted card proves finalization, so reconcile converges the exact
    stranded ``card_retract`` operation to ``succeeded`` and re-releases refs."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    _save(base, progress)
    _write_expired_op(base, op_id="op1", request_id="req1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    assert result["replayed"] is True
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"


def test_reconcile_retracted_card_converges_reconcile_required_operation(base, service) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    _save(base, progress)
    _write_expired_op(base, op_id="op1", request_id="req1", status="reconcile_required")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"


def test_reconcile_retracted_card_leaves_different_operation_untouched(base, service) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    _save(base, progress)
    _write_expired_op(base, op_id="op-other", request_id="req1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"  # untouched


def test_reconcile_retracted_card_leaves_live_operation_untouched(base, service) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    _save(base, progress)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "card_retract", owner="live-owner")
    reloaded = _load(base)
    _card_of(reloaded, "card1").retraction_operation_id = op.id
    LearningStore(root=base).save(reloaded)

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    current = coordinator.current_operation("kb1")
    assert current.status == "running"
    assert current.lease_owner == "live-owner"


def test_reconcile_published_after_rollback_converges_stranded_operation(base, service) -> None:
    """A confirmed rollback returned the card to immutable published, but the
    exact card_retract operation is still stranded (crash/None/exception on the
    lease release): reconcile converges that exact operation to failed through
    the card's durable operation linkage, never another operation."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.FAILED,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
            finished_at=901.0,
        )
    )
    _save(base, progress)
    _write_expired_op(base, op_id="op1", request_id="req1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    # The immutable published snapshot is preserved; only the stranded operation
    # was converged to failed.
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISHED
    assert _card_of(reloaded, "card1").published_at == 1000.0
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_reconcile_ignores_orphan_op_with_mismatched_request_id(base, service) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_expired_op(
        base, op_id="op-orphan", request_id="req-other", status="running", subject_id="card1"
    )

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    # The current operation differs from the card/intent operation (a different
    # request id): reconcile returns without card/record/media mutation and never
    # decides from filesystem evidence concurrently with a different operation.
    # The durable intent is retained for a later exact recovery (KB-04 P0
    # correction 1/2).
    assert result["status"] == "published"
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").retraction_intent is not None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


# ── definite failure with fully confirmed rollback to published ─────────────


def test_retract_definite_failure_rolls_back_to_published(
    base, service, manager, mock_reindex
) -> None:
    _setup_published_kb(base)
    card_rel = _card_rel_path(base)

    def _handler(file_paths):
        present = any(Path(p).resolve().as_posix().endswith(card_rel) for p in file_paths)
        if present:
            return True  # rollback reindex (card restored) succeeds
        raise RuntimeError("provider exploded during excluding reindex")

    mock_reindex(_handler)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "published"
    assert result["replayed"] is False

    # The exact quarantine bytes were atomically restored to the original path.
    raw_file = base / "kb1" / "raw" / card_rel
    assert raw_file.is_file()
    assert not list((base / "kb1" / "quarantine").rglob("*.md"))
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.published_at == 1000.0
    # Failed/recoverable retraction record, append-only.
    records = [r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"]
    latest = max(records, key=lambda r: (r.created_at, r.id))
    assert latest.status == RetractionStatus.FAILED
    # Index evidence restored + KB ready.
    metadata = json.loads((base / "kb1" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"][card_rel] == card.document_sha256
    assert manager.get_kb_entry("kb1")["status"] == "ready"
    # The card_retract operation failed (retraction did not happen); KB unblocked.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"
    # Mastery never lowered.
    assert reloaded.projections["kp1"].mastery_state.value == "stable_mastery"


def test_retract_after_failed_rollback_retries_with_new_request(
    base, service, mock_reindex
) -> None:
    _setup_published_kb(base)
    card_rel = _card_rel_path(base)
    excluding_calls = {"n": 0}

    def _handler(file_paths):
        present = any(Path(p).resolve().as_posix().endswith(card_rel) for p in file_paths)
        if present:
            return True  # rollback reindex (card restored) always succeeds
        # The first excluding reindex fails (forcing rollback); the second
        # (a fresh retraction after the rollback) succeeds.
        excluding_calls["n"] += 1
        if excluding_calls["n"] == 1:
            raise RuntimeError("excluding reindex fails")
        return True

    mock_reindex(_handler)

    first = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert first["status"] == "published"

    # A fresh explicit retraction (new request id) is allowed and succeeds.
    second = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req2",
            expected_card_revision=1,
        )
    )
    assert second["status"] == "retracted"
    reloaded = _load(base)
    records = [r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"]
    # Two append-only records: the failed one and the successful one.
    assert len(records) == 2
    assert {r.request_id for r in records} == {"req1", "req2"}
    assert any(r.status == RetractionStatus.FAILED for r in records)
    assert any(r.status == RetractionStatus.RETRACTED for r in records)


# ── ambiguous deletion/rollback → retract_reconcile_required + needs_reindex ─


def test_retract_ambiguous_rollback_locks_reconcile_required(
    base, service, manager, mock_reindex
) -> None:
    _setup_published_kb(base)
    card_rel = _card_rel_path(base)

    def _handler(file_paths):
        raise RuntimeError("provider explodes for every reindex")

    mock_reindex(_handler)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retract_reconcile_required"

    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    # All durable identities retained.
    assert card.quarantine_rel_path
    assert card.document_sha256
    assert card.retraction_operation_id
    assert card.retraction_request_id == "req1"
    # KB marked needs_reindex so later card/KB mutation is blocked.
    entry = manager.get_kb_entry("kb1")
    assert entry["needs_reindex"] is True
    assert entry["status"] == "needs_reindex"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "reconcile_required"


# ── observational reconcile to each provable terminal state / no-op states ──


def test_reconcile_restoration_proven_converges_published(base, service) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.RECONCILE_REQUIRED,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
            finished_at=901.0,
        )
    )
    _save(base, progress)
    # The restored document is fully present: raw + index evidence + ready KB.
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_reconcile_no_ops_on_unrelated_states(base, service, tmp_path) -> None:
    for i, status in enumerate(
        (
            KnowledgeCardStatus.DRAFT,
            KnowledgeCardStatus.STALE_EVIDENCE,
            KnowledgeCardStatus.DISCARDED,
            KnowledgeCardStatus.PUBLISH_FAILED,
        )
    ):
        sub = Path(tmp_path) / f"unrelated-{i}"
        sub.mkdir(parents=True, exist_ok=True)
        _make_kb(sub)
        store = LearningStore(root=sub)
        progress, card, document, document_sha, rel_path, _ = _published_progress()
        card.status = status
        store.save(progress)
        svc = KnowledgeCardRetractionService(LearningStore(root=sub), kb_base_dir=sub)
        result = svc.reconcile_retraction("b1", card_id="card1", user_id="owner")
        assert result["status"] == status.value
        reloaded = store.load("b1")
        assert _card_of(reloaded, "card1").status == status


# ── append-only CAS retry correctness ──────────────────────────────────────


def test_retract_survives_cas_conflict(base, service, mock_reindex, monkeypatch) -> None:
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    original_save = service.save
    calls = {"n": 0}

    def _conflicting_save(save_progress):
        calls["n"] += 1
        if calls["n"] == 2:  # inside _begin_retraction, before its CAS save
            current = service.store.load(save_progress.book_id)
            service.store.save(current)
        return original_save(save_progress)

    monkeypatch.setattr(service, "save", _conflicting_save)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retracted"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACTED
    records = [r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"]
    assert len(records) == 1
    assert records[0].status == RetractionStatus.RETRACTED


def test_retraction_history_is_append_only(base, service, mock_reindex) -> None:
    _setup_published_kb(base)
    card_rel = _card_rel_path(base)

    def _handler(file_paths):
        present = any(Path(p).resolve().as_posix().endswith(card_rel) for p in file_paths)
        if present:
            return True
        raise RuntimeError("excluding reindex fails")

    mock_reindex(_handler)
    first = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert first["status"] == "published"

    def _success(file_paths):
        return True

    mock_reindex(_success)
    _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req2",
            expected_card_revision=1,
        )
    )
    reloaded = _load(base)
    records = [r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"]
    # The original failed record is preserved verbatim, never overwritten.
    assert records[0].request_id == "req1"
    assert records[0].status == RetractionStatus.FAILED
    assert records[1].request_id == "req2"
    assert records[1].status == RetractionStatus.RETRACTED


# ── media reference retention during active/ambiguous states + release ──────


def test_media_references_retained_during_retracting_and_ambiguous(base, mock_reindex) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id=card.id)
    card.artifact_ids = [artifact.id]
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.QUARANTINING,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    quarantine_path = base / "kb1" / card.quarantine_rel_path
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(document, encoding="utf-8")
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")

    svc = KnowledgeCardRetractionService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    # Ambiguous state: the reference must remain live (never exposed to GC).
    result = svc.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retract_reconcile_required"
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is not None
    )


def test_media_reference_release_failure_retries_on_reconcile(base, monkeypatch) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id=card.id)
    card.artifact_ids = [artifact.id]
    _save(base, progress)

    svc = KnowledgeCardRetractionService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    calls = {"n": 0}
    original = media_store.delete_references_for_owner

    def _flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("media store write failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(media_store, "delete_references_for_owner", _flaky)

    # First release attempt fails (logged) — the card is already retracted.
    svc._release_media_references(card, "owner")
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is not None
    )

    # A later explicit reconcile retries the idempotent release.
    result = svc.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is None
    )


# ── no duplicate quarantine/reindex/move/delete on retries or reconcile ─────


def test_no_duplicate_quarantine_or_reindex_on_reconcile_after_success(
    base, service, mock_reindex
) -> None:
    _setup_published_kb(base)
    calls = {"n": 0}

    def _handler(file_paths):
        calls["n"] += 1
        return True

    mock_reindex(_handler)
    first = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert first["status"] == "retracted"
    assert calls["n"] == 1

    # Reconcile on the retracted card must not re-quarantine or re-reindex.
    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    assert calls["n"] == 1
    # The quarantine copy was completed (deleted) after durable retraction and
    # stays deleted on reconcile.
    quarantine_files = list((base / "kb1" / "quarantine").rglob("*.md"))
    assert len(quarantine_files) == 0
    assert not (base / "kb1" / "raw" / "learning_cards" / "card1-v1.md").exists()


# ── failure-of-failure paths ───────────────────────────────────────────────


def test_retract_finalize_failure_preserves_recoverable_state(base, service, monkeypatch) -> None:
    """If the terminal proof write fails, the card is never claimed retracted and
    the operation is converged to a durable recoverable reconcile state."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.REINDEXING,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            index_task_id="task-1",
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "card_retract", owner="writer-a")
    reloaded = _load(base)
    _card_of(reloaded, "card1").retraction_operation_id = op.id
    LearningStore(root=base).save(reloaded)

    def _failing_save(_progress):
        raise KnowledgeCardStateError("proof write failed")

    monkeypatch.setattr(service, "save", _failing_save)

    with pytest.raises(KnowledgeCardStateError):
        service._finalize(
            "b1",
            "card1",
            user_id="owner",
            status=KnowledgeCardStatus.RETRACTED,
            coordinator=coordinator,
            kb_name="kb1",
            op_id=op.id,
            owner="writer-a",
            request_id="req1",
            target_kb_name="kb1",
            rel_path=rel_path,
            quarantine_rel=card.quarantine_rel_path,
            document_sha=document_sha,
            expected_revision=1,
            now=1000.0,
            error_code="",
            sanitized_error="",
            lease_check=lambda: None,
        )
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RETRACTING
    current = coordinator.current_operation("kb1")
    assert current.status == "reconcile_required"


def test_retract_ambiguous_recoverable_when_config_write_fails(
    base, service, manager, mock_reindex, monkeypatch
) -> None:
    _setup_published_kb(base)

    def _handler(file_paths):
        raise RuntimeError("reindex fails")

    mock_reindex(_handler)

    def _explode(*args, **kwargs):
        raise RuntimeError("config write failed")

    monkeypatch.setattr(KnowledgeBaseManager, "mark_needs_reindex", _explode)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retract_reconcile_required"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    assert card.retraction_operation_id
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "reconcile_required"


def test_retract_quarantine_failure_locks_reconcile_required(
    base, service, mock_reindex, monkeypatch
) -> None:
    """A mid-flight filesystem/hash failure during quarantine (the raw bytes no
    longer match) cannot prove either terminal side: the card locks
    ``retract_reconcile_required`` with durable identities retained and the
    operation resolves to ``reconcile_required`` (never stranded)."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)

    def _boom(*args, **kwargs):
        raise KnowledgeCardStateError("raw bytes changed before quarantine")

    monkeypatch.setattr(KnowledgeCardRetractionService, "_quarantine_raw", _boom)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retract_reconcile_required"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    assert card.retraction_operation_id
    assert card.retraction_request_id == "req1"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "reconcile_required"


def test_retract_ambiguous_when_store_save_fails_during_finalize(
    base, service, mock_reindex, monkeypatch
) -> None:
    """Failure-of-failure: the reconcile-required finalization itself fails to
    save (store error). The card must retain durable recoverable identity and
    never claim published/retracted without proof."""
    _setup_published_kb(base)
    calls = {"n": 0}
    original_save = service.save

    def _failing_save(_progress):
        nonlocal calls
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("store exploded mid-finalize")
        return original_save(_progress)

    monkeypatch.setattr(service, "save", _failing_save)

    def _handler(file_paths):
        raise RuntimeError("reindex fails")

    mock_reindex(_handler)

    with pytest.raises(RuntimeError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status != KnowledgeCardStatus.RETRACTED
    assert card.status != KnowledgeCardStatus.PUBLISHED


# ── KB-04 P0 correction 1: crash-before-acquire / orphan-without-mutation ───


def test_reconcile_published_with_intent_no_op_keeps_intent_when_raw_and_quarantine_absent(
    base, service
) -> None:
    """Raw absent + quarantine absent is data loss/ambiguity, never the normal
    no-mutation state: reconcile must NOT clear the intent or claim the KB was
    untouched."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    # No raw file AND no quarantine copy — the only recoverable bytes are gone.
    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is not None  # retained for a later recovery
    assert not (base / "kb_write_operations.json").exists()


def test_reconcile_published_with_intent_resolve_orphan_retains_intent_on_none(
    base, service, monkeypatch
) -> None:
    """If the orphan-operation resolution returns None (operation replaced /
    live under an unproven lease), the durable intent is retained for retry."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(
        base, op_id="op-orphan", request_id="req-crash", status="running", subject_id="card1"
    )

    monkeypatch.setattr(KbWriteCoordinator, "resolve_manual", lambda *args, **kwargs: None)

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").retraction_intent is not None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


def test_reconcile_published_with_intent_resolve_orphan_retains_intent_on_exception(
    base, service, monkeypatch
) -> None:
    """If the orphan-operation resolution raises, the durable intent is retained."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(
        base, op_id="op-orphan", request_id="req-crash", status="running", subject_id="card1"
    )

    def _explode(*args, **kwargs):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(KbWriteCoordinator, "resolve_manual", _explode)

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").retraction_intent is not None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


# ── KB-04 P0 correction 2: never reconcile under a live/different operation ──


def _live_retracting_card(
    base: Path, *, op_id: str = "op1", request_id: str = "req1"
) -> tuple[LearningProgress, str, str]:
    """A RETRACTING card with a retraction record and quarantine evidence."""
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = op_id
    card.retraction_request_id = request_id
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id=request_id,
            status=RetractionStatus.QUARANTINING,
            operation_id=op_id,
            original_rel_path=rel_path,
            quarantine_rel_path=card.quarantine_rel_path,
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
        )
    )
    _save(base, progress)
    quarantine_path = base / "kb1" / card.quarantine_rel_path
    quarantine_path.parent.mkdir(parents=True, exist_ok=True)
    quarantine_path.write_text(document, encoding="utf-8")
    _write_second_raw_doc(base)
    return progress, op_id, document_sha


def test_reconcile_retracting_live_exact_operation_returns_without_mutation(base, service) -> None:
    _make_kb(base)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire(
        "kb1", "card_retract", owner="writer-a", request_id="req1", subject_id="card1"
    )
    progress, _, document_sha = _live_retracting_card(base, op_id=op.id)
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id="card1")
    reloaded = _load(base)
    _card_of(reloaded, "card1").artifact_ids = [artifact.id]
    LearningStore(root=base).save(reloaded)
    svc = KnowledgeCardRetractionService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )

    result = svc.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracting"

    # Learning store unchanged.
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACTING
    assert card.retraction_operation_id == op.id
    assert len(reloaded.knowledge_card_retraction_records) == 1
    assert reloaded.knowledge_card_retraction_records[0].status == RetractionStatus.QUARANTINING
    # Operation ledger unchanged.
    current = coordinator.current_operation("kb1")
    assert current.status == "running"
    assert current.lease_owner == "writer-a"
    # Media store unchanged.
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is not None
    )


def test_reconcile_retracting_different_current_operation_returns_without_mutation(
    base, service
) -> None:
    _make_kb(base)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "card_publish", owner="writer-b")
    progress, _, document_sha = _live_retracting_card(base, op_id="op-mine")
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id="card1")
    reloaded = _load(base)
    _card_of(reloaded, "card1").artifact_ids = [artifact.id]
    LearningStore(root=base).save(reloaded)
    svc = KnowledgeCardRetractionService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )

    result = svc.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracting"

    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RETRACTING
    assert len(reloaded.knowledge_card_retraction_records) == 1
    current = coordinator.current_operation("kb1")
    assert current.id == op.id
    assert current.status == "running"
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is not None
    )


def test_reconcile_reconcile_required_live_exact_operation_returns_without_mutation(
    base, service
) -> None:
    _make_kb(base)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire(
        "kb1", "card_retract", owner="writer-a", request_id="req1", subject_id="card1"
    )
    progress, _, document_sha = _live_retracting_card(base, op_id=op.id)
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    card.status = KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    reloaded.knowledge_card_retraction_records[0].status = RetractionStatus.RECONCILE_REQUIRED
    LearningStore(root=base).save(reloaded)

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retract_reconcile_required"

    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    current = coordinator.current_operation("kb1")
    assert current.status == "running"
    assert current.lease_owner == "writer-a"


def test_reconcile_reconcile_required_different_current_operation_returns_without_mutation(
    base, service
) -> None:
    _make_kb(base)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "upload", owner="writer-b")
    progress, _, document_sha = _live_retracting_card(base, op_id="op-mine")
    reloaded = _load(base)
    _card_of(reloaded, "card1").status = KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    LearningStore(root=base).save(reloaded)

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retract_reconcile_required"

    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    current = coordinator.current_operation("kb1")
    assert current.id == op.id
    assert current.status == "running"


def test_reconcile_published_with_intent_live_exact_operation_returns_without_mutation(
    base, service
) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire(
        "kb1", "card_retract", owner="writer-a", request_id="req-crash", subject_id="card1"
    )

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"

    reloaded = _load(base)
    assert _card_of(reloaded, "card1").retraction_intent is not None  # retained
    current = coordinator.current_operation("kb1")
    assert current.status == "running"
    assert current.lease_owner == "writer-a"


def test_reconcile_published_with_intent_different_current_operation_returns_without_mutation(
    base, service
) -> None:
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "upload", owner="writer-b")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"

    reloaded = _load(base)
    assert _card_of(reloaded, "card1").retraction_intent is not None  # retained
    current = coordinator.current_operation("kb1")
    assert current.id == op.id
    assert current.status == "running"
    assert current.lease_owner == "writer-b"


# ── KB-04 P0 correction 3: no index proof manufactured before provider success ─


def test_index_evidence_not_rewritten_before_rollback_reindex_succeeds(
    base, service, mock_reindex, monkeypatch
) -> None:
    """A failed rollback reindex must never leave self-written restoration
    evidence: ``_add_index_evidence`` is only invoked after the rollback reindex
    explicitly succeeds."""
    _setup_published_kb(base)
    card_rel = _card_rel_path(base)
    add_calls = {"n": 0}
    real_add = KnowledgeCardRetractionService._add_index_evidence

    def _spy_add(*args, **kwargs):
        add_calls["n"] += 1
        return real_add(*args, **kwargs)

    monkeypatch.setattr(KnowledgeCardRetractionService, "_add_index_evidence", _spy_add)

    def _handler(file_paths):
        raise RuntimeError("every reindex fails")

    mock_reindex(_handler)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retract_reconcile_required"
    # The rollback reindex never succeeded, so no restoration evidence was added.
    assert add_calls["n"] == 0
    # The original (pre-retraction) evidence is left intact — never dropped
    # before the excluding reindex succeeded (which it did not).
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    metadata = json.loads((base / "kb1" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"].get(card.document_rel_path) == card.document_sha256


def test_reconcile_cannot_falsely_terminalize_after_evidence_and_config_write_failure(
    base, service, manager, mock_reindex, monkeypatch
) -> None:
    """The excluding reindex succeeds but the index-evidence write fails AND the
    KB config write (mark_needs_reindex) fails: a later reconcile cannot claim
    retracted — the durable index evidence was never updated by the
    provider-confirmed reindex and no reindex marker was persisted."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)

    def _evidence_drop_fails(*args, **kwargs):
        return False  # metadata write failure

    monkeypatch.setattr(
        KnowledgeCardRetractionService, "_drop_index_evidence", _evidence_drop_fails
    )

    def _config_write_fails(*args, **kwargs):
        raise RuntimeError("config write failed")

    monkeypatch.setattr(KnowledgeBaseManager, "mark_needs_reindex", _config_write_fails)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retract_reconcile_required"

    r2 = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert r2["status"] == "retract_reconcile_required"
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED


# ── KB-04 P0 correction 4: heartbeat-guarded rollback reindex ────────────────


def test_rollback_reindex_lease_loss_cancels_provider_and_stays_recoverable(
    base, service, mock_reindex, monkeypatch
) -> None:
    """Lease loss during the rollback reindex cancels the in-flight provider
    coroutine and leaves the card/ledger recoverable (never resolves another
    holder, never claims published)."""
    _setup_published_kb(base)
    card_rel = _card_rel_path(base)
    rollback_started = asyncio.Event()
    cancelled = {"cancelled": False}

    def _handler(file_paths):
        present = any(Path(p).resolve().as_posix().endswith(card_rel) for p in file_paths)
        if not present:
            raise RuntimeError("excluding reindex fails")

        async def _blocking():
            rollback_started.set()
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled["cancelled"] = True
                raise

        return _blocking()

    mock_reindex(_handler)
    # Tiny heartbeat interval so the renew loop detects the ownership loss
    # promptly once the rollback reindex begins.
    monkeypatch.setattr(retraction_module, "heartbeat_interval_seconds", lambda coordinator: 0.01)

    original_verify = KbWriteCoordinator.verify_lease

    def _flaky_verify(self, kb_name, operation_id, *, owner=None):
        if rollback_started.is_set():
            raise KbOwnershipLostError(kb_name, operation_id)
        return original_verify(self, kb_name, operation_id, owner=owner)

    monkeypatch.setattr(KbWriteCoordinator, "verify_lease", _flaky_verify)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retract_reconcile_required"
    # The provider coroutine was cancelled/stopped by the lease loss.
    assert cancelled["cancelled"] is True

    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    assert card.retraction_operation_id
    # The stale writer never resolved the operation and never claimed published.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


# ── KB-04 review round 1: durable post-terminal quarantine cleanup ──────────


def test_retract_success_records_cleaned_cleanup_state(base, service, mock_reindex) -> None:
    """On normal retraction success the card is durably retracted, the exact
    matching quarantine copy is deleted, and the retraction record durably
    records ``cleaned`` (observable on the retract response and projection)."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    document_sha = _card_of(_load(base), "card1").document_sha256
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retracted"
    assert result["cleanup_status"] == "cleaned"
    assert result["cleanup_error"] == ""
    assert not (base / "kb1" / quarantine_rel).exists()
    reloaded = _load(base)
    latest = max(
        (r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"),
        key=lambda r: (r.created_at, r.id),
    )
    assert latest.cleanup_status == "cleaned"
    assert latest.cleanup_updated_at is not None


def test_retraction_projection_exposes_cleanup_state(base, service, mock_reindex) -> None:
    """The retraction projection makes the post-terminal cleanup state
    observable without exposing raw paths or unsanitized errors."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    projection = service.retraction_projection("b1", card_id="card1", user_id="owner")
    latest = max(
        (r for r in projection["retraction_records"]),
        key=lambda r: (r["created_at"], r["id"]),
    )
    assert latest["cleanup_status"] == "cleaned"
    assert latest["cleanup_error"] == ""
    assert "cleanup_updated_at" in latest and latest["cleanup_updated_at"] is not None
    assert projection["cleanup_status"] == "cleaned"


def test_retract_cleanup_unlink_failure_persists_failed_and_replay_retries(
    base, service, mock_reindex, monkeypatch
) -> None:
    """A quarantine-cleanup unlink failure never undoes the proven retraction:
    the card is durably retracted, the failure is persisted as ``failed``
    (durable + observable, not just a log line), and an explicit replay of the
    same retract request deterministically retries to ``cleaned`` — never the
    observational reconcile."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    document_sha = _card_of(_load(base), "card1").document_sha256
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    quarantine_file = base / "kb1" / quarantine_rel

    real_unlink = Path.unlink
    calls = {"n": 0}

    def _flaky_unlink(self, *args, **kwargs):
        if self == quarantine_file and calls["n"] == 0:
            calls["n"] += 1
            raise OSError("disk full during quarantine cleanup")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _flaky_unlink)

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retracted"
    # The cleanup failed, so the quarantine copy is retained and the failure is
    # durably observable on the exact retraction record.
    assert quarantine_file.is_file()
    assert result["cleanup_status"] == "failed"
    reloaded = _load(base)
    latest = max(
        (r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"),
        key=lambda r: (r.created_at, r.id),
    )
    assert latest.cleanup_status == "failed"
    assert "disk full" in latest.cleanup_error
    assert latest.cleanup_updated_at is not None

    # A restart exposes the failed cleanup; replaying the same retract request
    # (the explicit post-terminal cleanup path) retries deterministically.
    restarted = KnowledgeCardRetractionService(LearningStore(root=base), kb_base_dir=base)
    replayed = _run(
        restarted.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert replayed["status"] == "retracted"
    assert replayed["replayed"] is True
    assert replayed["cleanup_status"] == "cleaned"
    assert not quarantine_file.exists()


def test_retract_cleanup_keeps_mismatched_quarantine_bytes_failed(
    base, service, mock_reindex, monkeypatch
) -> None:
    """Cleanup never deletes a quarantine copy whose bytes differ from the
    published SHA-256: the copy is retained and the failure is durably recorded
    as ``failed``; the explicit post-terminal retry keeps refusing it."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    document_sha = _card_of(_load(base), "card1").document_sha256
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    quarantine_file = base / "kb1" / quarantine_rel

    # Simulate a crash after the durable retracted finalization but before the
    # post-terminal cleanup: the matching copy survives with cleanup pending.
    real_cleanup = KnowledgeCardRetractionService._complete_quarantine_cleanup_for_record
    monkeypatch.setattr(
        KnowledgeCardRetractionService,
        "_complete_quarantine_cleanup_for_record",
        lambda self, path_id, card_id, user_id, *, request_id, now: None,
    )
    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retracted"
    assert quarantine_file.is_file()

    # Tamper with the quarantine bytes so they no longer match the published hash.
    quarantine_file.write_text("# Tampered", encoding="utf-8")

    # Restore the real cleanup; the explicit post-terminal cleanup path refuses
    # the tampered copy and durably records the failure; the bytes are retained.
    monkeypatch.setattr(
        KnowledgeCardRetractionService,
        "_complete_quarantine_cleanup_for_record",
        real_cleanup,
    )
    restarted = KnowledgeCardRetractionService(LearningStore(root=base), kb_base_dir=base)
    cleaned = restarted.complete_quarantine_cleanup("b1", card_id="card1", user_id="owner")
    assert quarantine_file.is_file()  # refused
    assert cleaned["cleanup_status"] == "failed"
    reloaded = _load(base)
    latest = max(
        (r for r in reloaded.knowledge_card_retraction_records if r.card_id == "card1"),
        key=lambda r: (r.created_at, r.id),
    )
    assert latest.cleanup_status == "failed"
    assert "do not match" in latest.cleanup_error


def test_reconcile_retracted_card_is_observational_cleanup_via_replay(
    base, service, mock_reindex, monkeypatch
) -> None:
    """A crash between the durable retracted finalization and the quarantine
    cleanup leaves the copy behind. Reconcile stays observational: it must NOT
    delete the copy. The explicit post-terminal cleanup path (a restart + replay
    of the same retract request) completes it deterministically."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    document_sha = _card_of(_load(base), "card1").document_sha256
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    quarantine_file = base / "kb1" / quarantine_rel

    # Simulate a crash after retracted finalization but before cleanup.
    real_cleanup = KnowledgeCardRetractionService._complete_quarantine_cleanup_for_record
    monkeypatch.setattr(
        KnowledgeCardRetractionService,
        "_complete_quarantine_cleanup_for_record",
        lambda self, path_id, card_id, user_id, *, request_id, now: None,
    )
    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retracted"
    assert quarantine_file.is_file()
    snapshot = _kb_bytes_snapshot(base)

    # A restarted reconcile leaves the quarantine bytes byte-for-byte intact.
    restarted = KnowledgeCardRetractionService(LearningStore(root=base), kb_base_dir=base)
    result = restarted.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    assert _kb_bytes_snapshot(base) == snapshot
    assert quarantine_file.is_file()
    # The cleanup state stays observable as pending.
    assert result["cleanup_status"] == "pending"

    # Restore the real cleanup; a restart + replay of the same retract request
    # completes the post-terminal cleanup deterministically.
    monkeypatch.setattr(
        KnowledgeCardRetractionService,
        "_complete_quarantine_cleanup_for_record",
        real_cleanup,
    )
    replayed = _run(
        restarted.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert replayed["replayed"] is True
    assert replayed["cleanup_status"] == "cleaned"
    assert not quarantine_file.exists()


def test_reconcile_observational_kb_bytes_unchanged_on_every_outcome(
    tmp_path,
) -> None:
    """Every reconcile outcome — already retracted, exclusion convergence,
    restoration convergence, ambiguity, and published-with-intent — leaves the
    raw tree, quarantine tree, and index metadata byte-for-byte unchanged
    (requirement 9 / finding 1)."""
    scenarios = [
        ("retracted", _setup_reconcile_retracted, "retracted"),
        ("exclusion", _setup_reconcile_exclusion, "retracted"),
        ("restoration", _setup_reconcile_restoration, "published"),
        ("ambiguous", _setup_reconcile_ambiguous, "retract_reconcile_required"),
        ("published_intent", _setup_reconcile_published_intent, "published"),
    ]
    for name, setup, expected_status in scenarios:
        sub = Path(tmp_path) / name
        sub.mkdir(parents=True, exist_ok=True)
        _make_kb(sub)
        setup(sub)
        before = _kb_bytes_snapshot(sub)
        svc = KnowledgeCardRetractionService(LearningStore(root=sub), kb_base_dir=sub)
        result = svc.reconcile_retraction("b1", card_id="card1", user_id="owner")
        assert result["status"] == expected_status, name
        assert _kb_bytes_snapshot(sub) == before, f"{name}: reconcile mutated KB bytes"


def test_reconcile_retracted_guard_leaves_media_and_operation_untouched(base, service) -> None:
    """The already-retracted fast path guards BEFORE any side effect (finding 5):
    when a different current KB operation exists or the exact operation is live,
    reconcile returns without operation convergence or media release."""
    # ── different current operation ──
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retracted_at = 1000.0
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id="card1")
    card.artifact_ids = [artifact.id]
    _save(base, progress)
    coordinator = KbWriteCoordinator(base_dir=base)
    op_other = coordinator.acquire("kb1", "card_publish", owner="writer-b")
    svc = KnowledgeCardRetractionService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    result = svc.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "retracted"
    # Media reference stays live and the different operation is untouched.
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is not None
    )
    current = coordinator.current_operation("kb1")
    assert current.id == op_other.id
    assert current.status == "running"

    # ── live exact operation ──
    base2 = Path(base) / "live"
    base2.mkdir(parents=True, exist_ok=True)
    _make_kb(base2)
    progress2, card2, document2, sha2, rel2, _ = _published_progress()
    card2.status = KnowledgeCardStatus.RETRACTED
    card2.retracted_at = 1000.0
    media_store2, artifact2, _ = _artifact_bound_to_card(base2, card_id="card1")
    card2.artifact_ids = [artifact2.id]
    _save(base2, progress2)
    coord2 = KbWriteCoordinator(base_dir=base2)
    op_live = coord2.acquire(
        "kb1", "card_retract", owner="writer-a", request_id="req1", subject_id="card1"
    )
    reloaded2 = _load(base2)
    _card_of(reloaded2, "card1").retraction_operation_id = op_live.id
    LearningStore(root=base2).save(reloaded2)
    svc2 = KnowledgeCardRetractionService(
        LearningStore(root=base2), kb_base_dir=base2, media_store=media_store2
    )
    result2 = svc2.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result2["status"] == "retracted"
    assert (
        media_store2.find_live_reference(
            artifact_id=artifact2.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is not None
    )
    current2 = coord2.current_operation("kb1")
    assert current2.status == "running"
    assert current2.lease_owner == "writer-a"


# ── KB-04 review round 1: _finalize no-op never cleans quarantine (finding 3) ─


def test_finalize_returns_false_when_card_retracted_under_different_operation(
    base, service
) -> None:
    """``_finalize`` returns a boolean outcome: when the CAS loop bails because
    the card is an immutable retracted snapshot bound to a *different*
    operation, it returns ``False`` so the caller never cleans up after a
    non-applied finalization."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTED
    card.retraction_operation_id = "op-other"
    card.retraction_request_id = "req-other"
    card.retracted_at = 1000.0
    _save(base, progress)
    coordinator = KbWriteCoordinator(base_dir=base)

    result = service._finalize(
        "b1",
        "card1",
        user_id="owner",
        status=KnowledgeCardStatus.RETRACTED,
        coordinator=coordinator,
        kb_name="kb1",
        op_id="op-mine",
        owner="writer-a",
        request_id="req-mine",
        target_kb_name="kb1",
        rel_path=rel_path,
        quarantine_rel="quarantine/learning_cards/card1-v1-aaaa.md",
        document_sha=document_sha,
        expected_revision=1,
        now=1000.0,
        error_code="",
        sanitized_error="",
        lease_check=lambda: None,
    )
    assert result is False


def test_retract_skips_cleanup_when_finalize_noops(
    base, service, mock_reindex, monkeypatch
) -> None:
    """If ``_finalize`` does not apply (returns ``False``), the retract flow must
    not delete the only quarantine copy — the card may have been concurrently
    reverted, so deleting the copy would be permanent data loss."""
    _setup_published_kb(base)
    mock_reindex(lambda file_paths: True)
    document_sha = _card_of(_load(base), "card1").document_sha256
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    quarantine_file = base / "kb1" / quarantine_rel
    cleanup_calls = {"n": 0}
    real_cleanup = KnowledgeCardRetractionService._complete_quarantine_cleanup_for_record

    def _noop_finalize(self, *args, **kwargs):
        return False  # finalization bailed out

    def _spy_cleanup(self, *args, **kwargs):
        cleanup_calls["n"] += 1
        return real_cleanup(self, *args, **kwargs)

    monkeypatch.setattr(KnowledgeCardRetractionService, "_finalize", _noop_finalize)
    monkeypatch.setattr(
        KnowledgeCardRetractionService,
        "_complete_quarantine_cleanup_for_record",
        _spy_cleanup,
    )

    result = _run(
        service.retract(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
        )
    )
    assert result["status"] == "retracting"
    assert cleanup_calls["n"] == 0
    # The only recoverable bytes are retained: raw is quarantined and the
    # quarantine copy survives (no permanent data loss).
    assert not (base / "kb1" / "raw" / "learning_cards" / "card1-v1.md").exists()
    assert quarantine_file.is_file()


# ── KB-04 review round 1: _apply_reconcile CAS TOCTOU (finding 4) ────────────


def test_apply_reconcile_injected_save_conflict_noops_on_new_retracting(
    base, service, monkeypatch
) -> None:
    """An injected save conflict makes ``_apply_reconcile`` reload a card that a
    concurrent writer just transitioned to RETRACTING under a new operation: the
    CAS retry must no-op (drift) — it cannot overwrite the new retraction or
    resolve the stale operation."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.status = KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    progress.knowledge_card_retraction_records.append(
        KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="owner",
            target_kb_name="kb1",
            request_id="req1",
            status=RetractionStatus.RECONCILE_REQUIRED,
            operation_id="op1",
            original_rel_path=rel_path,
            quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
            document_sha256=document_sha,
            created_at=900.0,
            updated_at=901.0,
            finished_at=901.0,
        )
    )
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(base, op_id="op1", request_id="req1")

    original_save = service.save
    kb_before = _kb_bytes_snapshot(base)

    def _conflicting_save(save_progress):
        current = service.store.load(save_progress.book_id)
        card = _card_of(current, "card1")
        if (
            card.status == KnowledgeCardStatus.RETRACT_RECONCILE_REQUIRED
            and card.retraction_operation_id == "op1"
        ):
            coordinator = KbWriteCoordinator(base_dir=base)
            coordinator.resolve_manual(
                "kb1",
                "op1",
                "failed",
                error_code="interrupted",
                error="interrupted before any durable KB mutation",
            )
            op_new = coordinator.acquire(
                "kb1",
                "card_retract",
                owner="worker-b",
                request_id="req-new",
                subject_id="card1",
                user_id="owner",
            )
            card.status = KnowledgeCardStatus.RETRACTING
            card.retraction_operation_id = op_new.id
            card.retraction_request_id = "req-new"
            service.store.save(current)
        return original_save(save_progress)

    monkeypatch.setattr(service, "save", _conflicting_save)

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACTING  # never reverted
    assert card.retraction_request_id == "req-new"
    assert result["status"] == "retracting"
    # KB bytes (raw/quarantine/index metadata) are unchanged by the drifted
    # reconcile; the concurrent writer's operation is untouched.
    assert _kb_bytes_snapshot(base) == kb_before
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"
    assert ledger["operations"]["kb1"]["lease_owner"] == "worker-b"


def test_glm_multiworker_reconcile_cannot_revert_new_retraction_or_delete_copy(
    base, service, mock_reindex, monkeypatch
) -> None:
    """GLM multi-worker reproduction (findings 3/4): a published-with-old-intent
    reconcile resolves an expired orphan; a new retract acquires the freed lease
    and transitions the card to RETRACTING; the stale reconcile attempts
    same-status published convergence; the new writer reaches excluding-reindex
    success. The stale reconcile cannot revert the new retraction, and the only
    quarantine copy is deleted only when the new writer's exact finalization
    commits."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-old",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-old"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    _write_expired_op(
        base, op_id="op-old", request_id="req-old", status="running", subject_id="card1"
    )

    kb_after_worker_a_quarantine: dict[str, bytes] = {}

    def _resolve_orphan_and_advance_worker_a(*args, **kwargs):
        coordinator = KbWriteCoordinator(base_dir=base)
        resolved = coordinator.resolve_manual(
            "kb1",
            "op-old",
            "failed",
            error_code="interrupted",
            error="retraction interrupted before any durable KB mutation occurred",
        )
        assert resolved is not None and resolved.status == "failed"
        # Worker A acquires the freed lease and begins a new retraction.
        op_new = coordinator.acquire(
            "kb1",
            "card_retract",
            owner="worker-a",
            request_id="req-new",
            subject_id="card1",
            user_id="owner",
        )
        store = LearningStore(root=base)
        current = store.load("b1")
        card = _card_of(current, "card1")
        card.status = KnowledgeCardStatus.RETRACTING
        card.retraction_operation_id = op_new.id
        card.retraction_request_id = "req-new"
        card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
        card.error_code = ""
        card.sanitized_error = ""
        card.version += 1
        current.knowledge_card_retraction_records.append(
            KnowledgeCardRetractionRecord(
                id="rec-new",
                card_id=card.id,
                card_revision=card.revision,
                user_id="owner",
                target_kb_name="kb1",
                request_id="req-new",
                status=RetractionStatus.REINDEXING,
                operation_id=op_new.id,
                original_rel_path=rel_path,
                quarantine_rel_path=card.quarantine_rel_path,
                document_sha256=document_sha,
                index_task_id="task-new",
                created_at=1000.0,
                updated_at=1001.0,
            )
        )
        store.save(current)
        # Worker A quarantined the raw file (only copy now under quarantine).
        raw_file = base / "kb1" / "raw" / rel_path
        quarantine_file = base / "kb1" / card.quarantine_rel_path
        quarantine_file.parent.mkdir(parents=True, exist_ok=True)
        raw_file.unlink()
        quarantine_file.write_text(document, encoding="utf-8")
        # The excluding reindex succeeded: the index evidence was dropped.
        metadata_file = base / "kb1" / "metadata.json"
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        metadata.get("file_hashes", {}).pop(rel_path, None)
        metadata_file.write_text(json.dumps(metadata), encoding="utf-8")
        kb_after_worker_a_quarantine.update(_kb_bytes_snapshot(base))
        return True

    monkeypatch.setattr(
        KnowledgeCardRetractionService,
        "_resolve_orphan_operation_failed",
        _resolve_orphan_and_advance_worker_a,
    )

    # The stale reconcile attempts the same-status published convergence.
    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RETRACTING  # never reverted
    assert card.retraction_request_id == "req-new"
    assert card.retraction_intent is not None  # staging retained, not cleared
    assert result["status"] == "retracting"
    quarantine_file = base / "kb1" / card.quarantine_rel_path
    assert quarantine_file.is_file()  # the only copy survives until finalize
    # The stale reconcile never mutated KB bytes: the only copy is still present,
    # the raw file stays absent, and the index evidence stays dropped.
    assert _kb_bytes_snapshot(base) == kb_after_worker_a_quarantine
    assert "raw/learning_cards/card1-v1.md" not in kb_after_worker_a_quarantine

    # Worker A's exact durable finalize commits; only then is the only
    # quarantine copy deleted.
    coordinator = KbWriteCoordinator(base_dir=base)
    op_new = coordinator.current_operation("kb1")
    assert op_new.id != "op-old"
    finalized = service._finalize(
        "b1",
        "card1",
        user_id="owner",
        status=KnowledgeCardStatus.RETRACTED,
        coordinator=coordinator,
        kb_name="kb1",
        op_id=op_new.id,
        owner="worker-a",
        request_id="req-new",
        target_kb_name="kb1",
        rel_path=rel_path,
        quarantine_rel=card.quarantine_rel_path,
        document_sha=document_sha,
        expected_revision=1,
        now=1100.0,
        error_code="",
        sanitized_error="",
        lease_check=lambda: None,
    )
    assert finalized is True
    service._complete_quarantine_cleanup_for_record(
        "b1",
        "card1",
        "owner",
        request_id="req-new",
        now=1100.0,
    )
    reloaded = _load(base)
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RETRACTED
    assert not quarantine_file.exists()
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"


# ── KB-04 review round 2: identity-safe intent ownership and clear ──────────


def test_glm_race_a_new_request_blocked_until_old_intent_durably_cleared(base, service) -> None:
    """GLM Race A (review round 2): a published card carrying a durable staged
    intent with no record and no operation is not a fresh retraction. A
    different new request — and even the same public request — is blocked at
    ``_resolve_retraction_basis`` (reconcile_required) before it can overwrite
    the intent or acquire a new operation; only an explicit reconcile that
    proves no mutation durably clears the old intent, after which the card is a
    usable published snapshot again."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-old",
        attempt_id="attempt-old",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-old"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)

    # A different new request cannot start: it is blocked as reconcile-required
    # before persisting anything or acquiring an operation.
    with pytest.raises(KnowledgeCardReconcileRequiredError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req-new",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is not None
    assert card.retraction_intent.request_id == "req-old"
    assert card.retraction_request_id == "req-old"
    assert not (base / "kb_write_operations.json").exists()

    # Even the same public request is blocked until reconcile clears it.
    with pytest.raises(KnowledgeCardReconcileRequiredError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req-old",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.retraction_intent is not None
    assert card.retraction_request_id == "req-old"

    # Explicit reconcile (no op, no mutation proven) durably clears the old
    # intent; the card returns to a usable published snapshot with no ledger op.
    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None
    assert card.retraction_request_id == ""
    assert not (base / "kb_write_operations.json").exists()


def test_glm_race_a_crash_after_acquire_surviving_intent_locates_orphan(base, service) -> None:
    """Crash-after-acquire proof (review round 2): a writer persists its exact
    intent, acquires the ``card_retract`` operation, then crashes before
    ``_begin_retraction``. The surviving intent (target + subject + request
    identity and the internal attempt token) lets reconcile locate the exact
    orphan operation and durably resolve it failed, so the KB is never
    permanently blocked."""
    _setup_published_kb(base)
    document_sha = _card_of(_load(base), "card1").document_sha256
    rel_path = _card_rel_path(base)
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    attempt_id = service._persist_retraction_intent(
        "b1",
        "card1",
        user_id="owner",
        request_id="req-crash",
        expected_card_revision=1,
        target_kb_name="kb1",
        rel_path=rel_path,
        quarantine_rel=quarantine_rel,
        document_sha=document_sha,
        now=1000.0,
    )
    assert attempt_id
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.retraction_intent is not None
    assert card.retraction_intent.attempt_id == attempt_id
    # The writer acquired the lease then crashed; the lease expired.
    _write_expired_op(base, op_id="op-orphan", request_id="req-crash", subject_id="card1")

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None  # cleared only after the orphan resolved
    assert card.retraction_operation_id == "op-orphan"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_persist_retraction_intent_fails_closed_on_stale_preflight_overwrite(base, service) -> None:
    """A stale preflight read must not overwrite an existing different attempt:
    ``_persist_retraction_intent`` detects the winning intent under its CAS loop
    and fails closed rather than replacing it (review round 2)."""
    _setup_published_kb(base)
    document_sha = _card_of(_load(base), "card1").document_sha256
    rel_path = _card_rel_path(base)
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    progress = _load(base)
    card = _card_of(progress, "card1")
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-winner",
        attempt_id="attempt-winner",
        original_rel_path=rel_path,
        quarantine_rel_path=quarantine_rel,
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-winner"
    card.version += 1
    _save(base, progress)

    with pytest.raises(KnowledgeCardReconcileRequiredError):
        service._persist_retraction_intent(
            "b1",
            "card1",
            user_id="owner",
            request_id="req-loser",
            expected_card_revision=1,
            target_kb_name="kb1",
            rel_path=rel_path,
            quarantine_rel=quarantine_rel,
            document_sha=document_sha,
            now=1000.0,
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.retraction_intent is not None
    assert card.retraction_intent.request_id == "req-winner"
    assert card.retraction_intent.attempt_id == "attempt-winner"
    assert card.retraction_request_id == "req-winner"


def test_same_public_request_concurrent_persist_only_one_owns(base, service) -> None:
    """Same-public-request concurrency (review round 2): two writers that begin
    from a stale PUBLISHED/no-intent read with the same public ``request_id``
    cannot both believe they own the crash-recovery bridge. Only the first
    durably-created attempt owns it; the losing caller fails closed and its
    ``_clear_retraction_intent`` (e.g. a busy-failure handler) cannot clear the
    winner's intent."""
    _setup_published_kb(base)
    document_sha = _card_of(_load(base), "card1").document_sha256
    rel_path = _card_rel_path(base)
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)

    # Writer A durably owns the attempt.
    attempt_a = service._persist_retraction_intent(
        "b1",
        "card1",
        user_id="owner",
        request_id="req1",
        expected_card_revision=1,
        target_kb_name="kb1",
        rel_path=rel_path,
        quarantine_rel=quarantine_rel,
        document_sha=document_sha,
        now=1000.0,
    )
    assert attempt_a

    # Writer B (same public request_id, a distinct concurrent attempt) fails
    # closed: it cannot overwrite A's intent or believe it owns the bridge.
    with pytest.raises(KnowledgeCardReconcileRequiredError):
        service._persist_retraction_intent(
            "b1",
            "card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
            rel_path=rel_path,
            quarantine_rel=quarantine_rel,
            document_sha=document_sha,
            now=1000.0,
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.retraction_intent is not None
    assert card.retraction_intent.request_id == "req1"
    assert card.retraction_intent.attempt_id == attempt_a

    # The loser's stale busy-failure handler cannot clear the winner's intent.
    cleared = service._clear_retraction_intent(
        "b1",
        "card1",
        "owner",
        now=1001.0,
        request_id="req1",
        attempt_id="attempt-B",
        target_kb_name="kb1",
        rel_path=rel_path,
        quarantine_rel=quarantine_rel,
        document_sha=document_sha,
        card_revision=1,
    )
    assert cleared is False
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.retraction_intent is not None
    assert card.retraction_intent.attempt_id == attempt_a
    assert card.retraction_request_id == "req1"

    # The winner's exact clear succeeds.
    cleared = service._clear_retraction_intent(
        "b1",
        "card1",
        "owner",
        now=1002.0,
        request_id="req1",
        attempt_id=attempt_a,
        target_kb_name="kb1",
        rel_path=rel_path,
        quarantine_rel=quarantine_rel,
        document_sha=document_sha,
        card_revision=1,
    )
    assert cleared is True
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.retraction_intent is None
    assert card.retraction_request_id == ""


def test_begin_retraction_fails_closed_when_intent_owned_by_other_attempt(base, service) -> None:
    """Requirement 4 (review round 2): only the writer that durably owns the
    exact staged intent may begin. A caller whose attempt does not match the
    card's current intent fails closed and cannot mutate the winner's intent or
    transition the card."""
    _setup_published_kb(base)
    document_sha = _card_of(_load(base), "card1").document_sha256
    rel_path = _card_rel_path(base)
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    progress = _load(base)
    card = _card_of(progress, "card1")
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-winner",
        attempt_id="attempt-winner",
        original_rel_path=rel_path,
        quarantine_rel_path=quarantine_rel,
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-winner"
    card.version += 1
    _save(base, progress)

    with pytest.raises(KnowledgeCardStateError):
        service._begin_retraction(
            "b1",
            "card1",
            user_id="owner",
            request_id="req-loser",
            attempt_id="attempt-loser",
            expected_card_revision=1,
            target_kb_name="kb1",
            rel_path=rel_path,
            quarantine_rel=quarantine_rel,
            document_sha=document_sha,
            now=1000.0,
            op_id="op-loser",
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is not None
    assert card.retraction_intent.request_id == "req-winner"
    assert card.retraction_intent.attempt_id == "attempt-winner"
    assert card.retraction_request_id == "req-winner"
    assert card.retraction_operation_id == ""


def test_kb_busy_stale_clear_survives_cas_conflict_with_winners_intent(base, monkeypatch) -> None:
    """KbBusyError Race B (review round 2): Worker A persists its intent and its
    acquire fails busy; before A's stale handler clears, a CAS conflict installs
    Worker B's winning intent. A's clear must no-op (return False) — the exact
    card intent/request, coordinator ledger, raw/quarantine/index KB bytes,
    media store, and history all remain owned by the winner B."""
    _setup_published_kb(base)
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id="card1")
    progress = _load(base)
    card = _card_of(progress, "card1")
    card.artifact_ids = [artifact.id]
    _save(base, progress)
    svc = KnowledgeCardRetractionService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    document_sha = _card_of(_load(base), "card1").document_sha256
    rel_path = _card_rel_path(base)
    quarantine_rel = fixed_quarantine_rel_path("card1", 1, document_sha)
    # A busy KB operation forces Worker A's acquire to fail.
    coordinator = KbWriteCoordinator(base_dir=base)
    coordinator.acquire("kb1", "upload", owner="other-writer")
    kb_before = _kb_bytes_snapshot(base)
    history_before = [h.model_dump() for h in _load(base).history]

    original_save = svc.save
    calls = {"n": 0}

    def _conflicting_save(save_progress):
        calls["n"] += 1
        if calls["n"] == 2:  # Worker A's _clear_retraction_intent CAS save
            # A concurrent CAS conflict installs Worker B's winning intent.
            current = svc.store.load(save_progress.book_id)
            card = _card_of(current, "card1")
            card.retraction_intent = RetractionIntent(
                target_kb_name="kb1",
                request_id="req-B",
                attempt_id="attempt-B",
                original_rel_path=rel_path,
                quarantine_rel_path=quarantine_rel,
                document_sha256=document_sha,
                card_revision=1,
            )
            card.retraction_request_id = "req-B"
            card.version += 1
            svc.store.save(current)
        return original_save(save_progress)

    monkeypatch.setattr(svc, "save", _conflicting_save)

    with pytest.raises(KnowledgeCardRetractionUnavailableError):
        _run(
            svc.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req-A",
                expected_card_revision=1,
            )
        )

    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is not None
    assert card.retraction_intent.request_id == "req-B"
    assert card.retraction_intent.attempt_id == "attempt-B"
    assert card.retraction_request_id == "req-B"
    # Coordinator ledger stays owned by the busy operation (never clobbered).
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["operation_type"] == "upload"
    assert ledger["operations"]["kb1"]["lease_owner"] == "other-writer"
    # KB bytes (raw/quarantine/index) are unchanged by the stale clear.
    assert _kb_bytes_snapshot(base) == kb_before
    # Media references of the still-published card remain live (no release).
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id="card1",
        )
        is not None
    )
    # History is untouched by the losing attempt.
    assert [h.model_dump() for h in reloaded.history] == history_before


def test_reconcile_published_intent_clear_noops_when_operation_appears_at_commit(
    base, service, monkeypatch
) -> None:
    """Commit-boundary current-operation race (review round 2): reconcile reads
    ``current_op is None`` for a published-with-intent card, then a current
    target-KB operation appears before the clear's commit boundary. The clear
    no-ops, retains the exact intent, and the reconcile returns the reloaded
    current card without reporting that the old intent was cleared."""
    _make_kb(base)
    progress, card, document, document_sha, rel_path, _ = _published_progress()
    card.retraction_intent = RetractionIntent(
        target_kb_name="kb1",
        request_id="req-crash",
        attempt_id="attempt-crash",
        original_rel_path=rel_path,
        quarantine_rel_path=fixed_quarantine_rel_path(card.id, card.revision, document_sha),
        document_sha256=document_sha,
        card_revision=1,
    )
    card.retraction_request_id = "req-crash"
    _save(base, progress)
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)
    _write_second_raw_doc(base)
    kb_before = _kb_bytes_snapshot(base)

    real_clear = KnowledgeCardRetractionService._clear_retraction_intent

    def _clear_with_concurrent_op(self, path_id, card_id, user_id, now, **kwargs):
        # A current target-KB operation appears after reconcile's initial
        # current_op is None read, before the clear's commit boundary.
        coordinator = KbWriteCoordinator(base_dir=base)
        coordinator.acquire("kb1", "upload", owner="concurrent-writer")
        return real_clear(self, path_id, card_id, user_id, now, **kwargs)

    monkeypatch.setattr(
        KnowledgeCardRetractionService,
        "_clear_retraction_intent",
        _clear_with_concurrent_op,
    )

    result = service.reconcile_retraction("b1", card_id="card1", user_id="owner")
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is not None  # exact intent retained
    assert card.retraction_intent.request_id == "req-crash"
    assert card.retraction_intent.attempt_id == "attempt-crash"
    assert card.retraction_request_id == "req-crash"
    # The reloaded current card is returned; the old intent was not cleared.
    assert result["status"] == "published"
    assert result["retraction_request_id"] == "req-crash"
    # Observational KB-byte behavior is preserved.
    assert _kb_bytes_snapshot(base) == kb_before
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["operation_type"] == "upload"
    assert ledger["operations"]["kb1"]["lease_owner"] == "concurrent-writer"


# ── KB-04 P0 additional: single-document KB fails closed before mutation ────


def test_retract_single_document_kb_fails_closed_before_mutation(base, service) -> None:
    """A single-document KB (the card is the only supported raw file) fails
    closed before any KB mutation: the excluding raw set would be empty and the
    provider rejects empty reindex input, so this is an unsupported state."""
    _setup_published_kb(base, with_second_doc=False)
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retract(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
            )
        )
    reloaded = _load(base)
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.retraction_intent is None
    assert not (base / "kb_write_operations.json").exists()
    # The raw document and index evidence are untouched.
    assert (base / "kb1" / "raw" / "learning_cards" / "card1-v1.md").is_file()
    metadata = json.loads((base / "kb1" / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"]["learning_cards/card1-v1.md"] == card.document_sha256


# ── backward-compatible schema / migration ─────────────────────────────────


def test_retraction_record_roundtrips_losslessly() -> None:
    record = KnowledgeCardRetractionRecord(
        id="r1",
        card_id="card1",
        card_revision=1,
        user_id="owner",
        target_kb_name="kb1",
        request_id="req1",
        status=RetractionStatus.RETRACTED,
        operation_id="op1",
        original_rel_path="learning_cards/card1-v1.md",
        quarantine_rel_path="quarantine/learning_cards/card1-v1-aaaa.md",
        document_sha256="a" * 64,
        index_task_id="task-1",
        created_at=100.0,
        started_at=101.0,
        updated_at=102.0,
        finished_at=103.0,
    )
    data = record.model_dump(mode="json")
    reloaded = KnowledgeCardRetractionRecord.model_validate(data)
    assert reloaded.model_dump(mode="json") == data
    assert reloaded.status == RetractionStatus.RETRACTED


def test_new_progress_defaults_retraction_records() -> None:
    progress = LearningProgress(book_id="b1")
    assert progress.knowledge_card_retraction_records == []
    card = KnowledgeCardRecord(id="c1", knowledge_point_id="kp1")
    assert card.retraction_intent is None
    assert card.retraction_request_id == ""
    assert card.retraction_operation_id == ""
    assert card.quarantine_rel_path == ""


def test_legacy_fixture_loads_with_defaulted_retraction_fields(base) -> None:
    """Legacy/v2 JSON without the new KB-04 fields still loads losslessly."""
    import json as _json
    from pathlib import Path as _Path

    data = _json.loads(
        (_Path(__file__).parent / "fixtures" / "feynman_progress_v2.json").read_text(
            encoding="utf-8"
        )
    )
    loaded = LearningProgress.model_validate(data)
    assert loaded.knowledge_card_retraction_records == []
    for card in loaded.knowledge_cards:
        assert card.retraction_intent is None
    assert loaded.model_dump(mode="json") == data
