"""API tests for KB-04 knowledge-card retraction endpoints (§7.11, §8.5).

Covers the retract / reconcile-retraction surface on the learning router:
success with exact quarantine + excluding-index proof, stable structured error
codes for ownership / not-found / stale-version / state / writable-KB /
unavailable, idempotent replay, and observational reconcile.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.mastery_path import router
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.learning.knowledge_cards.publish import (
    fixed_document_rel_path,
    publication_key,
    render_card_markdown,
)
from deeptutor.learning.knowledge_cards.retraction import fixed_quarantine_rel_path
from deeptutor.learning.knowledge_cards.store import content_hash
from deeptutor.learning.models import (
    KnowledgeCardPublicationRecord,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    PublicationStatus,
    RetractionStatus,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.knowledge_card_builders import stable_mastery_progress
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import admin_scope
from deeptutor.services.rag import service as rag_module


def _write_provider_index(kb_dir: Path) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )


def _make_kb(base: Path, name: str = "kb1", **overrides) -> None:
    kb_dir = base / name
    (kb_dir / "raw").mkdir(parents=True)
    _write_provider_index(kb_dir)
    entry = {"path": name, "rag_provider": "llamaindex", "status": "ready", **overrides}
    (base / "kb_config.json").write_text(
        json.dumps({"knowledge_bases": {name: entry}}), encoding="utf-8"
    )


def _published_progress(
    book_id: str = "b1",
    *,
    user_id: str = "local-admin",
    card_id: str = "card1",
    target_kb_name: str = "kb1",
):
    progress, attempt, assessment = stable_mastery_progress(book_id=book_id, kp_id="kp1")
    card = KnowledgeCardRecord(
        id=card_id,
        user_id=user_id,
        path_id=book_id,
        knowledge_point_id="kp1",
        stable_attempt_id=attempt.id,
        stable_assessment_id=assessment.id,
        stable_assessment_sequence=assessment.assessment_sequence,
        status=KnowledgeCardStatus.PUBLISHED,
        revision=1,
        title="The Feynman Technique",
        body="Explain it simply.",
        content_hash=content_hash("The Feynman Technique", "Explain it simply."),
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
    return progress, card, document, document_sha, rel_path


def _setup_published_kb(base: Path) -> None:
    progress, card, document, document_sha, rel_path = _published_progress()
    LearningStore(root=base).save(progress)
    raw_file = base / "kb1" / "raw" / rel_path
    raw_file.parent.mkdir(parents=True, exist_ok=True)
    raw_file.write_text(document, encoding="utf-8")
    (base / "kb1" / "metadata.json").write_text(
        json.dumps({"file_hashes": {rel_path: document_sha}}), encoding="utf-8"
    )
    other = base / "kb1" / "raw" / "notes" / "intro.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("# Intro\n\nOrdinary notes.", encoding="utf-8")


def _mock_reindex(monkeypatch, outcome: str = "success") -> None:
    async def _init(self, kb_name, file_paths, **kwargs):
        if outcome == "success":
            return True
        if outcome == "no_docs":
            return False
        raise RuntimeError("provider exploded during reindex")

    monkeypatch.setattr(rag_module.RAGService, "initialize", _init)


@pytest.fixture
def app(tmp_path, monkeypatch):
    def _make_store(root=None):
        return LearningStore(root=tmp_path)

    monkeypatch.setattr("deeptutor.api.routers.mastery_path.LearningStore", _make_store)
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.current_kb_base_dir",
        lambda: Path(tmp_path),
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.current_kb_manager",
        lambda: KnowledgeBaseManager(base_dir=str(tmp_path)),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/learning")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def as_user():
    tokens = []

    def _set(user_id: str):
        token = set_current_user(
            CurrentUser(id=user_id, username=user_id, role="admin", scope=admin_scope())
        )
        tokens.append(token)
        return token

    yield _set
    for token in reversed(tokens):
        reset_current_user(token)


# ── retract endpoint ───────────────────────────────────────────────────────


def test_retract_endpoint_success(client, tmp_path, monkeypatch) -> None:
    _make_kb(tmp_path)
    _setup_published_kb(tmp_path)
    _mock_reindex(monkeypatch, "success")

    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "retracted"
    assert data["retracted_at"] is not None
    assert data["quarantine_rel_path"].startswith("quarantine/learning_cards/")

    # The exact raw file is gone from raw/. The quarantine copy was the only
    # recoverable bytes during the retraction and is deleted only after the
    # excluding index is confirmed and the card is durably retracted (KB-04 P0
    # correction 5), so none remains after a successful retraction.
    assert not (tmp_path / "kb1" / "raw" / "learning_cards" / "card1-v1.md").exists()
    quarantine_file = tmp_path / "kb1" / data["quarantine_rel_path"]
    assert not quarantine_file.exists()

    # Same request replays (idempotent).
    replay = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 1, "request_id": "req1"},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "retracted"
    assert replay.json()["replayed"] is True


def test_retract_ownership_denied(client, tmp_path, as_user) -> None:
    _make_kb(tmp_path)
    _setup_published_kb(tmp_path)
    as_user("intruder")
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "card_ownership"


def test_retract_not_found(client, tmp_path) -> None:
    _make_kb(tmp_path)
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/missing/retract",
        json={"expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "card_not_found"


def test_retract_stale_revision_conflict(client, tmp_path) -> None:
    _make_kb(tmp_path)
    _setup_published_kb(tmp_path)
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 9, "request_id": "req1"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "card_version_conflict"


def test_retract_non_published_state_conflict(client, tmp_path) -> None:
    _make_kb(tmp_path)
    progress, card, document, document_sha, rel_path = _published_progress()
    card.status = KnowledgeCardStatus.DRAFT
    LearningStore(root=tmp_path).save(progress)
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "card_state"


def test_retract_missing_request_id_is_422(client, tmp_path) -> None:
    _make_kb(tmp_path)
    _setup_published_kb(tmp_path)
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 1},
    )
    assert resp.status_code == 422


def test_retract_kb_not_writable_code(client, tmp_path) -> None:
    _make_kb(tmp_path)
    progress, card, document, document_sha, rel_path = _published_progress()
    card.target_kb_name = "missing"
    LearningStore(root=tmp_path).save(progress)
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "kb_not_writable"


def test_retract_busy_unavailable_code(client, tmp_path) -> None:
    _make_kb(tmp_path)
    _setup_published_kb(tmp_path)
    coordinator = __import__(
        "deeptutor.knowledge.write_coordinator", fromlist=["KbWriteCoordinator"]
    ).KbWriteCoordinator(base_dir=tmp_path)
    coordinator.acquire("kb1", "upload", owner="other-writer")
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retract",
        json={"expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "retraction_unavailable"


# ── reconcile-retraction endpoint ──────────────────────────────────────────


def test_reconcile_retraction_endpoint_noop_on_published_without_intent(client, tmp_path) -> None:
    _make_kb(tmp_path)
    _setup_published_kb(tmp_path)
    resp = client.post("/api/v1/learning/progress/b1/knowledge-cards/card1/reconcile-retraction")
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"
    assert resp.json()["replayed"] is False


def test_reconcile_retraction_endpoint_converges_retracted(client, tmp_path) -> None:
    _make_kb(tmp_path)
    progress, card, document, document_sha, rel_path = _published_progress()
    card.status = KnowledgeCardStatus.RETRACTING
    card.retraction_operation_id = "op1"
    card.retraction_request_id = "req1"
    card.quarantine_rel_path = fixed_quarantine_rel_path(card.id, card.revision, document_sha)
    progress.knowledge_card_retraction_records.append(
        __import__(
            "deeptutor.learning.models", fromlist=["KnowledgeCardRetractionRecord"]
        ).KnowledgeCardRetractionRecord(
            id="rec1",
            card_id=card.id,
            card_revision=card.revision,
            user_id="local-admin",
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
    LearningStore(root=tmp_path).save(progress)
    # Full exclusion evidence on disk: raw absent, quarantine present, no index
    # evidence for the card, KB ready.
    quarantine_file = tmp_path / "kb1" / card.quarantine_rel_path
    quarantine_file.parent.mkdir(parents=True, exist_ok=True)
    quarantine_file.write_text(document, encoding="utf-8")
    other = tmp_path / "kb1" / "raw" / "notes" / "intro.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("# Intro", encoding="utf-8")
    (tmp_path / "kb1" / "metadata.json").write_text(json.dumps({}), encoding="utf-8")

    resp = client.post("/api/v1/learning/progress/b1/knowledge-cards/card1/reconcile-retraction")
    assert resp.status_code == 200
    assert resp.json()["status"] == "retracted"


def test_reconcile_retraction_ownership_denied(client, tmp_path, as_user) -> None:
    _make_kb(tmp_path)
    _setup_published_kb(tmp_path)
    as_user("intruder")
    resp = client.post("/api/v1/learning/progress/b1/knowledge-cards/card1/reconcile-retraction")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "card_ownership"
