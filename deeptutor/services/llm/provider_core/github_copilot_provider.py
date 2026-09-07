"""GitHub Copilot provider backed by a persisted GitHub device login."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import time
from typing import Any

from deeptutor.services.github_copilot_auth import (
    CopilotModel,
    exchange_copilot_token,
    fetch_github_copilot_models,
    get_github_copilot_storage,
)
from deeptutor.services.llm.provider_core.base import LLMResponse
from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.provider_registry import find_by_name

DEFAULT_COPILOT_BASE_URL = "https://api.githubcopilot.com"
USER_AGENT = "DeepTutor/1"
EDITOR_VERSION = "vscode/1.99.0"
EDITOR_PLUGIN_VERSION = "copilot-chat/0.26.0"
_EXPIRY_SKEW_SECONDS = 60


class GitHubCopilotProvider(OpenAICompatProvider):
    """Provider that exchanges a stored GitHub token for Copilot access."""

    def __init__(self, default_model: str = "github-copilot/gpt-4.1"):
        self._copilot_access_token: str | None = None
        self._copilot_expires_at: float = 0.0
        self._storage = get_github_copilot_storage()
        self._models: dict[str, CopilotModel] = {}
        self._refresh_lock = asyncio.Lock()
        super().__init__(
            # The real short-lived token is installed by _ensure_api_key().
            # Passing a placeholder here would create a KeyPool that later
            # overwrites the client's Authorization header with that placeholder.
            api_key=None,
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

    async def _exchange_token(self) -> str:
        stored = self._storage.load()
        if stored is None:
            raise RuntimeError(
                "GitHub Copilot is not logged in for this owner. "
                "Run: deeptutor provider login github-copilot"
            )
        access = await exchange_copilot_token(stored.access)
        models = await fetch_github_copilot_models(access)
        self.api_base = access.api_base.rstrip("/")
        self._effective_base = self.api_base
        self._client.base_url = self.api_base + "/"
        self._models = {model.id: model for model in models}
        self._copilot_expires_at = access.expires_at
        self._copilot_access_token = access.token
        return self._copilot_access_token

    async def _ensure_api_key(self) -> None:
        async with self._refresh_lock:
            await self._refresh_api_key()

    async def _refresh_api_key(self) -> None:
        now = time.time()
        if self._copilot_access_token and now < self._copilot_expires_at - _EXPIRY_SKEW_SECONDS:
            self.api_key = self._copilot_access_token
            self._client.api_key = self._copilot_access_token
            return

        token = await self._exchange_token()
        self.api_key = token
        self._client.api_key = token

    def _should_use_responses_api(
        self,
        model: str | None,
        reasoning_effort: str | None,
        tools: list[dict[str, Any]] | None = None,
    ) -> bool:
        model_id = (model or self.default_model).split("/")[-1]
        discovered = self._models.get(model_id)
        if discovered is None:
            raise ValueError(f"GitHub Copilot model is not currently available: {model_id}")
        endpoints = discovered.supported_endpoints
        if endpoints is not None:
            if "/chat/completions" not in endpoints:
                return True
            if "/responses" not in endpoints:
                return False
        return super()._should_use_responses_api(model, reasoning_effort, tools)

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


async def validate_github_copilot_model(model: str) -> None:
    """Probe inference through the same authenticated, protocol-aware runtime."""
    provider = GitHubCopilotProvider(default_model=model)
    try:
        response = await provider.chat(
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=16,
        )
        if response.finish_reason == "error":
            raise RuntimeError(
                f"Copilot model validation failed for {model}: "
                f"{response.content or 'provider returned an error'}"
            )
    finally:
        await provider.aclose()
