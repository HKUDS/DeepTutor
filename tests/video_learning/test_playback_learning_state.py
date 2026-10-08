"""Playback provider discovery preserves learning edits made during HTTP I/O."""

from pathlib import Path

import httpx
import pytest

from deeptutor.video_learning import service
from deeptutor.video_learning.marks import create_mark


@pytest.mark.asyncio
@pytest.mark.parametrize("edit", ["position", "mark"])
async def test_playback_discovery_keeps_concurrent_learning(
    tmp_path: Path, monkeypatch, edit: str
) -> None:
    """Use the native HTTP client and persisted marks across provider discovery."""
    store = service.TimedMediaStore(tmp_path)
    material_id = service.material_id_for("dQw4w9WgXcQ")
    store.save(
        {
            "type": "timed_media",
            "material_id": material_id,
            "source": {"video_id": "dQw4w9WgXcQ", "url": "https://youtu.be/dQw4w9WgXcQ"},
            "metadata": {"duration_seconds": 120},
            "learning": {"last_position": 0},
            "transcript": {"cues": []},
            "_caption_text_version": 1,
        }
    )
    settings = service.normalize_video_learning_settings(
        {
            "default_provider": "invidious",
            "invidious": {"api_base_url": "https://video.example"},
        }
    )
    monkeypatch.setattr(service, "get_timed_media_store", lambda: store)
    monkeypatch.setattr(service, "load_video_learning_settings", lambda: settings)
    edited_learning = {}

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/videos/dQw4w9WgXcQ"
        with store.lock(material_id):
            latest = store.get(material_id, lock_held=True)
            if edit == "position":
                latest["learning"]["last_position"] = 42
            else:
                create_mark(
                    latest,
                    {"kind": "review", "start_seconds": 12, "note": "Review this concept"},
                )
            store.save(latest)
            edited_learning.update(latest["learning"])
        return httpx.Response(
            200, json={"title": "Video", "formatStreams": [{"type": "video/mp4", "itag": 18}]}
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        service.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
    )
    result = await service.material_with_playback(material_id)
    assert result["learning"] == edited_learning
    assert store.get(material_id)["learning"] == edited_learning
    assert result["playback"]["format_id"] == "18"
