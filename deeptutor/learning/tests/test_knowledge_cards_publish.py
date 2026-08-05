"""Service tests for durable knowledge-card publication (KB-03).

Covers deterministic Markdown/path/hash and provenance bounds, successful
publish through the coordinator + DocumentAdder/RAGService path with explicit
processed-file confirmation, writable-KB policy rejection before any mutation,
eligibility/idempotency conflicts, replay/retry without duplication, unambiguous
failure cleanup, ambiguous partial failure to ``reconcile_required`` +
``needs_reindex``, conservative reconcile using existing evidence only, and
lease contention / interrupted publication behavior (§7.9.2, requirements 1-13).
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
from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardEligibilityError,
    KnowledgeCardInputValidationError,
    KnowledgeCardKbNotWritableError,
    KnowledgeCardOwnershipError,
    KnowledgeCardPublicationConflictError,
    KnowledgeCardPublicationUnavailableError,
    KnowledgeCardReconcileRequiredError,
    KnowledgeCardStaleVersionError,
    KnowledgeCardStateError,
)
from deeptutor.learning.knowledge_cards.publish import (
    KnowledgeCardPublicationService,
    fixed_document_rel_path,
    publication_key,
    render_card_markdown,
)
from deeptutor.learning.knowledge_cards.store import content_hash
from deeptutor.learning.models import (
    KnowledgeCardPublicationRecord,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    LearningProgress,
    MasteryState,
    PublicationIntent,
    PublicationStatus,
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


def _card_progress(
    book_id: str = "b1",
    *,
    user_id: str = "owner",
    card_id: str = "card1",
    kp_id: str = "kp1",
    title: str = "The Feynman Technique",
    body: str = "Explain it simply, then trace the gap.",
    status: KnowledgeCardStatus = KnowledgeCardStatus.DRAFT,
    revision: int = 1,
) -> tuple[LearningProgress, KnowledgeCardRecord]:
    progress, attempt, assessment = stable_mastery_progress(book_id=book_id, kp_id=kp_id)
    card = KnowledgeCardRecord(
        id=card_id,
        user_id=user_id,
        path_id=book_id,
        knowledge_point_id=kp_id,
        stable_attempt_id=attempt.id,
        stable_assessment_id=assessment.id,
        stable_assessment_sequence=assessment.assessment_sequence,
        status=status,
        revision=revision,
        title=title,
        body=body,
        content_hash=content_hash(title, body),
        source_snapshot_ids=["s1"],
        evidence_ids=["ev1"],
    )
    progress.knowledge_cards.append(card)
    return progress, card


def _attach_failed_publication(
    progress: LearningProgress,
    card: KnowledgeCardRecord,
    *,
    user_id: str = "owner",
    request_id: str = "req-old",
    record_id: str = "rec1",
    target_kb_name: str = "kb1",
) -> KnowledgeCardPublicationRecord:
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key(user_id, card.id, card.revision, target_kb_name)
    record = KnowledgeCardPublicationRecord(
        id=record_id,
        card_id=card.id,
        publication_key=key,
        card_revision=card.revision,
        target_kb_name=target_kb_name,
        document_rel_path=rel_path,
        document_sha256=document_sha,
        status=PublicationStatus.PUBLISH_FAILED,
        request_id=request_id,
    )
    progress.knowledge_card_publication_records.append(record)
    card.target_kb_name = target_kb_name
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    return record


def _card_of(progress: LearningProgress, card_id: str) -> KnowledgeCardRecord:
    return next(card for card in progress.knowledge_cards if card.id == card_id)


def _save(base: Path, progress: LearningProgress) -> None:
    LearningStore(root=base).save(progress)


def _make_ready_publishing_card(
    base: Path, *, card_id: str = "card1", op_id: str = "op1"
) -> LearningProgress:
    """A card in PUBLISHING with a real KB state already holding its document."""
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISHING)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("owner", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    card.publication_operation_id = op_id
    progress.knowledge_card_publication_records.append(
        KnowledgeCardPublicationRecord(
            id="rec1",
            card_id=card.id,
            publication_key=key,
            card_revision=card.revision,
            target_kb_name="kb1",
            document_rel_path=rel_path,
            document_sha256=document_sha,
            status=PublicationStatus.PUBLISHING,
        )
    )
    _save(base, progress)
    return progress


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


def _write_expired_op(base: Path, *, op_id: str = "op1", status: str = "running") -> None:
    coordinator = KbWriteCoordinator(base_dir=base)
    coordinator._save(
        {
            "kb1": KbWriteOperation.from_dict(
                {
                    "id": op_id,
                    "kb_name": "kb1",
                    "operation_type": "card_publish",
                    "status": status,
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                    "lease_owner": "crash-owner",
                    "lease_expires_at": "2026-08-04T12:00:00Z",
                }
            )
        }
    )


def _write_orphan_op(
    base: Path,
    *,
    op_id: str = "op-orphan",
    subject_id: str = "card1",
    request_id: str = "req-crash",
    status: str = "running",
) -> None:
    """An expired card_publish orphan bound to a card by subject + request id."""
    coordinator = KbWriteCoordinator(base_dir=base)
    coordinator._save(
        {
            "kb1": KbWriteOperation.from_dict(
                {
                    "id": op_id,
                    "kb_name": "kb1",
                    "operation_type": "card_publish",
                    "status": status,
                    "subject_id": subject_id,
                    "request_id": request_id,
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                    "lease_owner": "crash-owner",
                    "lease_expires_at": "2026-08-04T12:00:00Z",
                }
            )
        }
    )


def _make_published_card_with_op(
    base: Path,
    *,
    card_id: str = "card1",
    op_id: str = "op1",
    published_at: float = 1000.0,
) -> LearningProgress:
    """A PUBLISHED card with a durable ``publication_operation_id`` linkage."""
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISHED)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("owner", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    card.publication_operation_id = op_id
    card.confirmed_at = published_at
    card.published_at = published_at
    progress.knowledge_card_publication_records.append(
        KnowledgeCardPublicationRecord(
            id="rec1",
            card_id=card.id,
            publication_key=key,
            card_revision=card.revision,
            target_kb_name="kb1",
            document_rel_path=rel_path,
            document_sha256=document_sha,
            status=PublicationStatus.PUBLISHED,
            published_at=published_at,
        )
    )
    _save(base, progress)
    return progress


def _artifact_bound_to_card(
    base: Path,
    *,
    card_id: str,
    user_id: str = "owner",
    artifact_id: str = "art1",
    owner_id: str | None = None,
    owner_type: ReferenceOwnerType = ReferenceOwnerType.KNOWLEDGE_CARD,
    soft_deleted: bool = False,
) -> tuple[MediaStore, GeneratedArtifact, ArtifactReference]:
    """A same-user artifact with a (optionally soft-deleted) card reference."""
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
def service(base: Path) -> KnowledgeCardPublicationService:
    return KnowledgeCardPublicationService(LearningStore(root=base), kb_base_dir=base)


@pytest.fixture
def manager(base: Path) -> KnowledgeBaseManager:
    return KnowledgeBaseManager(base_dir=str(base))


@pytest.fixture
def mock_provider(monkeypatch):
    def _patch(outcome: str):
        async def _add(self, kb_name, file_paths, **kwargs):
            if outcome == "success":
                return True
            if outcome == "no_mutation":
                return False
            raise RuntimeError("provider exploded mid-index")

        monkeypatch.setattr(rag_module.RAGService, "add_documents", _add)

    return _patch


# ── deterministic rendering / path / key / provenance bounds ───────────────


def test_fixed_path_and_publication_key() -> None:
    assert fixed_document_rel_path("card1", 1) == "learning_cards/card1-v1.md"
    assert fixed_document_rel_path("card1", 7) == "learning_cards/card1-v7.md"
    assert publication_key("u1", "card1", 1, "kb1") == "kb3:u1|card1|1|kb1"
    assert publication_key("u2", "card1", 1, "kb1") != publication_key("u1", "card1", 1, "kb1")
    assert publication_key("u1", "card2", 1, "kb1") != publication_key("u1", "card1", 1, "kb1")
    assert publication_key("u1", "card1", 2, "kb1") != publication_key("u1", "card1", 1, "kb1")
    assert publication_key("u1", "card1", 1, "kb2") != publication_key("u1", "card1", 1, "kb1")


def test_render_markdown_is_deterministic_and_bounded() -> None:
    progress, card = _card_progress(
        body="Explain it simply, then trace the gap. See https://private.example.com/x"
    )
    first = render_card_markdown(card, progress)
    second = render_card_markdown(card, progress)
    assert first == second
    assert first.startswith("# The Feynman Technique")
    assert "Explain it simply" in first
    # Allowed provenance identities.
    assert "- Knowledge point: `kp1`" in first
    assert "- Stable assessment: `ra1` (sequence 1)" in first
    assert "- Source: Source 1 (p.1)" in first
    assert "- Evidence: ev1" in first
    # Bounds: no raw conversation / evidence content, no content hashes, no URLs.
    assert "Learner's plain-language explanation" not in first
    assert "evidence-hash-1" not in first
    assert "src-hash-1" not in first
    # The body's URL is redacted (non-vacuous assertion: real URL in the input).
    assert "http://" not in first and "https://" not in first
    assert "example.com" not in first


def test_render_markdown_never_leaks_private_urls_or_base64() -> None:
    progress, card = _card_progress()
    progress.source_snapshots[0].locator = "https://example.com/private-document"
    progress.source_snapshots[0].citation_anchors = ["https://example.com/x"]
    rendered = render_card_markdown(card, progress)
    assert "example.com" not in rendered


# ── successful publish ─────────────────────────────────────────────────────


def test_publish_success_through_document_adder(base, service, mock_provider) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("success")

    result = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )

    assert result["status"] == "published"
    assert result["replayed"] is False
    assert result["document_rel_path"] == "learning_cards/card1-v1.md"
    assert result["confirmed_at"] is not None
    assert result["published_at"] is not None

    # Explicit processed-file confirmation: raw file + hash registry + ledger.
    kb_dir = base / "kb1"
    raw_file = kb_dir / "raw" / "learning_cards" / "card1-v1.md"
    assert raw_file.is_file()
    assert hashlib.sha256(raw_file.read_bytes()).hexdigest() == result["document_sha256"]
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"]["learning_cards/card1-v1.md"] == result["document_sha256"]
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"
    assert ledger["operations"]["kb1"]["operation_type"] == "card_publish"

    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    # Append-only revision history: the initial PUBLISHING revision and the
    # terminal PUBLISHED revision both survive; the projection is the latest.
    revisions = [
        r
        for r in reloaded.knowledge_card_publication_records
        if r.publication_key == result["publication_key"]
    ]
    assert [r.status for r in revisions] == [
        PublicationStatus.PUBLISHING,
        PublicationStatus.PUBLISHED,
    ]
    assert len(service._records_for_card(reloaded, "card1")) == 1
    record = revisions[-1]
    assert record.status == PublicationStatus.PUBLISHED
    assert record.document_sha256 == result["document_sha256"]


# ── writable-KB policy rejection before any KB mutation ────────────────────


@pytest.mark.parametrize(
    "kb_kwargs",
    [
        {"connected": True},
        {"needs_reindex": True},
        {"status": "processing"},
    ],
)
def test_publish_rejects_non_writable_kb_before_mutation(
    base, service, mock_provider, kb_kwargs
) -> None:
    _make_kb(base, **kb_kwargs)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("success")

    with pytest.raises(KnowledgeCardKbNotWritableError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


def test_publish_rejects_missing_kb_before_mutation(base, service) -> None:
    # No kb_config entry at all.
    progress, _ = _card_progress()
    _save(base, progress)
    with pytest.raises(KnowledgeCardKbNotWritableError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="missing-kb",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


def test_publish_rejects_unauthorized_owner(base, service, mock_provider) -> None:
    _make_kb(base)
    progress, _ = _card_progress(user_id="owner")
    _save(base, progress)
    mock_provider("success")
    with pytest.raises(KnowledgeCardOwnershipError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="intruder",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT


def test_publish_rejects_cross_path(base, service) -> None:
    _make_kb(base)
    progress, card = _card_progress()
    # The card was addressed through a different path than it belongs to.
    card.path_id = "other-path"
    _save(base, progress)
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT


# ── eligibility / idempotency conflicts ────────────────────────────────────


def test_publish_stales_card_on_stale_assessment(base, service) -> None:
    _make_kb(base)
    progress, card = _card_progress()
    # A newer assessment overtook the card's bound one.
    progress.projections["kp1"].latest_assessment_id = "ra-newer"
    _save(base, progress)
    with pytest.raises(KnowledgeCardEligibilityError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.STALE_EVIDENCE
    assert not (base / "kb_write_operations.json").exists()


def test_publish_stales_card_on_non_stable_mastery(base, service) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    progress.projections["kp1"].mastery_state = MasteryState.PROVISIONAL_MASTERY
    _save(base, progress)
    with pytest.raises(KnowledgeCardEligibilityError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.STALE_EVIDENCE


def test_publish_rejects_stale_card_revision(base, service) -> None:
    _make_kb(base)
    progress, _ = _card_progress(revision=1)
    _save(base, progress)
    with pytest.raises(KnowledgeCardStaleVersionError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=2,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT


def test_publish_conflicts_on_same_key_different_content(base, service) -> None:
    _make_kb(base)
    progress, card = _card_progress()
    # A prior publication record exists for the same key but different content.
    progress.knowledge_card_publication_records.append(
        KnowledgeCardPublicationRecord(
            id="rec1",
            card_id=card.id,
            publication_key=publication_key("owner", card.id, card.revision, "kb1"),
            card_revision=card.revision,
            target_kb_name="kb1",
            document_rel_path="learning_cards/card1-v1.md",
            document_sha256="0" * 64,
            status=PublicationStatus.PUBLISH_FAILED,
        )
    )
    _save(base, progress)
    with pytest.raises(KnowledgeCardPublicationConflictError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


def test_publish_refuses_publishing_and_reconcile_required_cards(base, service) -> None:
    _make_kb(base)
    for status in (
        KnowledgeCardStatus.PUBLISHING,
        KnowledgeCardStatus.RECONCILE_REQUIRED,
    ):
        store = LearningStore(root=base)
        store.delete("b1")
        progress, _ = _card_progress(status=status)
        store.save(progress)
        with pytest.raises(KnowledgeCardReconcileRequiredError):
            _run(
                service.publish(
                    "b1",
                    card_id="card1",
                    user_id="owner",
                    request_id="req1",
                    expected_card_revision=1,
                    target_kb_name="kb1",
                )
            )


# ── replay / retry without duplication ─────────────────────────────────────


def test_repeated_publish_after_reload_replays_without_duplicate(
    base, service, mock_provider
) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("success")

    first = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert first["status"] == "published"

    # A fresh service/store simulates a process restart reload.
    restarted = KnowledgeCardPublicationService(LearningStore(root=base), kb_base_dir=base)
    second = _run(
        restarted.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert second["status"] == "published"
    assert second["replayed"] is True

    reloaded = restarted.store.load("b1")
    # One logical publication (latest revision), one raw file, one hash entry.
    assert len(restarted._records_for_card(reloaded, "card1")) == 1
    assert (
        restarted._latest_publication(reloaded, second["publication_key"]).status
        == PublicationStatus.PUBLISHED
    )
    assert len(list((base / "kb1" / "raw" / "learning_cards").glob("*.md"))) == 1
    metadata = json.loads((base / "kb1" / "metadata.json").read_text(encoding="utf-8"))
    assert len(metadata["file_hashes"]) == 1


def test_retry_publish_reuses_key_path_hash_and_record(base, service, mock_provider) -> None:
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISH_FAILED)
    _attach_failed_publication(progress, card, request_id="req-old")
    _save(base, progress)
    mock_provider("success")

    result = _run(
        service.retry_publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req-retry",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert result["status"] == "published"
    assert result["document_rel_path"] == "learning_cards/card1-v1.md"

    reloaded = service.store.load("b1")
    # One logical publication record, reused not duplicated — but append-only
    # revision history: the original failure revision survives and the latest
    # revision is PUBLISHED.
    assert len(service._records_for_card(reloaded, "card1")) == 1
    revisions = [
        r
        for r in reloaded.knowledge_card_publication_records
        if r.publication_key == result["publication_key"]
    ]
    assert revisions[0].status == PublicationStatus.PUBLISH_FAILED
    assert revisions[0].request_id == "req-old"  # original failure preserved
    record = service._latest_publication(reloaded, result["publication_key"])
    assert record.status == PublicationStatus.PUBLISHED
    assert record.id == "rec1"
    # Exactly one raw file + one hash entry.
    assert len(list((base / "kb1" / "raw" / "learning_cards").glob("*.md"))) == 1
    metadata = json.loads((base / "kb1" / "metadata.json").read_text(encoding="utf-8"))
    assert len(metadata["file_hashes"]) == 1


def test_retry_publish_rejects_different_target_kb(base, service) -> None:
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISH_FAILED)
    _attach_failed_publication(progress, card)
    _save(base, progress)
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            service.retry_publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req-retry",
                expected_card_revision=1,
                target_kb_name="other-kb",
            )
        )


def test_retry_publish_requires_failed_card(base, service) -> None:
    _make_kb(base)
    progress, _ = _card_progress(status=KnowledgeCardStatus.DRAFT)
    _save(base, progress)
    with pytest.raises(KnowledgeCardStateError):
        _run(
            service.retry_publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req-retry",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )


# ── unambiguous failure cleanup ────────────────────────────────────────────


def test_unambiguous_failure_cleans_up_retains_draft_and_mastery(
    base, service, mock_provider
) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("no_mutation")

    result = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert result["status"] == "publish_failed"

    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISH_FAILED
    assert card.title == "The Feynman Technique"  # draft content retained
    assert card.body == "Explain it simply, then trace the gap."
    # Mastery is never lowered.
    assert reloaded.projections["kp1"].mastery_state == MasteryState.STABLE_MASTERY
    # Only the unsuccessful fixed raw file + matching hash entry were removed.
    assert not (base / "kb1" / "raw" / "learning_cards" / "card1-v1.md").exists()
    metadata_file = base / "kb1" / "metadata.json"
    if metadata_file.exists():
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        assert "learning_cards/card1-v1.md" not in metadata.get("file_hashes", {})
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


# ── ambiguous partial failure → reconcile_required + needs_reindex ─────────


def test_ambiguous_failure_converges_to_reconcile_required(
    base, service, manager, mock_provider
) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("raise")

    result = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert result["status"] == "reconcile_required"

    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RECONCILE_REQUIRED
    # KB marked needs_reindex so new publication is blocked until repaired.
    entry = manager.get_kb_entry("kb1")
    assert entry["needs_reindex"] is True
    assert entry["status"] == "needs_reindex"
    # The raw file is retained for inspection.
    assert (base / "kb1" / "raw" / "learning_cards" / "card1-v1.md").is_file()
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "reconcile_required"


# ── reconcile-publication: existing evidence only, never resubmits ─────────


def test_reconcile_converges_to_published_when_evidence_complete(base, service, manager) -> None:
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISHING)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("owner", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    card.publication_operation_id = "op1"
    progress.knowledge_card_publication_records.append(
        KnowledgeCardPublicationRecord(
            id="rec1",
            card_id=card.id,
            publication_key=key,
            card_revision=card.revision,
            target_kb_name="kb1",
            document_rel_path=rel_path,
            document_sha256=document_sha,
            status=PublicationStatus.PUBLISHING,
        )
    )
    _save(base, progress)
    raw_file = _write_raw_document(base, rel_path, document)
    before = raw_file.read_bytes()
    _write_index_evidence(base, rel_path, document_sha)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"

    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISHED
    # No resubmission: the fixed file was never rewritten or copied.
    assert raw_file.read_bytes() == before
    # Append-only: reconcile appends a PUBLISHED revision over PUBLISHING.
    assert len(service._records_for_card(reloaded, "card1")) == 1
    assert (
        service._latest_publication(reloaded, "kb3:owner|card1|1|kb1").status
        == PublicationStatus.PUBLISHED
    )


def test_reconcile_converges_to_publish_failed_when_nothing_written(base, service) -> None:
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISHING)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("owner", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    card.publication_operation_id = "op1"
    _save(base, progress)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "publish_failed"
    assert result["error_code"] == "interrupted"

    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISH_FAILED
    # Retryable: a confirmed failed submission can become retryable.
    assert not (base / "kb1" / "raw" / "learning_cards").exists()


def test_reconcile_keeps_reconcile_required_when_ambiguous(base, service) -> None:
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISHING)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("owner", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    card.publication_operation_id = "op1"
    _save(base, progress)
    # Raw file present but no index evidence → ambiguous.
    _write_raw_document(base, rel_path, document)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "reconcile_required"
    assert result["error_code"] == "ambiguous_state"

    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RECONCILE_REQUIRED


def test_reconcile_releases_interrupted_write_operation(base, service) -> None:
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISHING)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("owner", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    card.publication_operation_id = "op1"
    _save(base, progress)
    _write_expired_op(base, op_id="op1", status="running")

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "publish_failed"

    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_reconcile_refuses_to_force_live_publication(base, service) -> None:
    _make_kb(base)
    _make_ready_publishing_card(base, op_id="op1")
    coordinator = KbWriteCoordinator(base_dir=base)
    # A live lease (long expiry) means the publication is still in flight.
    op = coordinator.acquire("kb1", "card_publish", owner="live-owner")
    # Point the card at the live op.
    progress = service.store.load("b1")
    _card_of(progress, "card1").publication_operation_id = op.id
    service.store.save(progress)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    # Left untouched while a live lease is held.
    assert result["status"] == "publishing"


# ── published card must not strand an unresolved KB operation (KB-03 P0) ───


def test_reconcile_published_card_converges_stranded_expired_operation(base, service) -> None:
    """A crash/failure after the published card save but before the lease release
    leaves the exact card_publish operation running/expired. Explicit reconcile on
    the immutable published card converges it to ``succeeded`` and unblocks the KB
    without demoting or mutating the published snapshot."""
    _make_kb(base)
    _make_published_card_with_op(base, op_id="op1")
    _write_expired_op(base, op_id="op1", status="running")

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    assert result["replayed"] is True

    # The exact stranded operation is converged; the KB is unblocked.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"
    # The published snapshot is immutable (same timestamp, same linkage).
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.published_at == 1000.0
    assert card.publication_operation_id == "op1"


def test_reconcile_published_card_converges_reconcile_required_operation(base, service) -> None:
    """A published card whose exact operation is ``reconcile_required`` is
    converged on explicit reconcile so the KB can accept new work again."""
    _make_kb(base)
    _make_published_card_with_op(base, op_id="op1")
    _write_expired_op(base, op_id="op1", status="reconcile_required")

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"

    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"


def test_reconcile_published_card_leaves_live_operation_untouched(base, service) -> None:
    """A live active operation (unexpired lease) is never resolved without
    matching ownership — even when the published card points at it."""
    _make_kb(base)
    _make_published_card_with_op(base, op_id="op1")
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "card_publish", owner="live-owner")
    # Point the published card at the live op.
    progress = service.store.load("b1")
    _card_of(progress, "card1").publication_operation_id = op.id
    service.store.save(progress)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"
    current = coordinator.current_operation("kb1")
    assert current.status == "running"  # untouched, still live
    assert current.lease_owner == "live-owner"


def test_reconcile_published_card_leaves_different_operation_untouched(base, service) -> None:
    """Reconcile on a published card never resolves another operation — even a
    stranded one — when its id differs from the card's durable linkage."""
    _make_kb(base)
    _make_published_card_with_op(base, op_id="op1")
    _write_expired_op(base, op_id="op-other", status="running")

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"

    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"  # untouched


