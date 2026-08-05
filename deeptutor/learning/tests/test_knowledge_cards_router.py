"""KB-02 knowledge-card router adapter tests (spec §8.5, §14).

Covers the narrowly-scoped adapters UI-02 adds in ``mastery_path``:
owner-scoped card listing, server-derived draft create/resume, versioned
edit/discard, explicit generation retry, and the stable error mapping.
Every adapter reuses the already-reviewed ``KnowledgeCardDraftService``;
these tests exercise the HTTP boundary, not the domain invariants (which the
service tests cover). Deterministic — no real provider, KB, or media volume.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import mastery_path
from deeptutor.api.routers.mastery_path import router
from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.knowledge_card_builders import stable_mastery_progress
from deeptutor.services.media.store import MediaStore


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    # Patching the class __init__ makes every LearningStore() — including the
    # fresh stores the draft/publication/retraction services build per request —
    # land in tmp_path, exactly like the LRN-03 router tests.
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))

    # The draft-service factory builds a fresh MediaStore per request; route it
    # into the test volume so attach/detach/discard never touch real user media.
    def _draft_service():
        return KnowledgeCardDraftService(
            LearningStore(), media_store=MediaStore(root=tmp_path / "media")
        )

    monkeypatch.setattr(mastery_path, "get_draft_service", _draft_service)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/learning")
    return app


def _store_init_factory(root: Path):
    def _init(self, root_arg=None):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _seed_stable_mastery(book_id: str = "path1") -> None:
    progress, _attempt, _assessment = stable_mastery_progress(book_id=book_id)
    store = LearningStore()
    store.save(progress)


def _ensure(client: TestClient, book_id: str = "path1", kp_id: str = "kp1") -> dict:
    resp = client.post(
        f"/api/v1/learning/progress/{book_id}/knowledge-points/{kp_id}/knowledge-card"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "draft"
    return body


# ── list: owner scoping ───────────────────────────────────────────────────


def test_list_knowledge_cards_is_owner_scoped(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]

    # Inject another user's card directly; it must never surface on a list the
    # current actor (local-admin) reads (§6.6, §14).
    progress = LearningStore().load("path1")
    from deeptutor.learning.models import KnowledgeCardRecord, KnowledgeCardStatus

    progress.knowledge_cards.append(
        KnowledgeCardRecord(
            id="other-user-card",
            user_id="another-user",
            path_id="path1",
            knowledge_point_id="kp1",
            stable_assessment_id=progress.knowledge_cards[0].stable_assessment_id,
            stable_assessment_sequence=1,
            status=KnowledgeCardStatus.DRAFT,
            revision=1,
        )
    )
    LearningStore().save(progress)

    resp = client.get("/api/v1/learning/progress/path1/knowledge-cards")
    assert resp.status_code == 200
    cards = resp.json()["cards"]
    ids = [c["card_id"] for c in cards]
    assert card_id in ids
    assert "other-user-card" not in ids
    # Safe read projection: never exposes owner ids, source text or media paths.
    for card in cards:
        assert "user_id" not in card
        assert "body" in card
        assert "sources" in card
        assert "model_identity" in card


def test_list_knowledge_cards_includes_legacy_no_owner_cards(client: TestClient):
    _seed_stable_mastery()
    progress = LearningStore().load("path1")
    from deeptutor.learning.models import KnowledgeCardRecord, KnowledgeCardStatus

    progress.knowledge_cards.append(
        KnowledgeCardRecord(
            id="legacy-card",
            user_id="",
            path_id="path1",
            knowledge_point_id="kp1",
            stable_assessment_id="ra1",
            stable_assessment_sequence=1,
            status=KnowledgeCardStatus.DRAFT,
            revision=1,
        )
    )
    LearningStore().save(progress)

    resp = client.get("/api/v1/learning/progress/path1/knowledge-cards")
    assert resp.status_code == 200
    assert "legacy-card" in [c["card_id"] for c in resp.json()["cards"]]


# ── create / resume ───────────────────────────────────────────────────────


def test_ensure_creates_draft_and_is_idempotent(client: TestClient):
    _seed_stable_mastery()
    first = _ensure(client)
    assert first["created"] is True
    assert first["revision"] == 1
    assert first["latest_generation_attempt"]["status"] == "queued"

    # Same knowledge point resumes the occupying draft without a second shell.
    second = _ensure(client)
    assert second["card_id"] == first["card_id"]
    assert second["created"] is False


def test_ensure_missing_progress_is_a_404(client: TestClient):
    # A fresh progress with no assessment → the path document is missing → 404,
    # never an arbitrary draft.
    assert LearningStore().load("path1") is None
    resp = client.post("/api/v1/learning/progress/path1/knowledge-points/kp1/knowledge-card")
    assert resp.status_code == 404


# ── edit: version/idempotency + user-edit lock ────────────────────────────


def test_edit_bumps_revision_and_locks_by_user_edit(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    rev = body["revision"]

    resp = client.patch(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}",
        json={
            "expected_card_revision": rev,
            "request_id": "edit-1",
            "title": "为什么 TCP 需要三次握手",
            "body": "确认双向可达并同步初始序列号。",
        },
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["revision"] == rev + 1
    assert updated["generation_locked_by_user_edit"] is True
    assert updated["title"] == "为什么 TCP 需要三次握手"
    assert updated["sources"][0]["title"] == "Source 1"


def test_edit_stale_revision_is_a_409(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    stale = body["revision"]

    # One successful edit advances the revision…
    client.patch(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}",
        json={"expected_card_revision": stale, "request_id": "edit-1", "title": "A"},
    )
    # …so replaying the old revision is a recoverable conflict, never an overwrite.
    resp = client.patch(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}",
        json={"expected_card_revision": stale, "request_id": "edit-2", "body": "B"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "card_version_conflict"


def test_edit_requires_revision_and_idempotency_key(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    resp = client.patch(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}",
        json={"expected_card_revision": body["revision"]},  # no request_id
    )
    assert resp.status_code == 422


def test_edit_other_owner_is_a_403(client: TestClient):
    _seed_stable_mastery()
    # Seed a draft owned by another user.
    progress = LearningStore().load("path1")
    from deeptutor.learning.models import KnowledgeCardRecord, KnowledgeCardStatus

    progress.knowledge_cards.append(
        KnowledgeCardRecord(
            id="borrowed-card",
            user_id="someone-else",
            path_id="path1",
            knowledge_point_id="kp1",
            stable_assessment_id="ra1",
            stable_assessment_sequence=1,
            status=KnowledgeCardStatus.DRAFT,
            revision=1,
        )
    )
    LearningStore().save(progress)

    resp = client.patch(
        "/api/v1/learning/progress/path1/knowledge-cards/borrowed-card",
        json={"expected_card_revision": 1, "request_id": "edit-x", "title": "T"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "card_ownership"


def test_edit_published_card_is_a_409(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    progress = LearningStore().load("path1")
    card = next(c for c in progress.knowledge_cards if c.id == card_id)
    from deeptutor.learning.models import KnowledgeCardStatus

    card.status = KnowledgeCardStatus.PUBLISHING
    card.target_kb_name = "kb"
    LearningStore().save(progress)

    resp = client.patch(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}",
        json={"expected_card_revision": 1, "request_id": "edit-y", "body": "nope"},
    )
    assert resp.status_code == 409


# ── retry-generation ──────────────────────────────────────────────────────


def test_retry_generation_locked_by_user_edit_is_a_409(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    rev = body["revision"]
    attempt_id = body["latest_generation_attempt"]["id"]

    client.patch(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}",
        json={"expected_card_revision": rev, "request_id": "edit-1", "title": "手工内容"},
    )
    # The user edit bumped the revision (1 → 2) and locked generation, so an
    # explicit retry on the locked card is a recoverable conflict.
    resp = client.post(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}/retry-generation",
        json={
            "expected_card_revision": rev + 1,
            "request_id": "retry-1",
            "latest_generation_attempt_id": attempt_id,
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "generation_locked_by_user_edit"


def test_retry_generation_stale_attempt_is_a_409(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    # A stale latest_generation_attempt_id is a recoverable conflict (§8.5).
    resp = client.post(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}/retry-generation",
        json={
            "expected_card_revision": body["revision"],
            "request_id": "retry-2",
            "latest_generation_attempt_id": "not-the-latest-attempt",
        },
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "card_version_conflict"


# ── discard ───────────────────────────────────────────────────────────────


def test_discard_unpublished_draft(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    resp = client.post(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}/discard",
        json={"expected_card_revision": body["revision"], "request_id": "discard-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "discarded"
    # Discarding never mutates assessment/evidence or mastery.
    progress = LearningStore().load("path1")
    assert len(progress.rubric_assessments) == 1
    assert progress.projections["kp1"].mastery_state.value == "stable_mastery"


def test_discard_requires_revision_and_key(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    resp = client.post(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}/discard",
        json={},  # missing both required fields
    )
    assert resp.status_code == 422


def test_discard_published_card_is_a_409(client: TestClient):
    _seed_stable_mastery()
    body = _ensure(client)
    card_id = body["card_id"]
    progress = LearningStore().load("path1")
    card = next(c for c in progress.knowledge_cards if c.id == card_id)
    from deeptutor.learning.models import KnowledgeCardStatus

    card.status = KnowledgeCardStatus.PUBLISHED
    card.target_kb_name = "kb"
    LearningStore().save(progress)

    resp = client.post(
        f"/api/v1/learning/progress/path1/knowledge-cards/{card_id}/discard",
        json={"expected_card_revision": 1, "request_id": "discard-2"},
    )
    assert resp.status_code == 409


# ── not found / ownership error mapping ──────────────────────────────────


def test_unknown_card_is_a_404(client: TestClient):
    _seed_stable_mastery()
    resp = client.get("/api/v1/learning/progress/path1/knowledge-cards/nope")
    assert resp.status_code == 404
