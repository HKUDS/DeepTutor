"""Card actions must reach the handler over the configured Feishu WS transport."""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.partners.channels.feishu import _card_aware_ws_client


def _card_frame(ws_module, payload: bytes):
    frame = ws_module.Frame()
    frame.SeqID = 1
    frame.LogID = 1
    frame.service = 1
    frame.method = 1
    for key, value in (
        (ws_module.HEADER_TYPE, ws_module.MessageType.CARD.value),
        (ws_module.HEADER_MESSAGE_ID, "card-action-1"),
        (ws_module.HEADER_SUM, "1"),
        (ws_module.HEADER_SEQ, "0"),
    ):
        header = frame.headers.add()
        header.key = key
        header.value = value
    frame.payload = payload
    return frame


@pytest.mark.asyncio
async def test_card_frame_dispatches_and_returns_in_place_card_response() -> None:
    lark = pytest.importorskip("lark_oapi")
    import lark_oapi.ws.client as ws_module

    client_type = _card_aware_ws_client(lark.ws.Client, ws_module)
    client = object.__new__(client_type)
    response_card = {"card": {"type": "raw", "data": {"elements": []}}}
    client._event_handler = SimpleNamespace(
        do_without_validation=MagicMock(return_value=response_card)
    )
    client._write_message = AsyncMock()
    frame = _card_frame(ws_module, b'{"type":"card.action.trigger"}')

    await client._handle_data_frame(frame)

    client._event_handler.do_without_validation.assert_called_once_with(
        b'{"type":"card.action.trigger"}'
    )
    client._write_message.assert_awaited_once()
    sent = ws_module.Frame.FromString(client._write_message.await_args.args[0])
    assert ws_module._get_by_key(sent.headers, ws_module.HEADER_TYPE) == "card"
    envelope = json.loads(sent.payload)
    assert envelope["code"] == 200
    assert json.loads(base64.b64decode(envelope["data"])) == response_card


@pytest.mark.asyncio
async def test_card_callback_failure_returns_error_frame() -> None:
    lark = pytest.importorskip("lark_oapi")
    import lark_oapi.ws.client as ws_module

    client = object.__new__(_card_aware_ws_client(lark.ws.Client, ws_module))
    client._event_handler = SimpleNamespace(
        do_without_validation=MagicMock(side_effect=ValueError("invalid callback"))
    )
    client._write_message = AsyncMock()

    await client._handle_data_frame(_card_frame(ws_module, b"{}"))

    sent = ws_module.Frame.FromString(client._write_message.await_args.args[0])
    assert json.loads(sent.payload)["code"] == 500


@pytest.mark.asyncio
async def test_real_sdk_dispatcher_routes_card_action_over_websocket() -> None:
    lark = pytest.importorskip("lark_oapi")
    from lark_oapi.event.callback.model.p2_card_action_trigger import (
        CallBackCard,
        P2CardActionTriggerResponse,
    )
    import lark_oapi.ws.client as ws_module

    callback = MagicMock()

    def handle(data):
        callback(data)
        result = P2CardActionTriggerResponse()
        result.card = CallBackCard()
        result.card.type = "raw"
        result.card.data = {"elements": []}
        return result

    handler = (
        lark.EventDispatcherHandler.builder("", "").register_p2_card_action_trigger(handle).build()
    )
    client = object.__new__(_card_aware_ws_client(lark.ws.Client, ws_module))
    client._event_handler = handler
    client._write_message = AsyncMock()
    payload = json.dumps(
        {
            "schema": "2.0",
            "header": {"event_type": "card.action.trigger", "token": ""},
            "event": {
                "operator": {"open_id": "ou_owner"},
                "action": {"value": {"picker_id": "picker-1", "action": "page", "page": 1}},
                "context": {"open_message_id": "om_picker"},
            },
        }
    ).encode()

    await client._handle_data_frame(_card_frame(ws_module, payload))

    callback.assert_called_once()
    assert callback.call_args.args[0].event.operator.open_id == "ou_owner"
    sent = ws_module.Frame.FromString(client._write_message.await_args.args[0])
    envelope = json.loads(sent.payload)
    assert envelope["code"] == 200
    assert json.loads(base64.b64decode(envelope["data"])) == {
        "card": {"type": "raw", "data": {"elements": []}}
    }
