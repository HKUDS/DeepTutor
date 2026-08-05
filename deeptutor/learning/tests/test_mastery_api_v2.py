"""LRN-03 mastery API contract tests (spec §8.2, §8.3, §17.2).

These cover the read APIs (map / attempt detail / reviews), versioned map
edit/confirm, conflict resolve/reopen, challenge, and resume — including the
deterministic negative contract (unauthorized conflict mutation, conflict
snapshot injection, invalidated resume).
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.mastery_path import router
from deeptutor.learning.cycles import FeynmanCycleService
from deeptutor.learning.models import (
    AttemptStatus,
    ConflictStatus,
    KnowledgeMapVersion,
    SourceConflict,
    SourceSnapshot,
)
from deeptutor.learning.storage import LearningStore, invalidate_attempts


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Patching the class __init__ makes every LearningStore() — including the
    # fresh stores the cycle service builds per request — land in tmp_path.
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    # The production evaluator resolver reads the model catalog; give the app
    # the fixture catalog so attempt-creation boundaries resolve an evaluator.
    import deeptutor.services.config as config_module
    import deeptutor.services.config.model_catalog as config_model_catalog
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from tests.services.model_selection import _fixtures as fx

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    monkeypatch.setattr(service, "load", lambda: fx.catalog())
    monkeypatch.setattr(config_module, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(config_model_catalog, "get_model_catalog_service", lambda: service)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/learning")
    return app


def _store_init_factory(root):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


@pytest.fixture
def client(app):
    return TestClient(app)


def _init_path(client, book_id: str = "path1") -> None:
    resp = client.post(
        f"/api/v1/learning/progress/{book_id}/init-modules",
        json={
            "modules": [
                {
                    "id": "m1",
                    "name": "M1",
                    "order": 0,
                    "knowledge_points": [
                        {"id": "kp1", "name": "KP1", "type": "concept", "module_id": "m1"}
                    ],
                }
            ]
        },
    )
    assert resp.status_code == 200


def _register_map_and_sources(book_id: str) -> None:
    service = FeynmanCycleService(LearningStore())
    progress = service.load(book_id)
    progress.source_snapshots.extend(
        [
            SourceSnapshot(id="s1", citation_anchors=["p.3"]),
            SourceSnapshot(id="s2", citation_anchors=["fig.2"]),
        ]
    )
    progress.map_versions.append(
        KnowledgeMapVersion(
            id=f"{book_id}:map:1",
            path_id=book_id,
            version=1,
            source_snapshot_ids=["s1", "s2"],
        )
    )
    service.save(progress)


def _add_conflict(book_id: str) -> None:
    service = FeynmanCycleService(LearningStore())
    progress = service.load(book_id)
    progress.source_conflicts.append(
        SourceConflict(
            id="c1",
            path_id=book_id,
            knowledge_point_ids=["kp1"],
            claim="disagreement",
            source_snapshot_ids=["s1", "s2"],
            citation_anchors=["p.3", "fig.2"],
            version=1,
            status=ConflictStatus.OPEN,
        )
    )
    service.save(progress)


def _start_attempt(book_id: str) -> str:
    service = FeynmanCycleService(LearningStore())
    progress = service.load(book_id)
    attempt = service.start_cycle(
        progress,
        knowledge_point_id="kp1",
        cycle_type="initial",
        session_id="sess",
        turn_id="turn",
    )
    service.save(progress)
    return attempt.id


def _identity(**overrides) -> dict[str, str]:
    identity = {
        "path_id": "path1",
        "session_id": "sess",
        "turn_id": "turn",
        "message_id": "msg",
        "user_id": "owner",
    }
    identity.update(overrides)
    return identity


def _complete_chain(service, progress, attempt_id: str) -> list[str]:
    """Record a full valid evidence chain and return its evidence ids."""
    from deeptutor.learning.models import EvidenceKind

    ids: list[str] = []
    r = service.record_evidence(
        progress,
        attempt_id=attempt_id,
        kind="explanation",
        event_id="e-expl",
        content="My explanation",
        identity=_identity(),
        expected_attempt_version=progress.aggregate_versions.attempt,
    )
    ids.append(r["evidence_id"])
    for i in (1, 2):
        q = service.record_evidence(
            progress,
            attempt_id=attempt_id,
            kind="probe_question",
            event_id=f"e-q{i}",
            content=f"Q{i}?",
            identity=_identity(),
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        a = service.record_evidence(
            progress,
            attempt_id=attempt_id,
            kind="probe_answer",
            event_id=f"e-a{i}",
            content=f"A{i}",
            question_evidence_id=q["evidence_id"],
            identity=_identity(),
            expected_attempt_version=progress.aggregate_versions.attempt,
        )
        ids.extend([q["evidence_id"], a["evidence_id"]])
    qt = service.record_evidence(
        progress,
        attempt_id=attempt_id,
        kind="transfer_question",
        event_id="e-qt",
        content="T?",
        identity=_identity(),
        expected_attempt_version=progress.aggregate_versions.attempt,
    )
    at = service.record_evidence(
        progress,
        attempt_id=attempt_id,
        kind="transfer_answer",
        event_id="e-at",
        content="TA",
        question_evidence_id=qt["evidence_id"],
        identity=_identity(),
        expected_attempt_version=progress.aggregate_versions.attempt,
    )
    ids.extend([qt["evidence_id"], at["evidence_id"]])
    return ids


def _current_attempt_version(book_id: str) -> int:
    service = FeynmanCycleService(LearningStore())
    progress = service.load(book_id)
    return progress.aggregate_versions.attempt


def _finalize_attempt(book_id: str, attempt_id: str) -> None:
    from deeptutor.learning.models import RubricScores, SourceCitation

    service = FeynmanCycleService(LearningStore())
    progress = service.load(book_id)
    evidence_ids = _complete_chain(service, progress, attempt_id)
    service.finalize(
        progress,
        attempt_id=attempt_id,
        rubric=RubricScores(correctness=2, completeness=1, causal_clarity=1, transfer=2),
        critical_errors=[],
        strengths=[],
        gap_candidates=[],
        evidence_ids=evidence_ids,
        source_citations=[SourceCitation(source_snapshot_id="s1", anchor="p.3")],
        event_id=f"fin-{attempt_id}-1",
        expected_attempt_version=progress.aggregate_versions.attempt,
    )
    service.save(progress)


def _complete_evaluator_snapshot_dict() -> dict:
    """A complete, server-canonical challenge evaluator snapshot for p1."""
    from deeptutor.services.model_selection.fingerprint import (
        base_url_fingerprint,
        profile_revision,
    )
    from tests.services.model_selection import _fixtures as fx

    service = fx.catalog()["services"]["llm"]
    profile = next(p for p in service["profiles"] if p["id"] == "p1")
    return {
        "profile_id": "p1",
        "profile_name": "OpenAI Evaluator",
        "profile_revision": profile_revision(profile),
        "requested_provider": "openai",
        "requested_api_protocol": "openai_responses",
        "requested_model": "gpt-4o-mini",
        "resolved_provider": "openai",
        "resolved_api_protocol": "openai_responses",
        "resolved_model": "gpt-4o-mini",
        "auto_resolution_reason": "",
        "base_url_fingerprint": base_url_fingerprint("https://api.example.com/v1"),
        "strict_protocol": True,
        "prompt_version": "feynman-eval-v1",
        "rubric_version": "feynman-rubric-v1",
        "created_at": 2000.0,
    }


# ── read APIs ─────────────────────────────────────────────────────────────


class TestReadAPIs:
    def test_map_read_has_projections_and_evidence_summary(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _start_attempt("path1")
        resp = client.get("/api/v1/learning/progress/path1/map")
        assert resp.status_code == 200
        data = resp.json()
        assert data["map_version"] == 1
        assert data["projections"]["kp1"]["mastery_state"] == "in_progress"
        assert data["active_attempts"]["kp1"]["attempt_id"]
        assert data["evidence_summary"]["kp1"]["count"] == 0

    def test_attempt_detail(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        resp = client.get(f"/api/v1/learning/progress/path1/attempts/{attempt_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["attempt"]["id"] == attempt_id
        assert data["evidence"] == []
        assert data["assessments"] == []

    def test_reviews_empty(self, client):
        _init_path(client)
        resp = client.get("/api/v1/learning/progress/path1/reviews")
        assert resp.status_code == 200
        assert resp.json()["reviews"] == []


# ── map edit / confirm ────────────────────────────────────────────────────


class TestMapEditAPI:
    def test_edit_creates_new_version(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        resp = client.patch(
            "/api/v1/learning/progress/path1/map",
            json={
                "nodes": ["kp1"],
                "edges": [],
                "priorities": {},
                "expected_map_version": 1,
                "request_id": "edit-api-1",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["map_version"] == 2
        # The incompatible active attempt was atomically invalidated.
        detail = client.get(f"/api/v1/learning/progress/path1/attempts/{attempt_id}").json()
        assert detail["attempt"]["status"] == "invalidated"

    def test_edit_stale_version_conflict(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        resp = client.patch(
            "/api/v1/learning/progress/path1/map",
            json={
                "nodes": [],
                "edges": [],
                "priorities": {},
                "expected_map_version": 9,
                "request_id": "edit-api-stale",
            },
        )
        assert resp.status_code == 409

    def test_confirm_idempotent(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        first = client.post(
            "/api/v1/learning/progress/path1/map/confirm",
            json={"expected_map_version": 1, "request_id": "r1"},
        )
        second = client.post(
            "/api/v1/learning/progress/path1/map/confirm",
            json={"expected_map_version": 1, "request_id": "r1"},
        )
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["replayed"] is True
        assert second.json()["map_version"] == first.json()["map_version"]

    def test_edit_replay_after_restart_returns_full_result(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        body = {
            "nodes": ["kp1", "kp2"],
            "edges": [{"from": "kp1", "to": "kp2"}],
            "priorities": {"kp2": 1},
            "expected_map_version": 1,
            "request_id": "edit-1",
        }
        first = client.patch("/api/v1/learning/progress/path1/map", json=body)
        assert first.status_code == 200
        # A fresh store instance (same on-disk progress) replays the full result.
        second = client.patch("/api/v1/learning/progress/path1/map", json=body)
        assert second.status_code == 200
        data = second.json()
        assert data["replayed"] is True
        assert data["map_version"] == first.json()["map_version"] == 2
        assert data["nodes"] == first.json()["nodes"]
        assert data["map_version_id"] == first.json()["map_version_id"]

    def test_edit_same_key_different_payload_conflicts(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        base = {
            "nodes": ["kp1"],
            "edges": [],
            "priorities": {},
            "expected_map_version": 1,
            "request_id": "edit-2",
        }
        resp = client.patch("/api/v1/learning/progress/path1/map", json=base)
        assert resp.status_code == 200
        resp = client.patch(
            "/api/v1/learning/progress/path1/map",
            json={**base, "nodes": ["kp2"]},
        )
        assert resp.status_code == 409
        assert "reused with a different payload" in resp.json()["detail"]

    def test_confirm_source_change_appends_version(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        resp = client.post(
            "/api/v1/learning/progress/path1/map/confirm",
            json={
                "expected_map_version": 1,
                "source_snapshot_ids": ["s1"],
                "request_id": "confirm-src",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["map_version"] == 2
        assert resp.json()["invalidated_attempt_ids"] == [attempt_id]
        # Prior version preserved on disk.
        detail = client.get("/api/v1/learning/progress/path1/map").json()
        assert detail["map_versions"][0]["source_snapshot_ids"] == ["s1", "s2"]
        assert detail["map_versions"][1]["source_snapshot_ids"] == ["s1"]


# ── conflict resolve / reopen ─────────────────────────────────────────────


class TestConflictAPI:
    def test_resolve_success(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _add_conflict("path1")
        attempt_id = _start_attempt("path1")
        resp = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/resolve",
            json={
                "accepted_snapshot_id": "s1",
                "resolution_note": "s1 wins",
                "request_id": "res-api-1",
                "expected_conflict_version": 1,
                "expected_map_version": 1,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "resolved"
        detail = client.get(f"/api/v1/learning/progress/path1/attempts/{attempt_id}").json()
        assert detail["attempt"]["status"] == "invalidated"

    def test_resolve_snapshot_not_listed_rejected(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _add_conflict("path1")
        resp = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/resolve",
            json={
                "accepted_snapshot_id": "s99",
                "resolution_note": "bad",
                "request_id": "res-api-notlisted",
                "expected_conflict_version": 1,
                "expected_map_version": 1,
            },
        )
        assert resp.status_code == 422

    def test_resolve_requires_note(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _add_conflict("path1")
        resp = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/resolve",
            json={
                "accepted_snapshot_id": "s1",
                "resolution_note": "  ",
                "request_id": "res-api-note",
                "expected_conflict_version": 1,
                "expected_map_version": 1,
            },
        )
        assert resp.status_code == 422

    def test_unauthorized_resolve_forbidden(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _add_conflict("path1")
        # First, the default actor claims the path by resolving it.
        first = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/resolve",
            json={
                "accepted_snapshot_id": "s1",
                "resolution_note": "owner resolves",
                "request_id": "res-api-owner",
                "expected_conflict_version": 1,
                "expected_map_version": 1,
            },
        )
        assert first.status_code == 200
        # Reopen the conflict so there is something to mutate, then try as a
        # different user. The current revision is now v2 (RESOLVED) and the
        # map is v2.
        reopened = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/reopen",
            json={
                "request_id": "reopen-api-owner",
                "expected_conflict_version": 2,
                "expected_map_version": 2,
            },
        )
        assert reopened.status_code == 200
        from deeptutor.multi_user.models import CurrentUser
        from deeptutor.multi_user.paths import scope_for_user

        with patch(
            "deeptutor.api.routers.mastery_path.get_current_user",
            return_value=CurrentUser(
                id="intruder",
                username="intruder",
                role="user",
                scope=scope_for_user("intruder", is_admin=False),
            ),
        ):
            resp = client.post(
                "/api/v1/learning/progress/path1/conflicts/c1/resolve",
                json={
                    "accepted_snapshot_id": "s1",
                    "resolution_note": "intruder",
                    "request_id": "res-api-intruder",
                    "expected_conflict_version": 3,
                    "expected_map_version": 2,
                },
            )
            assert resp.status_code == 403

    def test_reopen_restores_block(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _add_conflict("path1")
        client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/resolve",
            json={
                "accepted_snapshot_id": "s1",
                "resolution_note": "ok",
                "request_id": "res-api-reopen",
                "expected_conflict_version": 1,
                "expected_map_version": 1,
            },
        )
        resp = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/reopen",
            json={
                "request_id": "reopen-api-block",
                "expected_conflict_version": 2,
                "expected_map_version": 2,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["blocking"] is True
        assert resp.json()["status"] == "open"

    def test_resolve_replay_after_restart_returns_full_result(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _add_conflict("path1")
        body = {
            "accepted_snapshot_id": "s1",
            "resolution_note": "s1 wins",
            "request_id": "resolve-1",
            "expected_conflict_version": 1,
            "expected_map_version": 1,
        }
        first = client.post("/api/v1/learning/progress/path1/conflicts/c1/resolve", json=body)
        assert first.status_code == 200
        second = client.post("/api/v1/learning/progress/path1/conflicts/c1/resolve", json=body)
        assert second.status_code == 200
        data = second.json()
        assert data["replayed"] is True
        assert data["conflict_version"] == first.json()["conflict_version"] == 2
        assert data["map_version_id"] == first.json()["map_version_id"]

    def test_resolve_stale_conflict_version_conflicts(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        _add_conflict("path1")
        resp = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/resolve",
            json={
                "accepted_snapshot_id": "s1",
                "resolution_note": "note",
                "request_id": "res-api-stale",
                "expected_conflict_version": 9,
                "expected_map_version": 1,
            },
        )
        assert resp.status_code == 409
        assert "expected conflict version" in resp.json()["detail"]


# ── challenge / resume ────────────────────────────────────────────────────


class TestChallengeResumeAPI:
    def test_challenge_reassess(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        # reassess_existing requires a prior assessment on the source attempt.
        _finalize_attempt("path1", attempt_id)
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={
                "mode": "reassess_existing",
                "reason": "review it",
                "request_id": "ch-api-reassess",
                "expected_attempt_version": _current_attempt_version("path1"),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "reassess_existing"
        assert data["status"] == "pending"
        assert data["source_attempt_id"] == attempt_id
        assert data["source_assessment_id"]

    def test_challenge_collect_new_evidence_links_attempt(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={
                "mode": "collect_new_evidence",
                "request_id": "ch-api-collect",
                "expected_attempt_version": _current_attempt_version("path1"),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result_attempt_id"]
        detail = client.get(
            f"/api/v1/learning/progress/path1/attempts/{data['result_attempt_id']}"
        ).json()
        assert detail["attempt"]["cycle_type"] == "reevaluation"
        assert detail["attempt"]["supersedes_attempt_id"] == attempt_id

    def test_invalidated_resume_requires_restart(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        service = FeynmanCycleService(LearningStore())
        progress = service.load("path1")
        invalidate_attempts(progress, attempt_ids=[attempt_id], reason="source_version_changed")
        service.save(progress)

        resp = client.post(f"/api/v1/learning/progress/path1/attempts/{attempt_id}/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "requires_restart"
        assert data["map_version"] == 1

    def test_resume_draft(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        resp = client.post(f"/api/v1/learning/progress/path1/attempts/{attempt_id}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resumed"

    def test_challenge_forged_evaluator_snapshot_rejected(self, client):
        """A challenge request that names a configured profile/model but forges
        the frozen protocol/strictness is rejected (409) — a client can never
        force a different protocol for a configured profile (§9.3)."""
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        _finalize_attempt("path1", attempt_id)
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={
                "mode": "reassess_existing",
                "request_id": "ch-forged",
                "expected_attempt_version": _current_attempt_version("path1"),
                "requested_evaluator_snapshot": {
                    "profile_id": "p1",  # configured profile
                    "resolved_model": "gpt-4o-mini",  # configured model
                    # Forged: the real profile resolves to openai_responses.
                    "resolved_api_protocol": "openai_chat_completions",
                    "strict_protocol": False,
                },
            },
        )
        assert resp.status_code == 409

    def test_challenge_unknown_evaluator_profile_rejected(self, client):
        """An alternative evaluator that is not a configured profile/model is
        rejected up front (§9.3)."""
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        _finalize_attempt("path1", attempt_id)
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={
                "mode": "reassess_existing",
                "request_id": "ch-unknown-eval",
                "expected_attempt_version": _current_attempt_version("path1"),
                "requested_evaluator_snapshot": {
                    "profile_id": "p-ghost",
                    "resolved_model": "ghost-model",
                    "resolved_api_protocol": "openai_responses",
                },
            },
        )
        assert resp.status_code == 409

    def test_challenge_unknown_attempt_404(self, client):
        _init_path(client)
        resp = client.post(
            "/api/v1/learning/progress/path1/attempts/nope/challenge",
            json={
                "mode": "reassess_existing",
                "request_id": "ch-api-404",
                "expected_attempt_version": 0,
            },
        )
        assert resp.status_code == 404

    def test_challenge_complete_valid_snapshot_accepted(self, client):
        """A complete server-canonical snapshot (every frozen identity field
        present and verified against the catalog) is accepted (200)."""
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        _finalize_attempt("path1", attempt_id)
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={
                "mode": "reassess_existing",
                "request_id": "ch-complete-valid",
                "expected_attempt_version": _current_attempt_version("path1"),
                "requested_evaluator_snapshot": _complete_evaluator_snapshot_dict(),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "reassess_existing"

    @pytest.mark.parametrize(
        "mutate,reason",
        [
            (lambda d: d.pop("profile_revision", None), "omitted profile_revision"),
            (lambda d: d.__setitem__("profile_revision", "forged"), "forged profile_revision"),
            (lambda d: d.pop("resolved_api_protocol", None), "omitted resolved_api_protocol"),
            (
                lambda d: d.__setitem__("resolved_api_protocol", "openai_chat_completions"),
                "forged resolved_api_protocol",
            ),
            (lambda d: d.pop("strict_protocol", None), "omitted strict_protocol"),
            (
                lambda d: d.__setitem__("strict_protocol", False),
                "forged strict_protocol (real profile is strict)",
            ),
            (lambda d: d.pop("base_url_fingerprint", None), "omitted base_url_fingerprint"),
            (
                lambda d: d.__setitem__("base_url_fingerprint", "forged-fp"),
                "forged base_url_fingerprint",
            ),
        ],
    )
    def test_challenge_incomplete_or_forged_snapshot_rejected(self, client, mutate, reason):
        """Every omitted/forged challenge-evaluator identity field fails closed
        at the public boundary with 409 — never accepted (finding 5)."""
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        _finalize_attempt("path1", attempt_id)
        snapshot = _complete_evaluator_snapshot_dict()
        mutate(snapshot)
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={
                "mode": "reassess_existing",
                "request_id": f"ch-incomplete-{reason.replace(' ', '-')}",
                "expected_attempt_version": _current_attempt_version("path1"),
                "requested_evaluator_snapshot": snapshot,
            },
        )
        assert resp.status_code == 409, reason

    def test_challenge_request_id_replay(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        _finalize_attempt("path1", attempt_id)
        body = {
            "mode": "collect_new_evidence",
            "request_id": "ch-1",
            "expected_attempt_version": _current_attempt_version("path1"),
        }
        first = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge", json=body
        )
        assert first.status_code == 200
        second = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge", json=body
        )
        assert second.status_code == 200
        assert second.json()["challenge_id"] == first.json()["challenge_id"]
        assert second.json()["result_attempt_id"] == first.json()["result_attempt_id"]
        # No second challenge/reevaluation attempt was created.
        detail = client.get(
            f"/api/v1/learning/progress/path1/attempts/{first.json()['result_attempt_id']}"
        ).json()
        assert detail["attempt"]["supersedes_attempt_id"] == attempt_id

    def test_challenge_same_key_different_payload_conflicts(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        _finalize_attempt("path1", attempt_id)
        base = {
            "mode": "collect_new_evidence",
            "request_id": "ch-2",
            "expected_attempt_version": _current_attempt_version("path1"),
        }
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge", json=base
        )
        assert resp.status_code == 200
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={**base, "mode": "reassess_existing"},
        )
        assert resp.status_code == 409
        assert "reused with a different payload" in resp.json()["detail"]

    def test_duplicate_pending_challenge_rejected(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        attempt_id = _start_attempt("path1")
        _finalize_attempt("path1", attempt_id)
        body = {
            "mode": "reassess_existing",
            "request_id": "ch-api-dup",
            "expected_attempt_version": _current_attempt_version("path1"),
        }
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge", json=body
        )
        assert resp.status_code == 200
        # A second mutation under a *different* idempotency key must hit the
        # duplicate-pending guard (the same key would be an idempotent replay).
        resp = client.post(
            f"/api/v1/learning/progress/path1/attempts/{attempt_id}/challenge",
            json={
                **body,
                "request_id": "ch-api-dup-2",
                "expected_attempt_version": _current_attempt_version("path1"),
            },
        )
        assert resp.status_code == 409
        assert "pending challenge already exists" in resp.json()["detail"]


# ── Final correction: request models reject omitted keys/versions ──────────


class TestRequiredIdempotencyKeysAPI:
    def test_map_edit_missing_request_id_422(self, client):
        _init_path(client)
        _register_map_and_sources("path1")
        resp = client.patch(
            "/api/v1/learning/progress/path1/map",
            json={"nodes": [], "edges": [], "priorities": {}, "expected_map_version": 1},
        )
        assert resp.status_code == 422

    def test_map_edit_missing_expected_version_422(self, client):
        _init_path(client)
        resp = client.patch(
            "/api/v1/learning/progress/path1/map",
            json={"nodes": [], "edges": [], "priorities": {}, "request_id": "r"},
        )
        assert resp.status_code == 422

    def test_confirm_map_missing_request_id_422(self, client):
        _init_path(client)
        resp = client.post(
            "/api/v1/learning/progress/path1/map/confirm",
            json={"expected_map_version": 1},
        )
        assert resp.status_code == 422

    def test_resolve_missing_expected_versions_422(self, client):
        _init_path(client)
        resp = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/resolve",
            json={
                "accepted_snapshot_id": "s1",
                "resolution_note": "note",
                "request_id": "r",
            },
        )
        assert resp.status_code == 422

    def test_reopen_missing_request_id_422(self, client):
        _init_path(client)
        resp = client.post(
            "/api/v1/learning/progress/path1/conflicts/c1/reopen",
            json={"expected_conflict_version": 1, "expected_map_version": 1},
        )
        assert resp.status_code == 422

    def test_challenge_missing_request_id_422(self, client):
        _init_path(client)
        resp = client.post(
            "/api/v1/learning/progress/path1/attempts/x/challenge",
            json={"mode": "reassess_existing", "expected_attempt_version": 1},
        )
        assert resp.status_code == 422

    def test_challenge_missing_expected_version_422(self, client):
        _init_path(client)
        resp = client.post(
            "/api/v1/learning/progress/path1/attempts/x/challenge",
            json={"mode": "reassess_existing", "request_id": "r"},
        )
        assert resp.status_code == 422
