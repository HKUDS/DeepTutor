"""Short-lived QR onboarding for Feishu/Lark and WeCom partner channels.

The protocols mirror the scan-to-create flows used by Hermes Agent (MIT).
Credentials exist only in an in-process session and are written to partner
config when an administrator explicitly applies a result.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import io
import time
from typing import Any, Callable, Literal
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import ValidationError

ChannelName = Literal["feishu", "wecom"]
OnboardingStatus = Literal[
    "pending_scan",
    "ready",
    "applied",
    "cancelled",
    "expired",
    "denied",
    "failed",
]


class ChannelOnboardingError(Exception):
    """An onboarding request could not be started, polled, or applied."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class _ProviderRequestError(ChannelOnboardingError):
    """A transport-level provider failure that may be retried later."""


class _InvalidProviderResponse(ChannelOnboardingError):
    """A provider response no longer matches the expected protocol."""


_FEISHU_ACCOUNTS_URLS = {
    "feishu": "https://accounts.feishu.cn",
    "lark": "https://accounts.larksuite.com",
}
_FEISHU_REGISTRATION_PATH = "/oauth/v1/app/registration"
_WECOM_GENERATE_URL = "https://work.weixin.qq.com/ai/qc/generate"
_WECOM_QUERY_URL = "https://work.weixin.qq.com/ai/qc/query_result"
_WECOM_CODE_PAGE_URL = "https://work.weixin.qq.com/ai/qc/gen?source=hermes&scode="
_WECOM_USER_AGENT = "HermesAgent/1.0"
_REQUEST_TIMEOUT_SECONDS = 15.0
_DEFAULT_FEISHU_LIFETIME_SECONDS = 600
_DEFAULT_WECOM_LIFETIME_SECONDS = 300
_FEISHU_POLL_INTERVAL_SECONDS = 5
_WECOM_POLL_INTERVAL_SECONDS = 3
_TERMINAL_RETENTION_SECONDS = 120


def _qr_data_url(payload: str) -> str | None:
    """Render a compact PNG QR data URL, tolerating an absent qrcode package."""
    try:
        import base64

        import qrcode

        image = qrcode.make(payload, border=2)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:
        # The URL remains usable on a phone; the UI renders it as a link.
        return None


def _json_body(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise ChannelOnboardingError("Provider returned a non-JSON response") from exc
    if not isinstance(body, dict):
        raise ChannelOnboardingError("Provider returned an unexpected response")
    return body


@dataclass
class OnboardingSession:
    session_id: str
    partner_id: str
    channel: ChannelName
    status: OnboardingStatus
    qr_payload: str
    fallback_url: str
    poll_interval_seconds: int
    deadline_monotonic: float
    expires_at: datetime
    feishu_device_code: str | None = None
    feishu_domain: str = "feishu"
    wecom_scode: str | None = None
    credentials: dict[str, str] = field(default_factory=dict)
    error_code: str | None = None
    terminal_at: float | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "partner_id": self.partner_id,
            "channel": self.channel,
            "status": self.status,
            "qr_payload": self.qr_payload,
            "qr_data_url": _qr_data_url(self.qr_payload),
            "fallback_url": self.fallback_url,
            "poll_interval_seconds": self.poll_interval_seconds,
            "expires_at": self.expires_at.isoformat(),
            **({"error_code": self.error_code} if self.error_code else {}),
        }

    def finish(
        self,
        status: OnboardingStatus,
        *,
        error_code: str | None = None,
        clear_credentials: bool = True,
    ) -> None:
        self.status = status
        self.error_code = error_code
        self.terminal_at = time.monotonic()
        if clear_credentials:
            self.credentials.clear()


