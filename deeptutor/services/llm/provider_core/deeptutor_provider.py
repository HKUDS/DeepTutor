"""OpenAI Chat Completions over an owner-scoped Studio device connection."""

from __future__ import annotations

from contextlib import suppress
import hashlib
from typing import Any

from openai import APIStatusError, DefaultAsyncHttpxClient

from deeptutor.services.deeptutor_account import DeepTutorAccount, get_deeptutor_account
from deeptutor.services.deeptutor_account.client import (
    DEFAULT_BASE_URL,
    DeepTutorAccountError,
    gateway_error,
    is_loopback_url,
)
from deeptutor.services.provider_registry import find_by_name

from .base import LLMResponse
from .openai_compat_provider import OpenAICompatProvider


class DeepTutorProvider(OpenAICompatProvider):
    def __init__(self, default_model: str, *, account: DeepTutorAccount | None = None) -> None:
        self._account = account or get_deeptutor_account()
        self._loopback_client: DefaultAsyncHttpxClient | None = None
        super().__init__(
            api_base=DEFAULT_BASE_URL,
            default_model=default_model,
            spec=find_by_name("deeptutor"),
            provider_name="deeptutor",
            wire_api="chat_completions",
            configure_env=False,
        )

    async def aclose(self) -> None:
        try:
            await super().aclose()
        finally:
            if self._loopback_client is not None:
                await self._loopback_client.aclose()

    @staticmethod
    def _supports_temperature(model_name: str, reasoning_effort: str | None = None) -> bool:
        # The gateway knows which upstream supports this sampling control.
        # Its public model ids are opaque, so use upstream sampling defaults.
        return False

    @staticmethod
    def _handle_error(error: Exception) -> LLMResponse:
        if isinstance(error, DeepTutorAccountError):
            raise error
        return OpenAICompatProvider._handle_error(error)

    async def _create_with_key_rotation(self, create: Any, kwargs: dict[str, Any]) -> Any:
        request = dict(kwargs)
        session_id = request.pop("deeptutor_session_id", None)
        if session_id:
            cache_scope = f"session:{session_id}"
        else:
            first = request["messages"][0] if request["messages"] else {}
            instructions = first.get("content") if first.get("role") == "system" else ""
            cache_scope = f"completion:{instructions}"
        extra_body = dict(request.get("extra_body") or {})
        extra_body["prompt_cache_key"] = hashlib.sha256(cache_scope.encode()).hexdigest()[:32]
        request["extra_body"] = extra_body
        request["extra_headers"] = {
            key: value
            for key, value in (request.get("extra_headers") or {}).items()
            if key.lower() != "authorization"
        }
        access = await self._account.access()
        for attempt in range(2):
            # Local Studio installations are reachable directly even when an
            # OS-wide HTTP proxy is enabled.
            http = None
            if is_loopback_url(access.base_url):
                if self._loopback_client is None:
                    self._loopback_client = DefaultAsyncHttpxClient(
                        trust_env=False, follow_redirects=False
                    )
                http = self._loopback_client
            client = self._client.with_options(
                base_url=access.base_url, api_key=access.token, http_client=http
            )
            try:
                return await client.chat.completions.create(**request)
            except APIStatusError as exc:
                error = gateway_error(
                    exc.status_code,
                    exc.body,
                    exc.response.headers,
                    access.public_url,
                )
            # Leave the SDK error behind. Its response can contain arbitrary
            # upstream content and must never become a public log or event.
            if error.error_code == "model_not_found":
                with suppress(DeepTutorAccountError):
                    await self._account.refresh_models(access)
            if attempt:
                raise error
            access = await self._account.retry_access(access, error)
        raise AssertionError("unreachable")
