from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from deeptutor.runtime.coordination import RedisCoordinator

pytestmark = [pytest.mark.asyncio, pytest.mark.redis_integration]


@pytest_asyncio.fixture
async def coordinator():
    url = os.environ.get("DEEPTUTOR_TEST_REDIS_URL", "")
    if not url:
        pytest.skip("DEEPTUTOR_TEST_REDIS_URL is not configured")
    prefix = f"deeptutor-test-{uuid.uuid4().hex}"
    instance = RedisCoordinator(url, key_prefix=prefix, lease_ttl_seconds=10)
    if not await instance.health():
        pytest.skip("test Redis is unavailable")
    try:
        yield instance
    finally:
        keys = [key async for key in instance.client.scan_iter(match=f"{prefix}:*")]
        if keys:
            await instance.client.delete(*keys)
        await instance.close()


async def test_redis_lease_event_command_and_leader_contract(coordinator) -> None:
    lease = await coordinator.acquire_turn("turn-a", "session-a", "worker-a")
    assert lease is not None
    assert await coordinator.acquire_turn("turn-b", "session-a", "worker-b") is None
    assert await coordinator.renew_turn(lease) is not None

    first = await coordinator.publish_event("turn-a", {"type": "content", "content": "hello"})
    assert first["seq"] == 1
    assert await coordinator.publish_event("turn-a", first) == first
    assert await coordinator.read_events("turn-a") == [first]

    command = await coordinator.submit_command("turn-a", "cancel", {}, command_id="command-a")
    assert command is not None
    assert await coordinator.submit_command("turn-a", "cancel", {}, command_id="command-a") is None
    assert (await coordinator.read_commands("turn-a"))[0][1] == command

    background = await coordinator.submit_background_command(
        "cron_reload", command_id="background-a"
    )
    assert background is not None
    background_rows = await coordinator.read_background_commands()
    assert background_rows[0][1] == background
    leader = await coordinator.acquire_leader("worker-a")
    assert leader is not None
    stale = leader.__class__("worker-b", leader.fencing_token, leader.expires_at)
    assert await coordinator.acknowledge_background_command(background_rows[0][0], stale) is False
    assert await coordinator.acknowledge_background_command(background_rows[0][0], leader) is True
    assert await coordinator.read_background_commands() == []

    assert await coordinator.acquire_leader("worker-b") is None
    assert await coordinator.leader_id() == "worker-a"
    assert await coordinator.release_leader(leader) is True
    assert await coordinator.release_turn(lease) is True


async def test_two_redis_coordinators_share_turn_and_background_streams(coordinator) -> None:
    second = RedisCoordinator(
        coordinator.redis_url,
        key_prefix=coordinator.key_prefix,
        lease_ttl_seconds=coordinator.lease_ttl_seconds,
    )
    try:
        lease = await coordinator.acquire_turn("turn-shared", "session-shared", "worker-a")
        assert lease is not None
        observed = await second.get_lease("turn-shared")
        assert observed is not None
        assert observed.turn_id == lease.turn_id
        assert observed.session_id == lease.session_id
        assert observed.owner_id == lease.owner_id
        assert observed.fencing_token == lease.fencing_token
        assert observed.expires_at == pytest.approx(lease.expires_at, abs=0.05)

        published = await coordinator.publish_event(
            "turn-shared", {"type": "content", "content": "from-a"}
        )
        assert await second.read_events("turn-shared") == [published]

        command = await second.submit_command("turn-shared", "cancel", command_id="cancel-from-b")
        assert command is not None
        assert (await coordinator.read_commands("turn-shared"))[0][1] == command

        background = await second.submit_background_command(
            "partner_reload",
            {"partner_id": "ada"},
            command_id="reload-from-b",
        )
        assert background is not None
        rows = await coordinator.read_background_commands()
        assert rows[0][1] == background
        await coordinator.acknowledge_background_command(rows[0][0])
        assert await second.read_background_commands() == []
        assert await coordinator.release_turn(lease) is True
    finally:
        await second.close()
