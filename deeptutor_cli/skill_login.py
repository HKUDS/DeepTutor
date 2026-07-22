"""
Browser OAuth login for skill hubs (loopback token capture)
============================================================

``deeptutor skills login`` opens the hub's GitHub/Google authorization page in
a browser and captures the minted API token via a one-shot loopback server on
``127.0.0.1``. The hub only ever redirects the token to ``127.0.0.1:<port>``
(host fixed server-side), and we verify an opaque ``state`` nonce on the way
back — so a stray request can't slip a token into the store.

The URL building and origin derivation are pure functions so they can be
unit-tested without standing up a browser flow.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import http.server
import secrets
import threading
import urllib.parse
import webbrowser

_SUCCESS_HTML = (
    "<!doctype html><meta charset=utf-8><title>登录成功</title>"
    "<body style='font:16px system-ui;text-align:center;padding:3rem'>"
    "<h2>✓ 已登录 EduHub</h2><p>令牌已交给命令行，可以关闭此页面返回终端。</p></body>"
)
_ERROR_HTML = (
    "<!doctype html><meta charset=utf-8><title>登录失败</title>"
    "<body style='font:16px system-ui;text-align:center;padding:3rem'>"
    "<h2>登录失败</h2><p>请回到终端查看错误信息并重试。</p></body>"
)


@dataclass(slots=True)
class LoginResult:
    token: str | None
    login: str | None
    error: str | None


def hub_origin_from_base(base_url: str) -> str:
    """Derive the web origin from a hub's ``/api/v1`` base URL.

    ``https://eduhub.deeptutor.info/api/v1`` -> ``https://eduhub.deeptutor.info``.
    """
    b = base_url.rstrip("/")
    for suffix in ("/api/v1", "/api"):
        if b.endswith(suffix):
            return b[: -len(suffix)]
    return b


def oauth_start_url(origin: str, provider: str, *, port: int, state: str) -> str:
    """The hub OAuth start URL carrying the CLI loopback port + state nonce."""
    query = urllib.parse.urlencode({"cli_port": port, "cli_state": state})
    return f"{origin.rstrip('/')}/api/auth/oauth/{provider}?{query}"


def run_login(
    origin: str,
    provider: str,
    *,
    on_url: Callable[[str], None] | None = None,
    open_browser: bool = True,
    timeout: float = 300.0,
) -> LoginResult:
    """Run the loopback OAuth dance and return the captured token.

    Stands up a loopback server on an ephemeral port, opens (or prints) the
    authorize URL, then blocks until the hub redirects back with a token whose
    ``state`` matches, or ``timeout`` elapses.
    """
    state = secrets.token_urlsafe(24)
    captured: dict[str, str | None] = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = urllib.parse.parse_qs(parsed.query)

            def first(key: str) -> str | None:
                values = params.get(key)
                return values[0] if values else None

            if first("state") != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"state mismatch")
                return
            captured["token"] = first("token")
            captured["login"] = first("login")
            captured["error"] = first("error")
            ok = bool(captured.get("token")) and not captured.get("error")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((_SUCCESS_HTML if ok else _ERROR_HTML).encode("utf-8"))
            done.set()

        def log_message(self, *args: object) -> None:  # silence default logging
            return

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    url = oauth_start_url(origin, provider, port=port, state=state)

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if on_url:
            on_url(url)
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass  # headless / no browser — user opens the printed URL
        if not done.wait(timeout):
            return LoginResult(None, None, "登录超时（未在浏览器完成授权）")
    finally:
        server.shutdown()
        server.server_close()

    return LoginResult(captured.get("token"), captured.get("login"), captured.get("error"))


__all__ = ["LoginResult", "hub_origin_from_base", "oauth_start_url", "run_login"]
