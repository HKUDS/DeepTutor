from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import video_remote_control
from deeptutor.api.routers.auth import require_auth
from deeptutor.services.auth import TokenPayload
from deeptutor.services.path_service import PathService
from deeptutor.services.tunnel_handoff import TunnelState


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


def test_renderer_uses_configured_origin_and_watch_position(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    monkeypatch.setattr(
        video_remote_control,
        "get_invidious_public_base_url",
        lambda: "https://tunnel.invidious.example",
    )
    captured: list[str] = []
    monkeypatch.setattr(
        video_remote_control,
        "generate_qr_data_url",
        lambda launch_url: captured.append(launch_url) or ("data:image/svg+xml,test", ""),
    )
    app = FastAPI()
    app.include_router(video_remote_control.router, prefix="/api/v1/video-learning")
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/video-learning/renderers",
            json={"video_id": "dQw4w9WgXcQ", "position_seconds": 42},
        )
        assert created.status_code == 200
        ticket = created.json()["ticket"]
        assert captured[-1] == (
            f"https://tunnel.invidious.example/watch?v=dQw4w9WgXcQ&t=42#dt_bootstrap={ticket}"
        )

        invalid = client.post(
            "/api/v1/video-learning/renderers",
            json={"video_id": "short"},
        )
        assert invalid.status_code == 422
    PathService.reset_instance()


def test_phone_handoff_binds_latest_controller_cookie(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    monkeypatch.setattr(
        video_remote_control,
        "get_invidious_public_base_url",
        lambda: "https://invidious.example",
    )
    monkeypatch.setattr(
        video_remote_control,
        "load_tunnel_state",
        lambda: TunnelState(
            url="https://deeptutor.example", host="deeptutor.example"
        ),
    )
    monkeypatch.setattr(
        video_remote_control,
        "_token_payload_for_owner",
        lambda owner_id: TokenPayload("alice", "admin", owner_id),
    )
    monkeypatch.setattr(
        video_remote_control,
        "get_current_user",
        lambda: SimpleNamespace(id="owner-a"),
    )
    secrets_captured: list[str] = []

    def fake_pairing(payload, redirect_path, viewer_session_id, controller_secret):
        secrets_captured.append(controller_secret)
        assert redirect_path == f"/video-learning?viewer_session={viewer_session_id}"
        return "pairing-id", 120

    monkeypatch.setattr(video_remote_control, "create_phone_pairing", fake_pairing)
    app = FastAPI()
    app.include_router(video_remote_control.router, prefix="/api/v1/video-learning")
    app.dependency_overrides[require_auth] = lambda: None
    with TestClient(app) as client:
        created = client.post("/api/v1/video-learning/renderers", json={})
        assert created.status_code == 200
        ticket = created.json()["ticket"]
        redeemed = client.post(
            "/api/v1/video-learning/renderers/bootstrap", json={"ticket": ticket}
        ).json()
        device_id = redeemed["device_id"]
        auth = {"Authorization": f"VideoLearning {device_id}:{redeemed['token']}"}
        synced = client.post(
            "/api/v1/video-learning/player/sync",
            headers=auth,
            json={
                "instance_origin": "https://invidious.example",
                "video_id": "dQw4w9WgXcQ",
                "title": "Demo",
                "position_ms": 12_000,
                "duration_ms": 120_000,
                "playback_state": "playing",
            },
        )
        assert synced.status_code == 200
        session_id = synced.json()["session"]["session_id"]

        handoff = client.post("/api/v1/video-learning/player/phone-handoff", headers=auth)
        assert handoff.status_code == 200
        assert handoff.json()["qr_url"] == "https://deeptutor.example/access/device?pairing=pairing-id"

        command_url = f"/api/v1/video-learning/sessions/{session_id}/commands"
        assert client.post(command_url, json={"type": "pause"}).status_code == 403
        client.cookies.set("dt_video_controller", f"{session_id}:wrong")
        assert (
            client.post(command_url, json={"type": "pause"}).status_code
            == 403
        )
        client.cookies.set(
            "dt_video_controller", f"{session_id}:{secrets_captured[0]}"
        )
        volume = client.post(
            command_url,
            json={"type": "volume", "volume": 35},
        )
        assert volume.status_code == 200
        assert volume.json()["payload"] == {"volume": 35}
        rate = client.post(
            command_url,
            json={"type": "playback_rate", "playback_rate": 1.5},
        )
        assert rate.status_code == 200

        replaced = client.post("/api/v1/video-learning/player/phone-handoff", headers=auth)
        assert replaced.status_code == 200
        assert (
            client.post(command_url, json={"type": "pause"}).status_code
            == 403
        )
        client.cookies.set(
            "dt_video_controller", f"{session_id}:{secrets_captured[1]}"
        )
        seek = client.post(
            command_url,
            json={"type": "seek", "delta_ms": -20_000},
        )
        assert seek.status_code == 200
        assert seek.json()["payload"] == {"position_ms": 0}
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
