"""Mochat delivery errors must propagate to the public retry boundary."""

import json

import httpx
import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.manager import send_with_retry
from deeptutor.partners.channels.mochat import MochatChannel


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "api"])
async def test_mochat_delivery_is_retried(failure: str) -> None:
    """Use actual HTTP response parsing and the channel's session send path."""
    requests = 0
    delivered: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        if requests == 1:
            if failure == "http":
                return httpx.Response(503)
            return httpx.Response(200, json={"code": 503, "message": "try again"})
        delivered.append(json.loads(request.content)["content"])
        return httpx.Response(200, json={"code": 200, "data": {"messageId": "test-delivery"}})

    channel = MochatChannel({"claw_token": "test-token"}, MessageBus())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        channel._http = client
        await send_with_retry(
            channel,
            OutboundMessage(channel="mochat", chat_id="session_test", content="学习回复"),
            max_attempts=2,
            retry_delays=(0,),
        )
    assert delivered == ["学习回复"]
    assert requests == 2
