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

    def __init__(
        self,
        default_model: str = "github-copilot/gpt-4.1",
        *,
        configure_env: bool = True,
    ):
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
            configure_env=configure_env,
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

    @staticmethod
    def _supports_temperature(
        model_name: str,
        reasoning_effort: str | None = None,
    ) -> bool:
        if model_name.lower().split("/")[-1] == "gpt-6-astra":
            return False
        return OpenAICompatProvider._supports_temperature(model_name, reasoning_effort)

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

    @staticmethod
    def _normalize_responses_input(value: Any) -> Any:
        if not isinstance(value, list):
            return value
        normalized = []
        for item in value:
            if not isinstance(item, dict):
                normalized.append(item)
                continue
            # Copilot rejects message/reasoning status, including the null
            # added by SDK model_dump for reasoning. Function-call status is
            # accepted; keep tool lifecycle fields and reasoning IDs intact.
            excluded = set()
            if item.get("type") == "reasoning":
                excluded.add("status")
            elif item.get("type") == "message" or ("type" not in item and "role" in item):
                excluded.update(("status", "id"))
            normalized.append({key: val for key, val in item.items() if key not in excluded})
        return normalized

    async def _create_with_key_rotation(self, create, kwargs: dict[str, Any]) -> Any:
        if create == self._client.responses.create:
            # Run after extra kwargs are merged in both streaming and ordinary
            # requests. extra_body can override input again inside the SDK.
            kwargs = {**kwargs, "input": self._normalize_responses_input(kwargs.get("input"))}
            extra_body = kwargs.get("extra_body")
            if isinstance(extra_body, dict) and "input" in extra_body:
                kwargs["extra_body"] = {
                    **extra_body,
                    "input": self._normalize_responses_input(extra_body["input"]),
                }
        return await super()._create_with_key_rotation(create, kwargs)

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
