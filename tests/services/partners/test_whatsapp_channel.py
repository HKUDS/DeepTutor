from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from deeptutor.partners.bus.queue import MessageBus
from deeptutor.partners.channels.whatsapp import WhatsAppChannel, WhatsAppConfig


def _channel() -> WhatsAppChannel:
    return WhatsAppChannel(
        WhatsAppConfig(enabled=True, allow_from=["*"]),
        MagicMock(spec=MessageBus),
    )


@pytest.mark.asyncio
async def test_bridge_qr_is_published_for_the_webui() -> None:
    channel = _channel()

    await channel._handle_bridge_message(json.dumps({"type": "qr", "qr": "scan-me"}))

    assert channel.setup_state == {
        "status": "waiting_for_scan",
        "qr_payload": "scan-me",
    }


@pytest.mark.asyncio
async def test_bridge_connection_status_is_published_for_the_webui() -> None:
    channel = _channel()

    await channel._handle_bridge_message(json.dumps({"type": "status", "status": "connected"}))

    assert channel.setup_state == {"status": "connected"}
