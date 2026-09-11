"""CodeBuddy provider that talks to the cloud over plain HTTP.

The CodeBuddy cloud exposes an OpenAI-compatible ``/chat/completions`` under
``<endpoint>/v2`` and accepts the OAuth session that the IDE plugin and CLI
already store on disk. That makes the Agent SDK (a bundled headless CLI
binary) unnecessary for chat, so this provider is preferred whenever a login
state or API key is available.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import importlib.util
import os
from typing import Any

from openai import AuthenticationError

from deeptutor.services.codebuddy_credentials import (
    CodeBuddyAuthUnavailable,
    CodeBuddyCredentials,
    load_credentials,
    refresh_credentials,
    resolve_api_base,
)
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.provider_registry import find_by_name

DEFAULT_CODEBUDDY_MODEL = "codebuddy/hy3"
_NO_KEY_PLACEHOLDER = "sk-no-key-required"
_SIGN_IN_HINT = (
    "CodeBuddy is not signed in. Sign in with the CodeBuddy IDE plugin, run "
    "`codebuddy` and enter `/login`, or set CODEBUDDY_API_KEY."
)


def normalize_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    key = api_key.strip()
    if not key or key == _NO_KEY_PLACEHOLDER:
        return None
    return key


class CodeBuddyHTTPProvider(OpenAICompatProvider):
    """CodeBuddy over HTTP, authenticating with the local login state."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str = DEFAULT_CODEBUDDY_MODEL,
        *,
        configure_env: bool = True,
    ):
        self._explicit_api_key = normalize_api_key(api_key)
        self._credentials: CodeBuddyCredentials | None = (
            None if self._explicit_api_key else load_credentials()
        )

        extra_headers: dict[str, str] = {}
        if self._explicit_api_key:
            extra_headers["X-API-Key"] = self._explicit_api_key
        elif self._credentials and self._credentials.user_id:
            extra_headers["X-User-Id"] = self._credentials.user_id

        super().__init__(
            api_key=None,
            api_base=resolve_api_base(self._credentials.domain if self._credentials else ""),
            default_model=default_model or DEFAULT_CODEBUDDY_MODEL,
            extra_headers=extra_headers,
            spec=find_by_name("codebuddy"),
            provider_name="codebuddy",
            configure_env=configure_env,
        )
        if self._explicit_api_key:
            self._apply_token(self._explicit_api_key)

    def get_default_model(self) -> str:
        return self.default_model or DEFAULT_CODEBUDDY_MODEL

    def _apply_token(self, token: str) -> None:
        self.api_key = token
        self._client.api_key = token

    async def _ensure_auth(self, *, reload_from_disk: bool = False) -> None:
        if self._explicit_api_key:
            return

        credentials = self._credentials
        if reload_from_disk or credentials is None:
            credentials = load_credentials() or credentials
        if credentials is None:
            raise CodeBuddyAuthUnavailable(_SIGN_IN_HINT)

        if credentials.is_expired():
            credentials = await refresh_credentials(credentials)

        base = credentials.api_base
        if base != str(self._client.base_url).rstrip("/"):
            self._client.base_url = base
            self.api_base = base
        self._credentials = credentials
        self._apply_token(credentials.access_token)

    async def _chat_impl(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str | None,
        max_tokens: int,
        temperature: float,
        reasoning_effort: str | None,
        tool_choice: str | dict[str, Any] | None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        # Session affinity is SDK-only; strip it so OpenAI client kwargs stay clean.
        kwargs.pop("deeptutor_session_id", None)
        await self._ensure_auth()
        try:
            return await super().chat_stream(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                on_content_delta=on_content_delta,
                on_reasoning_delta=on_reasoning_delta,
                **kwargs,
            )
        except AuthenticationError:
            await self._ensure_auth(reload_from_disk=True)
            return await super().chat_stream(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                on_content_delta=on_content_delta,
                on_reasoning_delta=on_reasoning_delta,
                **kwargs,
            )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self._chat_impl(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            **kwargs,
        )

    # Deliberately does not declare ``on_tool_args_delta``. The runtime probes
    # for that parameter by name (``_provider_streams_tool_args``) and only
    # hands the callback to a provider that opts in; this one forwards unknown
    # keywords into the request body, so declaring it without implementing the
    # streaming would serialise a function into an API call. Not opting in
    # simply keeps the old behaviour: tool calls arrive whole.
    async def chat_stream(  # type: ignore[override]
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self._chat_impl(
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            on_content_delta,
            on_reasoning_delta,
            **kwargs,
        )


def codebuddy_http_available(api_key: str | None = None) -> bool:
    """Whether HTTP access can authenticate without the Agent SDK."""
    if normalize_api_key(api_key) or normalize_api_key(os.environ.get("CODEBUDDY_API_KEY")):
        return True
    return load_credentials() is not None


def sdk_installed() -> bool:
    return importlib.util.find_spec("codebuddy_agent_sdk") is not None


def build_codebuddy_provider(
    api_key: str | None = None,
    default_model: str = DEFAULT_CODEBUDDY_MODEL,
    *,
    configure_env: bool = True,
) -> Any:
    """Return the HTTP transport when it can authenticate, else the Agent SDK.

    ``DEEPTUTOR_CODEBUDDY_BACKEND`` (``http`` / ``sdk``) forces one transport;
    the SDK is still needed for CLI-driven agent features such as sandboxed
    shell tools.
    """
    preference = (os.environ.get("DEEPTUTOR_CODEBUDDY_BACKEND") or "").strip().lower()
    has_sdk = sdk_installed()

    if preference == "sdk" and has_sdk:
        use_http = False
    elif preference == "http":
        use_http = True
    else:
        use_http = codebuddy_http_available(api_key) or not has_sdk

    if use_http:
        return CodeBuddyHTTPProvider(
            api_key=api_key,
            default_model=default_model,
            configure_env=configure_env,
        )

    from deeptutor.services.llm.provider_core.codebuddy_provider import CodeBuddyProvider

    return CodeBuddyProvider(api_key=api_key, default_model=default_model)


__all__ = [
    "CodeBuddyHTTPProvider",
    "DEFAULT_CODEBUDDY_MODEL",
    "build_codebuddy_provider",
    "codebuddy_http_available",
    "normalize_api_key",
    "sdk_installed",
]
