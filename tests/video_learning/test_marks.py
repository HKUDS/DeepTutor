from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.video_learning import service
from deeptutor.video_learning.marks import (
    create_mark,
    delete_mark,
    heuristic_suggestions,
    normalize_mark,
    suggest_marks,
    update_mark,
)


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / feature


@pytest.fixture
def client_and_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[TestClient, service.TimedMediaStore]:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/video-learning")
    return TestClient(app), service.get_timed_media_store()


def _material(store: service.TimedMediaStore, *, duration: float = 120) -> dict:
    material = {
        "version": 1,
        "type": "timed_media",
        "material_id": service.material_id_for("dQw4w9WgXcQ"),
        "created_at": "2026-01-01T00:00:00+00:00",
        "source": {
            "provider": "youtube",
            "video_id": "dQw4w9WgXcQ",
            "url": "https://youtu.be/dQw4w9WgXcQ",
        },
        "metadata": {"title": "Demo", "duration_seconds": duration},
        "transcript": {
            "status": "ready",
            "cues": [
                {"start": 10, "end": 18, "text": "Gradient descent finds a local minimum."},
                {"start": 18, "end": 30, "text": "Why does the learning rate matter?"},
                {"start": 40, "end": 55, "text": "This example is worth reviewing later."},
            ],
        },
        "segments": [
            {
                "locator": 1,
                "start": 10,
                "end": 30,
                "text": "Gradient descent finds a local minimum. Why does the learning rate matter?",
            },
            {
                "locator": 2,
                "start": 40,
                "end": 55,
                "text": "This example is worth reviewing later.",
            },
        ],
        "learning": {"last_position": 0},
    }
    return store.save(material)


def test_mark_range_clamps_and_snapshots_quote(tmp_path: Path) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store)
    mark = create_mark(
        material,
        {
            "kind": "key_point",
            "start_seconds": 10,
            "end_seconds": 400,
            "quote": "keep this quote",
        },
    )
    assert mark["end_seconds"] == 120
    assert mark["quote"] == "keep this quote"
    assert mark["start_locator"] == 1
    assert mark["source"] == "immersive"
    assert mark["metadata"] == {}


def test_mark_updates_and_deletion_are_material_scoped(tmp_path: Path) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store)
    mark = create_mark(material, {"kind": "review", "start_seconds": 40, "end_seconds": 55})
    updated = update_mark(material, mark["mark_id"], {"note": "rewatch", "reviewed": True})
    assert updated["reviewed_at"]
    assert delete_mark(material, mark["mark_id"])["mark_id"] == mark["mark_id"]
    with pytest.raises(service.TimedMediaNotFound):
        delete_mark(material, mark["mark_id"])


def test_point_bookmark_and_reversed_ranges(tmp_path: Path) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store)
    mark = create_mark(material, {"kind": "question", "start_seconds": 18, "end_seconds": 18})
    assert mark["start_seconds"] == mark["end_seconds"] == 18
    with pytest.raises(service.TimedMediaError):
        normalize_mark(material, {"kind": "question", "start_seconds": 5, "end_seconds": 1})


@pytest.mark.asyncio
async def test_suggestions_fall_back_without_llm_and_do_not_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    material = _material(store)

    async def unavailable(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr("deeptutor.services.llm.complete", unavailable)
    suggestions = await suggest_marks(material, 20)
    assert suggestions
    assert all("mark_id" not in row for row in suggestions)
    assert store.get(material["material_id"])["learning"].get("marks", []) == []


def test_heuristic_suggestions_use_current_segment(tmp_path: Path) -> None:
    store = service.TimedMediaStore(root=tmp_path / "timed_media")
    suggestions = heuristic_suggestions(_material(store), 20)
    assert suggestions[0]["start_seconds"] == 10
    assert any(row["kind"] == "question" for row in suggestions)


def test_router_mark_crud_and_isolation(client_and_store) -> None:
    client, store = client_and_store
    material = _material(store)
    other = _material(store)
    other["material_id"] = service.material_id_for("89ThCi5qq-A")
    store.save(other)
    material_id = material["material_id"]

    created = client.post(
        f"/api/video-learning/materials/{material_id}/marks",
        json={
            "kind": "key_point",
            "start_seconds": 10,
            "end_seconds": 18,
            "quote": "Gradient descent finds a local minimum.",
        },
    )
    assert created.status_code == 201
    mark_id = created.json()["mark_id"]

    point = client.post(
        f"/api/video-learning/materials/{material_id}/marks",
        json={"kind": "question", "start_seconds": 18, "end_seconds": 18},
    )
    assert point.status_code == 201
    assert point.json()["end_seconds"] == 18
    listed = client.get(f"/api/video-learning/materials/{material_id}/marks")
    assert listed.status_code == 200
    assert [row["mark_id"] for row in listed.json()] == [mark_id, point.json()["mark_id"]]

    patched = client.patch(
        f"/api/video-learning/materials/{material_id}/marks/{mark_id}",
        json={"note": "core claim"},
    )
    assert patched.status_code == 200
    assert patched.json()["note"] == "core claim"

    missing = client.patch(
        f"/api/video-learning/materials/{other['material_id']}/marks/{mark_id}",
        json={"note": "stolen"},
    )
    assert missing.status_code == 404

    deleted = client.delete(f"/api/video-learning/materials/{material_id}/marks/{mark_id}")
    assert deleted.status_code == 200
    assert [row["mark_id"] for row in store.get(material_id)["learning"]["marks"]] == [
        point.json()["mark_id"]
    ]


def test_router_suggestions_are_ephemeral(client_and_store, monkeypatch) -> None:
    client, store = client_and_store
    material = _material(store)

    async def fake_complete(*_args: object, **_kwargs: object) -> str:
        return '[{"kind":"review","start_seconds":40,"end_seconds":55,"quote":"invented quote"}]'

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    response = client.post(
        f"/api/video-learning/materials/{material['material_id']}/mark-suggestions",
        json={"time_seconds": 42},
    )
    assert response.status_code == 200
    assert response.json()["suggestions"]
    assert response.json()["suggestions"][0]["quote"] == "This example is worth reviewing later."
    assert store.get(material["material_id"])["learning"].get("marks", []) == []
