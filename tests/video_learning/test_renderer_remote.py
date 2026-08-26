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
        created = client.post(
            "/api/v1/video-learning/renderers",
            json={"device_name": "iPad", "invidious_origin": "http://127.0.0.1:4302"},
        )
        assert created.status_code == 200
        ticket = created.json()["ticket"]
        redeemed = client.post(
            "/api/v1/video-learning/renderers/bootstrap",
            json={"ticket": ticket},
        )
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


def test_renderer_bootstrap_exchanges_one_time_invidious_login(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    monkeypatch.setattr(
        video_remote_control,
        "get_invidious_public_base_url",
        lambda: "https://invidious.example",
    )
    monkeypatch.setattr(
        video_remote_control.InvidiousTokenStore,
        "has_token",
        classmethod(lambda cls, owner_id: True),
    )
    async def fake_handoff(owner_id: str):
        return {
            "exchange_code": "one-time-exchange-code",
            "session_id": "server-only-session-id",
            "expires_at": 1893456000,
        }

    monkeypatch.setattr(video_remote_control, "create_renderer_session_handoff", fake_handoff)

    app = FastAPI()
    app.include_router(video_remote_control.router, prefix="/api/v1/video-learning")
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-learning/renderers",
            json={"invidious_origin": "https://invidious.example"},
        )
        assert created.status_code == 200
        assert created.json()["invidious_login_available"] is True
        ticket = created.json()["ticket"]

        redeemed = client.post(
            "/api/v1/video-learning/renderers/bootstrap",
            json={"ticket": ticket},
        )
        assert redeemed.status_code == 200
        login = redeemed.json()["invidious_login"]
        assert login["origin"] == "https://invidious.example"
        assert login["exchange_code"] == "one-time-exchange-code"
    assert "session_id" not in login
    assert "session_id" not in created.json()["qr_data_url"]
    PathService.reset_instance()


def test_renderer_qr_targets_feed_without_losing_fragment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    captured: dict[str, str] = {}

    def capture_qr(launch_url: str) -> tuple[str, str]:
        captured["launch_url"] = launch_url
        return "data:image/svg+xml,test", ""

    monkeypatch.setattr(video_remote_control, "generate_qr_data_url", capture_qr)
    app = FastAPI()
    app.include_router(video_remote_control.router, prefix="/api/v1/video-learning")
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-learning/renderers",
            json={
                "device_name": "iPad",
                "invidious_origin": "https://invidious.example",
            },
        )
        assert created.status_code == 200
        ticket = created.json()["ticket"]
        assert captured["launch_url"] == (
            f"https://invidious.example/feed/popular#dt_bootstrap={ticket}"
        )
    PathService.reset_instance()
