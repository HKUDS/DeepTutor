from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.llm.provider_core import github_copilot_provider as module


@pytest.mark.asyncio
async def test_provider_exchanges_stored_token_before_every_uncached_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exchanges = 0
    seen_keys: list[str] = []

    async def exchange():
        nonlocal exchanges
        exchanges += 1
        return SimpleNamespace(token="copilot-access", expires_at=2_000_000_000)

    async def chat(self, **_kwargs):
        seen_keys.append(self.api_key)
        return SimpleNamespace(content="ok")

    monkeypatch.setattr(module, "exchange_copilot_token", exchange)
    monkeypatch.setattr(module.OpenAICompatProvider, "chat", chat)

    provider = module.GitHubCopilotProvider()
    assert provider._key_pool is None
    await provider.chat(messages=[{"role": "user", "content": "hello"}])
    await provider.chat(messages=[{"role": "user", "content": "again"}])

    assert exchanges == 1
    assert seen_keys == ["copilot-access", "copilot-access"]
