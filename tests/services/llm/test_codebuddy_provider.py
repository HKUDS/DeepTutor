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
    assert "CODEBUDDY_API_KEY" not in os.environ


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
async def test_fetch_codebuddy_models_uses_account_catalog(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        async def communicate(self):
            return (
                b"Currently supported models for your account:\n"
                b"  - hy3\n  - glm-5.2\n  - hy3\n",
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


def test_codebuddy_registry_aliases_and_factory() -> None:
    spec = find_by_name("workbuddy")

    assert spec is not None
    assert spec.name == "codebuddy"
    assert spec.backend == "codebuddy"

    provider = get_runtime_provider(
        LLMConfig(
            model="codebuddy/default",
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
