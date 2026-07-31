"""Tests for the LLM client wrapper."""

from __future__ import annotations

from types import SimpleNamespace

from _pytest.monkeypatch import MonkeyPatch
import pytest

from deeptutor.core.agentic import client as agentic_client
from deeptutor.services.llm.client import LLMClient
from deeptutor.services.llm.config import LLMConfig


@pytest.mark.asyncio
async def test_client_complete_uses_factory(monkeypatch: MonkeyPatch) -> None:
    """Client complete should delegate to factory.complete."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    async def _fake_complete(**_kwargs: object) -> str:
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", _fake_complete)

    result = await client.complete("hello")

    assert result == "ok"


@pytest.mark.asyncio
async def test_client_complete_forwards_byok_source_to_factory(
    monkeypatch: MonkeyPatch,
) -> None:
    """The explicit config source must survive a missing request ContextVar."""
    config = LLMConfig(
        model="model",
        api_key="key",
        base_url="https://example.com",
        source="byok",
    )
    captured: dict[str, object] = {}

    async def _fake_complete(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", _fake_complete)

    assert await LLMClient(config).complete("hello") == "ok"
    assert captured["source"] == "byok"


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


def test_client_reports_multimodal_image_support() -> None:
    assert (
        LLMClient(
            LLMConfig(model="gpt-4o", api_key="key", base_url="https://example.com")
        ).supports_multimodal_images()
        is True
    )
    assert (
        LLMClient(
            LLMConfig(model="gpt-3.5-turbo", api_key="key", base_url="https://example.com")
        ).supports_multimodal_images()
        is False
    )


def test_agentic_client_wraps_byok_calls_with_safety_accounting_not_platform_quota() -> None:
    client = SimpleNamespace(chat=SimpleNamespace(completions=object()))
    wrapped = agentic_client._wrap_token_quota(client, source="byok")
    assert isinstance(wrapped, agentic_client._TokenQuotaClient)
    assert wrapped._client is client


def test_agentic_client_wraps_platform_calls_when_user_quota_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.token_quota.current_user_quota_policy",
        lambda: object(),
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=object()))

    wrapped = agentic_client._wrap_token_quota(client, source="platform")

    assert isinstance(wrapped, agentic_client._TokenQuotaClient)
    assert wrapped._client is client


def test_llm_client_does_not_write_byok_key_to_process_environment(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = LLMClient(
        LLMConfig(
            model="gpt-user",
            api_key="sk-user-secret",
            base_url="https://api.openai.com/v1",
            source="byok",
        )
    )
    assert client.config.api_key == "sk-user-secret"
    assert "OPENAI_API_KEY" not in __import__("os").environ


@pytest.mark.asyncio
async def test_client_complete_sync_running_loop() -> None:
    """complete_sync should raise when called from a running event loop."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    with pytest.raises(RuntimeError):
        client.complete_sync("hello")


@pytest.mark.asyncio
async def test_client_get_model_func_uses_factory(monkeypatch: MonkeyPatch) -> None:
    """get_model_func should append prompt after history messages."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    captured: dict[str, object] = {}

    async def _fake_complete(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", _fake_complete)

    func = client.get_model_func()
    result = await func(
        "hello",
        system_prompt="sys",
        history_messages=[{"role": "user", "content": "old"}],
    )

    assert result == "ok"
    assert captured["prompt"] == "hello"
    assert captured["system_prompt"] == "sys"
    assert captured["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "old"},
        {"role": "user", "content": "hello"},
    ]


@pytest.mark.asyncio
async def test_client_get_model_func_empty_history_uses_prompt(
    monkeypatch: MonkeyPatch,
) -> None:
    """Empty history_messages must not override the current prompt."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    captured: dict[str, object] = {}

    async def _fake_complete(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", _fake_complete)

    func = client.get_model_func()
    result = await func("hello", system_prompt="sys", history_messages=[])

    assert result == "ok"
    assert captured["prompt"] == "hello"
    assert captured["system_prompt"] == "sys"
    assert captured["messages"] is None


@pytest.mark.asyncio
async def test_client_get_model_func_explicit_messages_override_prompt(
    monkeypatch: MonkeyPatch,
) -> None:
    """Explicit messages are already complete and should pass through as-is."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    captured: dict[str, object] = {}

    async def _fake_complete(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", _fake_complete)

    messages = [{"role": "user", "content": "from messages"}]
    func = client.get_model_func()
    result = await func("", system_prompt="sys", messages=messages)

    assert result == "ok"
    assert captured["messages"] == messages


@pytest.mark.asyncio
async def test_client_get_vision_model_func_uses_factory(monkeypatch: MonkeyPatch) -> None:
    """Vision model func should pass multimodal args into factory."""
    config = LLMConfig(model="model", api_key="key", base_url="https://example.com")
    client = LLMClient(config)

    captured: dict[str, object] = {}

    async def _fake_complete(**kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr("deeptutor.services.llm.factory.complete", _fake_complete)

    func = client.get_vision_model_func()
    result = await func(
        "hello",
        image_data="abc123",
        messages=[{"role": "user", "content": "hi"}],
    )

    assert result == "ok"
    assert captured["prompt"] == "hello"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["image_data"] == "abc123"
