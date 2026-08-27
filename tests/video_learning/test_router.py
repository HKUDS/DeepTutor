from datetime import datetime, timezone
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.multi_user.paths import current_owner_id, owner_secrets_dir
from deeptutor.video_learning.invidious_auth import AuthStateStore, InvidiousTokenStore
from deeptutor.video_learning.service import TimedMediaStore


@pytest.fixture
def client_and_store(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("deeptutor.multi_user.paths.SYSTEM_ROOT", tmp_path / "system")
    store = TimedMediaStore(root=tmp_path / "timed_media")
    monkeypatch.setattr("deeptutor.video_learning.service.get_timed_media_store", lambda: store)
    monkeypatch.setattr("deeptutor.api.routers.video_learning.get_timed_media_store", lambda: store)

    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_integrations_settings",
        lambda: {
            "invidious_base_url": "http://127.0.0.1:3000",
            "invidious_public_base_url": "http://100.101.207.44:3000",
        },
    )
    monkeypatch.setattr(
        "deeptutor.services.config.runtime_settings.load_system_settings",
        lambda: {"next_public_api_base_external": "http://100.101.207.44:8001"},
    )

    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/v1/video-learning")
    app.include_router(video_learning.public_router, prefix="/api/v1/video-learning")
    client = TestClient(app)
    return client, store


