from __future__ import annotations

import asyncio
import os
import uuid

import pytest

from deeptutor.runtime.coordination import RedisCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytestmark = [pytest.mark.asyncio, pytest.mark.redis_integration]


async def test_four_workers_complete_one_thousand_turns_without_conflicts(tmp_path) -> None:
    """Exercise the release-scale coordination invariants against real Redis.

    The fake workload deliberately keeps provider execution out of the test so
    lease, event, command, and durable-state failures remain deterministic.
    """

    redis_url = os.environ.get("DEEPTUTOR_TEST_REDIS_URL", "")
    if not redis_url:
        pytest.skip("DEEPTUTOR_TEST_REDIS_URL is not configured")

    prefix = f"deeptutor-stress-{uuid.uuid4().hex}"
    coordinators = [
        RedisCoordinator(
            redis_url,
            key_prefix=prefix,
            lease_ttl_seconds=10,
            stream_retention_seconds=300,
        )
        for _ in range(4)
    ]
    if not await coordinators[0].health():
        pytest.skip("test Redis is unavailable")

    database_path = tmp_path / "stress.sqlite3"
    stores = [SQLiteSessionStore(database_path) for _ in range(4)]
    session_ids = [f"stress-session-{index}" for index in range(200)]
    for session_id in session_ids:
        await stores[0].create_session(session_id=session_id)

    gate = asyncio.Semaphore(50)

    async def execute_turn(round_index: int, session_index: int) -> None:
        async with gate:
            worker_index = (round_index + session_index) % len(coordinators)
            coordinator = coordinators[worker_index]
            store = stores[worker_index]
            session_id = session_ids[session_index]
            turn_id = f"stress-turn-{round_index}-{session_index}"
            lease = await coordinator.acquire_turn(turn_id, session_id, f"worker-{worker_index}")
            assert lease is not None

            # Every other worker races to create a different turn for the same
            # session. Redis must reject all of them before SQLite sees a write.
            contenders = await asyncio.gather(
                *(
                    candidate.acquire_turn(
                        f"rejected-{round_index}-{session_index}-{candidate_index}",
                        session_id,
                        f"worker-{candidate_index}",
                    )
                    for candidate_index, candidate in enumerate(coordinators)
                    if candidate_index != worker_index
                )
            )
            assert contenders == [None, None, None]

            await store.begin_turn(
                session_id,
                "chat",
                turn_id=turn_id,
                owner_id=lease.owner_id,
                fencing_token=lease.fencing_token,
            )
            content = await coordinator.publish_event(
                turn_id,
                {"type": "content", "content": turn_id, "source": "stress"},
            )
            done = await coordinator.publish_event(
                turn_id,
                {
                    "type": "done",
                    "content": "",
                    "source": "stress",
                    "metadata": {"status": "completed"},
                },
            )

            remote = coordinators[(worker_index + 1) % len(coordinators)]
            replay = await remote.read_events(turn_id)
            assert replay == [content, done]
            assert [event["seq"] for event in replay] == [1, 2]
            assert await remote.read_events(turn_id, after_seq=1) == [done]

            command_id = f"duplicate-{turn_id}"
            commands = await asyncio.gather(
                remote.submit_command(turn_id, "cancel", command_id=command_id),
                coordinator.submit_command(turn_id, "cancel", command_id=command_id),
            )
            assert sum(command is not None for command in commands) == 1
            assert len(await coordinator.read_commands(turn_id)) == 1

            await store.append_events(
                turn_id,
                replay,
                fencing_token=lease.fencing_token,
            )
            assert await store.transition_turn(
                turn_id,
                "completed",
                expected_status="running",
                fencing_token=lease.fencing_token,
            )
            assert await coordinator.release_turn(lease)

    try:
        for round_index in range(5):
            await asyncio.gather(
                *(execute_turn(round_index, session_index) for session_index in range(200))
            )

        assert await stores[0].list_nonterminal_turns() == []
        for session_id in session_ids:
            assert await stores[0].get_active_turn(session_id) is None
    finally:
        keys = [key async for key in coordinators[0].client.scan_iter(match=f"{prefix}:*")]
        if keys:
            await coordinators[0].client.delete(*keys)
        await asyncio.gather(*(coordinator.close() for coordinator in coordinators))
