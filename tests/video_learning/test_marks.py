from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.video_learning.marks import (
    create_mark,
    delete_mark,
    heuristic_suggestions,
    normalize_mark,
    suggest_marks,
    update_mark,
)
from deeptutor.video_learning.service import TimedMediaError, TimedMediaNotFound, TimedMediaStore


def _material(store: TimedMediaStore, *, duration: float = 120) -> dict:
    return store.create(
        {
            "type": "timed_media",
            "source": {
                "provider": "youtube",
                "video_id": "dQw4w9WgXcQ",
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "duration_seconds": duration,
            },
            "metadata": {"title": "Demo", "author": "Tutor", "duration_seconds": duration, "chapters": []},
            "transcript": {
                "language": "en",
                "source": "invidious",
                "cues": [
                    {"start": 10, "end": 18, "text": "Gradient descent finds a local minimum."},
                    {"start": 18, "end": 30, "text": "Why does the learning rate matter?"},
                    {"start": 40, "end": 55, "text": "This example is worth reviewing later."},
                ],
            },
            "segments": [
                {"locator": 1, "start": 10, "end": 30, "text": "Gradient descent finds a local minimum. Why does the learning rate matter?"},
                {"locator": 2, "start": 40, "end": 55, "text": "This example is worth reviewing later."},
            ],
            "playback": {"formats": {}, "official_url": "https://youtu.be/dQw4w9WgXcQ"},
            "learning": {"last_position": 0, "notes": [], "marks": []},
        }
    )


@pytest.fixture
def client_and_store(tmp_path: Path, monkeypatch):
    store = TimedMediaStore(root=tmp_path / "timed_media")
    monkeypatch.setattr("deeptutor.video_learning.service.get_timed_media_store", lambda: store)
    monkeypatch.setattr("deeptutor.api.routers.video_learning.get_timed_media_store", lambda: store)
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/v1/video-learning")
    return TestClient(app), store


def test_normalize_mark_rejects_kind_and_reversed_times():
    material = {"source": {"duration_seconds": 100}, "segments": [], "transcript": {"cues": []}, "learning": {"marks": []}}
    with pytest.raises(TimedMediaError):
        normalize_mark(material, {"kind": "highlight", "start_seconds": 1, "end_seconds": 2})
    with pytest.raises(TimedMediaError):
        normalize_mark(material, {"kind": "key_point", "start_seconds": 8, "end_seconds": 2})


def test_normalize_mark_clamps_to_duration_and_snapshots_quote(tmp_path: Path):
    store = TimedMediaStore(tmp_path)
    material = _material(store)
    mark = create_mark(
        material,
        {"kind": "key_point", "start_seconds": 10, "end_seconds": 400, "quote": "keep this quote"},
    )
    assert mark["end_seconds"] == 120
    assert mark["quote"] == "keep this quote"
    assert mark["start_locator"] == 1
    assert mark["source"] == "immersive"
    assert mark["metadata"] == {}
    store.save(material)
    assert store.get(material["material_id"])["learning"]["marks"][0]["mark_id"] == mark["mark_id"]


def test_update_and_delete_are_owner_material_scoped(tmp_path: Path):
    store = TimedMediaStore(tmp_path)
    material = _material(store)
    mark = create_mark(material, {"kind": "review", "start_seconds": 40, "end_seconds": 55})
    updated = update_mark(material, mark["mark_id"], {"note": "rewatch the example", "reviewed": True})
    assert updated["note"] == "rewatch the example"
    assert updated["reviewed_at"]
    deleted = delete_mark(material, mark["mark_id"])
    assert deleted["mark_id"] == mark["mark_id"]
    with pytest.raises(TimedMediaNotFound):
        delete_mark(material, mark["mark_id"])


def test_point_bookmark_allows_equal_start_and_end(tmp_path: Path):
    material = _material(TimedMediaStore(tmp_path))
    mark = create_mark(material, {"kind": "question", "start_seconds": 18, "end_seconds": 18})
    assert mark["start_seconds"] == mark["end_seconds"] == 18


@pytest.mark.asyncio
async def test_suggestions_do_not_persist_and_fallback_without_llm(tmp_path: Path, monkeypatch):
    store = TimedMediaStore(tmp_path)
    material = _material(store)
    store.save(material)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr("deeptutor.services.llm.complete", boom)
    suggestions = await suggest_marks(material, 20)
    assert suggestions
    assert all("mark_id" not in row for row in suggestions)
    reloaded = store.get(material["material_id"])
    assert reloaded["learning"]["marks"] == []


@pytest.mark.asyncio
async def test_suggestions_parse_llm_json_without_saving(tmp_path: Path, monkeypatch):
    store = TimedMediaStore(tmp_path)
    material = _material(store)
    store.save(material)

    async def fake_complete(*_args, **_kwargs):
        return '```json\n[{"kind":"key_point","start_seconds":10,"end_seconds":18,"quote":"Gradient descent finds a local minimum."}]\n```'

    monkeypatch.setattr("deeptutor.video_learning.marks.complete", fake_complete, raising=False)
    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    suggestions = await suggest_marks(material, 12)
    assert suggestions[0]["kind"] == "key_point"
    assert suggestions[0]["author"] == "assistant"
    assert store.get(material["material_id"])["learning"]["marks"] == []


def test_heuristic_suggestions_use_current_segment(tmp_path: Path):
    material = _material(TimedMediaStore(tmp_path))
    rows = heuristic_suggestions(material, 20)
    assert rows[0]["start_seconds"] == 10
    assert any(row["kind"] == "question" for row in rows)


def test_router_mark_crud_and_isolation(client_and_store):
    client, store = client_and_store
    material = _material(store)
    mat_id = material["material_id"]
    other = _material(store)

    created = client.post(
        f"/api/v1/video-learning/materials/{mat_id}/marks",
        json={"kind": "key_point", "start_seconds": 10, "end_seconds": 18, "quote": "Gradient descent finds a local minimum."},
    )
    assert created.status_code == 201
    mark_id = created.json()["mark_id"]

    patched = client.patch(
        f"/api/v1/video-learning/materials/{mat_id}/marks/{mark_id}",
        json={"note": "core claim"},
    )
    assert patched.status_code == 200
    assert patched.json()["note"] == "core claim"

    missing = client.patch(
        f"/api/v1/video-learning/materials/{other['material_id']}/marks/{mark_id}",
        json={"note": "stolen"},
    )
    assert missing.status_code == 404

    invalid = client.post(
        f"/api/v1/video-learning/materials/{mat_id}/marks",
        json={"kind": "rainbow", "start_seconds": 1, "end_seconds": 2},
    )
    assert invalid.status_code == 400

    deleted = client.delete(f"/api/v1/video-learning/materials/{mat_id}/marks/{mark_id}")
    assert deleted.status_code == 200
    assert store.get(mat_id)["learning"]["marks"] == []


def test_router_suggestions_are_ephemeral(client_and_store, monkeypatch):
    client, store = client_and_store
    material = _material(store)

    async def fake_complete(*_args, **_kwargs):
        return '[{"kind":"review","start_seconds":40,"end_seconds":55,"quote":"This example is worth reviewing later."}]'

    monkeypatch.setattr("deeptutor.services.llm.complete", fake_complete)
    response = client.post(
        f"/api/v1/video-learning/materials/{material['material_id']}/mark-suggestions",
        json={"time_seconds": 42},
    )
    assert response.status_code == 200
    assert response.json()["suggestions"]
    assert store.get(material["material_id"])["learning"]["marks"] == []
