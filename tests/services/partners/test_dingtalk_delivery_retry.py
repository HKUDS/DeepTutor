"""DingTalk delivery failures must reach the shared retry boundary."""

import json

import httpx
import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.dingtalk import DingTalkChannel
from deeptutor.partners.channels.manager import send_with_retry


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["token", "http", "api"])
async def test_transient_text_failure_is_retried(failure: str) -> None:
    """Use the native HTTP client and public sender, without external accounts."""
    token_requests = 0
    messages: list[dict] = []
    delivered: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal token_requests
        if request.url.path.endswith("accessToken"):
            token_requests += 1
            if failure == "token" and token_requests == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"accessToken": "test-token", "expireIn": 7200})
        payload = json.loads(request.content)
        messages.append(payload)
        if len(messages) == 1 and failure == "http":
            return httpx.Response(503)
        if len(messages) == 1 and failure == "api":
            return httpx.Response(200, json={"errcode": 500, "errmsg": "temporarily unavailable"})
        delivered.append(json.loads(payload["msgParam"])["text"])
        return httpx.Response(200, json={"processQueryKey": "test-delivery"})

    channel = DingTalkChannel(
        {"client_id": "test-id", "client_secret": "test-secret"}, MessageBus()
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        channel._http = client
        await send_with_retry(
            channel,
            OutboundMessage(channel="dingtalk", chat_id="test-recipient", content="学习回复"),
            max_attempts=2,
            retry_delays=(0,),
        )
    assert delivered == ["学习回复"]
    assert token_requests == (2 if failure == "token" else 1)
    assert len(messages) == (1 if failure == "token" else 2)
