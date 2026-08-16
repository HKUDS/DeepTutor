from __future__ import annotations

import asyncio
import os
import shutil
import sys
from types import SimpleNamespace

import pytest

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.provider_core import CodeBuddyProvider
from deeptutor.services.llm.provider_core.codebuddy_provider import fetch_codebuddy_models
from deeptutor.services.llm.provider_factory import get_runtime_provider
from deeptutor.services.provider_registry import find_by_name


class FakeOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeTextBlock:
    def __init__(self, text: str):
        self.text = text


class FakeAssistantMessage:
    def __init__(self, content):
        self.content = content


class FakeResultMessage:
    def __init__(self, result: str = "", is_error: bool = False):
        self.result = result
        self.is_error = is_error


class FakeToolUseBlock:
    def __init__(self, call_id: str, name: str, arguments: dict[str, object]):
        self.id = call_id
        self.name = name
        self.input = arguments


def fake_tool(name, description, parameters):
    def decorate(func):
        func.tool_definition = (name, description, parameters)
        return func

    return decorate


def fake_mcp_server(name, tools):
    return {"name": name, "tools": tools}


@pytest.mark.asyncio
async def test_codebuddy_provider_streams_sdk_text_blocks(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        yield FakeAssistantMessage([FakeTextBlock("hel"), FakeTextBlock("lo")])
        yield FakeResultMessage("ignored because assistant text already streamed")

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(query=fake_query, CodeBuddyAgentOptions=FakeOptions),
    )
    monkeypatch.delenv("CODEBUDDY_API_KEY", raising=False)

    provider = CodeBuddyProvider(api_key="secret", default_model="codebuddy/claude-sonnet-4")
    deltas: list[str] = []
    response = await provider.chat_stream(
        messages=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": [{"type": "text", "text": "Say hello"}]},
        ],
        model=None,
        max_tokens=32,
        on_content_delta=lambda text: _append_async(deltas, text),
    )

    assert response.content == "hello"
    assert deltas == ["hello"]
    assert "System instructions:\nBe concise." in captured["prompt"]
    assert "User:\nSay hello" in captured["prompt"]
    assert captured["options"].kwargs["model"] == "claude-sonnet-4"
    assert captured["options"].kwargs["permission_mode"] == "plan"
    assert captured["options"].kwargs["env"]["CODEBUDDY_API_KEY"] == "secret"
    assert captured["options"].kwargs["tools"] == []
    assert captured["options"].kwargs["thinking"] == {"type": "disabled"}
    assert "CODEBUDDY_API_KEY" not in os.environ


@pytest.mark.asyncio
async def test_codebuddy_explicit_reasoning_effort_enables_sdk_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        yield FakeResultMessage("done")

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(query=fake_query, CodeBuddyAgentOptions=FakeOptions),
    )

    response = await CodeBuddyProvider().chat(
        [{"role": "user", "content": "think"}],
        reasoning_effort="high",
    )

    assert response.content == "done"
    assert captured["options"].kwargs["thinking"] == {"type": "adaptive"}
    assert captured["options"].kwargs["effort"] == "high"


@pytest.mark.asyncio
async def test_codebuddy_provider_uses_result_when_no_assistant_text(monkeypatch) -> None:
    async def fake_query(**_kwargs):
        yield FakeResultMessage("final")

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(query=fake_query, CodeBuddyAgentOptions=FakeOptions),
    )

    response = await CodeBuddyProvider().chat([{"role": "user", "content": "ping"}])

    assert response.content == "final"
    assert response.finish_reason == "stop"


@pytest.mark.asyncio
async def test_codebuddy_provider_maps_sdk_mcp_tool_calls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_query(**kwargs):
        captured.update(kwargs)
        yield FakeAssistantMessage(
            [
                FakeToolUseBlock(
                    "tool-1",
                    "mcp__deeptutor__web_search",
                    {"query": "latest news"},
                )
            ]
        )

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(
            query=fake_query,
            CodeBuddyAgentOptions=FakeOptions,
            tool=fake_tool,
            create_sdk_mcp_server=fake_mcp_server,
        ),
    )

    response = await CodeBuddyProvider().chat(
        [{"role": "user", "content": "Search the web"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
    )

    assert response.finish_reason == "tool_calls"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].id == "tool-1"
    assert response.tool_calls[0].name == "web_search"
    assert response.tool_calls[0].arguments == {"query": "latest news"}
    option_kwargs = captured["options"].kwargs
    assert option_kwargs["tools"] == ["mcp__deeptutor__web_search"]
    assert "deeptutor" in option_kwargs["mcp_servers"]


@pytest.mark.asyncio
async def test_codebuddy_session_survives_cross_task_turns(monkeypatch) -> None:
    """Chat streams run each turn in a fresh task; SDK cancel scopes must not."""
    clients = []

    class FakeClient:
        def __init__(self, options):
            self.options = options
            self.prompts = []
            self.connect_task = None
            self.disconnect_task = None
            self.response_index = 0
            clients.append(self)

        async def connect(self):
            self.connect_task = asyncio.current_task()

        async def query(self, prompt):
            self.prompts.append(prompt)

        async def receive_response(self):
            self.response_index += 1
            yield FakeResultMessage("first" if self.response_index == 1 else "second")

        async def interrupt(self):
            pass

        async def disconnect(self):
            self.disconnect_task = asyncio.current_task()

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(
            query=lambda **_kwargs: None,
            CodeBuddyAgentOptions=FakeOptions,
            CodeBuddySDKClient=FakeClient,
        ),
    )
    provider = CodeBuddyProvider()

    async def turn(content: str) -> str:
        response = await provider.chat(
            [{"role": "user", "content": content}],
            deeptutor_session_id="cross-task",
        )
        return response.content

    first = await asyncio.create_task(turn("one"))
    second = await asyncio.create_task(turn("two"))
    await provider.aclose()

    assert first == "first"
    assert second == "second"
    assert len(clients) == 1
    assert clients[0].connect_task is not None
    assert clients[0].disconnect_task is clients[0].connect_task
    assert clients[0].prompts == ["User:\none", "User:\ntwo"]


