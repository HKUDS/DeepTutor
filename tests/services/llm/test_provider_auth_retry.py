"""Exercise OAuth recovery through real SDK HTTP error handling."""

from __future__ import annotations

import json

import httpx
from openai import AsyncOpenAI
import pytest

from deeptutor.services.codebuddy_credentials import CodeBuddyCredentials
from deeptutor.services.llm.provider_core import codebuddy_http_provider as codebuddy


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_http_401_reaches_provider_auth_recovery(
    monkeypatch: pytest.MonkeyPatch, stream: bool
) -> None:
    credentials = iter([CodeBuddyCredentials("old-token"), CodeBuddyCredentials("new-token")])
    monkeypatch.setattr(codebuddy, "load_credentials", lambda: next(credentials))
    provider = codebuddy.CodeBuddyHTTPProvider(configure_env=False)
    await provider._client.close()
    authorizations: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        authorizations.append(request.headers["authorization"])
        if len(authorizations) == 1:
            return httpx.Response(
                401, json={"error": {"message": "expired", "type": "authentication_error"}}
            )
        payload = json.loads(request.content)
        choice = {"index": 0, "finish_reason": "stop"}
        if payload.get("stream"):
            chunk = {
                "id": "reply",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "test",
                "choices": [{**choice, "delta": {"content": "OK"}}],
            }
            return httpx.Response(
                200,
                text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(
            200,
            json={
                "id": "reply",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [{**choice, "message": {"role": "assistant", "content": "OK"}}],
            },
        )

    provider._client = AsyncOpenAI(
        api_key="old-token",
        base_url="https://provider.invalid/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    provider._wire_api = "chat_completions"
    try:
        call = provider.chat_stream if stream else provider.chat
        result = await call(messages=[{"role": "user", "content": "hello"}])
        assert result.content == "OK"
        assert result.finish_reason == "stop"
        assert len(authorizations) == 2
        assert authorizations[-1] == "Bearer new-token"
    finally:
        await provider.aclose()
