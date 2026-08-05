"""API tests for KB-03 knowledge-card publication endpoints (§7.9.2).

Covers the publish / retry-publish / reconcile-publication surface on the
learning router, the read projection, stable structured error codes, and
ownership/path isolation.
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
from deeptutor.learning.knowledge_cards.store import content_hash
from deeptutor.learning.models import (
    KnowledgeCardPublicationRecord,
    KnowledgeCardRecord,
    KnowledgeCardStatus,
    PublicationStatus,
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


def _card_progress(
    book_id: str = "b1",
    *,
    user_id: str = "local-admin",
    status: KnowledgeCardStatus = KnowledgeCardStatus.DRAFT,
    **overrides,
):
    progress, attempt, assessment = stable_mastery_progress(book_id=book_id, kp_id="kp1")
    card = KnowledgeCardRecord(
        id="card1",
        user_id=user_id,
        path_id=book_id,
        knowledge_point_id="kp1",
        stable_attempt_id=attempt.id,
        stable_assessment_id=assessment.id,
        stable_assessment_sequence=assessment.assessment_sequence,
        status=status,
        revision=1,
        title="The Feynman Technique",
        body="Explain it simply.",
        content_hash=content_hash("The Feynman Technique", "Explain it simply."),
        source_snapshot_ids=["s1"],
        evidence_ids=["ev1"],
        **overrides,
    )
    progress.knowledge_cards.append(card)
    return progress, card


def _save(base: Path, progress) -> None:
    LearningStore(root=base).save(progress)


def _mock_provider(monkeypatch, outcome: str) -> None:
    async def _add(self, kb_name, file_paths, **kwargs):
        if outcome == "success":
            return True
        if outcome == "no_mutation":
            return False
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(rag_module.RAGService, "add_documents", _add)


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


# ── publish endpoint ───────────────────────────────────────────────────────


def test_publish_endpoint_success(client, tmp_path, monkeypatch) -> None:
    _make_kb(tmp_path)
    _save(tmp_path, _card_progress()[0])
    _mock_provider(monkeypatch, "success")

    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"
    assert data["document_rel_path"] == "learning_cards/card1-v1.md"
    assert data["confirmed_at"] is not None
    assert data["published_at"] is not None

    raw_file = tmp_path / "kb1" / "raw" / "learning_cards" / "card1-v1.md"
    assert raw_file.is_file()


def test_read_publication_projection(client, tmp_path, monkeypatch) -> None:
    _make_kb(tmp_path)
    _save(tmp_path, _card_progress()[0])
    _mock_provider(monkeypatch, "success")
    client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    resp = client.get("/api/v1/learning/progress/b1/knowledge-cards/card1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"
    assert len(data["publication_records"]) == 1


def test_publish_ownership_denied(client, tmp_path, as_user) -> None:
    _make_kb(tmp_path)
    _save(tmp_path, _card_progress(user_id="local-admin")[0])
    as_user("intruder")
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "card_ownership"


def test_publish_not_found(client, tmp_path) -> None:
    _make_kb(tmp_path)
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/missing/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "card_not_found"


def test_publish_stale_revision_conflict(client, tmp_path, monkeypatch) -> None:
    _make_kb(tmp_path)
    _save(tmp_path, _card_progress()[0])
    _mock_provider(monkeypatch, "success")
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 9, "request_id": "req1"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "card_version_conflict"


def test_publish_kb_not_writable_code(client, tmp_path) -> None:
    # No kb_config entry → kb_not_writable.
    _save(tmp_path, _card_progress()[0])
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "missing", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "kb_not_writable"


def test_publish_missing_request_id_is_422(client, tmp_path) -> None:
    _make_kb(tmp_path)
    _save(tmp_path, _card_progress()[0])
    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1},
    )
    assert resp.status_code == 422


def test_publish_invalid_book_id_is_400(client, tmp_path) -> None:
    resp = client.post(
        "/api/v1/learning/progress/bad:book/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert resp.status_code == 400


# ── retry-publish endpoint ─────────────────────────────────────────────────


def test_retry_publish_endpoint_reuses_original(client, tmp_path, monkeypatch) -> None:
    _make_kb(tmp_path)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISH_FAILED)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("local-admin", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    progress.knowledge_card_publication_records.append(
        KnowledgeCardPublicationRecord(
            id="rec1",
            card_id=card.id,
            publication_key=key,
            card_revision=card.revision,
            target_kb_name="kb1",
            document_rel_path=rel_path,
            document_sha256=document_sha,
            status=PublicationStatus.PUBLISH_FAILED,
        )
    )
    _save(tmp_path, progress)
    _mock_provider(monkeypatch, "success")

    resp = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/retry-publish",
        json={"expected_card_revision": 1, "request_id": "req-retry"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "published"
    assert data["document_sha256"] == document_sha

    reloaded = LearningStore(root=tmp_path).load("b1")
    # One logical publication, reused not duplicated; append-only revisions.
    from deeptutor.learning.knowledge_cards.publish import (
        KnowledgeCardPublicationService,
    )

    svc = KnowledgeCardPublicationService(LearningStore(root=tmp_path))
    assert len(svc._records_for_card(reloaded, "card1")) == 1
    assert svc._latest_publication(reloaded, key).status == PublicationStatus.PUBLISHED


# ── reconcile-publication endpoint ─────────────────────────────────────────


def test_reconcile_publication_endpoint_converges(client, tmp_path) -> None:
    _make_kb(tmp_path)
    progress, card = _card_progress(status=KnowledgeCardStatus.PUBLISHING)
    document = render_card_markdown(card, progress)
    document_sha = hashlib.sha256(document.encode("utf-8")).hexdigest()
    rel_path = fixed_document_rel_path(card.id, card.revision)
    key = publication_key("local-admin", card.id, card.revision, "kb1")
    card.target_kb_name = "kb1"
    card.document_rel_path = rel_path
    card.document_sha256 = document_sha
    card.publication_key = key
    card.publication_operation_id = "op1"
    _save(tmp_path, progress)

    resp = client.post("/api/v1/learning/progress/b1/knowledge-cards/card1/reconcile-publication")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "publish_failed"
    assert data["error_code"] == "interrupted"


def test_reconcile_publication_ownership_denied(client, tmp_path, as_user) -> None:
    _make_kb(tmp_path)
    _save(tmp_path, _card_progress()[0])
    as_user("intruder")
    resp = client.post("/api/v1/learning/progress/b1/knowledge-cards/card1/reconcile-publication")
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "card_ownership"


# ── review regressions: reconcile state guard + post-publish target mismatch ─


def test_reconcile_draft_endpoint_no_ops_and_still_publishable(
    client, tmp_path, monkeypatch
) -> None:
    _make_kb(tmp_path)
    _save(tmp_path, _card_progress()[0])
    resp = client.post("/api/v1/learning/progress/b1/knowledge-cards/card1/reconcile-publication")
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"
    # A fresh draft misuse stays publishable afterward.
    _mock_provider(monkeypatch, "success")
    pub = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"


def test_publish_different_target_conflict_endpoint(client, tmp_path, monkeypatch) -> None:
    _make_kb(tmp_path)  # kb1
    kb2_dir = tmp_path / "kb2"
    (kb2_dir / "raw").mkdir(parents=True)
    _write_provider_index(kb2_dir)
    config = json.loads((tmp_path / "kb_config.json").read_text(encoding="utf-8"))
    config["knowledge_bases"]["kb2"] = {
        "path": "kb2",
        "rag_provider": "llamaindex",
        "status": "ready",
        "needs_reindex": False,
    }
    (tmp_path / "kb_config.json").write_text(json.dumps(config), encoding="utf-8")
    _save(tmp_path, _card_progress()[0])
    _mock_provider(monkeypatch, "success")

    first = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "published"

    # Same target replays.
    replay = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb1", "expected_card_revision": 1, "request_id": "req1"},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True

    # A different target is a stable conflict, not an idempotent success.
    conflict = client.post(
        "/api/v1/learning/progress/b1/knowledge-cards/card1/publish",
        json={"target_kb_name": "kb2", "expected_card_revision": 1, "request_id": "req2"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "publication_conflict"