# ── lease contention / interrupted publish ─────────────────────────────────


def test_publish_refused_when_kb_lease_held(base, service) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    coordinator = KbWriteCoordinator(base_dir=base)
    coordinator.acquire("kb1", "card_publish", owner="other-writer")

    with pytest.raises(KnowledgeCardPublicationUnavailableError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT


def test_publish_persists_confirmed_at_only_through_publish(base, service, mock_provider) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("success")
    # Before publish, no confirmed_at.
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").confirmed_at is None

    _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").confirmed_at is not None


# ── reconcile state guard (review finding 3) ────────────────────────────────


def test_reconcile_no_ops_on_fresh_draft(base, service) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "draft"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.DRAFT
    assert card.publication_intent is None


@pytest.mark.parametrize(
    "status",
    [
        KnowledgeCardStatus.STALE_EVIDENCE,
        KnowledgeCardStatus.DISCARDED,
        KnowledgeCardStatus.RETRACTED,
    ],
)
def test_reconcile_no_ops_on_non_publication_states(base, service, status) -> None:
    _make_kb(base)
    store = LearningStore(root=base)
    progress, _ = _card_progress(status=status)
    store.save(progress)
    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == status.value
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == status


def test_reconcile_draft_with_intent_no_op_keeps_draft(base, service) -> None:
    """Crash between intent persistence and acquire: no orphan op exists, so
    reconcile clears the intent and keeps the card a usable draft."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key="kb3:owner|card1|1|kb1",
        document_rel_path="learning_cards/card1-v1.md",
        document_sha256="0" * 64,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "draft"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.DRAFT
    assert card.publication_intent is None


def test_reconcile_draft_with_intent_resolves_orphan_op(base, service) -> None:
    """Crash after acquire but before operation-id attachment: the orphan
    ``card_publish`` op is located by durable identity and converged without
    releasing another card's operation, and the card stays a usable draft."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key="kb3:owner|card1|1|kb1",
        document_rel_path="learning_cards/card1-v1.md",
        document_sha256="0" * 64,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    coordinator = KbWriteCoordinator(base_dir=base)
    coordinator._save(
        {
            "kb1": KbWriteOperation.from_dict(
                {
                    "id": "op-orphan",
                    "kb_name": "kb1",
                    "operation_type": "card_publish",
                    "status": "running",
                    "subject_id": "card1",
                    "request_id": "req-crash",
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                    "lease_owner": "crash-owner",
                    "lease_expires_at": "2026-08-04T12:00:00Z",
                }
            )
        }
    )
    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "draft"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.DRAFT
    assert card.publication_intent is None
    # The orphan op no longer blocks the KB.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


# ── orphan intent is only cleared after durable operation convergence ──────


def test_reconcile_draft_intent_no_evidence_retains_intent_when_resolve_none(
    base, service, monkeypatch
) -> None:
    """No-evidence draft-with-intent reconcile: a ``None`` from ``resolve_manual``
    means the operation was NOT durably converged — the intent must be retained
    (the only durable identity of the orphan) so a later reconcile can retry,
    and the operation is never released."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key="kb3:owner|card1|1|kb1",
        document_rel_path="learning_cards/card1-v1.md",
        document_sha256="0" * 64,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    _write_orphan_op(base, op_id="op-orphan", request_id="req-crash")

    original_resolve = KbWriteCoordinator.resolve_manual
    calls = {"n": 0}

    def _resolve_none_then_real(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(KbWriteCoordinator, "resolve_manual", _resolve_none_then_real)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "draft"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.DRAFT
    assert card.publication_intent is not None  # retained
    # The operation was not released.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"

    # A later explicit reconcile retries and, on durable convergence, clears the
    # intent and releases the orphan op.
    result2 = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result2["status"] == "draft"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.DRAFT
    assert card.publication_intent is None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_reconcile_draft_intent_no_evidence_retains_intent_when_resolve_raises(
    base, service, monkeypatch
) -> None:
    """No-evidence draft-with-intent reconcile: an exception from
    ``resolve_manual`` must not clear the intent — the orphan stays discoverable."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key="kb3:owner|card1|1|kb1",
        document_rel_path="learning_cards/card1-v1.md",
        document_sha256="0" * 64,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    _write_orphan_op(base, op_id="op-orphan", request_id="req-crash")

    original_resolve = KbWriteCoordinator.resolve_manual
    calls = {"n": 0}

    def _resolve_raises_then_real(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ledger write failed")
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(KbWriteCoordinator, "resolve_manual", _resolve_raises_then_real)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "draft"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.DRAFT
    assert card.publication_intent is not None  # retained
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"

    # Later explicit reconcile retries successfully.
    result2 = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result2["status"] == "draft"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.publication_intent is None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "failed"


def test_reconcile_draft_intent_evidence_complete_attaches_op_id_when_resolve_fails(
    base, service, monkeypatch
) -> None:
    """Evidence-complete reconcile starting from a draft intent attaches the exact
    ``publication_operation_id`` before the intent is cleared, so when the
    operation resolution itself fails the next reconcile still locates and
    converges it (never stranding the KB)."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key=publication_key("owner", card.id, card.revision, "kb1"),
        document_rel_path=rel_path,
        document_sha256=document_sha,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    _write_orphan_op(base, op_id="op-orphan", request_id="req-crash")
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)

    original_resolve = KbWriteCoordinator.resolve_manual
    calls = {"n": 0}

    def _resolve_raises_then_real(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ledger write failed")
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(KbWriteCoordinator, "resolve_manual", _resolve_raises_then_real)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"

    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    # The exact operation id is durably attached before the intent was cleared.
    assert card.publication_operation_id == "op-orphan"
    assert card.publication_intent is None
    # The operation was not resolved on the failed attempt.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"

    # The next reconcile locates the op via the durable linkage and converges it.
    result2 = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result2["status"] == "published"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"


def test_reconcile_draft_intent_evidence_complete_attaches_op_id_when_resolve_none(
    base, service, monkeypatch
) -> None:
    """Same as above but ``resolve_manual`` returns ``None`` instead of raising:
    the card is published, the op id is attached, and the next reconcile
    converges the stranded operation."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key=publication_key("owner", card.id, card.revision, "kb1"),
        document_rel_path=rel_path,
        document_sha256=document_sha,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    _write_orphan_op(base, op_id="op-orphan", request_id="req-crash")
    _write_raw_document(base, rel_path, document)
    _write_index_evidence(base, rel_path, document_sha)

    original_resolve = KbWriteCoordinator.resolve_manual
    calls = {"n": 0}

    def _resolve_none_then_real(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return original_resolve(*args, **kwargs)

    monkeypatch.setattr(KbWriteCoordinator, "resolve_manual", _resolve_none_then_real)

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "published"

    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.publication_operation_id == "op-orphan"
    assert card.publication_intent is None
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"

    result2 = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result2["status"] == "published"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "succeeded"


# ── exact orphan request identity (KB-03 P0) ────────────────────────────────


def test_reconcile_draft_intent_ignores_orphan_op_with_missing_request_id(base, service) -> None:
    """An orphan operation without a request id is never treated as this card's
    orphan: it returns ``None`` and the operation is never released."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key="kb3:owner|card1|1|kb1",
        document_rel_path="learning_cards/card1-v1.md",
        document_sha256="0" * 64,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    _write_orphan_op(base, op_id="op-orphan", request_id="")

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    # op is None → the draft is kept usable, but the operation is NOT released.
    assert result["status"] == "draft"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


def test_reconcile_draft_intent_ignores_orphan_op_with_mismatched_request_id(base, service) -> None:
    """An orphan operation with a different request id is never treated as this
    card's orphan: it returns ``None`` and the operation is never released."""
    _make_kb(base)
    progress, card = _card_progress()  # DRAFT
    card.publication_intent = PublicationIntent(
        target_kb_name="kb1",
        publication_key="kb3:owner|card1|1|kb1",
        document_rel_path="learning_cards/card1-v1.md",
        document_sha256="0" * 64,
        request_id="req-crash",
        expected_card_revision=1,
    )
    _save(base, progress)
    _write_orphan_op(base, op_id="op-orphan", request_id="req-other")

    result = service.reconcile_publication("b1", card_id="card1", user_id="owner")
    assert result["status"] == "draft"
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


# ── Markdown privacy / safety + path sandbox (review finding 4) ─────────────


def test_render_markdown_neutralizes_malicious_content() -> None:
    progress, card = _card_progress(
        title="Click [here](javascript:alert(1))",
        body=(
            "<script>alert('xss')</script>\n"
            "See https://private.example.com/api?key=sk-secret123\n"
            "[bad](javascript:evil())\n"
            "Normal learning prose < 10 and > 0."
        ),
    )
    rendered = render_card_markdown(card, progress)
    assert "javascript:" not in rendered
    assert "example.com" not in rendered
    assert "sk-secret123" not in rendered
    assert "<script>" not in rendered
    # Ordinary safe prose and useful Markdown survive.
    assert "Normal learning prose" in rendered
    assert "See" in rendered


def test_render_markdown_redacts_base64_payloads() -> None:
    progress, card = _card_progress(
        body="Before.\n![](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==)\nAfter."
    )
    rendered = render_card_markdown(card, progress)
    assert "iVBORw0KGgo" not in rendered
    assert "data:image/png" not in rendered


def test_fixed_path_rejects_traversal_card_id() -> None:
    for bad in ("../../etc/passwd", "a/b", "a\\b", "card:1", ".."):
        with pytest.raises(KnowledgeCardInputValidationError):
            fixed_document_rel_path(bad, 1)
    with pytest.raises(KnowledgeCardInputValidationError):
        fixed_document_rel_path("", 1)
    with pytest.raises(KnowledgeCardInputValidationError):
        fixed_document_rel_path("card1", 0)


# ── post-publish target mismatch (review finding 6) ─────────────────────────


def test_publish_to_different_target_after_publish_conflicts(base, service, mock_provider) -> None:
    _make_kb(base)  # kb1
    # Register a second writable KB in the same config.
    kb2_dir = base / "kb2"
    (kb2_dir / "raw").mkdir(parents=True)
    _write_provider_index(kb2_dir)
    config = json.loads((base / "kb_config.json").read_text(encoding="utf-8"))
    config["knowledge_bases"]["kb2"] = {
        "path": "kb2",
        "rag_provider": "llamaindex",
        "status": "ready",
        "needs_reindex": False,
    }
    (base / "kb_config.json").write_text(json.dumps(config), encoding="utf-8")
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("success")

    first = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert first["status"] == "published"

    # Same key + same target replays.
    replay = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert replay["replayed"] is True

    # A different target is a stable conflict, never an idempotent success.
    with pytest.raises(KnowledgeCardPublicationConflictError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req2",
                expected_card_revision=1,
                target_kb_name="kb2",
            )
        )


# ── lease heartbeat / ownership loss (review findings 1 & 5) ────────────────


def test_publish_aborts_when_lease_lost_during_staging(
    base, service, mock_provider, monkeypatch
) -> None:
    """The cooperative staging ``lease_check`` aborts the publish when the lease
    is lost mid-staging: the card converges to reconcile_required and is never
    marked published, and the stale writer never resolves the operation."""
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("success")

    calls = {"n": 0}
    original_verify = KbWriteCoordinator.verify_lease

    def _flaky_verify(self, kb_name, operation_id, *, owner=None):
        calls["n"] += 1
        if calls["n"] > 1:
            raise KbOwnershipLostError(kb_name, operation_id)
        return original_verify(self, kb_name, operation_id, owner=owner)

    monkeypatch.setattr(KbWriteCoordinator, "verify_lease", _flaky_verify)

    result = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert result["status"] == "reconcile_required"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.RECONCILE_REQUIRED
    assert card.publication_operation_id  # durable op reference retained
    # The stale writer did not resolve the operation.
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "running"


def test_finalize_refuses_to_publish_after_lease_lost(base, service) -> None:
    """Before the terminal card write, the ownership gate fails closed: a lost
    lease (e.g. a newer upload/delete/reindex took over) prevents a stale
    ``published`` finalization and never resolves the newer holder's op."""
    _make_kb(base)
    _make_ready_publishing_card(base, op_id="op1")
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "card_publish", owner="writer-a")
    progress = service.store.load("b1")
    _card_of(progress, "card1").publication_operation_id = op.id
    service.store.save(progress)

    def _lost_lease() -> None:
        raise KbOwnershipLostError("kb1", op.id)

    with pytest.raises(KbOwnershipLostError):
        service._finalize(
            "b1",
            "card1",
            status=KnowledgeCardStatus.PUBLISHED,
            coordinator=coordinator,
            kb_name="kb1",
            op_id=op.id,
            owner="writer-a",
            rel_path="learning_cards/card1-v1.md",
            document_sha="0" * 64,
            expected_revision=1,
            now=1000.0,
            error_code="",
            sanitized_error="",
            lease_check=_lost_lease,
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISHING
    current = coordinator.current_operation("kb1")
    assert current.id == op.id
    assert current.status == "running"


# ── reference revalidation at the publish boundary (review finding 8) ───────


def test_publish_fails_closed_on_deleted_evidence(base, service, mock_provider) -> None:
    _make_kb(base)
    progress, card = _card_progress()
    progress.evidence_items = [item for item in progress.evidence_items if item.id != "ev1"]
    _save(base, progress)
    mock_provider("success")
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            service.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


def test_publish_fails_closed_on_unowned_artifact(base, service, mock_provider) -> None:
    _make_kb(base)
    progress, card = _card_progress()
    media_store, artifact = media_store_with_artifact(base, user_id="other-user")
    card.artifact_ids = [artifact.id]
    _save(base, progress)
    mock_provider("success")
    svc = KnowledgeCardPublicationService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            svc.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = svc.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


# ── card-level live artifact reference (KB-03 P0) ───────────────────────────


def test_publish_fails_closed_when_artifact_referenced_by_another_card(
    base, service, mock_provider
) -> None:
    """A same-user artifact bound to *another* card/context must fail closed at
    the publish boundary — before lease acquisition or KB mutation."""
    _make_kb(base)
    progress, card = _card_progress()
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id="card1", owner_id="other-card")
    card.artifact_ids = [artifact.id]
    _save(base, progress)
    mock_provider("success")
    svc = KnowledgeCardPublicationService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            svc.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = svc.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


def test_publish_fails_closed_when_artifact_reference_is_soft_deleted(
    base, service, mock_provider
) -> None:
    """A soft-deleted card reference must fail closed — the artifact is no
    longer durably owned by the card at the publish boundary."""
    _make_kb(base)
    progress, card = _card_progress()
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id="card1", soft_deleted=True)
    card.artifact_ids = [artifact.id]
    _save(base, progress)
    mock_provider("success")
    svc = KnowledgeCardPublicationService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            svc.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = svc.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


