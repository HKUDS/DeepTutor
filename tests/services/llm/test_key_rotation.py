from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


@pytest.mark.asyncio
async def test_openai_compatible_llm_retries_429_with_next_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services.llm.provider_core import openai_compat_provider as provider_module

    seen_auth: list[str] = []

    class _RateLimitError(Exception):
        status_code = 429

    class _Completions:
        async def create(self, **kwargs: Any) -> Any:
            seen_auth.append((kwargs.get("extra_headers") or {}).get("Authorization", ""))
            if len(seen_auth) == 1:
                raise _RateLimitError("429 rate limited")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="ok",
                            tool_calls=[],
                            reasoning_content=None,
                            reasoning=None,
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

    class _Client:
        def __init__(self, **_kwargs: Any) -> None:
            self.chat = SimpleNamespace(completions=_Completions())
            self.responses = SimpleNamespace()

    monkeypatch.setattr(provider_module, "AsyncOpenAI", _Client)
    provider = provider_module.OpenAICompatProvider(
        api_key=["key-a", "key-b"],
        api_base="https://api.example.test/v1",
        default_model="gpt-4o-mini",
    )

    response = await provider.chat([{"role": "user", "content": "hello"}])

    assert response.content == "ok"
    assert seen_auth == ["Bearer key-a", "Bearer key-b"]
