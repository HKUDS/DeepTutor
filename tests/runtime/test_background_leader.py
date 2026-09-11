from __future__ import annotations

import asyncio

import pytest

from deeptutor.runtime.background_leader import BackgroundLeaderSupervisor
from deeptutor.runtime.coordination import MemoryCoordinator


@pytest.mark.asyncio
async def test_only_one_supervisor_runs_services_and_successor_takes_over() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=0.08)
    running: set[str] = set()
    max_running = 0

    def callbacks(worker_id: str):
        async def start() -> None:
            nonlocal max_running
            running.add(worker_id)
            max_running = max(max_running, len(running))

        async def stop() -> None:
            running.discard(worker_id)

        return start, stop

    start_a, stop_a = callbacks("a")
    start_b, stop_b = callbacks("b")
    first = BackgroundLeaderSupervisor(
        coordinator,
        "a",
        start_callbacks=[start_a],
        stop_callbacks=[stop_a],
        renew_interval_seconds=0.02,
        election_interval_seconds=0.01,
    )
    second = BackgroundLeaderSupervisor(
        coordinator,
        "b",
        start_callbacks=[start_b],
        stop_callbacks=[stop_b],
        renew_interval_seconds=0.02,
        election_interval_seconds=0.01,
    )
    await first.start()
    await second.start()
    await asyncio.sleep(0.05)
    assert len(running) == 1
    assert max_running == 1

    leader = next(iter(running))
    await (first if leader == "a" else second).close()
    await asyncio.sleep(0.05)
    assert running == ({"b"} if leader == "a" else {"a"})
    assert max_running == 1

    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_background_commands_run_once_and_continue_after_leader_transfer() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=0.08)
    handled: list[tuple[str, str]] = []

    def callback(worker_id: str):
        async def handle(command) -> None:
            handled.append((worker_id, command.command_id))

        return handle

    first = BackgroundLeaderSupervisor(
        coordinator,
        "a",
        control_callback=callback("a"),
        renew_interval_seconds=0.02,
        election_interval_seconds=0.01,
    )
    second = BackgroundLeaderSupervisor(
        coordinator,
        "b",
        control_callback=callback("b"),
        renew_interval_seconds=0.02,
        election_interval_seconds=0.01,
    )
    await coordinator.submit_background_command("cron_reload", command_id="before")
    await first.start()
    await second.start()
    await asyncio.sleep(0.05)
    assert [command_id for _, command_id in handled] == ["before"]

    leader = await coordinator.leader_id()
    assert leader in {"a", "b"}
    await (first if leader == "a" else second).close()
    await asyncio.sleep(0.05)
    await coordinator.submit_background_command("cron_reload", command_id="after")
    await asyncio.sleep(0.05)

    assert [command_id for _, command_id in handled] == ["before", "after"]
    assert handled[-1][0] != leader
    await first.close()
    await second.close()


@pytest.mark.asyncio
async def test_slow_service_start_keeps_leader_lease_alive() -> None:
    coordinator = MemoryCoordinator(lease_ttl_seconds=0.05)
    started = asyncio.Event()
    release_start = asyncio.Event()
    contenders: list[str] = []

    async def slow_start() -> None:
        started.set()
        await release_start.wait()

    supervisor = BackgroundLeaderSupervisor(
        coordinator,
        "leader",
        start_callbacks=[slow_start],
        stop_callbacks=[lambda: asyncio.sleep(0)],
        renew_interval_seconds=0.01,
        election_interval_seconds=0.005,
    )
    await supervisor.start()
    await asyncio.wait_for(started.wait(), timeout=0.1)
    await asyncio.sleep(0.08)
    contender = await coordinator.acquire_leader("contender")
    if contender is not None:
        contenders.append(contender.owner_id)

    assert contenders == []
    assert await coordinator.leader_id() == "leader"

    release_start.set()
    await supervisor.close()
