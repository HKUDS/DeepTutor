"""Serve the packaged Vite SPA and reverse-proxy API traffic to the backend.

The browser talks only to the frontend origin. ``/api/*`` and ``/ws/*`` are
forwarded to ``DEEPTUTOR_API_BASE_URL`` (the IPv4 loopback on the resolved
backend port, unless a split deployment set an in-network base). Codex OAuth
callbacks on ``/auth/callback`` are rewritten to the backend auth route.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
import os
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket, WebSocketDisconnect

from deeptutor.brand import PRODUCT_NAME

CODEX_CALLBACK_PATH = "/auth/callback"
CODEX_CALLBACK_API_PATH = "/api/v1/auth/openai-codex/callback"
DEFAULT_API_BASE = "http://127.0.0.1:8001"
SPA_DIR_ENV = "DEEPTUTOR_SPA_DIR"
API_BASE_ENV = "DEEPTUTOR_API_BASE_URL"

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


def resolve_api_base(raw: str | None = None) -> str:
    value = (raw if raw is not None else os.environ.get(API_BASE_ENV, "")).strip()
    return value.rstrip("/") or DEFAULT_API_BASE


def resolve_spa_dir(raw: str | None = None) -> Path | None:
    value = (raw if raw is not None else os.environ.get(SPA_DIR_ENV, "")).strip()
    if value:
        path = Path(value)
        return path if (path / "index.html").is_file() else None
    try:
        import deeptutor_web
    except ImportError:
        return None
    path = Path(deeptutor_web.__file__).resolve().parent
    return path if (path / "index.html").is_file() else None


def backend_path(pathname: str) -> str:
    if pathname == CODEX_CALLBACK_PATH:
        return CODEX_CALLBACK_API_PATH
    return pathname


def is_proxied_path(pathname: str) -> bool:
    return (
        pathname == CODEX_CALLBACK_PATH
        or pathname.startswith("/api/")
        or pathname.startswith("/ws/")
        or pathname == "/api"
        or pathname == "/ws"
    )


def _forward_request_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() not in _HOP_BY_HOP}


def _forward_response_headers(headers: httpx.Headers) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() not in _HOP_BY_HOP}


class _SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            return await super().get_response("index.html", scope)


def _ws_url(api_base: str, path: str, query: str) -> str:
    if api_base.startswith("https://"):
        target = "wss://" + api_base[len("https://") :]
    elif api_base.startswith("http://"):
        target = "ws://" + api_base[len("http://") :]
    else:
        target = api_base
    url = f"{target}{path}"
    return f"{url}?{query}" if query else url


def create_app(
    *,
    spa_dir: Path | None = None,
    api_base: str | None = None,
) -> Starlette:
    assets = spa_dir if spa_dir is not None else resolve_spa_dir()
    upstream = resolve_api_base(api_base)

    @asynccontextmanager
    async def lifespan(app: Starlette):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(None),
            limits=httpx.Limits(max_connections=100, keepalive_expiry=60.0),
            follow_redirects=False,
        ) as client:
            app.state.http = client
            app.state.api_base = upstream
            app.state.spa_dir = assets
            yield

    async def proxy_http(request: Request) -> Response:
        client: httpx.AsyncClient = request.app.state.http
        target = f"{request.app.state.api_base}{backend_path(request.url.path)}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        outbound = client.build_request(
            request.method,
            target,
            headers=_forward_request_headers(request.headers),
            content=request.stream(),
        )
        inbound = await client.send(outbound, stream=True)

        async def body():
            try:
                async for chunk in inbound.aiter_raw():
                    yield chunk
            finally:
                await inbound.aclose()

        return StreamingResponse(
            body(),
            status_code=inbound.status_code,
            headers=_forward_response_headers(inbound.headers),
        )

    async def proxy_ws(websocket: WebSocket) -> None:
        import websockets

        url = _ws_url(
            websocket.app.state.api_base,
            backend_path(websocket.url.path),
            websocket.url.query,
        )
        extra_headers: list[tuple[str, str]] = []
        cookie = websocket.headers.get("cookie")
        if cookie:
            extra_headers.append(("Cookie", cookie))
        authorization = websocket.headers.get("authorization")
        if authorization:
            extra_headers.append(("Authorization", authorization))
        subprotocols = websocket.scope.get("subprotocols") or []
        connect_kwargs: dict[str, object] = {"additional_headers": extra_headers}
        if subprotocols:
            connect_kwargs["subprotocols"] = subprotocols
        try:
            backend = await websockets.connect(url, **connect_kwargs)
        except Exception:
            await websocket.close(code=1011)
            return

        await websocket.accept(subprotocol=getattr(backend, "subprotocol", None) or None)

        async def client_to_backend() -> None:
            try:
                while True:
                    message = await websocket.receive()
                    message_type = message.get("type")
                    if message_type == "websocket.disconnect":
                        return
                    if "text" in message and message["text"] is not None:
                        await backend.send(message["text"])
                    elif "bytes" in message and message["bytes"] is not None:
                        await backend.send(message["bytes"])
            except WebSocketDisconnect:
                return

        async def backend_to_client() -> None:
            try:
                async for payload in backend:
                    if isinstance(payload, bytes):
                        await websocket.send_bytes(payload)
                    else:
                        await websocket.send_text(str(payload))
            except Exception:
                return

        try:
            await asyncio.gather(client_to_backend(), backend_to_client())
        finally:
            with suppress(Exception):
                await backend.close()
            with suppress(Exception):
                await websocket.close()

    routes: list[Route | WebSocketRoute | Mount] = [
        WebSocketRoute("/api/{rest:path}", proxy_ws),
        WebSocketRoute("/ws/{rest:path}", proxy_ws),
        Route("/auth/callback", proxy_http, methods=_HTTP_METHODS),
        Route("/api", proxy_http, methods=_HTTP_METHODS),
        Route("/api/{rest:path}", proxy_http, methods=_HTTP_METHODS),
        Route("/ws", proxy_http, methods=_HTTP_METHODS),
        Route("/ws/{rest:path}", proxy_http, methods=_HTTP_METHODS),
    ]
    if assets is not None:
        routes.append(Mount("/", app=_SPAStaticFiles(directory=assets, html=True)))
    else:
        routes.append(Route("/{rest:path}", _missing_assets, methods=_HTTP_METHODS))
        routes.append(Route("/", _missing_assets, methods=_HTTP_METHODS))

    return Starlette(routes=routes, lifespan=lifespan)


_HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


async def _missing_assets(_request: Request) -> Response:
    return Response(f"{PRODUCT_NAME} Web assets are not installed.", status_code=503)


class _LazyApp:
    """Import-safe ASGI wrapper so collecting tests does not require assets."""

    def __init__(self) -> None:
        self._app: Starlette | None = None

    def _ensure(self) -> Starlette:
        if self._app is None:
            self._app = create_app()
        return self._app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self._ensure()(scope, receive, send)


app = _LazyApp()

__all__ = [
    "API_BASE_ENV",
    "SPA_DIR_ENV",
    "app",
    "backend_path",
    "create_app",
    "is_proxied_path",
    "resolve_api_base",
    "resolve_spa_dir",
]