@pytest.mark.asyncio
async def test_codebuddy_provider_reuses_session_and_sends_message_delta(monkeypatch) -> None:
    clients = []

    class FakeClient:
        def __init__(self, options):
            self.options = options
            self.prompts = []
            self.connected = 0
            self.disconnected = 0
            self.response_index = 0
            clients.append(self)

        async def connect(self):
            self.connected += 1

        async def query(self, prompt):
            self.prompts.append(prompt)

        async def receive_response(self):
            self.response_index += 1
            yield FakeResultMessage("first" if self.response_index == 1 else "second")

        async def interrupt(self):
            pass

        async def disconnect(self):
            self.disconnected += 1

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(
            query=lambda **_kwargs: None,
            CodeBuddyAgentOptions=FakeOptions,
            CodeBuddySDKClient=FakeClient,
        ),
    )
    provider = CodeBuddyProvider()
    initial = [{"role": "user", "content": "first question"}]
    first = await provider.chat(initial, deeptutor_session_id="chat-1")
    second = await provider.chat(
        [
            *initial,
            {"role": "assistant", "content": "first"},
            {"role": "user", "content": "second question"},
        ],
        deeptutor_session_id="chat-1",
    )

    assert first.content == "first"
    assert second.content == "second"
    assert len(clients) == 1
    assert clients[0].connected == 1
    assert clients[0].prompts == ["User:\nfirst question", "User:\nsecond question"]
    await provider.aclose()
    assert clients[0].disconnected == 1


@pytest.mark.asyncio
async def test_codebuddy_session_drains_interrupt_before_tool_result_round(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, options):
            self.options = options
            self.response_index = 0
            self.interrupted = 0

        async def connect(self):
            pass

        async def query(self, _prompt):
            self.response_index += 1

        async def receive_response(self):
            if self.response_index == 1:
                yield FakeAssistantMessage(
                    [
                        FakeToolUseBlock(
                            "tool-1",
                            "mcp__deeptutor__web_search",
                            {"query": "latest news"},
                        )
                    ]
                )
                yield FakeResultMessage("Interrupted by user")
            else:
                yield FakeResultMessage("final answer")

        async def interrupt(self):
            self.interrupted += 1

        async def disconnect(self):
            pass

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(
            query=lambda **_kwargs: None,
            CodeBuddyAgentOptions=FakeOptions,
            CodeBuddySDKClient=FakeClient,
            tool=fake_tool,
            create_sdk_mcp_server=fake_mcp_server,
        ),
    )
    provider = CodeBuddyProvider()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Search the web",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    initial = [{"role": "user", "content": "Search"}]

    tool_response = await provider.chat(
        initial,
        tools=tools,
        deeptutor_session_id="chat-tools",
    )
    final_response = await provider.chat(
        [
            *initial,
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [tool_response.tool_calls[0].to_openai_tool_call()],
            },
            {
                "role": "tool",
                "tool_call_id": "tool-1",
                "content": "real search result",
            },
        ],
        tools=tools,
        deeptutor_session_id="chat-tools",
    )

    assert tool_response.finish_reason == "tool_calls"
    assert final_response.content == "final answer"
    session = provider._sessions["chat-tools"]
    assert session.client.interrupted == 1
    await provider.aclose()


@pytest.mark.asyncio
async def test_fetch_codebuddy_models_uses_account_catalog(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        async def communicate(self):
            return (
                b"Currently supported models for your account:\n  - hy3\n  - glm-5.2\n  - hy3\n",
                b"",
            )

    async def fake_subprocess(*args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: "codebuddy.cmd" if name == "codebuddy" else None,
    )
    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(query=lambda: None),
    )

    assert await fetch_codebuddy_models("secret") == ["hy3", "glm-5.2"]
    assert isinstance(captured["env"], dict)
    assert captured["env"]["CODEBUDDY_API_KEY"] == "secret"


def test_codebuddy_registry_aliases_and_factory(monkeypatch) -> None:
    spec = find_by_name("workbuddy")

    assert spec is not None
    assert spec.name == "codebuddy"
    assert spec.backend == "codebuddy"

    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_BACKEND", "sdk")
    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.codebuddy_http_provider.sdk_installed",
        lambda: True,
    )
    provider = get_runtime_provider(
        LLMConfig(
            model="codebuddy/hy3",
            api_key="",
            binding="codebuddy",
            provider_name="codebuddy",
        )
    )

    assert isinstance(provider, CodeBuddyProvider)


def test_codebuddy_ignores_deeptutor_no_key_placeholder() -> None:
    provider = CodeBuddyProvider(api_key="sk-no-key-required")

    assert provider.api_key is None


async def _append_async(items: list[str], text: str) -> None:
    items.append(text)
