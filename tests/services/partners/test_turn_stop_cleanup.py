"""Partner stop boundaries own their detached web and inbound turns."""

import asyncio

import pytest

from deeptutor.services.partners.manager import PartnerConfig, PartnerManager


@pytest.mark.asyncio
@pytest.mark.parametrize("queued", [True, False])
async def test_stop_partner_finishes_web_turn_and_releases_file_lease(
    partners_root, monkeypatch, queued
):
    manager = PartnerManager()
    manager.save_config("ada", PartnerConfig(name="Ada"))
    await manager.start_partner("ada")
    entered = asyncio.Event()

    async def pending_reply(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(manager, "send_message", pending_reply)
    turn = manager.start_web_turn("ada", "web-test", "question")
    queue = turn.subscribe()
    try:
        if not queued:
            await asyncio.wait_for(entered.wait(), timeout=1)
        await manager.stop_partner("ada")
        assert turn.task.done()
        assert turn.done
        assert queue.get_nowait()["type"] == "stopped"
        assert not manager.web_session_is_busy("ada", "web-test")
    finally:
        turn.task.cancel()
        await asyncio.gather(turn.task, return_exceptions=True)
        if not turn.done:
            turn.finish([])
        await manager.stop_partner("ada")


@pytest.mark.asyncio
async def test_immediate_stop_web_turn_finishes_queued_task(partners_root):
    manager = PartnerManager()
    manager.save_config("ada", PartnerConfig(name="Ada"))
    await manager.start_partner("ada")
    turn = manager.start_web_turn("ada", "web-test", "question")
    queue = turn.subscribe()
    try:
        assert manager.stop_web_turn("ada", "web-test")
        await asyncio.gather(turn.task, return_exceptions=True)
        assert turn.done
        assert queue.get_nowait()["type"] == "stopped"
        assert not manager.web_session_is_busy("ada", "web-test")
    finally:
        if not turn.done:
            turn.finish([])
        await manager.stop_partner("ada")
