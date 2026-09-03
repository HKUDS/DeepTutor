from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.api.routers.auth import require_admin, require_learning_surface
from deeptutor.services.notebook.service import NotebookManager
from deeptutor.video_learning import notes as video_notes
from deeptutor.video_learning import service


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / feature


@pytest.fixture
def notebook_manager(tmp_path: Path) -> NotebookManager:
    return NotebookManager(base_dir=str(tmp_path / "notebooks"))


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    notebook_manager: NotebookManager,
) -> TestClient:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    monkeypatch.setattr(
        service, "video_learning_settings_path", lambda: tmp_path / "video_learning.json"
    )
    monkeypatch.setattr(video_notes, "get_notebook_manager", lambda: notebook_manager)
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/video-learning")
    return TestClient(app)


def _material(*, duration: int = 100) -> dict[str, object]:
    material_id = service.material_id_for("dQw4w9WgXcQ")
    return {
        "version": 1,
        "type": "timed_media",
        "material_id": material_id,
        "source": {
            "provider": "youtube",
            "video_id": "dQw4w9WgXcQ",
            "url": "https://youtu.be/dQw4w9WgXcQ",
        },
        "metadata": {"duration_seconds": duration},
        "transcript": {
            "status": "ready",
            "cues": [{"start": 1.25, "end": 3.5, "text": "one\n<script>two</script>"}],
        },
        "learning": {"last_position": 0},
        "provider_cache": {
            "invidious_formats": [{"format_id": "18", "mime_type": "video/mp4"}],
        },
    }


def test_main_mounts_settings_as_admin_only_and_learning_policy_scoped() -> None:
    from deeptutor.api.main import app

    async def reject_admin() -> None:
        raise HTTPException(status_code=418, detail="admin dependency called")

    async def reject_learning_surface() -> None:
        raise HTTPException(status_code=419, detail="learning policy dependency called")

    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[require_admin] = reject_admin
    app.dependency_overrides[require_learning_surface] = reject_learning_surface
    try:
        # Assert through HTTP instead of inspecting ``app.routes``. FastAPI
        # 0.141 keeps included routers nested, but dependency overrides remain
        # the public, representation-independent way to observe each gate.
        with TestClient(app) as app_client:
            settings_response = app_client.get("/api/settings/video-learning")
            learning_response = app_client.get("/api/video-learning/materials/not-a-material")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)

    assert settings_response.status_code == 418
    assert settings_response.json()["detail"] == "admin dependency called"
    assert learning_response.status_code == 419
    assert learning_response.json()["detail"] == "learning policy dependency called"


def test_progress_clamps_to_duration_and_unknown_material_is_404(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)
    material_id = str(material["material_id"])

    response = client.put(
        f"/api/video-learning/materials/{material_id}/progress",
        json={"time_seconds": 125, "duration_seconds": 100},
    )
    assert response.status_code == 200
    assert response.json() == {"time_seconds": 100.0, "duration_seconds": 100.0}
    assert service.get_timed_media_store().get(material_id)["learning"]["last_position"] == 100

    missing = client.get("/api/video-learning/materials/0123456789abcdef")
    assert missing.status_code == 404


