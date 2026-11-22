"""Authenticate plan requests from the Desktop shell."""

import hmac
import os
import re

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

_HEADER = b"x-deeptutor-desktop-session"
_SCOPE_KEY = "deeptutor.desktop_plan_authenticated"
_session_token: bytes | None = None


def configure_desktop_request_auth() -> bool:
    global _session_token
    token = os.environ.pop("DEEPTUTOR_CHATGPT_PLAN_SESSION", "")
    _session_token = token.encode("ascii") if re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else None
    return _session_token is not None


def is_desktop_frontend(scope: Scope) -> bool:
    return scope.get(_SCOPE_KEY) is True


class DesktopOriginMiddleware:
    def __init__(self, app: ASGIApp, origin: str) -> None:
        self.app = app
        self.origin = origin

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            unsafe = scope["type"] == "websocket" or scope.get("method") not in {
                "GET",
                "HEAD",
                "OPTIONS",
            }
            pairs = scope["headers"]
            tokens = [value for name, value in pairs if name == _HEADER]
            scope = {
                **scope,
                _SCOPE_KEY: bool(
                    _session_token
                    and len(tokens) == 1
                    and (origin == self.origin or (origin is None and not unsafe))
                    and hmac.compare_digest(tokens[0], _session_token)
                ),
                "headers": [(name, value) for name, value in pairs if name != _HEADER],
            }
        await self.app(scope, receive, send)
