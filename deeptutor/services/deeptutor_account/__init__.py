"""Device sign-in and owner-scoped access to DeepTutor Studio."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import platform
import secrets
import socket
import time
from typing import Any
from urllib.parse import urlsplit

from deeptutor.multi_user.paths import get_owner_secrets_dir
from deeptutor.multi_user.personal_models import owner_catalog_service
from deeptutor.services.config.model_catalog import ModelCatalogService

from .catalog import parse_models, publish_models
from .client import (
    DEFAULT_BASE_URL,
    REFRESH_ERRORS,
    DeepTutorAccountError,
    GatewayClient,
    checked_url,
)
from .storage import DeviceStore

_REFRESH_GRACE = 120
_EXPIRY_SKEW = 300


@dataclass(frozen=True)
class SignIn:
    attempt: str
    base_url: str
    device_code: str = field(repr=False)
    verifier: str = field(repr=False)
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_at: float
    interval: float

    def public(self) -> dict[str, str]:
        return {
            "user_code": self.user_code,
            "verification_uri": self.verification_uri,
            "verification_uri_complete": self.verification_uri_complete,
            "expires_at": datetime.fromtimestamp(self.expires_at, tz=timezone.utc).isoformat(),
        }


@dataclass(frozen=True)
class Access:
    base_url: str
    public_url: str
    device_id: str
    token: str = field(repr=False)


def _token_fields(payload: dict[str, Any]) -> dict[str, Any]:
    expires_at = datetime.fromisoformat(payload["expires_at"])
    if expires_at.tzinfo is None:
        raise ValueError("Missing time zone")
    device_id = payload["device"]["id"]
    access_token, refresh_token = payload["access_token"], payload["refresh_token"]
    if not all(
        isinstance(value, str) and value for value in (device_id, access_token, refresh_token)
    ):
        raise ValueError("Missing device credentials")
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at.isoformat(),
        "device_id": device_id,
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }


def _access(credentials: dict[str, Any]) -> Access:
    return Access(
        credentials["base_url"],
        credentials["public_url"],
        credentials["device_id"],
        credentials["access_token"],
    )


def _origin(url: str) -> str:
    parts = urlsplit(checked_url(url))
    return f"{parts.scheme}://{parts.netloc}"


class DeepTutorAccount:
    def __init__(
        self, store: DeviceStore, catalog: ModelCatalogService, gateway: GatewayClient | None = None
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.gateway = gateway or GatewayClient()

    async def start(
        self, base_url: str | None = None, *, device_label: str | None = None
    ) -> SignIn:
        base = checked_url(
            (base_url or os.getenv("DEEPTUTOR_STUDIO_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        )
        if urlsplit(base).query or urlsplit(base).fragment:
            raise DeepTutorAccountError("invalid_url", 400)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        return await asyncio.to_thread(
            self._start,
            base,
            verifier,
            challenge.rstrip(b"=").decode(),
            (device_label or socket.gethostname())[:64],
        )

    def _start(self, base: str, verifier: str, challenge: str, label: str) -> SignIn:
        attempt = secrets.token_hex(16)
        with self.store.locked():
            state = self.store.load()
            state.pop("login_error", None)
            self.store.save(
                {
                    **state,
                    "attempt": attempt,
                    "pending": {},
                    "pending_until": time.time() + 20,
                }
            )
        try:
            response = self.gateway.request(
                base,
                "/device/start",
                body={"client_id": "deeptutor", "code_challenge": challenge, "device_label": label},
            )
            sign_in = SignIn(
                attempt,
                base,
                response["device_code"],
                verifier,
                response["user_code"],
                checked_url(response["verification_uri"]),
                checked_url(response["verification_uri_complete"]),
                time.time() + max(1, min(float(response["expires_in"]), 600)),
                max(1, min(float(response["interval"]), 600)),
            )
            with self.store.locked():
                state = self.store.load()
                if state.get("attempt") != attempt:
                    raise DeepTutorAccountError("account_changed", 409)
                self.store.save(
                    {
                        **state,
                        "pending": sign_in.public(),
                        "pending_until": sign_in.expires_at,
                    }
                )
            return sign_in
        except (KeyError, TypeError, ValueError, DeepTutorAccountError) as exc:
            self._cancel(attempt)
            if isinstance(exc, DeepTutorAccountError):
                raise
            raise DeepTutorAccountError("invalid_response", 502) from None

    async def cancel(
        self, sign_in: SignIn | None = None, *, error: DeepTutorAccountError | None = None
    ) -> None:
        await asyncio.to_thread(self._cancel, sign_in.attempt if sign_in else None, error)

    def _cancel(self, attempt: str | None, error: DeepTutorAccountError | None = None) -> None:
        with self.store.locked():
            state = self.store.load()
            if attempt is None or state.get("attempt") == attempt:
                for key in ("attempt", "pending", "pending_until", "login_error"):
                    state.pop(key, None)
                if error:
                    state["login_error"] = {
                        "error_code": error.error_code,
                        "message": error.message,
                    }
                self.store.save(state)

    async def finish(self, sign_in: SignIn) -> Access:
        interval = delay = sign_in.interval
        while time.time() + delay < sign_in.expires_at:
            await asyncio.sleep(delay)
            try:
                result = await asyncio.to_thread(self._poll, sign_in)
            except DeepTutorAccountError as exc:
                if exc.status_code != 429 and exc.error_code != "network_error":
                    raise
                delay = max(interval, exc.retry_after or interval * 2)
                continue
            if isinstance(result, Access):
                return result
            if result == "slow_down":
                interval += 5
            elif result != "authorization_pending":
                raise DeepTutorAccountError(result, 400)
            delay = interval
        raise DeepTutorAccountError("expired_token", 400)

    def _poll(self, sign_in: SignIn) -> str | Access:
        from deeptutor.__version__ import __version__

        with self.store.locked():
            if self.store.load().get("attempt") != sign_in.attempt:
                raise DeepTutorAccountError("account_changed", 409)
        system = platform.system()
        result = self.gateway.request(
            sign_in.base_url,
            "/device/token",
            body={
                "client_id": "deeptutor",
                "device_code": sign_in.device_code,
                "code_verifier": sign_in.verifier,
                "platform": "Docker"
                if Path("/.dockerenv").is_file()
                else ("macOS" if system == "Darwin" else system[:40]),
                "client_version": __version__[:40],
            },
        )
        if "error" in result:
            error = result["error"]
            if error in ("authorization_pending", "slow_down", "access_denied", "expired_token"):
                return str(error)
            raise DeepTutorAccountError("invalid_response", 502)
        return self._complete(sign_in, result)

    def _complete(self, sign_in: SignIn, result: dict[str, Any]) -> Access:
        try:
            credentials = {
                **_token_fields(result),
                "base_url": sign_in.base_url,
                "public_url": _origin(result["cloud"]["public_url"]),
                "user": {key: result["user"][key] for key in ("id", "email", "name")},
                "account": {key: result["account"][key] for key in ("id", "name")},
            }
        except (KeyError, TypeError, ValueError):
            raise DeepTutorAccountError("invalid_response", 502) from None
        with self.store.locked():
            state = self.store.load()
            superseded = state.get("attempt") != sign_in.attempt
            previous = state.get("credentials")
            if not superseded:
                if previous and (
                    previous["base_url"] == credentials["base_url"]
                    and previous["account"]["id"] == credentials["account"]["id"]
                ):
                    credentials["models"] = previous.get("models", [])
                else:
                    publish_models(self.catalog, sign_in.base_url, [])
                self.store.save({**state, "credentials": credentials})
        if superseded:
            self._revoke(credentials)
            raise DeepTutorAccountError("account_changed", 409)
        if previous:
            self._revoke(previous)
        return _access(credentials)

    async def status(self) -> dict[str, Any]:
        return await asyncio.to_thread(self._status)

    def _status(self) -> dict[str, Any]:
        with self.store.locked():
            state = self.store.load()
        if state.get("attempt") and time.time() < state.get("pending_until", 0):
            return {"state": "pending", **state["pending"]}
        error = state.get("login_error", {})
        credentials = state.get("credentials")
        if not credentials:
            return {"state": "error" if error else "idle", **error}
        return {
            "state": "connected",
            "user": credentials["user"],
            "account": credentials["account"],
            "public_url": credentials["public_url"],
            "models": credentials.get("models", []),
            "paid_balance": credentials.get("paid_balance"),
            **error,
        }

    async def logout(self) -> None:
        await asyncio.to_thread(self._logout)

    def _logout(self) -> None:
        with self.store.locked():
            credentials = self.store.load().get("credentials")
            self.store.save({})
            publish_models(self.catalog, "", [])
        if credentials:
            self._revoke(credentials)

    def _revoke(self, credentials: dict[str, Any]) -> None:
        try:
            self.gateway.request(
                credentials["base_url"],
                "/device/logout",
                body={"refresh_token": credentials["refresh_token"]},
            )
        except DeepTutorAccountError:
            # Local sign-out succeeds even when the site is unreachable.
            pass

    async def access(
        self, previous: Access | None = None, *, force_refresh: bool = False
    ) -> Access:
        try:
            return await asyncio.to_thread(self._access_or_refresh, previous, force_refresh)
        except DeepTutorAccountError as exc:
            if exc.error_code != "network_error":
                raise
        return await asyncio.to_thread(self._access_or_refresh, previous, force_refresh)

    def _access_or_refresh(self, previous: Access | None, force_refresh: bool) -> Access:
        with self.store.locked():
            state = self.store.load()
            credentials = state.get("credentials")
            if not credentials:
                raise DeepTutorAccountError("authentication_required", 401)
            access = _access(credentials)
            if previous and (access.device_id, access.base_url) != (
                previous.device_id,
                previous.base_url,
            ):
                raise DeepTutorAccountError("account_changed", 409)
            started_at = credentials.get("refresh_started_at")
            expires = datetime.fromisoformat(credentials["expires_at"]).timestamp()
            saved = datetime.fromisoformat(credentials["saved_at"]).timestamp()
            skew = max(0, min(_EXPIRY_SKEW, (expires - saved) / 2))
            if (
                started_at is None
                and (not force_refresh or (previous and access.token != previous.token))
                and expires > time.time() + (0 if force_refresh else skew)
            ):
                return access
            if started_at is not None and time.time() - started_at >= _REFRESH_GRACE:
                self._forget(state)
                raise DeepTutorAccountError("invalid_grant", 401)
            if started_at is None:
                credentials["refresh_started_at"] = time.time()
                self.store.save(state)
            try:
                result = self.gateway.request(
                    access.base_url,
                    "/device/refresh",
                    body={"refresh_token": credentials["refresh_token"]},
                )
            except DeepTutorAccountError as exc:
                if exc.error_code == "invalid_grant":
                    self._forget(state)
                elif started_at is None and exc.status_code in (403, 429):
                    # These responses are returned before any rotation.
                    credentials.pop("refresh_started_at", None)
                    self.store.save(state)
                raise
            try:
                fields = _token_fields(result)
                if fields["device_id"] != access.device_id:
                    raise ValueError("Device ID changed during refresh")
            except (KeyError, TypeError, ValueError):
                raise DeepTutorAccountError("invalid_response", 502) from None
            credentials.update(fields)
            credentials.pop("refresh_started_at", None)
            self.store.save(state)
            return _access(credentials)

    def _forget(self, state: dict[str, Any]) -> None:
        state.pop("credentials", None)
        self.store.save(state)
        publish_models(self.catalog, "", [])

    async def _get(self, path: str, access: Access) -> tuple[dict[str, Any], Access]:
        for attempt in range(2):
            try:
                data = await asyncio.to_thread(
                    self.gateway.request,
                    access.base_url,
                    path,
                    token=access.token,
                    public_url=access.public_url,
                )
                return data, access
            except DeepTutorAccountError as exc:
                if attempt:
                    raise
                access = await self.retry_access(access, exc)
        raise AssertionError("unreachable")

    async def retry_access(self, access: Access, error: DeepTutorAccountError) -> Access:
        if error.status_code == 401 and error.error_code in REFRESH_ERRORS:
            return await self.access(access, force_refresh=True)
        if error.status_code == 429 and error.retry_after is not None and error.retry_after <= 60:
            await asyncio.sleep(max(1, error.retry_after))
            return await self.access(access)
        raise error

    async def refresh_models(self, previous: Access | None = None) -> list[dict[str, Any]]:
        payload, access = await self._get("/models", await self.access(previous))
        models = parse_models(payload)
        await asyncio.to_thread(self._save_models, access, models)
        return models

    async def refresh_balance(self, previous: Access | None = None) -> None:
        payload, access = await self._get("/account", await self.access(previous))
        try:
            credit = payload["credit"]
            balance = (
                credit["pools"]["paid"]["available_micro_credits"] / credit["micro_per_credit"]
            )
        except (KeyError, TypeError, ZeroDivisionError):
            raise DeepTutorAccountError("invalid_response", 502) from None
        await asyncio.to_thread(self._save_balance, access, balance)

    def _current_credentials(self, state: dict[str, Any], access: Access) -> dict[str, Any]:
        credentials = state.get("credentials")
        if not credentials or (credentials["device_id"], credentials["base_url"]) != (
            access.device_id,
            access.base_url,
        ):
            raise DeepTutorAccountError("account_changed", 409)
        return credentials

    def _save_models(self, access: Access, models: list[dict[str, Any]]) -> None:
        with self.store.locked():
            state = self.store.load()
            self._current_credentials(state, access)["models"] = models
            state.pop("login_error", None)
            publish_models(self.catalog, access.base_url, models)
            self.store.save(state)

    def _save_balance(self, access: Access, balance: float) -> None:
        with self.store.locked():
            state = self.store.load()
            self._current_credentials(state, access)["paid_balance"] = balance
            self.store.save(state)


@lru_cache(maxsize=256)
def _owner_account(root: Path, catalog: ModelCatalogService) -> DeepTutorAccount:
    return DeepTutorAccount(DeviceStore(root), catalog)


def get_deeptutor_account() -> DeepTutorAccount:
    return _owner_account(get_owner_secrets_dir(), owner_catalog_service())
