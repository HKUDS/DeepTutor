"""Verify named tool choices at the Codex provider request boundary."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any, Literal

import pytest

from deeptutor.services.codex_auth.contracts import CodexToken
import deeptutor.services.llm.provider_core.openai_codex_provider as codex_provider

pytestmark = pytest.mark.asyncio

ChatMethod = Literal["chat", "chat_stream"]
ToolChoice = str | dict[str, Any] | None


class _FakeCodexService:
    """Supply synthetic credentials without reading the user's OAuth state."""

    @asynccontextmanager
    async def inference_guard(self) -> AsyncIterator[None]:
        """Keep the provider's normal inference-guard path in the test."""
        yield

    async def get_token(self) -> CodexToken:
        """Return a synthetic token; no real account or network is needed."""
        return CodexToken(
            access_token="test-token",
            account_id="test-account",
            expires_at=2_000_000_000,
            generation=1,
        )

    def validate_runtime_profile(
        self,
        token: CodexToken,
        model: str,
        reasoning_effort: str | None,
    ) -> None:
        """Avoid fetching a model catalog in a request-shape regression."""
        del token, model, reasoning_effort


@pytest.fixture
def captured_requests(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture outgoing bodies and emulate one successful content delta."""
    captured: list[dict[str, Any]] = []
    service = _FakeCodexService()

    async def _fake_request(
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        *,
        verify: bool,
        on_content_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> tuple[str, list[codex_provider.ToolCallRequest], str]:
        del url, headers, verify
        captured.append(body)
        if on_content_delta is not None:
            await on_content_delta("ok")
        return "ok", [], "stop"

    monkeypatch.setattr(codex_provider, "get_codex_oauth_service", lambda: service)
    monkeypatch.setattr(codex_provider, "_request_codex", _fake_request)
    return captured


@pytest.mark.parametrize("method", ["chat", "chat_stream"])
@pytest.mark.parametrize("tool_name", ["ask_user", "read_source"])
async def test_named_function_choice(
    captured_requests: list[dict[str, Any]],
    method: ChatMethod,
    tool_name: str,
) -> None:
    """Both public entry points flatten names without mutating caller input."""
    choice = {"type": "function", "function": {"name": tool_name}}
    tools = [
        {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": "A test function",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    original_choice = deepcopy(choice)
    original_tools = deepcopy(tools)
    deltas: list[str] = []

    async def on_content_delta(text: str) -> None:
        deltas.append(text)

    provider = codex_provider.OpenAICodexProvider()
    result = await getattr(provider, method)(
        messages=[{"role": "user", "content": "Use the selected tool."}],
        tools=tools,
        tool_choice=choice,
        on_content_delta=on_content_delta,
    )

    assert result.content == "ok"
    assert result.finish_reason == "stop"
    assert len(captured_requests) == 1
    body = captured_requests[0]
    assert body["tool_choice"] == {"type": "function", "name": tool_name}
    assert body["tools"][0]["name"] == tool_name
    assert "function" not in body["tools"][0]
    assert choice == original_choice
    assert tools == original_tools
    assert deltas == (["ok"] if method == "chat_stream" else [])


@pytest.mark.parametrize("method", ["chat", "chat_stream"])
@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        pytest.param(None, "auto", id="default"),
        pytest.param("auto", "auto", id="auto"),
        pytest.param("required", "required", id="required"),
        pytest.param("none", "none", id="none"),
        pytest.param(
            {"type": "function", "name": "ask_user"},
            {"type": "function", "name": "ask_user"},
            id="already-flat",
        ),
    ],
)
async def test_other_choices_keep_existing_behavior(
    captured_requests: list[dict[str, Any]],
    method: ChatMethod,
    choice: ToolChoice,
    expected: ToolChoice,
) -> None:
    """Defaults, strings, and already-flat choices must not be rewritten."""
    original_choice = deepcopy(choice)
    provider = codex_provider.OpenAICodexProvider()

    result = await getattr(provider, method)(
        messages=[{"role": "user", "content": "Hello"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "ask_user",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice=choice,
    )

    assert result.finish_reason == "stop"
    assert len(captured_requests) == 1
    assert captured_requests[0]["tool_choice"] == expected
    assert choice == original_choice
