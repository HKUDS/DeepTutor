from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

import pytest
from starlette.testclient import TestClient

from deeptutor.runtime import spa_server


def _write_spa(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text("<html><body>spa</body></html>", encoding="utf-8")
    assets = root / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('ok')", encoding="utf-8")
    return root


class _BackendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = json.dumps({"path": self.path, "cookie": self.headers.get("Cookie", "")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _serve_backend() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BackendHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


def test_backend_path_rewrites_codex_callback() -> None:
    assert spa_server.backend_path("/auth/callback") == spa_server.CODEX_CALLBACK_API_PATH
    assert spa_server.backend_path("/api/v1/sessions") == "/api/v1/sessions"
    assert spa_server.is_proxied_path("/api/v1/ws")
    assert spa_server.is_proxied_path("/auth/callback")
    assert not spa_server.is_proxied_path("/")


def test_resolve_api_base_prefers_ipv4_loopback() -> None:
    assert spa_server.resolve_api_base("") == "http://127.0.0.1:8001"
    assert spa_server.resolve_api_base("http://backend:8001/") == "http://backend:8001"


def test_spa_serves_index_and_assets(tmp_path: Path) -> None:
    spa_dir = _write_spa(tmp_path / "dist")
    app = spa_server.create_app(spa_dir=spa_dir, api_base="http://127.0.0.1:9")
    with TestClient(app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert "spa" in home.text

        asset = client.get("/assets/app.js")
        assert asset.status_code == 200
        assert "console.log" in asset.text

        fallback = client.get("/session/abc")
        assert fallback.status_code == 200
        assert "spa" in fallback.text


def test_missing_assets_return_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spa_server, "resolve_spa_dir", lambda raw=None: None)
    app = spa_server.create_app(spa_dir=None, api_base="http://127.0.0.1:9")
    with TestClient(app) as client:
        assert client.get("/").status_code == 503


def test_http_proxy_forwards_api_and_callback(tmp_path: Path) -> None:
    spa_dir = _write_spa(tmp_path / "dist")
    server, api_base = _serve_backend()
    try:
        app = spa_server.create_app(spa_dir=spa_dir, api_base=api_base)
        with TestClient(app) as client:
            sessions = client.get("/api/v1/sessions", headers={"Cookie": "dt_token=abc"})
            assert sessions.status_code == 200
            payload = sessions.json()
            assert payload["path"] == "/api/v1/sessions"
            assert payload["cookie"] == "dt_token=abc"

            callback = client.get("/auth/callback?code=1")
            assert callback.status_code == 200
            assert callback.json()["path"] == "/api/v1/auth/openai-codex/callback?code=1"
    finally:
        server.shutdown()
        server.server_close()
