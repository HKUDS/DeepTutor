"""GitHub Copilot provider with graceful fallback to existing local auth."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import time
from typing import Any

import httpx
from openai import AuthenticationError

from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.provider_registry import find_by_name

DEFAULT_COPILOT_BASE_URL = "https://api.githubcopilot.com"
DEFAULT_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
USER_AGENT = "DeepTutor/1"
EDITOR_VERSION = "vscode/1.99.0"
EDITOR_PLUGIN_VERSION = "copilot-chat/0.26.0"
_EXPIRY_SKEW_SECONDS = 60


class GitHubCopilotProvider(OpenAICompatProvider):
    """Provider that first tries existing Copilot auth, then oauth-cli-kit tokens."""

    def __init__(self, default_model: str = "github-copilot/gpt-4.1"):
        self._copilot_access_token: str | None = None
        self._copilot_expires_at: float = 0.0
        super().__init__(
            api_key="copilot",
            api_base=DEFAULT_COPILOT_BASE_URL,
            default_model=default_model,
            extra_headers={
                "Editor-Version": EDITOR_VERSION,
                "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
                "User-Agent": USER_AGENT,
            },
            spec=find_by_name("github_copilot"),
            provider_name="github_copilot",
        )

    async def _try_existing_local_auth(self) -> None:
        self.api_key = "copilot"
        self._client.api_key = "copilot"

    async def _load_stored_github_token(self) -> str | None:
        try:
            from oauth_cli_kit.storage import FileTokenStorage
        except ImportError:
            return None
        storage = FileTokenStorage(  # nosec B106 - token_filename is a file name, not a password.
            token_filename="github-copilot.json",
            app_name="nanobot",
            import_codex_cli=False,
        )
        token = storage.load()
        if not token or not getattr(token, "access", None):
            return None
        return str(token.access)

    async def _exchange_token(self) -> str:
        github_token = await self._load_stored_github_token()
        if not github_token:
            raise RuntimeError(
                "GitHub Copilot auth is unavailable. Validate local Copilot auth or log in first."
            )

        timeout = httpx.Timeout(20.0, connect=20.0)
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, trust_env=True
        ) as client:
            response = await client.get(
                DEFAULT_COPILOT_TOKEN_URL,
                headers={
                    "Authorization": f"token {github_token}",
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                    "Editor-Version": EDITOR_VERSION,
                    "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
                },
            )
            response.raise_for_status()
            payload = response.json()

        token = payload.get("token")
        if not token:
            raise RuntimeError("GitHub Copilot token exchange returned no token.")
        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)):
            self._copilot_expires_at = float(expires_at)
        else:
            refresh_in = payload.get("refresh_in") or 1500
            self._copilot_expires_at = time.time() + int(refresh_in)
        self._copilot_access_token = str(token)
        return self._copilot_access_token

    async def _ensure_api_key(self) -> None:
        now = time.time()
        if self._copilot_access_token and now < self._copilot_expires_at - _EXPIRY_SKEW_SECONDS:
            self.api_key = self._copilot_access_token
            self._client.api_key = self._copilot_access_token
            return

        await self._try_existing_local_auth()

    async def _chat_impl(
        self,
        stream: bool,
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
        await self._ensure_api_key()
        try:
            if stream:
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
            return await super().chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                **kwargs,
            )
        except AuthenticationError:
            token = await self._exchange_token()
            self.api_key = token
            self._client.api_key = token
            if stream:
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
            return await super().chat(
                messages=messages,
                tools=tools,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
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
            False,
            messages,
            tools,
            model,
            max_tokens,
            temperature,
            reasoning_effort,
            tool_choice,
            **kwargs,
        )

    async def chat_stream(
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
            True,
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
