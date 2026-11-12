"""Path-level strategy notes: versioned, archived not deleted, learner-owned.

Also covers ``strategy_outcomes`` — the deterministic aggregation of recorded
strategy results that the tutor reads as evidence.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.models import LearnerProfile, LearningProgress, TeachingObservation
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.teaching import strategy_outcomes
from deeptutor.tools.mastery_tool import MasteryBuildTool


@pytest.fixture
def store(tmp_path, monkeypatch):
    def _init(self, root_arg=None):
        from pathlib import Path

        self._root = Path(tmp_path) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(LearningStore, "__init__", _init)
    return LearningStore()


async def _build(path_id: str) -> None:
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        path_name="策略路径",
        modules=[
            {
                "name": "模块",
                "objective": "能说出这一节在讲什么",
                "knowledge_points": [{"name": "概念甲", "type": "concept"}],
            }
        ],
    )
    assert result.success, result.content


@pytest.mark.asyncio
async def test_note_round_trip_and_revision_history(store):
    await _build("strategy_path")

    created = store.save_strategy_note(
        "strategy_path", "note-1", "先给数据流骨架", evidence=[{"kind": "observation"}]
    )
    assert created["revision"] == 1
    assert created["status"] == "active"
    assert created["created_by"] == "agent"
    assert created["evidence"] == [{"kind": "observation"}]

    revised = store.save_strategy_note("strategy_path", "note-1", "先给骨架，再落到字段")
    assert revised["revision"] == 2
    assert revised["body"] == "先给骨架，再落到字段"

    history = store.strategy_note_history("strategy_path", "note-1")
    assert [entry["revision"] for entry in history] == [2, 1]
    assert history[1]["body"] == "先给数据流骨架"


@pytest.mark.asyncio
async def test_archive_hides_but_restore_recovers(store):
    await _build("archive_path")
    store.save_strategy_note("archive_path", "note-1", "术语三件套")

    archived = store.set_strategy_note_status("archive_path", "note-1", "archived")
    assert archived["status"] == "archived"
    assert store.list_strategy_notes("archive_path") == []
    assert [n["note_id"] for n in store.list_strategy_notes("archive_path", include_archived=True)] == [
        "note-1"
    ]

    restored = store.set_strategy_note_status("archive_path", "note-1", "active")
    assert restored["status"] == "active"
    assert [n["note_id"] for n in store.list_strategy_notes("archive_path")] == ["note-1"]


@pytest.mark.asyncio
async def test_rollback_restores_an_earlier_revision(store):
    await _build("rollback_path")
    store.save_strategy_note("rollback_path", "note-1", "v1 body")
    store.save_strategy_note("rollback_path", "note-1", "v2 body")

    rolled = store.rollback_strategy_note("rollback_path", "note-1", 1)
    assert rolled["body"] == "v1 body"
    assert rolled["revision"] == 3  # rollback is itself a new revision

    missing = store.rollback_strategy_note("rollback_path", "note-1", 99)
    assert missing is None


@pytest.mark.asyncio
async def test_learner_authored_note_keeps_its_provenance(store):
    await _build("learner_path")
    note = store.save_strategy_note(
        "learner_path", "note-1", "例子请用能改写的代码", created_by="learner"
    )
    assert note["created_by"] == "learner"


def test_strategy_outcomes_aggregate_by_strategy():
    profile = LearnerProfile(
        teaching_observations={
            "obs-1": TeachingObservation(
                knowledge_point_id="kp1",
                text="框架先行有效",
                basis="learner_report",
                strategy="framework_first",
                outcome="helped",
                evidence="懂了",
            ),
            "obs-2": TeachingObservation(
                knowledge_point_id="kp2",
                text="框架先行又有效",
                basis="learner_report",
                strategy="framework_first",
                outcome="helped",
                evidence="明白了",
            ),
            "obs-3": TeachingObservation(
                knowledge_point_id="kp1",
                text="细节先行没接住",
                basis="learner_report",
                strategy="detail_first",
                outcome="not_helped",
                evidence="还是不懂",
            ),
            "obs-4": TeachingObservation(
                knowledge_point_id="kp1",
                text="没有结果",
                basis="tentative",
                strategy="term_trio",
                outcome="unknown",
            ),
        }
    )

    outcomes = strategy_outcomes(profile)
    assert outcomes["total"] == 3
    top = outcomes["strategies"][0]
    assert top["strategy"] == "framework_first"
    assert top["helped"] == 2
    assert top["knowledge_point_ids"] == ["kp1", "kp2"]
    # An "unknown" outcome is not counted as a result.
    assert all(row["strategy"] != "term_trio" for row in outcomes["strategies"])


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.api.routers.mastery_path import router

    monkeypatch.setattr(
        "deeptutor.api.routers.mastery_path.LearningStore",
        lambda root=None: LearningStore(root=tmp_path),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/mastery-paths")
    return TestClient(app)


def test_strategy_endpoints_round_trip(client, tmp_path):
    store = LearningStore(root=tmp_path)
    store.save(LearningProgress(book_id="strat-api", name="Strat API"))
    base = "/api/mastery-paths/topics/strat-api/strategy"

    created = client.post(base, json={"body": "先给数据流骨架"})
    assert created.status_code == 200
    note = created.json()
    assert note["created_by"] == "learner"
    assert note["revision"] == 1
    note_id = note["note_id"]

    listed = client.get(base)
    assert [n["note_id"] for n in listed.json()["notes"]] == [note_id]

    edited = client.patch(f"{base}/{note_id}", json={"body": "先给骨架，再落到字段"})
    assert edited.status_code == 200
    assert edited.json()["revision"] == 2

    history = client.get(f"{base}/{note_id}/history")
    assert [entry["revision"] for entry in history.json()["history"]] == [2, 1]

    rolled = client.post(f"{base}/{note_id}/rollback", json={"revision": 1})
    assert rolled.status_code == 200
    assert rolled.json()["body"] == "先给数据流骨架"

    archived = client.delete(f"{base}/{note_id}")
    assert archived.json()["status"] == "archived"
    assert client.get(base).json()["notes"] == []

    restored = client.post(f"{base}/{note_id}/restore")
    assert restored.json()["status"] == "active"


def test_strategy_endpoints_reject_empty_body(client, tmp_path):
    store = LearningStore(root=tmp_path)
    store.save(LearningProgress(book_id="strat-api-2", name="Strat API 2"))
    response = client.post(
        "/api/mastery-paths/topics/strat-api-2/strategy", json={"body": "  "}
    )
    assert response.status_code == 422
