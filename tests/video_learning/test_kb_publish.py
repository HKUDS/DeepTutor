from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.video_learning.kb_publish import (
    ideation_text_for_material,
    learning_publish_state,
    note_relative_path,
    parse_timed_media_ref,
    publish_material_to_kb,
    render_video_learning_note,
    source_chunks_for_material,
    timed_media_ref,
    watching_jump_url,
)
from deeptutor.video_learning.marks import create_mark
from deeptutor.video_learning.service import TimedMediaStore


def _material(store: TimedMediaStore) -> dict:
    material = store.create(
        {
            "type": "timed_media",
            "source": {
                "provider": "youtube",
                "video_id": "dQw4w9WgXcQ",
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "duration_seconds": 120,
            },
            "metadata": {
                "title": "Gradient Descent Intro",
                "author": "Tutor",
                "duration_seconds": 120,
                "chapters": [],
            },
            "transcript": {
                "language": "en",
                "source": "invidious",
                "cues": [
                    {"start": 10, "end": 18, "text": "Gradient descent finds a local minimum."},
                    {"start": 18, "end": 30, "text": "Why does the learning rate matter?"},
                ],
            },
            "segments": [
                {
                    "locator": 1,
                    "start": 10,
                    "end": 30,
                    "text": "Gradient descent finds a local minimum. Why does the learning rate matter?",
                }
            ],
            "playback": {"formats": {}, "official_url": "https://youtu.be/dQw4w9WgXcQ"},
            "learning": {"last_position": 0, "notes": [], "marks": []},
        }
    )
    create_mark(
        material,
        {
            "kind": "key_point",
            "start_seconds": 10,
            "end_seconds": 18,
            "quote": "Gradient descent finds a local minimum.",
            "note": "core claim",
        },
    )
    store.save(material)
    return store.get(material["material_id"])


@pytest.fixture
def client_and_store(tmp_path: Path, monkeypatch):
    store = TimedMediaStore(root=tmp_path / "timed_media")
    monkeypatch.setattr("deeptutor.video_learning.service.get_timed_media_store", lambda: store)
    monkeypatch.setattr("deeptutor.api.routers.video_learning.get_timed_media_store", lambda: store)
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/v1/video-learning")
    return TestClient(app), store


def test_timed_media_ref_roundtrip_and_jump_url():
    ref = timed_media_ref("abc123", 12.5, 18.0)
    parsed = parse_timed_media_ref(ref)
    assert parsed == {
        "material_id": "abc123",
        "start_seconds": 12.5,
        "end_seconds": 18.0,
    }
    assert watching_jump_url("abc123", 12.5).startswith("/home?watching_material=abc123&t=12.5")


def test_render_note_and_source_chunks_include_marks(tmp_path: Path):
    store = TimedMediaStore(tmp_path / "timed_media")
    material = _material(store)
    note = render_video_learning_note(material)
    assert "Gradient Descent Intro" in note
    assert "Gradient descent finds a local minimum." in note
    assert note_relative_path(material) == "video-learning/youtube-dQw4w9WgXcQ.md"
    chunks = source_chunks_for_material(material)
    assert chunks
    assert chunks[0]["source"] == "timed_media"
    assert "jump_url" in chunks[0]["metadata"]
    assert "core claim" in ideation_text_for_material(material) or "Gradient descent" in ideation_text_for_material(material)


@pytest.mark.asyncio
async def test_publish_material_to_kb_writes_stable_note(tmp_path: Path, monkeypatch):
    store = TimedMediaStore(tmp_path / "timed_media")
    material = _material(store)
    raw_dir = tmp_path / "kb-raw"
    raw_dir.mkdir()
    resource = SimpleNamespace(name="default", id="kb-default", base_dir=str(tmp_path / "kb-base"))

    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.assert_writable",
        lambda kb_name: resource,
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.manager_for_resource",
        lambda _resource: SimpleNamespace(get_raw_path=lambda _name: raw_dir),
    )

    async def fake_add_documents(**_kwargs):
        return 1

    monkeypatch.setattr("deeptutor.knowledge.add_documents.add_documents", fake_add_documents)

    first = await publish_material_to_kb(material, kb_name="default")
    assert first["updated"] is True
    note_path = raw_dir / "video-learning" / "youtube-dQw4w9WgXcQ.md"
    assert note_path.is_file()
    assert learning_publish_state(first["material"])["content_hash"] == first["content_hash"]

    second = await publish_material_to_kb(first["material"], kb_name="default")
    assert second["updated"] is False


def test_router_publish_and_create_book(client_and_store, monkeypatch, tmp_path: Path):
    client, store = client_and_store
    material = _material(store)
    mat_id = material["material_id"]
    raw_dir = tmp_path / "kb-raw"
    raw_dir.mkdir()
    resource = SimpleNamespace(name="default", id="kb-default", base_dir=str(tmp_path / "kb-base"))

    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.assert_writable",
        lambda kb_name: resource,
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.manager_for_resource",
        lambda _resource: SimpleNamespace(get_raw_path=lambda _name: raw_dir),
    )

    async def fake_add_documents(**_kwargs):
        return 1

    monkeypatch.setattr("deeptutor.knowledge.add_documents.add_documents", fake_add_documents)

    class FakeEngine:
        async def create_book(self, **kwargs):
            assert kwargs["timed_media_ids"] == [mat_id]
            assert kwargs["knowledge_bases"] == ["default"]
            book = SimpleNamespace(
                id="book123",
                title="From Video",
                model_dump=lambda mode="json": {"id": "book123", "title": "From Video"},
            )
            proposal = SimpleNamespace(
                model_dump=lambda mode="json": {"title": "From Video", "estimated_chapters": 3}
            )
            return book, proposal

    monkeypatch.setattr("deeptutor.book.engine.get_book_engine", lambda: FakeEngine())

    published = client.post(f"/api/v1/video-learning/materials/{mat_id}/publish-to-kb", json={"kb_name": "default"})
    assert published.status_code == 200
    body = published.json()
    assert body["updated"] is True
    assert body["path"] == "video-learning/youtube-dQw4w9WgXcQ.md"
    assert store.get(mat_id)["learning"]["kb_publish"]["kb_name"] == "default"

    created = client.post(
        f"/api/v1/video-learning/materials/{mat_id}/create-book",
        json={"kb_name": "default", "publish": False, "language": "en"},
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["book"]["id"] == "book123"
    assert payload["kb_publish"]["path"] == "video-learning/youtube-dQw4w9WgXcQ.md"
