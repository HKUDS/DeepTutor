from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core import ClaudeCodeProvider
from deeptutor.services.llm.provider_factory import get_runtime_provider
from deeptutor.services.provider_registry import find_by_name


class FakeOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class FakeToolUseBlock:
    def __init__(self, call_id: str, name: str, arguments: dict[str, object]):
        self.id = call_id
        self.name = name
        self.input = arguments


class FakeAssistantMessage:
    def __init__(self, content):
        self.content = content


class FakeResultMessage:
    def __init__(self, result: str = "", is_error: bool = False):
        self.result = result
        self.is_error = is_error


def fake_tool(name, description, parameters):
    def decorate(func):
        func.tool_definition = (name, description, parameters)
        return func

    return decorate


def fake_mcp_server(name, tools):
    return {"name": name, "tools": tools}


class FakeClient:
    """Replays one scripted response per query, like ``ClaudeSDKClient``."""

    instances: list["FakeClient"] = []
    script: list[list[object]] = []

    def __init__(self, options):
        self.options = options
        self.prompts: list[str] = []
        self.interrupts = 0
        self.disconnected = False
        FakeClient.instances.append(self)

    async def connect(self):
        self.owner = asyncio.current_task()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()

    async def query(self, prompt):
        if not isinstance(prompt, str):
            prompt = [message async for message in prompt]
        self.prompts.append(prompt)

    async def receive_response(self):
        for message in FakeClient.script.pop(0):
            yield message

    async def interrupt(self):
        self.interrupts += 1

    async def disconnect(self):
        assert self.owner is asyncio.current_task()
        self.disconnected = True


def _install_fake_sdk(monkeypatch, **extra):
    FakeClient.instances = []
    sdk = SimpleNamespace(
        ClaudeAgentOptions=FakeOptions,
        ClaudeSDKClient=FakeClient,
        tool=fake_tool,
        create_sdk_mcp_server=fake_mcp_server,
        **extra,
    )
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", sdk)
    return sdk


WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Weather lookup",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    },
}


@pytest.mark.asyncio
async def test_one_shot_lifts_system_prompt_and_isolates_claude_code(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        yield FakeAssistantMessage([FakeTextBlock("hel"), FakeTextBlock("lo")])
        yield FakeResultMessage("hello")

    _install_fake_sdk(monkeypatch, query=fake_query)

    provider = ClaudeCodeProvider(default_model="claude-code/sonnet")
    response = await provider.chat(
        messages=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Say hello"},
        ]
    )

    assert response.content == "hello"
    options = captured["options"].kwargs
    assert options["system_prompt"] == "Be concise."
    assert options["model"] == "sonnet"
    assert options["tools"] == []
    assert options["setting_sources"] == []
    assert options["max_turns"] == 1
    assert "mcp_servers" not in options
    assert "Be concise." not in captured["prompt"]
    assert "User:\nSay hello" in captured["prompt"]


