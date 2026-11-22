"""Stop ACK must fence admission through the owner's final lease release."""

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import auth, unified_ws
from deeptutor.app.service import TurnApplicationService


class CancelProtocolTests(unittest.TestCase):
    def test_ack_waits_for_owner_teardown(self):
        entered, released = Event(), Event()

        async def allow(_ws):
            return None

        async def accepted_only(*_args, **_kwargs):
            entered.set()
            return True

        async def settled(*_args, **_kwargs):
            entered.set()
            await asyncio.to_thread(released.wait, 3)
            return released.is_set()

        turns = NS(cancel_turn=accepted_only, cancel_turn_and_wait=settled)
        app = FastAPI()
        app.state.application_container = NS(turns=turns)
        app.include_router(unified_ws.router)
        with patch.object(auth, "ws_require_auth", allow), TestClient(app) as client:
            with client.websocket_connect("/ws") as ws, ThreadPoolExecutor() as pool:
                ws.send_json(
                    {
                        "type": "cancel_turn",
                        "turn_id": "turn-test",
                        "command_id": "stop-test",
                        "protocol_version": "2.0",
                    }
                )
                receipt = pool.submit(ws.receive_json)
                try:
                    self.assertTrue(entered.wait(2))
                    with self.assertRaises(TimeoutError):
                        receipt.result(timeout=0.05)
                finally:
                    released.set()
                self.assertTrue(receipt.result(timeout=3)["accepted"])


class CancelReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_row_still_waits_for_lease_and_duplicate_stop_is_safe(self):
        turn = {"id": "test-turn", "status": "cancelled"}
        store = NS(get_turn=AsyncMock(return_value=turn))
        coordinator = NS(get_lease=AsyncMock(side_effect=[object(), None]))
        service = NS(
            cancel_turn=AsyncMock(return_value=False),
            _resolve=lambda: (store, None),
            coordinator=coordinator,
            _ACTIVE_TURN_STATUSES={"queued", "running", "waiting_input"},
            _CANCEL_WAIT_INTERVAL_SECONDS=0.001,
        )
        result = await TurnApplicationService.cancel_turn_and_wait.__wrapped__(
            service, "test-turn", command_id="same-stop", timeout_seconds=1
        )
        self.assertTrue(result)
        self.assertEqual(coordinator.get_lease.await_count, 2)

    async def test_lease_timeout_cannot_acknowledge_stopped(self):
        store = NS(get_turn=AsyncMock(return_value={"id": "test-turn", "status": "cancelled"}))
        service = NS(
            cancel_turn=AsyncMock(return_value=False),
            _resolve=lambda: (store, None),
            coordinator=NS(get_lease=AsyncMock(return_value=object())),
            _ACTIVE_TURN_STATUSES={"queued", "running", "waiting_input"},
            _CANCEL_WAIT_INTERVAL_SECONDS=0.001,
        )
        self.assertFalse(
            await TurnApplicationService.cancel_turn_and_wait.__wrapped__(
                service, "test-turn", timeout_seconds=0
            )
        )