def test_publish_fails_closed_when_artifact_referenced_by_other_context(
    base, service, mock_provider
) -> None:
    """A live reference owned by a non-card context (session) does not satisfy
    the card-level ownership requirement — publish fails closed."""
    _make_kb(base)
    progress, card = _card_progress()
    media_store, artifact, _ = _artifact_bound_to_card(
        base, card_id="card1", owner_type=ReferenceOwnerType.SESSION
    )
    card.artifact_ids = [artifact.id]
    _save(base, progress)
    mock_provider("success")
    svc = KnowledgeCardPublicationService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )
    with pytest.raises(KnowledgeCardInputValidationError):
        _run(
            svc.publish(
                "b1",
                card_id="card1",
                user_id="owner",
                request_id="req1",
                expected_card_revision=1,
                target_kb_name="kb1",
            )
        )
    reloaded = svc.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.DRAFT
    assert not (base / "kb_write_operations.json").exists()


def test_publish_succeeds_with_live_card_artifact_reference(base, mock_provider) -> None:
    """An artifact durably bound to the publishing card by a live KNOWLEDGE_CARD
    reference is accepted at the publish boundary (real MediaStore APIs)."""
    _make_kb(base)
    progress, card = _card_progress()
    media_store, artifact, _ = _artifact_bound_to_card(base, card_id="card1")
    card.artifact_ids = [artifact.id]
    LearningStore(root=base).save(progress)
    mock_provider("success")
    svc = KnowledgeCardPublicationService(
        LearningStore(root=base), kb_base_dir=base, media_store=media_store
    )

    result = _run(
        svc.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert result["status"] == "published"
    reloaded = svc.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert card.artifact_ids == [artifact.id]
    # The live card reference survives publication (still live).
    assert (
        media_store.find_live_reference(
            artifact_id=artifact.id,
            user_id="owner",
            owner_type=ReferenceOwnerType.KNOWLEDGE_CARD,
            owner_id=card.id,
        )
        is not None
    )


# ── CAS retry correctness (review finding 9) ────────────────────────────────


def test_retry_survives_cas_conflict(base, service, mock_provider, monkeypatch) -> None:
    """A concurrent writer bumping the document version mid-begin forces the CAS
    retry loop to reload and re-apply; the durable record/projection stays
    consistent after the restart."""
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISH_FAILED)
    _attach_failed_publication(progress, card, request_id="req-old")
    _save(base, progress)
    mock_provider("success")

    original_save = service.save
    calls = {"n": 0}

    def _conflicting_save(save_progress):
        calls["n"] += 1
        if calls["n"] == 2:  # inside _begin_publication, before its CAS save
            # A concurrent writer bumps the persisted document version so the
            # in-flight CAS save is rejected and the loop reloads/re-applies.
            current = service.store.load(save_progress.book_id)
            service.store.save(current)
        return original_save(save_progress)

    monkeypatch.setattr(service, "save", _conflicting_save)

    result = _run(
        service.retry_publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req-retry",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert result["status"] == "published"
    reloaded = service.store.load("b1")
    card = _card_of(reloaded, "card1")
    assert card.status == KnowledgeCardStatus.PUBLISHED
    assert (
        service._latest_publication(reloaded, result["publication_key"]).status
        == PublicationStatus.PUBLISHED
    )


# ── append-only publication history (review finding 7) ──────────────────────


def test_publication_history_is_append_only(base, service, mock_provider) -> None:
    _make_kb(base)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISH_FAILED)
    _attach_failed_publication(progress, card, request_id="req-old")
    _save(base, progress)
    mock_provider("success")

    _run(
        service.retry_publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req-retry",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    reloaded = service.store.load("b1")
    revisions = [
        record
        for record in reloaded.knowledge_card_publication_records
        if record.publication_key == "kb3:owner|card1|1|kb1"
    ]
    # The original failure/request/timestamp is preserved, never overwritten.
    assert revisions[0].status == PublicationStatus.PUBLISH_FAILED
    assert revisions[0].request_id == "req-old"
    # The latest revision projects the current state with the retry request.
    assert revisions[-1].status == PublicationStatus.PUBLISHED
    assert revisions[-1].request_id == "req-retry"


# ── failure-of-failure paths (review finding 10) ────────────────────────────


def test_finalize_failure_preserves_recoverable_state(base, service, monkeypatch) -> None:
    """If the proof write fails, the card is never marked published and the
    operation is converged to a durable recoverable reconcile state."""
    _make_kb(base)
    _make_ready_publishing_card(base, op_id="op1")
    coordinator = KbWriteCoordinator(base_dir=base)
    op = coordinator.acquire("kb1", "card_publish", owner="writer-a")
    progress = service.store.load("b1")
    _card_of(progress, "card1").publication_operation_id = op.id
    service.store.save(progress)

    def _failing_save(_progress):
        raise KnowledgeCardStateError("proof write failed")

    monkeypatch.setattr(service, "save", _failing_save)

    with pytest.raises(KnowledgeCardStateError):
        service._finalize(
            "b1",
            "card1",
            status=KnowledgeCardStatus.PUBLISHED,
            coordinator=coordinator,
            kb_name="kb1",
            op_id=op.id,
            owner="writer-a",
            rel_path="learning_cards/card1-v1.md",
            document_sha="0" * 64,
            expected_revision=1,
            now=1000.0,
            error_code="",
            sanitized_error="",
            lease_check=lambda: None,
        )
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.PUBLISHING
    current = coordinator.current_operation("kb1")
    assert current.status == "reconcile_required"


def test_ambiguous_failure_recoverable_when_config_write_fails(
    base, service, manager, mock_provider, monkeypatch
) -> None:
    _make_kb(base)
    progress, _ = _card_progress()
    _save(base, progress)
    mock_provider("raise")

    def _explode(*args, **kwargs):
        raise RuntimeError("config write failed")

    monkeypatch.setattr(KnowledgeBaseManager, "mark_needs_reindex", _explode)

    result = _run(
        service.publish(
            "b1",
            card_id="card1",
            user_id="owner",
            request_id="req1",
            expected_card_revision=1,
            target_kb_name="kb1",
        )
    )
    assert result["status"] == "reconcile_required"
    reloaded = service.store.load("b1")
    assert _card_of(reloaded, "card1").status == KnowledgeCardStatus.RECONCILE_REQUIRED
    ledger = json.loads((base / "kb_write_operations.json").read_text(encoding="utf-8"))
    assert ledger["operations"]["kb1"]["status"] == "reconcile_required"
