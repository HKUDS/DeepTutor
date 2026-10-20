"""Tests for the opt-in fastapi-guard integration (deeptutor/api/security_guard.py).

Guard state (rate-limit windows, ban lists) is process-wide, so every test uses
its own client address from ``_unique_ip``. The requests are driven straight
through the ASGI interface so the peer address (``scope["client"]``) is under the
test's control and streaming responses are observed chunk by chunk.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from copy import deepcopy
import importlib.util
import itertools
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import pytest

from deeptutor.api.security_guard import INSTALL_HINT, install_security_guard
from deeptutor.services.config.runtime_settings import (
    DEFAULT_SYSTEM_SETTINGS,
    RuntimeSettingsService,
)

requires_guard = pytest.mark.skipif(
    importlib.util.find_spec("guard") is None,
    reason="fastapi-guard is an optional extra (deeptutor[guard])",
)

_REPO = Path(__file__).resolve().parents[2]
_ORIGIN = "http://localhost:3000"
_ip_counter = itertools.count(1)


def _unique_ip() -> str:
    n = next(_ip_counter)
    return f"198.18.{n // 250}.{n % 250 + 1}"


def _guard_settings(**overrides: Any) -> dict[str, Any]:
    settings = deepcopy(DEFAULT_SYSTEM_SETTINGS["security_guard"])
    settings["enabled"] = True
    settings.update(overrides)
    return settings


def _build_app(**overrides: Any) -> FastAPI:
    app = FastAPI()
    assert install_security_guard(app, _guard_settings(**overrides)) is True
    # Same order as deeptutor/api/main.py: the guard first, CORS added last.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[_ORIGIN],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, Any]:
        return {"body": (await request.body()).decode()}

    return app


async def _call(
    app: Any,
    path: str = "/ping",
    *,
    method: str = "GET",
    query: str = "",
    headers: Iterable[tuple[str, str]] = (),
    client: tuple[str, int] | None = ("127.0.0.1", 50000),
    body: bytes = b"",
) -> tuple[int, dict[str, str], bytes]:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers],
        "client": client,
        "server": ("testserver", 80),
    }
    sent_body = False

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    status = 0
    response_headers: dict[str, str] = {}
    chunks: list[bytes] = []

    async def send(message: dict[str, Any]) -> None:
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]
            response_headers.update({k.decode().lower(): v.decode() for k, v in message["headers"]})
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await app(scope, receive, send)
    return status, response_headers, b"".join(chunks)


def _run_python(code: str, tmp_path: Path, **env: str) -> subprocess.CompletedProcess[str]:
    import os

    child_env = {**os.environ, "DEEPTUTOR_HOME": str(tmp_path), **env}
    for key in ("DEEPTUTOR_GUARD_ENABLED", "DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES"):
        if key not in env:
            child_env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO,
        env=child_env,
        capture_output=True,
        check=True,
        text=True,
    )


_STACK_PROBE = """
import json, sys
import deeptutor.api.main as m
print(json.dumps({
    "stack": [layer.cls.__name__ for layer in m.app.user_middleware],
    "guard_imported": "guard" in sys.modules or "guard_core" in sys.modules,
}))
"""


# --- opt-in behaviour -------------------------------------------------------


def test_disabled_by_default_never_imports_guard(tmp_path: Path) -> None:
    result = _run_python(_STACK_PROBE, tmp_path)
    probe = json.loads(result.stdout.strip().splitlines()[-1])

    assert probe["guard_imported"] is False
    assert "PureASGISecurityMiddleware" not in probe["stack"]
    assert probe["stack"][0] == "CORSMiddleware"


def test_disabled_settings_add_nothing() -> None:
    app = FastAPI()
    settings = _guard_settings(enabled=False)

    assert install_security_guard(app, settings) is False
    assert app.user_middleware == []


def test_enabled_without_package_fails_with_install_hint(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "guard", None)  # `import guard` raises ImportError

    with pytest.raises(RuntimeError, match=r"deeptutor\[guard\]") as excinfo:
        install_security_guard(FastAPI(), _guard_settings())

    assert str(excinfo.value) == INSTALL_HINT


@requires_guard
def test_enabled_main_app_keeps_cors_outermost(tmp_path: Path) -> None:
    result = _run_python(_STACK_PROBE, tmp_path, DEEPTUTOR_GUARD_ENABLED="true")
    probe = json.loads(result.stdout.strip().splitlines()[-1])

    # user_middleware is outermost first.
    assert probe["stack"][0] == "CORSMiddleware"
    assert probe["stack"].count("PureASGISecurityMiddleware") == 1
    assert probe["stack"].index("PureASGISecurityMiddleware") > 0
    assert probe["guard_imported"] is True


def test_settings_defaults_json_and_env_overrides(tmp_path: Path) -> None:
    defaults = RuntimeSettingsService(tmp_path / "a", process_env={}).load_system()[
        "security_guard"
    ]
    assert defaults == {
        "enabled": False,
        "rate_limit": 300,
        "rate_limit_window": 60,
        "trusted_proxies": ["127.0.0.1", "::1"],
        "exempt_ips": ["127.0.0.1", "::1"],
        "whitelist": [],
        "blacklist": [],
    }

    overridden = RuntimeSettingsService(
        tmp_path / "b",
        process_env={
            "DEEPTUTOR_GUARD_ENABLED": "1",
            "DEEPTUTOR_GUARD_RATE_LIMIT": "50",
            "DEEPTUTOR_GUARD_RATE_LIMIT_WINDOW": "10",
            "DEEPTUTOR_GUARD_TRUSTED_PROXIES": "10.0.0.0/8, 192.168.1.5",
            "DEEPTUTOR_GUARD_EXEMPT_IPS": "10.1.2.3; 10.9.0.0/16",
            "DEEPTUTOR_GUARD_WHITELIST": "203.0.113.0/24",
            "DEEPTUTOR_GUARD_BLACKLIST": "198.51.100.9",
        },
    ).load_system()["security_guard"]
    assert overridden == {
        "enabled": True,
        "rate_limit": 50,
        "rate_limit_window": 10,
        "trusted_proxies": ["10.0.0.0/8", "192.168.1.5"],
        "exempt_ips": ["10.1.2.3", "10.9.0.0/16"],
        "whitelist": ["203.0.113.0/24"],
        "blacklist": ["198.51.100.9"],
    }

    # system.json: an explicit empty list means "trust no proxy" (not the default).
    from_file = RuntimeSettingsService(tmp_path / "c", process_env={})
    system = from_file.load_system(include_process_overrides=False)
    system["security_guard"] = {"enabled": True, "trusted_proxies": [], "exempt_ips": []}
    from_file.save_system(system)
    saved = from_file.load_system()["security_guard"]
    assert saved["enabled"] is True
    assert saved["trusted_proxies"] == []
    assert saved["exempt_ips"] == []
    assert saved["rate_limit"] == 300


@requires_guard
def test_security_config_is_stateless_and_scoped() -> None:
    from deeptutor.api.security_guard import build_security_config

    config = build_security_config(_guard_settings(trusted_proxies=[]))

    assert config.enable_redis is False
    assert config.enable_cors is False
    assert config.security_headers == {"enabled": False}
    assert config.detection_scan_body is False
    assert config.enable_agent is False
    assert config.trusted_proxies == ()
    assert config.exempt_ips == ("127.0.0.1", "::1")
    assert (config.rate_limit, config.rate_limit_window) == (300, 60)


# --- request screening ------------------------------------------------------


@requires_guard
@pytest.mark.asyncio
async def test_rate_limit_burst_returns_429_with_cors_header() -> None:
    app = _build_app(rate_limit=3, rate_limit_window=60, trusted_proxies=[])
    ip = _unique_ip()
    headers = [("origin", _ORIGIN)]

    statuses = [(await _call(app, client=(ip, 1), headers=headers))[0] for _ in range(3)]
    status, response_headers, _ = await _call(app, client=(ip, 1), headers=headers)

    assert statuses == [200, 200, 200]
    assert status == 429
    assert response_headers["access-control-allow-origin"] == _ORIGIN


@requires_guard
@pytest.mark.asyncio
async def test_allowlist_rejects_other_addresses_with_403() -> None:
    allowed = _unique_ip()
    app = _build_app(whitelist=[allowed], trusted_proxies=[])

    status_other, headers_other, _ = await _call(
        app, client=(_unique_ip(), 1), headers=[("origin", _ORIGIN)]
    )
    status_allowed, _, _ = await _call(app, client=(allowed, 1))

    assert status_other == 403
    assert headers_other["access-control-allow-origin"] == _ORIGIN
    assert status_allowed == 200


@requires_guard
@pytest.mark.asyncio
async def test_spoofed_forwarded_for_is_ignored_from_untrusted_peer() -> None:
    app = _build_app(rate_limit=3, rate_limit_window=60)  # trusts loopback only
    peer = _unique_ip()

    statuses = [
        (await _call(app, client=(peer, 1), headers=[("x-forwarded-for", _unique_ip())]))[0]
        for _ in range(4)
    ]

    assert statuses == [200, 200, 200, 429]


@requires_guard
@pytest.mark.asyncio
async def test_forwarded_for_is_honoured_from_trusted_proxy() -> None:
    app = _build_app(rate_limit=2, rate_limit_window=60)  # trusts loopback
    client_a, client_b = _unique_ip(), _unique_ip()

    def via_proxy(client_ip: str):
        return _call(app, client=("127.0.0.1", 1), headers=[("x-forwarded-for", client_ip)])

    a = [(await via_proxy(client_a))[0] for _ in range(3)]
    b = (await via_proxy(client_b))[0]

    assert a == [200, 200, 429]
    assert b == 200  # a different forwarded client has its own window


@requires_guard
@pytest.mark.asyncio
async def test_loopback_without_forwarded_for_is_not_rate_limited() -> None:
    """The bundled frontend arrives as loopback with no X-Forwarded-For."""
    app = _build_app(rate_limit=3, rate_limit_window=60)

    statuses = [(await _call(app, client=("127.0.0.1", 1)))[0] for _ in range(8)]

    assert statuses == [200] * 8


@requires_guard
@pytest.mark.asyncio
async def test_loopback_attack_query_is_still_blocked() -> None:
    app = _build_app(rate_limit=3, rate_limit_window=60)

    status, _, _ = await _call(app, client=("127.0.0.1", 1), query="q=<script>alert(1)</script>")

    assert status == 400


@requires_guard
@pytest.mark.asyncio
async def test_lan_peer_is_still_rate_limited_with_loopback_exempt() -> None:
    app = _build_app(rate_limit=3, rate_limit_window=60)
    peer = _unique_ip()

    statuses = [(await _call(app, client=(peer, 1)))[0] for _ in range(4)]

    assert statuses == [200, 200, 200, 429]


@requires_guard
@pytest.mark.asyncio
async def test_loopback_with_forwarded_for_stays_limited_per_forwarded_client() -> None:
    app = _build_app(rate_limit=3, rate_limit_window=60)
    forwarded = _unique_ip()

    statuses = [
        (await _call(app, client=("127.0.0.1", 1), headers=[("x-forwarded-for", forwarded)]))[0]
        for _ in range(4)
    ]

    assert statuses == [200, 200, 200, 429]


@requires_guard
@pytest.mark.asyncio
async def test_allowlist_without_loopback_refuses_the_bundled_frontend() -> None:
    app = _build_app(whitelist=[_unique_ip()])

    status, _, _ = await _call(app, client=("127.0.0.1", 1))

    assert status == 403


@requires_guard
@pytest.mark.asyncio
async def test_allowlist_with_loopback_admits_the_bundled_frontend() -> None:
    app = _build_app(whitelist=["127.0.0.1", "::1"])

    status, _, _ = await _call(app, client=("127.0.0.1", 1))

    assert status == 200


@requires_guard
@pytest.mark.asyncio
async def test_attack_pattern_in_query_is_blocked_with_400() -> None:
    app = _build_app(trusted_proxies=[])

    status, _, _ = await _call(app, client=(_unique_ip(), 1), query="q=<script>alert(1)</script>")

    assert status == 400


@requires_guard
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "referer",
    ["http://localhost:3000/chat", "http://127.0.0.1:3000/", "http://192.168.50.199:3782/"],
)
async def test_browser_referer_with_local_address_is_allowed(referer: str) -> None:
    app = _build_app(trusted_proxies=[])

    status, _, _ = await _call(app, client=(_unique_ip(), 1), headers=[("referer", referer)])

    assert status == 200


@requires_guard
@pytest.mark.asyncio
async def test_referer_carrying_an_attack_pattern_is_still_blocked() -> None:
    app = _build_app(trusted_proxies=[])

    status, _, _ = await _call(
        app,
        client=(_unique_ip(), 1),
        headers=[("referer", "http://localhost:3000/<script>alert(1)</script>")],
    )

    assert status == 400


@requires_guard
@pytest.mark.asyncio
async def test_request_body_is_not_scanned() -> None:
    app = _build_app(trusted_proxies=[])
    payload = b"explain <script>alert(1)</script> and ' OR 1=1 -- in my homework"

    status, _, body = await _call(
        app,
        "/echo",
        method="POST",
        client=(_unique_ip(), 1),
        headers=[("content-type", "text/plain")],
        body=payload,
    )

    assert status == 200
    assert json.loads(body)["body"] == payload.decode()


@requires_guard
@pytest.mark.asyncio
async def test_streaming_chunks_are_delivered_incrementally() -> None:
    app = _build_app(trusted_proxies=[])
    release: list[asyncio.Event] = [asyncio.Event() for _ in range(3)]

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def gen():
            for index, gate in enumerate(release):
                yield f"chunk{index}".encode()
                await gate.wait()  # the next chunk exists only after the client saw this one

        return StreamingResponse(gen(), media_type="text/event-stream")

    seen: list[bytes] = []
    first_chunk = asyncio.Event()

    async def drive() -> None:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/stream",
            "raw_path": b"/stream",
            "query_string": b"",
            "headers": [],
            "client": (_unique_ip(), 1),
            "server": ("testserver", 80),
        }

        async def receive() -> dict[str, Any]:
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                seen.append(message["body"])
                release[len(seen) - 1].set()
                first_chunk.set()

        await app(scope, receive, send)

    # A buffering middleware would never emit chunk0 (the generator is parked on
    # its gate), so the wait below would time out instead of completing.
    task = asyncio.create_task(drive())
    await asyncio.wait_for(first_chunk.wait(), timeout=10)
    await asyncio.wait_for(task, timeout=10)

    assert seen == [b"chunk0", b"chunk1", b"chunk2"]


@requires_guard
@pytest.mark.asyncio
async def test_forwarded_for_works_for_ipv4_mapped_proxy_peer_when_mapped_form_is_listed() -> None:
    """Dual-stack binds report IPv4 peers as ``::ffff:a.b.c.d``; list that form too."""
    app = _build_app(
        rate_limit=3,
        rate_limit_window=60,
        trusted_proxies=["10.0.0.0/8", "::ffff:10.0.0.0/104"],
        exempt_ips=[],
    )
    proxy = ("::ffff:10.0.0.9", 1)
    same_client = _unique_ip()

    limited = [
        (await _call(app, client=proxy, headers=[("x-forwarded-for", same_client)]))[0]
        for _ in range(4)
    ]
    distinct = [
        (await _call(app, client=proxy, headers=[("x-forwarded-for", _unique_ip())]))[0]
        for _ in range(5)
    ]

    assert limited == [200, 200, 200, 429]
    assert distinct == [200] * 5


# --- uvicorn peer handling --------------------------------------------------


def _loaded_uvicorn_app(app: FastAPI, **kwargs: Any) -> Any:
    import uvicorn

    config = uvicorn.Config(app, log_config=None, **kwargs)
    config.load()
    return config.loaded_app


@requires_guard
@pytest.mark.asyncio
async def test_uvicorn_with_no_proxy_headers_keeps_guard_identity(monkeypatch) -> None:
    """The launch flag DeepTutor already passes keeps the socket peer as identity.

    With ``FORWARDED_ALLOW_IPS=*`` and the flag in place, rotating X-Forwarded-For
    values from one peer must not give the attacker a fresh rate-limit window.
    """
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    app = _build_app(rate_limit=3, rate_limit_window=60)  # guard trusts loopback only
    served = _loaded_uvicorn_app(app, proxy_headers=False)
    peer = _unique_ip()

    statuses = [
        (await _call(served, client=(peer, 1), headers=[("x-forwarded-for", _unique_ip())]))[0]
        for _ in range(4)
    ]

    assert statuses == [200, 200, 200, 429]


@requires_guard
@pytest.mark.asyncio
async def test_uvicorn_default_proxy_headers_would_defeat_the_limit(monkeypatch) -> None:
    """Control for the test above: without the flag the same attack succeeds."""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    app = _build_app(rate_limit=3, rate_limit_window=60)
    served = _loaded_uvicorn_app(app, proxy_headers=True)
    peer = _unique_ip()

    statuses = [
        (await _call(served, client=(peer, 1), headers=[("x-forwarded-for", _unique_ip())]))[0]
        for _ in range(4)
    ]

    assert statuses == [200, 200, 200, 200]


@requires_guard
def test_access_log_records_guard_rejections_in_main_app(tmp_path: Path) -> None:
    probe = """
from fastapi.testclient import TestClient
import deeptutor.api.main as m
client = TestClient(m.app, client=("203.0.113.9", 5000))
print([client.get("/api/auth/status").status_code for _ in range(3)])
"""
    result = _run_python(
        probe,
        tmp_path,
        DEEPTUTOR_GUARD_ENABLED="true",
        DEEPTUTOR_GUARD_RATE_LIMIT="1",
    )

    assert '203.0.113.9 - "GET /api/auth/status HTTP/1.1" 429' in result.stdout
