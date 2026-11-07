"""Tests for the LLM client wrapper."""

from __future__ import annotations

import sys
import types

from _pytest.monkeypatch import MonkeyPatch
import pytest

from src.services.llm.client import LLMClient
from src.services.llm.config import LLMConfig


@pytest.mark.asyncio
async def test_client_complete_uses_factory(monkeypatch: MonkeyPatch) -> None:
    """Client complete should delegate to factory.complete."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    async def _fake_complete(**_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr("src.services.llm.factory.complete", _fake_complete)

    result = await client.complete("hello")

    assert result == "ok"


def test_client_complete_sync(monkeypatch: MonkeyPatch) -> None:
    """complete_sync should run in a fresh event loop."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    async def _fake_complete(
        _prompt: str,
        _system_prompt: str | None = None,
        _history: list[dict[str, str]] | None = None,
        **_kwargs: object,
    ) -> str:
        return "ok"

    monkeypatch.setattr(client, "complete", _fake_complete)

    assert client.complete_sync("hello") == "ok"


@pytest.mark.asyncio
async def test_client_complete_sync_running_loop() -> None:
    """complete_sync should raise when called from a running event loop."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    with pytest.raises(RuntimeError):
        client.complete_sync("hello")


def test_client_get_model_func_openai(monkeypatch: MonkeyPatch) -> None:
    """OpenAI-style model func should call openai_complete_if_cache."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    module = types.ModuleType("lightrag.llm.openai")
    module.openai_complete_if_cache = lambda *_args, **_kwargs: "ok"
    monkeypatch.setitem(sys.modules, "lightrag", types.ModuleType("lightrag"))
    monkeypatch.setitem(sys.modules, "lightrag.llm", types.ModuleType("lightrag.llm"))
    monkeypatch.setitem(sys.modules, "lightrag.llm.openai", module)

    monkeypatch.setattr("src.services.llm.client.system_in_messages", lambda *_a: True)

    func = client.get_model_func()

    assert func("hello") == "ok"


def test_client_get_model_func_factory(monkeypatch: MonkeyPatch) -> None:
    """Non-OpenAI providers should route via factory.complete."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    def _fake_complete(**_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr("src.services.llm.factory.complete", _fake_complete)
    monkeypatch.setattr("src.services.llm.client.system_in_messages", lambda *_a: False)

    func = client.get_model_func()

    assert func("hello") == "ok"


def test_client_get_vision_model_func_factory(monkeypatch: MonkeyPatch) -> None:
    """Vision model func should route via factory for non-OpenAI bindings."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    def _fake_complete(**_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr("src.services.llm.factory.complete", _fake_complete)
    monkeypatch.setattr("src.services.llm.client.system_in_messages", lambda *_a: False)

    func = client.get_vision_model_func()

    assert func("hello") == "ok"


def test_client_get_vision_model_func_openai(monkeypatch: MonkeyPatch) -> None:
    """OpenAI-style vision model func should call openai_complete_if_cache."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    module = types.ModuleType("lightrag.llm.openai")
    module.openai_complete_if_cache = lambda *_args, **_kwargs: "ok"
    monkeypatch.setitem(sys.modules, "lightrag", types.ModuleType("lightrag"))
    monkeypatch.setitem(sys.modules, "lightrag.llm", types.ModuleType("lightrag.llm"))
    monkeypatch.setitem(sys.modules, "lightrag.llm.openai", module)

    monkeypatch.setattr("src.services.llm.client.system_in_messages", lambda *_a: True)

    func = client.get_vision_model_func()

    assert func("hello", messages=[{"role": "user", "content": "hi"}]) == "ok"