@pytest.mark.asyncio
async def test_default_model_alias_is_left_to_the_account(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        yield FakeResultMessage("ok")

    _install_fake_sdk(monkeypatch, query=fake_query)

    await ClaudeCodeProvider().chat(messages=[{"role": "user", "content": "hi"}])

    assert "model" not in captured["options"].kwargs


@pytest.mark.asyncio
async def test_session_tool_call_drains_without_interrupt_and_sends_only_new_tail(
    monkeypatch,
) -> None:
    _install_fake_sdk(monkeypatch)
    FakeClient.script = [
        [
            FakeAssistantMessage(
                [FakeToolUseBlock("toolu_1", "mcp__deeptutor__get_weather", {"city": "Hanoi"})]
            ),
            FakeResultMessage("max turns", is_error=True),
        ],
        [FakeAssistantMessage([FakeTextBlock("31C and rainy")]), FakeResultMessage("done")],
    ]

    provider = ClaudeCodeProvider()
    messages = [
        {"role": "system", "content": "Use tools."},
        {"role": "user", "content": "Weather in Hanoi?"},
    ]
    first = await provider.chat(messages, tools=[WEATHER_TOOL], deeptutor_session_id="s1")

    assert first.finish_reason == "tool_calls"
    assert [(c.id, c.name, c.arguments) for c in first.tool_calls] == [
        ("toolu_1", "get_weather", {"city": "Hanoi"})
    ]
    client = FakeClient.instances[0]
    assert client.interrupts == 0
    assert client.options.kwargs["allowed_tools"] == ["mcp__deeptutor__get_weather"]

    call = first.tool_calls[0]
    messages += [
        {"role": "assistant", "content": "", "tool_calls": [call.to_openai_tool_call()]},
        {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": "31C rain"},
    ]
    second = await provider.chat(messages, tools=[WEATHER_TOOL], deeptutor_session_id="s1")

    assert second.content == "31C and rainy"
    assert len(FakeClient.instances) == 1
    assert client.prompts[1] == "Tool result (get_weather):\n31C rain"

    await provider.aclose()
    assert client.disconnected


@pytest.mark.asyncio
async def test_missing_login_is_reported_as_error_response(monkeypatch) -> None:
    async def fake_query(**kwargs):
        raise RuntimeError("Invalid API key · Please run /login")
        yield  # pragma: no cover

    _install_fake_sdk(monkeypatch, query=fake_query)

    response = await ClaudeCodeProvider().chat(messages=[{"role": "user", "content": "hi"}])

    assert response.finish_reason == "error"
    assert "/login" in (response.content or "")


def test_claude_code_registry_alias_and_factory() -> None:
    spec = find_by_name("claude-code")

    assert spec is not None
    assert spec.name == "claude_code"
    assert spec.is_oauth

    provider = get_runtime_provider(
        LLMConfig(
            model="claude-code/default",
            api_key="",
            binding="claude_code",
            provider_name="claude_code",
        )
    )

    assert isinstance(provider, ClaudeCodeProvider)


@pytest.mark.asyncio
async def test_model_catalog_comes_from_cli_handshake(monkeypatch) -> None:
    from deeptutor.services.llm.provider_core.claude_code_provider import (
        fetch_claude_code_catalog,
        fetch_claude_code_models,
    )

    async def server_info(self):
        return {
            "models": [
                {"value": "default", "displayName": "Default (recommended)"},
                {"value": "opus", "displayName": "Opus 5.5"},
                {"value": "", "displayName": "ignored"},
            ]
        }

    monkeypatch.setattr(FakeClient, "get_server_info", server_info, raising=False)
    _install_fake_sdk(monkeypatch)

    assert await fetch_claude_code_catalog() == [
        {"id": "claude-code/default", "name": "Default (account setting)"},
        {"id": "claude-code/opus", "name": "Opus 5.5"},
    ]
    assert await fetch_claude_code_models() == ["claude-code/default", "claude-code/opus"]
    assert FakeClient.instances[0].disconnected


@pytest.mark.asyncio
async def test_model_catalog_falls_back_to_aliases_when_cli_fails(monkeypatch) -> None:
    from deeptutor.services.llm.provider_core.claude_code_provider import (
        fetch_claude_code_catalog,
    )

    async def broken_connect(self):
        raise RuntimeError("CLI not found")

    monkeypatch.setattr(FakeClient, "connect", broken_connect)
    _install_fake_sdk(monkeypatch)

    catalog = await fetch_claude_code_catalog()

    assert [model["id"] for model in catalog] == [
        "claude-code/default",
        "claude-code/sonnet",
        "claude-code/opus",
        "claude-code/haiku",
    ]


IMAGE_URL = "data:image/png;base64,iVBORw0KGgo="


@pytest.mark.asyncio
async def test_text_only_turns_stay_plain_strings(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        yield FakeResultMessage("ok")

    _install_fake_sdk(monkeypatch, query=fake_query)

    await ClaudeCodeProvider().chat(messages=[{"role": "user", "content": "hi"}])

    assert captured["prompt"] == "User:\nhi"


@pytest.mark.asyncio
async def test_one_shot_sends_images_as_anthropic_blocks(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(**kwargs):
        captured["prompt"] = [message async for message in kwargs["prompt"]]
        yield FakeAssistantMessage([FakeTextBlock("a red square")])
        yield FakeResultMessage("a red square")

    _install_fake_sdk(monkeypatch, query=fake_query)

    response = await ClaudeCodeProvider().chat(
        messages=[
            {"role": "system", "content": "Be terse."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Source evidence: fig-1."},
                    {"type": "image_url", "image_url": {"url": IMAGE_URL}},
                    {"type": "text", "text": "What is shown?"},
                ],
            },
        ]
    )

    assert response.content == "a red square"
    [message] = captured["prompt"]
    assert message["type"] == "user"
    assert message["message"]["content"] == [
        {"type": "text", "text": "User:\nSource evidence: fig-1."},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
        },
        {"type": "text", "text": "What is shown?"},
    ]


@pytest.mark.asyncio
async def test_session_sends_only_new_image_message_as_blocks(monkeypatch) -> None:
    _install_fake_sdk(monkeypatch)
    FakeClient.script = [
        [FakeAssistantMessage([FakeTextBlock("first")]), FakeResultMessage("first")],
        [FakeAssistantMessage([FakeTextBlock("it is red")]), FakeResultMessage("it is red")],
    ]

    provider = ClaudeCodeProvider()
    messages = [{"role": "user", "content": "Look at figure 1."}]
    await provider.chat(messages, deeptutor_session_id="s1")

    messages += [
        {"role": "assistant", "content": "first"},
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": IMAGE_URL}}]},
    ]
    response = await provider.chat(messages, deeptutor_session_id="s1")

    assert response.content == "it is red"
    client = FakeClient.instances[0]
    assert client.prompts[0] == "User:\nLook at figure 1."
    [message] = client.prompts[1]
    assert message["message"]["content"] == [
        {"type": "text", "text": "User:"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="},
        },
    ]
    await provider.aclose()


@pytest.mark.asyncio
async def test_cancel_active_stream_closes_in_owner_task(monkeypatch):
    entered = asyncio.Event()

    async def blocked_response(self):
        entered.set()
        await asyncio.Event().wait()
        yield FakeResultMessage("unreachable")

    monkeypatch.setattr(FakeClient, "receive_response", blocked_response)
    _install_fake_sdk(monkeypatch)
    provider = ClaudeCodeProvider()
    task = asyncio.create_task(
        provider.chat(
            [{"role": "user", "content": "Wait"}],
            deeptutor_session_id="cancel",
        )
    )
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert FakeClient.instances[0].disconnected
    assert not provider._sessions
    await provider.aclose()


@pytest.mark.asyncio
async def test_regeneration_replaces_old_cli_transcript(monkeypatch):
    _install_fake_sdk(monkeypatch)
    FakeClient.script = [[FakeResultMessage("one")], [FakeResultMessage("two")]]
    provider = ClaudeCodeProvider()
    await provider.chat([{"role": "user", "content": "Original"}], deeptutor_session_id="branch")
    await provider.chat([{"role": "user", "content": "Edited"}], deeptutor_session_id="branch")
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[0].disconnected
    assert FakeClient.instances[1].prompts == ["User:\nEdited"]
    options = FakeClient.instances[1].options.kwargs
    assert options["permission_mode"] == "dontAsk"
    assert options["extra_args"] == {"strict-mcp-config": None}
    await provider.aclose()


@pytest.mark.asyncio
async def test_cancel_during_sdk_connect_settles_owner(monkeypatch):
    import anyio

    from deeptutor.services.llm.provider_core.claude_code_provider import _ClaudeCodeSession

    entered = asyncio.Event()

    async def connect(self):
        self.owner = asyncio.current_task()
        self.group = anyio.create_task_group()
        await self.group.__aenter__()
        entered.set()
        await asyncio.Event().wait()

    async def disconnect(self):
        assert self.owner is asyncio.current_task()
        await self.group.__aexit__(None, None, None)
        self.disconnected = True

    monkeypatch.setattr(FakeClient, "connect", connect)
    monkeypatch.setattr(FakeClient, "disconnect", disconnect)
    sdk = _install_fake_sdk(monkeypatch)
    task = asyncio.create_task(_ClaudeCodeSession.start(sdk=sdk, signature="test", options=None))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert FakeClient.instances[0].disconnected