class ChannelOnboardingManager:
    """Manage in-memory scan sessions and apply completed credentials."""

    def __init__(
        self,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS)
        )
        self._now = now
        self._sessions: dict[str, OnboardingSession] = {}
        self._active_by_key: dict[tuple[str, ChannelName], str] = {}
        self._keys_lock = asyncio.Lock()

    async def start(self, partner_id: str, channel: ChannelName) -> dict[str, Any]:
        if channel not in ("feishu", "wecom"):
            raise ChannelOnboardingError("Unsupported onboarding channel")
        async with self._keys_lock:
            await self._purge_expired_locked()
            key = (partner_id, channel)
            active_id = self._active_by_key.get(key)
            if active_id:
                session = self._sessions.get(active_id)
                if session and self._now() < session.deadline_monotonic:
                    return session.public_dict()
                if session:
                    session.finish("expired")
                    self._active_by_key.pop(key, None)

            session = await self._start_session(partner_id, channel)
            self._sessions[session.session_id] = session
            self._active_by_key[key] = session.session_id
            return session.public_dict()

    async def status(self, partner_id: str, session_id: str) -> dict[str, Any]:
        session = self._get_session(partner_id, session_id)
        async with session.lock:
            if self._now() >= session.deadline_monotonic and session.status in (
                "pending_scan",
                "ready",
            ):
                session.finish("expired")
                self._active_by_key.pop((session.partner_id, session.channel), None)
                return session.public_dict()
            if session.status == "pending_scan":
                await self._poll(session)
            self._maybe_cleanup(session)
            return session.public_dict()

    async def cancel(self, partner_id: str, session_id: str) -> dict[str, Any]:
        session = self._get_session(partner_id, session_id)
        async with session.lock:
            if session.status in ("pending_scan", "ready"):
                session.finish("cancelled")
                self._active_by_key.pop((session.partner_id, session.channel), None)
            return session.public_dict()

    async def apply(
        self,
        partner_id: str,
        session_id: str,
        partner_manager: Any,
    ) -> dict[str, Any]:
        from deeptutor.services.partners.manager import mask_channel_secrets

        session = self._get_session(partner_id, session_id)
        async with session.lock:
            if session.status != "ready":
                raise ChannelOnboardingError(
                    f"Onboarding session is not ready (status: {session.status})",
                    status_code=409,
                )

            instance = partner_manager.get_partner(partner_id)
            config = instance.config if instance else partner_manager.load_config(partner_id)
            if config is None:
                raise ChannelOnboardingError("Partner not found", status_code=404)

            source = config.channels if isinstance(config.channels, dict) else {}
            merged = {
                key: (dict(value) if isinstance(value, dict) else value)
                for key, value in source.items()
            }
            current = merged.get(session.channel)
            current = dict(current) if isinstance(current, dict) else {}

            # Feishu deliberately replaces the app binding: a new scan creates a
            # new app. Preserve other settings while replacing credentials and
            # binding the scanner as the initial allowed user.
            if session.channel == "feishu":
                existing_allow = [item for item in current.get("allow_from", []) or [] if item]
                next_config = self._feishu_config(session)
                scanner = next_config["allow_from"][0]
                if existing_allow and scanner not in existing_allow:
                    existing_allow.append(scanner)
                next_config["allow_from"] = existing_allow or [scanner]
                current.update(next_config)
            else:
                existing_allow = [item for item in current.get("allow_from", []) or [] if item]
                current.update(self._wecom_config(session))
                current["allow_from"] = existing_allow or ["*"]
            merged[session.channel] = current

            try:
                from deeptutor.partners.config.schema import ChannelsConfig

                ChannelsConfig(**merged)
            except (ValidationError, TypeError) as exc:
                raise ChannelOnboardingError(f"Invalid merged channels config: {exc}") from exc

            config.channels = merged
            try:
                partner_manager.save_config(partner_id, config)
            except Exception as exc:
                raise ChannelOnboardingError("Failed to save channel configuration") from exc
            if instance:
                try:
                    await partner_manager.reload_channels(partner_id)
                except Exception:
                    # Keep the ready session so an administrator can retry after
                    # the same save/reload behavior as PATCH /partners/{id}.
                    raise

            session.finish("applied")
            self._active_by_key.pop((session.partner_id, session.channel), None)
            return {
                "session": session.public_dict(),
                "channels": mask_channel_secrets(merged),
            }

    def _feishu_config(self, session: OnboardingSession) -> dict[str, Any]:
        credentials = session.credentials
        app_id = credentials.get("app_id", "")
        app_secret = credentials.get("app_secret", "")
        open_id = credentials.get("open_id", "")
        if not app_id or not app_secret:
            raise ChannelOnboardingError("Feishu credentials are incomplete")
        if not open_id:
            raise ChannelOnboardingError("Feishu did not return the scanning user identity")
        return {
            "enabled": True,
            "app_id": app_id,
            "app_secret": app_secret,
            "domain": session.feishu_domain,
            "allow_from": [open_id],
        }

    def _wecom_config(self, session: OnboardingSession) -> dict[str, Any]:
        credentials = session.credentials
        bot_id = credentials.get("bot_id", "")
        secret = credentials.get("secret", "")
        if not bot_id or not secret:
            raise ChannelOnboardingError("WeCom credentials are incomplete")
        return {
            "enabled": True,
            "bot_id": bot_id,
            "secret": secret,
        }

    def _get_session(self, partner_id: str, session_id: str) -> OnboardingSession:
        session = self._sessions.get(session_id)
        if session is None or session.partner_id != partner_id:
            raise ChannelOnboardingError("Onboarding session not found", status_code=404)
        return session

    async def _purge_expired_locked(self) -> None:
        now = self._now()
        stale_ids = []
        for session_id, session in self._sessions.items():
            if (
                session.terminal_at is not None
                and now - session.terminal_at >= _TERMINAL_RETENTION_SECONDS
            ):
                stale_ids.append(session_id)
            elif session.terminal_at is None and now >= session.deadline_monotonic:
                session.finish("expired")
                self._active_by_key.pop((session.partner_id, session.channel), None)
                stale_ids.append(session_id)
        for session_id in stale_ids:
            self._sessions.pop(session_id, None)

    def _maybe_cleanup(self, session: OnboardingSession) -> None:
        if (
            session.terminal_at is not None
            and self._now() - session.terminal_at >= _TERMINAL_RETENTION_SECONDS
        ):
            self._sessions.pop(session.session_id, None)

    async def _start_session(self, partner_id: str, channel: ChannelName) -> OnboardingSession:
        if channel == "feishu":
            return await self._start_feishu(partner_id)
        return await self._start_wecom(partner_id)

    async def _start_feishu(self, partner_id: str) -> OnboardingSession:
        base_url = _FEISHU_ACCOUNTS_URLS["feishu"]
        async with self._client_factory() as client:
            init = await self._post_feishu(client, base_url, {"action": "init"})
            methods = init.get("supported_auth_methods")
            if not isinstance(methods, list) or "client_secret" not in methods:
                raise ChannelOnboardingError(
                    "Feishu registration does not support client-secret onboarding"
                )

            begin = await self._post_feishu(
                client,
                base_url,
                {
                    "action": "begin",
                    "archetype": "PersonalAgent",
                    "auth_method": "client_secret",
                    "request_user_info": "open_id",
                },
            )

        device_code = str(begin.get("device_code") or "")
        qr_payload = str(begin.get("verification_uri_complete") or "")
        if not device_code or not qr_payload:
            raise ChannelOnboardingError("Feishu did not return a scan request")
        lifetime = max(
            1,
            min(
                int(begin.get("expire_in") or _DEFAULT_FEISHU_LIFETIME_SECONDS),
                _DEFAULT_FEISHU_LIFETIME_SECONDS,
            ),
        )
        interval = max(1, int(begin.get("interval") or _FEISHU_POLL_INTERVAL_SECONDS))
        deadline = self._now() + lifetime
        return OnboardingSession(
            session_id=uuid4().hex,
            partner_id=partner_id,
            channel="feishu",
            status="pending_scan",
            qr_payload=qr_payload,
            fallback_url=qr_payload,
            poll_interval_seconds=interval,
            deadline_monotonic=deadline,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=lifetime),
            feishu_device_code=device_code,
        )

    async def _start_wecom(self, partner_id: str) -> OnboardingSession:
        async with self._client_factory() as client:
            response = await client.get(
                _WECOM_GENERATE_URL,
                params={"source": "hermes"},
                headers={"User-Agent": _WECOM_USER_AGENT},
            )
            response.raise_for_status()
            body = _json_body(response)

        data = body.get("data")
        data = data if isinstance(data, dict) else {}
        scode = str(data.get("scode") or "")
        auth_url = str(data.get("auth_url") or "")
        if not scode or not auth_url:
            raise ChannelOnboardingError("WeCom did not return a scan request")
        fallback_url = _WECOM_CODE_PAGE_URL + quote(scode, safe="")
        lifetime = _DEFAULT_WECOM_LIFETIME_SECONDS
        deadline = self._now() + lifetime
        return OnboardingSession(
            session_id=uuid4().hex,
            partner_id=partner_id,
            channel="wecom",
            status="pending_scan",
            qr_payload=auth_url,
            fallback_url=fallback_url,
            poll_interval_seconds=_WECOM_POLL_INTERVAL_SECONDS,
            deadline_monotonic=deadline,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=lifetime),
            wecom_scode=scode,
        )

    async def _poll(self, session: OnboardingSession) -> None:
        if session.channel == "feishu":
            await self._poll_feishu(session)
        else:
            await self._poll_wecom(session)

    async def _poll_feishu(self, session: OnboardingSession) -> None:
        assert session.feishu_device_code is not None
        base_url = _FEISHU_ACCOUNTS_URLS[session.feishu_domain]
        try:
            async with self._client_factory() as client:
                result = await self._post_feishu(
                    client,
                    base_url,
                    {
                        "action": "poll",
                        "device_code": session.feishu_device_code,
                        "tp": "ob_app",
                    },
                )
        except _ProviderRequestError:
            # Hermes treats polling transport failures as retryable. The next
            # status request polls again.
            return
        except ChannelOnboardingError:
            session.finish("failed", error_code="invalid_response")
            self._active_by_key.pop((session.partner_id, "feishu"), None)
            return

        user_info = result.get("user_info")
        user_info = user_info if isinstance(user_info, dict) else {}
        if user_info.get("tenant_brand") == "lark":
            session.feishu_domain = "lark"

        app_id = str(result.get("client_id") or "")
        app_secret = str(result.get("client_secret") or "")
        open_id = str(user_info.get("open_id") or "")
        if app_id and app_secret:
            if not open_id:
                session.finish("failed", error_code="missing_open_id")
                self._active_by_key.pop((session.partner_id, "feishu"), None)
                return
            session.credentials = {
                "app_id": app_id,
                "app_secret": app_secret,
                "open_id": open_id,
            }
            session.status = "ready"
            return

        error = str(result.get("error") or "")
        if error == "access_denied":
            session.finish("denied", error_code="access_denied")
            self._active_by_key.pop((session.partner_id, "feishu"), None)
        elif error == "expired_token":
            session.finish("expired", error_code="expired_token")
            self._active_by_key.pop((session.partner_id, "feishu"), None)
        # authorization_pending and unrecognized protocol values remain
        # retryable until Feishu returns credentials or a terminal error.

    async def _poll_wecom(self, session: OnboardingSession) -> None:
        assert session.wecom_scode is not None
        try:
            async with self._client_factory() as client:
                response = await client.get(
                    _WECOM_QUERY_URL,
                    params={"scode": session.wecom_scode},
                    headers={"User-Agent": _WECOM_USER_AGENT},
                )
                response.raise_for_status()
                try:
                    result = _json_body(response)
                except ChannelOnboardingError:
                    raise _InvalidProviderResponse(
                        "WeCom returned an unexpected response"
                    ) from None
        except httpx.HTTPStatusError:
            session.finish("failed", error_code="provider_http_error")
            self._active_by_key.pop((session.partner_id, "wecom"), None)
            return
        except httpx.RequestError:
            return
        except _InvalidProviderResponse:
            session.finish("failed", error_code="invalid_response")
            self._active_by_key.pop((session.partner_id, "wecom"), None)
            return

        data = result.get("data")
        data = data if isinstance(data, dict) else {}
        status = str(data.get("status") or "").lower()
        if not status:
            session.finish("failed", error_code="invalid_response")
            self._active_by_key.pop((session.partner_id, "wecom"), None)
            return
        if status != "success":
            # The console endpoint does not document its intermediate values;
            # anything other than success remains retryable until expiration.
            return

        bot_info = data.get("bot_info")
        bot_info = bot_info if isinstance(bot_info, dict) else {}
        bot_id = str(bot_info.get("botid") or bot_info.get("bot_id") or "")
        secret = str(bot_info.get("secret") or "")
        if not bot_id or not secret:
            session.finish("failed", error_code="missing_credentials")
            self._active_by_key.pop((session.partner_id, "wecom"), None)
            return
        session.credentials = {"bot_id": bot_id, "secret": secret}
        session.status = "ready"

    async def _post_feishu(
        self, client: httpx.AsyncClient, base_url: str, form: dict[str, str]
    ) -> dict[str, Any]:
        try:
            response = await client.post(
                base_url + _FEISHU_REGISTRATION_PATH,
                data=form,
            )
        except httpx.RequestError as exc:
            raise _ProviderRequestError(f"Feishu registration request failed: {exc}") from exc
        # Feishu returns JSON on 4xx polling responses; HTTP status is not the
        # protocol status.
        return _json_body(response)


_manager: ChannelOnboardingManager | None = None


def get_channel_onboarding_manager() -> ChannelOnboardingManager:
    global _manager
    if _manager is None:
        _manager = ChannelOnboardingManager()
    return _manager


def reset_channel_onboarding_manager_for_tests() -> None:
    global _manager
    _manager = None
