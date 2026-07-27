"""PKCE, loopback callback, and HTTP operations for Codex OAuth."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Iterable
from dataclasses import dataclass
import hashlib
import secrets
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from .constants import (
    CODEX_CALLBACK_PATH,
    CODEX_OAUTH_CLIENT_ID,
    CODEX_OAUTH_ISSUER,
    CODEX_OAUTH_ORIGINATOR,
    CODEX_OAUTH_SCOPE,
    CODEX_REVOKE_URL,
    CODEX_TOKEN_URL,
)
from .contracts import CodexAuthError, CodexCredentials


@dataclass(frozen=True)
class PkceCodes:
    verifier: str
    challenge: str


@dataclass(frozen=True)
class OAuthCallbackResult:
    code: str | None
    state: str | None
    error: str | None


_OAUTH_STATE_MAX_LENGTH = 128
_BASE64URL_STATE_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def oauth_state_matches(value: str | None, expected: str) -> bool:
    if (
        not value
        or len(value) > _OAUTH_STATE_MAX_LENGTH
        or any(character not in _BASE64URL_STATE_CHARS for character in value)
    ):
        return False
    try:
        value_bytes = value.encode("ascii")
        expected_bytes = expected.encode("ascii")
    except UnicodeEncodeError:
        return False
    return secrets.compare_digest(value_bytes, expected_bytes)


def generate_pkce() -> PkceCodes:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PkceCodes(verifier=verifier, challenge=challenge)


def build_authorize_url(*, redirect_uri: str, state: str, pkce: PkceCodes) -> str:
    query = urlencode(
        {
            "response_type": "code",
            "client_id": CODEX_OAUTH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "scope": CODEX_OAUTH_SCOPE,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
            "state": state,
            "originator": CODEX_OAUTH_ORIGINATOR,
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
        }
    )
    return f"{CODEX_OAUTH_ISSUER}/oauth/authorize?{query}"


class LoopbackCallback:
    """A one-shot OAuth callback listener bound only to loopback addresses.

    The redirect URI has to stay ``http://localhost:<port>`` because that is what
    the upstream OAuth client accepts, and ``localhost`` resolves to either stack
    depending on the host. Both loopback addresses are therefore bound, with a
    plain IPv4 bind as the fallback on hosts without IPv6.
    """

    hosts = ("127.0.0.1", "::1")

    def __init__(
        self,
        server: asyncio.AbstractServer,
        result: asyncio.Future[OAuthCallbackResult],
        port: int,
    ) -> None:
        self._server = server
        self._result = result
        self._cancelled = False
        self._accepting = True
        self.port = port

    @classmethod
    async def start(
        cls,
        ports: Iterable[int],
        expected_state: str | None = None,
    ) -> LoopbackCallback:
        loop = asyncio.get_running_loop()
        result: asyncio.Future[OAuthCallbackResult] = loop.create_future()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            status = "404 Not Found"
            body = (
                "<!doctype html><title>DeepTutor Codex</title>"
                "<p>This callback path is not available.</p>"
            )
            try:
                request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
                request_line = request.split(b"\r\n", 1)[0].decode("ascii")
                method, target, _version = request_line.split(" ", 2)
                parsed = urlsplit(target)
                if method == "GET" and parsed.path == CODEX_CALLBACK_PATH:
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    states = query.get("state", [])
                    if expected_state is not None and (
                        len(states) != 1 or not oauth_state_matches(states[0], expected_state)
                    ):
                        status = "400 Bad Request"
                        body = (
                            "<!doctype html><title>DeepTutor Codex</title>"
                            "<p>The authentication callback was invalid.</p>"
                        )
                    else:
                        callback_result = OAuthCallbackResult(
                            code=_first(query.get("code")),
                            state=_first(states),
                            error=_first(query.get("error")),
                        )
                        try:
                            callback.submit(callback_result)
                        except CodexAuthError:
                            status = "409 Conflict"
                            body = (
                                "<!doctype html><title>DeepTutor Codex</title>"
                                "<p>Authentication could not be received.</p>"
                            )
                        else:
                            status = "200 OK"
                            body = (
                                "<!doctype html><title>DeepTutor Codex</title>"
                                "<p>Authentication received. You can return to DeepTutor.</p>"
                            )
            except (ValueError, UnicodeDecodeError, asyncio.IncompleteReadError, TimeoutError):
                status = "400 Bad Request"
                body = (
                    "<!doctype html><title>DeepTutor Codex</title>"
                    "<p>The authentication callback was invalid.</p>"
                )

            encoded = body.encode("utf-8")
            writer.write(
                (
                    f"HTTP/1.1 {status}\r\n"
                    "Content-Type: text/html; charset=utf-8\r\n"
                    f"Content-Length: {len(encoded)}\r\n"
                    "Cache-Control: no-store\r\n"
                    "Connection: close\r\n\r\n"
                ).encode("ascii")
                + encoded
            )
            try:
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        async def bind(hosts: list[str], port: int) -> asyncio.Server | None:
            try:
                server = await asyncio.start_server(
                    handle,
                    hosts,
                    port,
                    start_serving=False,
                )
            except OSError:
                return None
            if len({int(sock.getsockname()[1]) for sock in server.sockets}) == 1:
                return server
            # An ephemeral port can land differently on each stack, and the
            # redirect URI can only name one of them. Fall back to a single bind.
            server.close()
            await server.wait_closed()
            return None

        server: asyncio.Server | None = None
        for port in ports:
            server = await bind(list(cls.hosts), port) or await bind([cls.hosts[0]], port)
            if server is not None:
                break
        if server is None or not server.sockets:
            raise CodexAuthError(
                "callback_unavailable",
                "DeepTutor could not start the local Codex sign-in callback.",
                503,
            )
        bound_port = int(server.sockets[0].getsockname()[1])
        callback = cls(server=server, result=result, port=bound_port)
        await server.start_serving()
        return callback

    def submit(self, result: OAuthCallbackResult) -> None:
        if not self._accepting or self._result.done():
            raise CodexAuthError(
                "login_not_active",
                "Codex sign-in is not waiting for a callback.",
                409,
            )
        self._accepting = False
        self._result.set_result(result)

    async def _close(self) -> None:
        self._server.close()
        await self._server.wait_closed()

    async def wait(self, timeout: float) -> OAuthCallbackResult:
        try:
            callback = await asyncio.wait_for(asyncio.shield(self._result), timeout=timeout)
        except TimeoutError as exc:
            self._accepting = False
            await self._close()
            raise CodexAuthError(
                "login_timeout",
                (
                    "The DeepTutor server did not receive the Codex OAuth callback "
                    f"on localhost:{self.port}. For a remote deployment, keep the "
                    "SSH port-forwarding tunnel open and try again."
                ),
                408,
            ) from exc
        except asyncio.CancelledError as exc:
            self._accepting = False
            await self._close()
            if self._cancelled:
                raise CodexAuthError(
                    "login_cancelled",
                    "Codex sign-in was cancelled.",
                    409,
                ) from exc
            raise
        self._accepting = False
        await self._close()
        return callback

    async def cancel(self) -> None:
        self._cancelled = True
        self._accepting = False
        if not self._result.done():
            self._result.cancel()
        await self._close()


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


class CodexOAuthClient:
    """HTTP client for the audited Codex OAuth token endpoints."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        verifier: str,
    ) -> dict[str, Any]:
        return await self._token_request(
            data={
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
            error_code="token_exchange_failed",
            public_message="Codex sign-in could not be completed.",
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._token_request(
            json_payload={
                "client_id": CODEX_OAUTH_CLIENT_ID,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            error_code="token_refresh_failed",
            public_message="Codex authentication could not be refreshed.",
        )

    async def revoke(self, credentials: CodexCredentials) -> None:
        token = credentials.refresh_token or credentials.access_token
        hint = "refresh_token" if credentials.refresh_token else "access_token"
        try:
            response = await self._http.post(
                CODEX_REVOKE_URL,
                data={
                    "client_id": CODEX_OAUTH_CLIENT_ID,
                    "token": token,
                    "token_type_hint": hint,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CodexAuthError(
                "token_revoke_failed",
                "Codex authentication could not be revoked remotely.",
                502,
            ) from exc

    async def _token_request(
        self,
        *,
        data: dict[str, str] | None = None,
        json_payload: dict[str, str] | None = None,
        error_code: str,
        public_message: str,
    ) -> dict[str, Any]:
        try:
            response = await self._http.post(
                CODEX_TOKEN_URL,
                data=data,
                json=json_payload,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            raise CodexAuthError(error_code, public_message, 502) from exc
