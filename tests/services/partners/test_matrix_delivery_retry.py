"""Native Matrix SDK error responses must reach the shared retry boundary."""

from aiohttp import web
import pytest

from deeptutor.partners.bus.events import OutboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.manager import send_with_retry


@pytest.mark.asyncio
async def test_matrix_error_response_is_retried() -> None:
    """Exercise the native SDK against a local server, without a Matrix account."""
    pytest.importorskip("nio")
    from nio import AsyncClient, AsyncClientConfig

    from deeptutor.partners.channels.matrix import MatrixChannel

    requests = 0
    delivered: list[str] = []

    async def send(request: web.Request) -> web.Response:
        nonlocal requests
        if "/send/" not in request.path:
            return web.json_response({})
        requests += 1
        if requests == 1:
            return web.json_response({"errcode": "M_UNKNOWN", "error": "try again"}, status=400)
        delivered.append((await request.json())["body"])
        return web.json_response({"event_id": "$test-delivery"})

    app = web.Application()
    app.router.add_put("/{path:.*}", send)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    client = AsyncClient(
        f"http://127.0.0.1:{port}",
        user="@test:localhost",
        config=AsyncClientConfig(max_limit_exceeded=0, max_timeouts=0),
    )
    client.access_token = "test-token"
    channel = MatrixChannel({}, MessageBus())
    channel.client = client
    try:
        await send_with_retry(
            channel,
            OutboundMessage(channel="matrix", chat_id="!test:localhost", content="学习回复"),
            max_attempts=2,
            retry_delays=(0,),
        )
        assert delivered == ["学习回复"]
        assert requests == 2
    finally:
        await client.close()
        await runner.cleanup()