def test_video_notes_use_notebook_storage_and_stay_material_scoped(
    client: TestClient,
    notebook_manager: NotebookManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = _material()
    service.get_timed_media_store().save(material)
    material_id = str(material["material_id"])
    notes_url = f"/api/video-learning/materials/{material_id}/notes"

    created_response = client.post(
        notes_url, json={"body": "  Revisit the opening idea.  ", "time_seconds": 2}
    )

    assert created_response.status_code == 200
    created = created_response.json()
    assert created["material_id"] == material_id
    assert created["body"] == "Revisit the opening idea."
    assert created["time_seconds"] == 2.0
    assert created["locator"] == 1
    assert "one" in created["quote"]
    assert created["notebook_id"]

    notebook = notebook_manager.get_notebook(created["notebook_id"])
    assert notebook is not None
    assert notebook["name"] == video_notes.NOTEBOOK_NAME
    assert notebook["records"][0]["type"] == "video_learning"
    assert notebook["records"][0]["metadata"]["material_id"] == material_id
    persisted = str(notebook)
    assert "https://youtu.be" not in persisted
    assert "provider_cache" not in persisted
    assert "dQw4w9WgXcQ" not in persisted

    material["metadata"]["title"] = "T" * 300
    material["transcript"]["cues"][0]["text"] = "q" * 400
    service.get_timed_media_store().save(material)
    bounded_response = client.post(notes_url, json={"body": "Note", "time_seconds": 2})
    assert bounded_response.status_code == 200
    assert len(bounded_response.json()["quote"]) <= 280
    records = notebook_manager.get_notebook(created["notebook_id"])["records"]
    assert len(records[-1]["title"]) <= 160

    updated_response = client.put(
        f"{notes_url}/{created['note_id']}", json={"body": "Updated note."}
    )
    assert updated_response.status_code == 200
    assert updated_response.json()["body"] == "Updated note."
    assert (
        notebook_manager.get_notebook(created["notebook_id"])["records"][0]["summary"]
        == "Updated note."
    )

    other_manager = NotebookManager(
        base_dir=str(notebook_manager.base_dir.parent / "other-account-notebooks")
    )
    monkeypatch.setattr(video_notes, "get_notebook_manager", lambda: other_manager)
    assert client.get(notes_url).json() == []

    monkeypatch.setattr(video_notes, "get_notebook_manager", lambda: notebook_manager)
    for note in client.get(notes_url).json():
        delete_response = client.delete(f"{notes_url}/{note['note_id']}")
        assert delete_response.status_code == 200
    assert client.get(notes_url).json() == []


def test_video_note_errors_are_bounded_and_useful(client: TestClient) -> None:
    material = _material(duration=100)
    service.get_timed_media_store().save(material)
    notes_url = f"/api/video-learning/materials/{material['material_id']}/notes"

    assert client.post(notes_url, json={"body": " ", "time_seconds": 2}).status_code == 400
    assert client.post(notes_url, json={"body": "Note", "time_seconds": 101}).status_code == 400
    assert client.post(notes_url, json={"body": "", "time_seconds": 2}).status_code == 422
    assert client.get("/api/video-learning/materials/0123456789abcdef/notes").status_code == 404
    assert client.put(f"{notes_url}/missing-note", json={"body": "Note"}).status_code == 404


def test_progress_does_not_replace_known_duration_with_client_value(client: TestClient) -> None:
    material = _material(duration=100)
    service.get_timed_media_store().save(material)
    response = client.put(
        f"/api/video-learning/materials/{material['material_id']}/progress",
        json={"time_seconds": 50, "duration_seconds": 10},
    )
    assert response.json() == {"time_seconds": 50.0, "duration_seconds": 100.0}


def test_refresh_transcript_returns_refreshed_material(client: TestClient, monkeypatch) -> None:
    material = _material()

    async def refresh(material_id: str) -> dict[str, object]:
        assert material_id == material["material_id"]
        return {**material, "transcript": {"status": "ready", "cues": []}}

    monkeypatch.setattr(video_learning, "refresh_invidious_transcript", refresh)
    response = client.post(
        f"/api/video-learning/materials/{material['material_id']}/transcript/refresh"
    )

    assert response.status_code == 200
    assert response.json()["transcript"]["status"] == "ready"


def test_refresh_transcript_returns_404_for_unknown_material(client: TestClient) -> None:
    response = client.post("/api/video-learning/materials/0123456789abcdef/transcript/refresh")

    assert response.status_code == 404


def test_subtitles_are_valid_vtt_and_escape_markup(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)

    response = client.get(f"/api/video-learning/materials/{material['material_id']}/subtitles.vtt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/vtt")
    assert "00:00:01.250 --> 00:00:03.500" in response.text
    assert "one &lt;script&gt;two&lt;/script&gt;" in response.text
    assert "\n<script>" not in response.text


@pytest.mark.parametrize(
    "url",
    [
        "http://invidious:3001/video",
        "https://redirector.googlevideo.com:8443/video",
        "http://r1.googlevideo.com/video",
        "https://googlevideo.com.evil.test/video",
    ],
)
def test_stream_redirect_guard_rejects_cross_origin_or_unsafe_media_urls(url: str) -> None:
    with pytest.raises(service.TimedMediaError):
        video_learning._allowed_stream_url(url, "http://invidious:3000")


def test_stream_redirect_guard_accepts_same_origin_and_google_media() -> None:
    assert video_learning._allowed_stream_url("/videoplayback", "http://invidious:3000") == (
        "http://invidious:3000/videoplayback"
    )
    assert video_learning._allowed_stream_url(
        "https://r1.googlevideo.com/videoplayback", "http://invidious:3000"
    ).startswith("https://r1.googlevideo.com/")
    assert video_learning._allowed_stream_url(
        "https://watch.example.test/videoplayback",
        "http://invidious:3000",
        "https://watch.example.test",
    ).startswith("https://watch.example.test/")


@pytest.mark.asyncio
async def test_live_stream_rejects_invalid_invidious_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    monkeypatch.setattr(service, "video_learning_settings_path", lambda: tmp_path / "settings.json")
    service.save_video_learning_settings(
        {
            "default_provider": "invidious",
            "invidious": {"api_base_url": "http://invidious:3000"},
        }
    )
    material = _material()
    service.get_timed_media_store().save(material)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url: str):
            return httpx.Response(200, text="not json")

    monkeypatch.setattr(video_learning.httpx, "AsyncClient", lambda **_kwargs: Client())
    with pytest.raises(service.TimedMediaError, match="invalid video metadata"):
        await video_learning._live_stream_url(str(material["material_id"]), "18")


def test_stream_rejects_multi_range_before_contacting_upstream(client: TestClient) -> None:
    response = client.get(
        f"/api/video-learning/materials/{service.material_id_for('dQw4w9WgXcQ')}/stream/18",
        headers={"Range": "bytes=0-1,4-5"},
    )
    assert response.status_code == 416


def test_stream_forwards_a_206_range_response(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    material = _material()
    service.get_timed_media_store().save(material)

    async def live_stream(_material_id: str, _format_id: str) -> tuple[str, str]:
        return "https://r1.googlevideo.com/videoplayback", "video/mp4"

    class UpstreamClient:
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    upstream_client = UpstreamClient()
    upstream_response = httpx.Response(
        206,
        content=b"video-bytes",
        headers={"Content-Range": "bytes 0-10/100", "Content-Type": "video/mp4"},
        request=httpx.Request("GET", "https://r1.googlevideo.com/videoplayback"),
    )

    async def open_upstream(_url: str, _mime: str, range_header: str | None):
        assert range_header == "bytes=0-10"
        return upstream_client, upstream_response

    monkeypatch.setattr(video_learning, "_live_stream_url", live_stream)
    monkeypatch.setattr(video_learning, "_open_upstream", open_upstream)

    response = client.get(
        f"/api/video-learning/materials/{material['material_id']}/stream/18",
        headers={"Range": "bytes=0-10"},
    )

    assert response.status_code == 206
    assert response.content == b"video-bytes"
    assert response.headers["content-range"] == "bytes 0-10/100"
    assert upstream_client.closed is True
