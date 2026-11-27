"""ChatGPT plan OAuth for a single-user Open DeepTutor Desktop runtime."""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
import httpx
from jose import JWTError, jwt

from deeptutor.runtime.home import get_runtime_home
from deeptutor.services.chatgpt_plan_context import PlanError as PlanError
from deeptutor.services.chatgpt_plan_context import request_account_id, request_allowed
from deeptutor.services.file_io import atomic_write_text

from .vault import desktop_vault_path

DISPLAY_NAME = "ChatGPT Plan"
ISSUER = "https://auth.openai.com"
RESOURCE = "https://api.openai.com/v1"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
USAGE_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {USAGE_SCOPE}"
_CALLBACK = "/auth/callback"
_TERMINAL_REFRESH_ERRORS = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


def response_error_code(response: Any) -> str:
    if not isinstance(response, dict):
        return ""
    error = response.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "")
    if isinstance(error, str) and error:
        return error
    return str(response.get("code") or "")


class PlanSession:
    """Owns a loopback listener and an encrypted session for one local runtime."""

    def __init__(self, path: Path, key: str, *, loop: asyncio.AbstractEventLoop | None = None):
        self.path = path
        self.cipher = Fernet(key.encode())
        self.lock = asyncio.Lock()
        self.loop = loop
        self.pending: dict[str, Any] | None = None
        self.listener: asyncio.Server | None = None
        self.deadline: asyncio.TimerHandle | None = None
        self.error: str | None = None

    def _load(self) -> dict[str, Any]:
        try:
            saved = json.loads(self.cipher.decrypt(self.path.read_bytes()))
        except FileNotFoundError:
            saved = {}
        except (OSError, ValueError, InvalidToken) as exc:
            raise PlanError("vault_unavailable") from exc
        if "accounts" not in saved:
            host_id = saved.pop("host_id", None)
            client_id = saved.get("client_id")
            saved = {
                "host_id": host_id,
                "active": client_id,
                "accounts": {client_id: saved} if client_id else {},
                "welcome_seen": USAGE_SCOPE
                in (saved.get("credentials") or {}).get("scope", "").split(),
            }
        return saved

    def _save(self, data: dict[str, Any]) -> None:
        atomic_write_text(self.path, self.cipher.encrypt(json.dumps(data).encode()).decode())

    def status(self) -> dict[str, Any]:
        saved = self._load()
        accounts = saved["accounts"]
        active = saved.get("active")
        account = accounts.get(active, {})
        credentials = account.get("credentials") or {}
        sharing = USAGE_SCOPE in credentials.get("scope", "").split()
        return {
            "connected": bool(credentials),
            "sharing": sharing,
            "account": account.get("account") if credentials else None,
            "active_account_id": self._account_id(active) if active else None,
            "accounts": [
                {
                    "id": self._account_id(client_id),
                    "label": record.get("label") or record.get("account") or DISPLAY_NAME,
                    "connected": bool(record.get("credentials")),
                    "revocation_pending": bool(record.get("pending_revocation")),
                }
                for client_id, record in accounts.items()
            ],
            "show_welcome": sharing and not saved.get("welcome_seen", False),
            "pending": self.pending is not None,
            "error": self.error
            or account.get("error")
            or ("revoke_unconfirmed" if account.get("pending_revocation") else None),
        }

    @staticmethod
    def _account_id(client_id: str) -> str:
        return hashlib.sha256(client_id.encode()).hexdigest()[:24]

    def _saved_client_id(self, saved: dict[str, Any], account_id: str | None) -> str | None:
        if account_id is None:
            return saved.get("active")
        for client_id in saved["accounts"]:
            if self._account_id(client_id) == account_id:
                return client_id
        raise PlanError("account_unavailable")

    async def dismiss_welcome(self) -> None:
        async with self.lock:
            saved = self._load()
            saved["welcome_seen"] = True
            self._save(saved)

    def _stop_listener(self) -> None:
        if self.deadline:
            self.deadline.cancel()
            self.deadline = None
        if self.listener:
            self.listener.close()
            self.listener = None

    def _expire(self) -> None:
        self._stop_listener()
        self.pending = None
        self.error = "authorization_expired"

    async def cancel(self) -> None:
        async with self.lock:
            self._stop_listener()
            self.pending = None
            self.error = None

    async def start(
        self, account_id: str | None = None, *, add: bool = False, label: str | None = None
    ) -> str:
        async with self.lock:
            if self.pending:
                raise PlanError("authorization_pending")
            saved = self._load()
            host = saved.get("host_id") or f"urn:uuid:{uuid4()}"
            accounts = saved["accounts"]
            client_id = None if add else self._saved_client_id(saved, account_id)
            account = accounts.get(client_id, {})
            if account.get("pending_revocation"):
                raise PlanError("revoke_unconfirmed")
            if not saved.get("host_id"):
                saved["host_id"] = host
                self._save(saved)
            self.error = None
            self.listener = await asyncio.start_server(
                self._handle_callback, "127.0.0.1", 0, limit=8192
            )
            port = self.listener.sockets[0].getsockname()[1]
            redirect_uri = f"http://127.0.0.1:{port}{_CALLBACK}"
            self.deadline = asyncio.get_running_loop().call_later(180, self._expire)
            verifier = secrets.token_urlsafe(48)
            state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.pending = dict(
                state=state,
                nonce=nonce,
                verifier=verifier,
                client_id=client_id,
                label=label if add else None,
                redirect_uri=redirect_uri,
                host=f"127.0.0.1:{port}",
            )
            params = dict(
                client_id=client_id or "dynamic_agent_client",
                ext_agent_host_id=host,
                response_type="code",
                redirect_uri=redirect_uri,
                resource=RESOURCE,
                scope=SCOPES,
                state=state,
                nonce=nonce,
                code_challenge_method="S256",
                code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("="),
            )
            if client_id is None:
                params["agent_name_hint"] = "Open DeepTutor"
            else:
                credentials = account.get("credentials") or {}
                if USAGE_SCOPE not in credentials.get("scope", "").split():
                    params["prompt"] = "consent"
            return f"{AUTHORIZE_URL}?{urlencode(params)}"

    async def _handle_callback(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        accepted = False
        try:
            raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            request, *headers = raw.decode("ascii").split("\r\n")
            method, target, _ = request.split()
            url = urlsplit(target)
            hosts = [line[5:].strip() for line in headers if line.lower().startswith("host:")]
            params = parse_qs(url.query, max_num_fields=16)
            if method == "GET" and not url.netloc and url.path == _CALLBACK and len(hosts) == 1:
                accepted = await self.complete(hosts[0], params)
        except (
            ValueError,
            UnicodeError,
            asyncio.TimeoutError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ):
            pass
        finally:
            status = "200 OK" if accepted else "400 Bad Request"
            message = (
                "Return to Open DeepTutor to see your connection status."
                if accepted
                else "This callback could not be accepted."
            )
            writer.write(
                (
                    f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                    f"Cache-Control: no-store\r\nConnection: close\r\n\r\n{message}"
                ).encode()
            )
            writer.close()

    async def complete(self, host: str, params: dict[str, list[str]]) -> bool:
        async with self.lock:
            pending = self.pending
            if (
                not pending
                or host != pending["host"]
                or any(len(values) != 1 for values in params.values())
            ):
                return False
            if not hmac.compare_digest(
                params.get("state", [""])[0].encode(), pending["state"].encode()
            ):
                return False
            self._stop_listener()
            try:
                if "error" in params:
                    raise PlanError("authorization_denied")
                code = params.get("code", [""])[0]
                issued_id = params.get("client_id", [pending["client_id"]])[0]
                if (
                    not code
                    or not isinstance(issued_id, str)
                    or issued_id == "dynamic_agent_client"
                    or not re.fullmatch(r"[A-Za-z0-9_.-]{1,240}", issued_id)
                    or (pending["client_id"] and issued_id != pending["client_id"])
                ):
                    raise PlanError("invalid_callback")
                saved = self._load()
                accounts = saved["accounts"]
                existing = accounts.get(issued_id, {})
                if existing.get("pending_revocation"):
                    raise PlanError("revoke_unconfirmed")
                token = await self._exchange(
                    dict(
                        grant_type="authorization_code",
                        client_id=issued_id,
                        code=code,
                        redirect_uri=pending["redirect_uri"],
                        code_verifier=pending["verifier"],
                        resource=RESOURCE,
                    ),
                    SCOPES,
                )
                claims = await self._identity(token.get("id_token"), issued_id, pending["nonce"])
                if existing.get("subject") and existing["subject"] != claims["sub"]:
                    raise PlanError("account_changed")
                accounts[issued_id] = dict(
                    client_id=issued_id,
                    subject=claims["sub"],
                    account=claims.get("email") or claims.get("name") or "ChatGPT",
                    label=existing.get("label") or pending["label"],
                    credentials=token,
                )
                saved["active"] = issued_id
                self._save(saved)
            except PlanError as exc:
                self.error = exc.code
            except (OSError, httpx.HTTPError, ValueError):
                self.error = "connection_failed"
            finally:
                self.pending = None
            return True

    async def _identity(
        self, token: str | None, audience: str, nonce: str | None, *, allow_expired: bool = False
    ) -> dict[str, Any]:
        if not token:
            raise PlanError("invalid_identity")
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                response = await client.get(f"{ISSUER}/.well-known/jwks.json")
                response.raise_for_status()
                keys = response.json()
            claims = jwt.decode(
                token,
                keys,
                algorithms=["RS256"],
                audience=audience,
                issuer=ISSUER,
                options={
                    "require_exp": not allow_expired,
                    "verify_exp": not allow_expired,
                    "require_aud": True,
                    "require_sub": True,
                    "require_iss": True,
                    "verify_at_hash": False,
                },
            )
        except (JWTError, ValueError, TypeError) as exc:
            raise PlanError("invalid_identity") from exc
        expiry = claims.get("exp")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)):
            raise PlanError("invalid_identity")
        if nonce is not None and claims.get("nonce") != nonce:
            raise PlanError("invalid_identity")
        audiences = claims.get("aud")
        if isinstance(audiences, list) and len(audiences) > 1 and claims.get("azp") != audience:
            raise PlanError("invalid_identity")
        return claims

    async def _exchange(self, data: dict[str, Any], scope: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.post(TOKEN_URL, data=data)
        if response.status_code != 200:
            try:
                code = response_error_code(response.json())
            except ValueError:
                code = ""
            if response.status_code < 500 and code in _TERMINAL_REFRESH_ERRORS:
                raise PlanError("login_required")
            raise PlanError("connection_failed")
        body = response.json()
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("access_token"), str)
            or not body["access_token"]
        ):
            raise PlanError("invalid_credentials")
        if "scope" in body and not isinstance(body["scope"], str):
            raise PlanError("invalid_credentials")
        for field in ("refresh_token", "id_token"):
            if body.get(field) is not None and not isinstance(body[field], str):
                raise PlanError("invalid_credentials")
        lifetime = body.get("expires_in", 3600)
        if (
            isinstance(lifetime, bool)
            or not isinstance(lifetime, (int, float))
            or not 0 < lifetime <= 86400
        ):
            raise PlanError("invalid_credentials")
        return dict(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            id_token=body.get("id_token"),
            scope=body.get("scope", scope),
            expires_at=time.time() + lifetime,
            earliest_refresh_at=body.get("earliest_refresh_at"),
        )

    async def access_token(self, *, rejected: str | None = None) -> str:
        if self.loop is not None and self.loop is not asyncio.get_running_loop():
            # Model diagnostics run in a worker thread. Keep rotation and
            # account changes on the event loop that owns the vault.
            return await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(self._access_token(rejected), self.loop)
            )
        return await self._access_token(rejected)

    async def rejected_access_token(self, token: str) -> None:
        # A resource 401 alone cannot distinguish expiry, a revoked grant,
        # or a permission check. Refresh once without replaying inference.
        await self.access_token(rejected=token)
        raise PlanError("access_renewed")

    def _clear_credentials(
        self, saved: dict[str, Any], account: dict[str, Any], *, error: str | None = None
    ) -> None:
        account.pop("credentials", None)
        account.pop("pending_refresh", None)
        account.pop("access_rejected", None)
        if error:
            account["error"] = error
        else:
            account.pop("error", None)
        self._save(saved)

    async def _validate_refresh_identity(
        self, saved: dict[str, Any], account: dict[str, Any], token: dict[str, Any]
    ) -> None:
        if not account.get("pending_refresh"):
            return
        try:
            # A delayed JWKS check still has to authenticate the stored identity.
            # An expired identity can confirm continuity but cannot authorize use.
            claims = await self._identity(
                token.get("id_token"), account["client_id"], None, allow_expired=True
            )
            if claims["sub"] != account["subject"]:
                raise PlanError("invalid_identity")
        except PlanError:
            self._clear_credentials(saved, account, error="login_required")
            raise PlanError("login_required") from None
        account.pop("pending_refresh", None)
        if claims["exp"] <= time.time():
            account["access_rejected"] = True
        self._save(saved)

    async def _access_token(self, rejected: str | None) -> str:
        async with self.lock:
            saved = self._load()
            active = saved.get("active")
            if (
                active
                and request_allowed.get()
                and self._account_id(active) != request_account_id.get()
            ):
                raise PlanError("request_account_changed")
            account = saved["accounts"].get(active, {})
            token = account.get("credentials") or {}
            if not token:
                raise PlanError("login_required")
            if USAGE_SCOPE not in token.get("scope", "").split():
                raise PlanError("sharing_required")
            await self._validate_refresh_identity(saved, account, token)
            if (
                rejected
                and rejected == token["access_token"]
                and not account.get("access_rejected")
            ):
                account["access_rejected"] = True
                self._save(saved)
            rejected_current = bool(account.get("access_rejected"))
            if not rejected_current and token["expires_at"] > time.time() + 30:
                return str(token["access_token"])
            if not token.get("refresh_token"):
                self._clear_credentials(saved, account, error="login_required")
                raise PlanError("login_required")
            earliest = _refresh_time(token.get("earliest_refresh_at"))
            if earliest is not None and earliest > time.time():
                if not rejected_current and token["expires_at"] > time.time():
                    return str(token["access_token"])
                raise PlanError("connection_failed")
            rotation = asyncio.create_task(self._rotate(saved, account, token))
            try:
                token = await asyncio.shield(rotation)
            except asyncio.CancelledError:
                # Keep the lock until the replacement is stored.
                try:
                    await asyncio.shield(rotation)
                finally:
                    raise
            await self._validate_refresh_identity(saved, account, token)
            if token["expires_at"] <= time.time() or account.get("access_rejected"):
                raise PlanError("connection_failed")
            if USAGE_SCOPE not in token.get("scope", "").split():
                raise PlanError("sharing_required")
            return str(token["access_token"])

    async def _rotate(
        self, saved: dict[str, Any], account: dict[str, Any], token: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            refreshed = await self._exchange(
                dict(
                    grant_type="refresh_token",
                    client_id=account["client_id"],
                    refresh_token=token["refresh_token"],
                    resource=RESOURCE,
                ),
                token.get("scope", ""),
            )
        except PlanError as exc:
            if exc.code == "login_required":
                self._clear_credentials(saved, account, error=exc.code)
            raise
        if not refreshed.get("refresh_token"):
            refreshed["refresh_token"] = token["refresh_token"]
        account.update(credentials=refreshed, pending_refresh=bool(refreshed.get("id_token")))
        account.pop("access_rejected", None)
        self._save(saved)
        return refreshed

    async def models(self) -> list[dict[str, str]]:
        token = await self.access_token()
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            response = await client.get(
                f"{RESOURCE}/models", headers={"Authorization": f"Bearer {token}"}
            )
        if response.status_code != 200:
            if response.status_code == 401:
                await self.rejected_access_token(token)
            raise PlanError("catalog_unavailable")
        payload = response.json()
        catalog = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(catalog, list):
            raise PlanError("catalog_unavailable")
        return [
            dict(id=row["slug"], label=str(row.get("display_name") or row["slug"]))
            for row in catalog
            if isinstance(row, dict)
            and row.get("visibility") == "list"
            and isinstance(row.get("slug"), str)
            and 0 < len(row["slug"]) <= 128
        ]

    async def disconnect(self, account_id: str | None = None) -> bool:
        async with self.lock:
            self._stop_listener()
            self.pending = None
            self.error = None
            saved = self._load()
            client_id = self._saved_client_id(saved, account_id)
            account = saved["accounts"].get(client_id, {})
            if not account:
                return True
            credentials = account.get("credentials") or {}
            token = account.get("pending_revocation") or credentials.get("refresh_token")
            if token:
                account["pending_revocation"] = token
            self._clear_credentials(saved, account)
            if not token:
                return not credentials.get("access_token")
            if not await self._revoke(token, account["client_id"]):
                return False
            account.pop("pending_revocation", None)
            self._save(saved)
            return True

    async def _revoke(self, token: str, client_id: str) -> bool:
        async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
            for attempt in range(2):
                try:
                    discovery = await client.get(f"{ISSUER}/.well-known/openid-configuration")
                    discovery.raise_for_status()
                    body = discovery.json()
                    target = body.get("revocation_endpoint") if isinstance(body, dict) else None
                    if not isinstance(target, str):
                        return False
                    endpoint = urlsplit(target)
                    if endpoint.scheme != "https" or endpoint.netloc != "auth.openai.com":
                        return False
                    response = await client.post(
                        target,
                        data={
                            "token": token,
                            "token_type_hint": "refresh_token",
                            "client_id": client_id,
                        },
                    )
                    if response.status_code < 500:
                        return response.status_code == 200
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code < 500:
                        return False
                except httpx.RequestError:
                    pass
                except ValueError:
                    return False
                if attempt == 0:
                    await asyncio.sleep(0.5)
        return False


def _refresh_time(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value / 1000 if value > 1e12 else float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


_session: PlanSession | None = None


def configure_desktop_session(*, request_auth: bool) -> None:
    """Consume the vault key before application subprocesses start."""
    global _session
    key = os.environ.pop("DEEPTUTOR_CHATGPT_PLAN_KEY", "")
    if (
        request_auth
        and key
        and _session is None
        and os.getenv("DEEPTUTOR_AUTH_ENABLED", "").lower() == "false"
    ):
        try:
            _session = PlanSession(
                desktop_vault_path(get_runtime_home()),
                key,
                loop=asyncio.get_running_loop(),
            )
        except ValueError:
            pass


def available() -> bool:
    return _session is not None


def active_account_id() -> str | None:
    if _session is None:
        return None
    try:
        active = _session._load().get("active")
    except PlanError:
        return None
    return _session._account_id(active) if active else None


def get_session() -> PlanSession:
    if _session is None:
        raise PlanError("desktop_required")
    return _session
