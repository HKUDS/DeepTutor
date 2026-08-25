from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import video_remote_control
from deeptutor.api.routers.auth import require_auth
from deeptutor.services.path_service import PathService


def test_renderer_bootstrap_presence_and_open_video(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    app = FastAPI()
    app.include_router(video_remote_control.router, prefix="/api/v1/video-learning")
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        created = client.post("/api/v1/video-learning/renderers", json={"device_name": "iPad"})
        assert created.status_code == 200
        ticket = created.json()["ticket"]
        redeemed = client.post("/api/v1/video-learning/renderers/bootstrap", json={"ticket": ticket})
        assert redeemed.status_code == 200
        data = redeemed.json()
        auth = {"Authorization": f"VideoLearning {data['device_id']}:{data['token']}"}
        assert client.post("/api/v1/video-learning/player/presence", headers=auth).status_code == 200
        opened = client.post(
            f"/api/v1/video-learning/devices/{data['device_id']}/commands",
            json={"type": "open_video", "video_id": "dQw4w9WgXcQ"},
        )
        assert opened.status_code == 200
        polled = client.post("/api/v1/video-learning/player/presence", headers=auth)
        assert polled.json()["commands"][0]["payload"] == {"video_id": "dQw4w9WgXcQ"}
    PathService.reset_instance()
