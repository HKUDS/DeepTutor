from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.api.routers.auth import require_admin, require_auth
from deeptutor.video_learning import service


class _Paths:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_workspace_feature_dir(self, feature: str) -> Path:
        assert feature == "timed_media"
        return self.root / feature


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setattr(service, "get_current_path_service", lambda: _Paths(tmp_path))
    monkeypatch.setattr(
        service, "video_learning_settings_path", lambda: tmp_path / "video_learning.json"
    )
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/v1/video-learning")
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


def test_main_mounts_settings_as_admin_only_and_learning_as_authenticated() -> None:
    from deeptutor.api.main import app

    mounts: dict[str, set[object]] = {}
    for route in app.routes:
        path = str(getattr(route, "path", ""))
        if path.startswith("/api/v1/settings/video-learning"):
            key = "/api/v1/settings/video-learning"
        elif path.startswith("/api/v1/video-learning"):
            key = "/api/v1/video-learning"
        else:
            continue
        mounts.setdefault(key, set()).update(
            dependency.call for dependency in route.dependant.dependencies
        )
    assert require_admin in mounts["/api/v1/settings/video-learning"]
    assert require_auth in mounts["/api/v1/video-learning"]


def test_progress_clamps_to_duration_and_unknown_material_is_404(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)
    material_id = str(material["material_id"])

    response = client.put(
        f"/api/v1/video-learning/materials/{material_id}/progress",
        json={"time_seconds": 125, "duration_seconds": 100},
    )
    assert response.status_code == 200
    assert response.json() == {"time_seconds": 100.0, "duration_seconds": 100.0}
    assert service.get_timed_media_store().get(material_id)["learning"]["last_position"] == 100

    missing = client.get("/api/v1/video-learning/materials/0123456789abcdef")
    assert missing.status_code == 404


def test_progress_does_not_replace_known_duration_with_client_value(client: TestClient) -> None:
    material = _material(duration=100)
    service.get_timed_media_store().save(material)
    response = client.put(
        f"/api/v1/video-learning/materials/{material['material_id']}/progress",
        json={"time_seconds": 50, "duration_seconds": 10},
    )
    assert response.json() == {"time_seconds": 50.0, "duration_seconds": 100.0}


def test_subtitles_are_valid_vtt_and_escape_markup(client: TestClient) -> None:
    material = _material()
    service.get_timed_media_store().save(material)

    response = client.get(
        f"/api/v1/video-learning/materials/{material['material_id']}/subtitles.vtt"
    )

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
        f"/api/v1/video-learning/materials/{service.material_id_for('dQw4w9WgXcQ')}/stream/18",
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
        f"/api/v1/video-learning/materials/{material['material_id']}/stream/18",
        headers={"Range": "bytes=0-10"},
    )

    assert response.status_code == 206
    assert response.content == b"video-bytes"
    assert response.headers["content-range"] == "bytes 0-10/100"
    assert upstream_client.closed is True
