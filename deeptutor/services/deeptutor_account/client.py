"""HTTP contract for the DeepTutor Studio device and model gateway."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from deeptutor.services.llm.error_mapping import parse_retry_after_seconds
from deeptutor.services.llm.exceptions import LLMAPIError

DEFAULT_BASE_URL = "https://deeptutor.studio/api/gateway/v1"
REFRESH_ERRORS = frozenset({"token_expired", "invalid_api_key"})
_ERROR_MESSAGES = {
    "access_denied": "DeepTutor Studio sign-in was declined.",
    "expired_token": "The DeepTutor Studio device code expired. Start again.",
    "invalid_grant": "Your DeepTutor Studio sign-in has ended. Sign in again.",
    "authentication_required": "Sign in to DeepTutor Studio before using its models.",
    "account_changed": "The DeepTutor Studio connection changed. Select a model and try again.",
    "paid_credit_required": "Select an available DeepTutor model that uses paid credits.",
    "paid_account_required": "This model requires a paid DeepTutor Studio account.",
    "insufficient_credit": "Your DeepTutor Studio paid credits are exhausted.",
    "budget_exceeded": "This device has reached its DeepTutor Studio daily spending limit.",
    "model_not_found": "This DeepTutor model is unavailable. Refresh the model list in Settings.",
    "token_expired": "Your DeepTutor Studio session expired. Check your sign-in in Settings.",
    "invalid_api_key": "DeepTutor Studio rejected this session. Check your sign-in in Settings.",
    "rate_limited": "DeepTutor Studio is rate limiting this device. Try again shortly.",
    "network_error": "Could not reach DeepTutor Studio. Try again shortly.",
    "invalid_response": "DeepTutor Studio returned an invalid response.",
    "invalid_url": "Use an HTTPS URL for DeepTutor Studio or HTTP on localhost.",
    "storage_error": "Could not read or save the private DeepTutor Studio credentials.",
}
_CREDIT_ERRORS = {"paid_credit_required", "paid_account_required", "insufficient_credit"}
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


class DeepTutorAccountError(LLMAPIError):
    """Gateway error with safe copy and machine-readable recovery information."""

    retryable = False  # Each gateway operation owns its retry policy.

    def __init__(
        self,
        code: str,
        status: int,
        *,
        public_url: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        self.error_code = code
        self.retry_after = retry_after
        self.action_url = (
            f"{public_url}/account/credits" if public_url and code in _CREDIT_ERRORS else None
        )
        default = (
            "The DeepTutor Studio account cannot perform this action."
            if status == 403
            else "The DeepTutor Studio request failed."
        )
        super().__init__(_ERROR_MESSAGES.get(code, default), status, "deeptutor")


def is_loopback_url(url: str) -> bool:
    return urlsplit(url).hostname in _LOOPBACK_HOSTS


def checked_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        parts.port
    except (TypeError, ValueError, AttributeError):
        raise DeepTutorAccountError("invalid_url", 400) from None
    if (
        not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or any(char.isspace() for char in value)
        or "\\" in value
        or not (
            parts.scheme == "https"
            or (parts.scheme == "http" and parts.hostname in _LOOPBACK_HOSTS)
        )
    ):
        raise DeepTutorAccountError("invalid_url", 400)
    return value


def gateway_error(
    status: int, body: object, headers: httpx.Headers, public_url: str | None = None
) -> DeepTutorAccountError:
    data: Any = body
    if isinstance(data, dict):
        data = data.get("error", data.get("detail", data))
    code = data.get("code") if isinstance(data, dict) else data
    if not isinstance(code, str) or code not in _ERROR_MESSAGES:
        code = "rate_limited" if status == 429 else "gateway_error"
    return DeepTutorAccountError(
        code,
        status,
        public_url=public_url,
        retry_after=parse_retry_after_seconds(headers.get("Retry-After")),
    )


class GatewayClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport

    def request(
        self,
        base_url: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        public_url: str | None = None,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(
                transport=self.transport,
                timeout=15,
                follow_redirects=False,
                trust_env=not is_loopback_url(base_url),
            ) as http:
                response = http.request(
                    "POST" if body is not None else "GET",
                    f"{base_url}{path}",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"} if token else None,
                )
        except httpx.RequestError:
            raise DeepTutorAccountError("network_error", 503) from None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if not response.is_success:
            raise gateway_error(response.status_code, payload, response.headers, public_url)
        if not isinstance(payload, dict):
            raise DeepTutorAccountError("invalid_response", 502)
        return payload