def test_invidious_status_unconnected(client_and_store):
    client, _ = client_and_store
    resp = client.get("/api/v1/video-learning/invidious/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["configured"] is True
    assert data["connected"] is False
    assert data["invidious_public_base_url"] == "http://100.101.207.44:3000"


def test_invidious_authorize_url(client_and_store):
    client, _ = client_and_store
    resp = client.get("/api/v1/video-learning/invidious/authorize")
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert "100.101.207.44:3000/authorize_token" in url
    assert "scopes=" in url


def test_video_subtitles_are_served_as_webvtt(client_and_store):
    client, store = client_and_store
    material = store.create(
        {
            "type": "timed_media",
            "source": {
                "provider": "youtube",
                "video_id": "dQw4w9WgXcQ",
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "duration_seconds": 3662,
            },
            "metadata": {"title": "Test Song", "author": "Singer", "duration_seconds": 3662, "chapters": []},
            "transcript": {
                "language": "en",
                "source": "invidious",
                "cues": [
                    {"start": 1.25, "end": 2.5, "text": "Safe <caption> & text"},
                    {"start": 3661.05, "end": 3661.2, "text": "Final line"},
                ],
            },
            "segments": [],
            "playback": {"formats": {}, "official_url": "https://youtu.be/dQw4w9WgXcQ"},
            "learning": {"last_position": 0, "notes": []},
        }
    )

    resp = client.get(f"/api/v1/video-learning/materials/{material['material_id']}/subtitles.vtt")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/vtt")
    assert resp.headers["cache-control"] == "no-store"
    assert resp.text == (
        "WEBVTT\n\n"
        "1\n"
        "00:00:01.250 --> 00:00:02.500\n"
        "Safe &lt;caption&gt; &amp; text\n\n"
        "2\n"
        "01:01:01.050 --> 01:01:01.200\n"
        "Final line\n"
    )


def test_video_note_persists_optional_subtitle_quote(client_and_store):
    client, store = client_and_store
    material = store.create(
        {
            "type": "timed_media",
            "source": {"provider": "youtube", "video_id": "dQw4w9WgXcQ", "duration_seconds": 120},
            "metadata": {"title": "Lesson", "duration_seconds": 120, "chapters": []},
            "transcript": {
                "language": "en",
                "source": "invidious",
                "cues": [{"start": 10, "end": 18, "text": "Gradient descent finds a local minimum."}],
            },
            "segments": [],
            "playback": {"formats": {}, "official_url": "https://youtu.be/dQw4w9WgXcQ"},
            "learning": {"last_position": 0, "notes": []},
        }
    )
    material_id = material["material_id"]

    response = client.post(
        f"/api/v1/video-learning/materials/{material_id}/notes",
        json={
            "text": "Core idea",
            "time_seconds": 10,
            "quote": "  Gradient descent finds a local minimum.  ",
        },
    )
    legacy = client.post(
        f"/api/v1/video-learning/materials/{material_id}/notes",
        json={"text": "Timestamp only", "time_seconds": 20},
    )

    assert response.status_code == 201
    assert response.json()["quote"] == "Gradient descent finds a local minimum."
    assert legacy.status_code == 201
    assert legacy.json()["quote"] == ""
    saved_notes = store.get(material_id)["learning"]["notes"]
    assert [note["text"] for note in saved_notes] == ["Core idea", "Timestamp only"]


@pytest.mark.asyncio
async def test_invidious_callback_flow(client_and_store):
    client, _ = client_and_store
    # Invalid state
    resp = client.get("/api/v1/video-learning/invidious/callback?token=tok123&state=badstate")
    assert resp.status_code == 400
    assert "Authorization Expired" in resp.text

    # Valid state
    state = await AuthStateStore.create_state(current_owner_id())
    resp = client.get(f"/api/v1/video-learning/invidious/callback?token=my_secret_token&state={state}")
    assert resp.status_code == 200
    assert "Connected to Invidious!" in resp.text
    assert resp.headers.get("cache-control") == "no-store, no-cache, must-revalidate, max-age=0"

    # Token stored securely
    assert InvidiousTokenStore.get_token(current_owner_id()) == "my_secret_token"

    # Disconnect
    resp = client.post("/api/v1/video-learning/invidious/disconnect")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert InvidiousTokenStore.get_token(current_owner_id()) is None


@pytest.mark.asyncio
async def test_watch_progress_and_history_sync(client_and_store, monkeypatch):
    client, store = client_and_store
    owner = current_owner_id()
    InvidiousTokenStore.set_token(owner, "auth_token_xyz")

    synced_videos = []

    class MockTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "/api/v1/auth/history/" in url:
                video_id = url.split("/api/v1/auth/history/")[-1]
                synced_videos.append(video_id)
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(404)

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "deeptutor.video_learning.invidious_auth.httpx.AsyncClient",
        lambda *args, **kwargs: real_async_client(transport=MockTransport()),
    )

    material = store.create({
        "type": "timed_media",
        "source": {
            "provider": "youtube",
            "video_id": "dQw4w9WgXcQ",
            "url": "https://youtu.be/dQw4w9WgXcQ",
            "duration_seconds": 200,
        },
        "metadata": {"title": "Test Song", "author": "Singer", "duration_seconds": 200, "chapters": []},
        "transcript": {"language": "en", "source": "invidious", "cues": []},
        "segments": [],
        "playback": {"formats": {}, "official_url": "https://youtu.be/dQw4w9WgXcQ"},
        "learning": {"last_position": 0, "notes": []},
    })
    mat_id = material["material_id"]

    # Threshold for 200s is min(30s, 0.10 * 200) = 20s.
    # 1. Below threshold: 10s playback -> not synced
    resp = client.post(
        f"/api/v1/video-learning/materials/{mat_id}/watch-progress",
        json={"time_seconds": 10.0, "cumulative_played_seconds": 10.0},
    )
    assert resp.status_code == 200
    assert resp.json()["synced_to_invidious"] is False
    assert len(synced_videos) == 0

    # 2. At threshold: 25s playback -> synced!
    resp = client.post(
        f"/api/v1/video-learning/materials/{mat_id}/watch-progress",
        json={"time_seconds": 25.0, "cumulative_played_seconds": 25.0},
    )
    assert resp.status_code == 200
    assert resp.json()["synced_to_invidious"] is True
    assert synced_videos == ["dQw4w9WgXcQ"]

    # 3. Subsequent calls should be idempotent and not call sync again
    resp = client.post(
        f"/api/v1/video-learning/materials/{mat_id}/watch-progress",
        json={"time_seconds": 30.0, "cumulative_played_seconds": 30.0},
    )
    assert resp.status_code == 200
    assert resp.json()["synced_to_invidious"] is True
    assert len(synced_videos) == 1  # Not duplicated
