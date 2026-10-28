from __future__ import annotations

import asyncio
from contextvars import ContextVar
from pathlib import Path
import shutil

import pytest
import pytest_asyncio

from deeptutor.runtime.ts_engine.client import EngineClient, EngineUnavailableError

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None
    or not (
        Path(__file__).parents[2] / "packages/chat-engine/dist/src/transport/stdio.js"
    ).is_file(),
    reason="Build the experimental TypeScript engine first",
)

CONFIG = {"explorationBudget": 3, "settlementBudget": 3, "emptyRecoveryBudget": 2}
SCOPE = ContextVar("test_engine_scope", default="missing")


class Host:
    def __init__(self, *, gate=None, failure=None):
        self.seen = []
        self.gate = gate
        self.failure = failure
        self.entered = asyncio.Event()

    async def invoke(self, operation, args, state):
        self.seen.append((operation, SCOPE.get()))
        if operation == "call_round":
            self.entered.set()
            if self.gate is not None:
                await self.gate.wait()
            if self.failure is not None:
                raise self.failure
            return dict(
                hasTools=False, hasText=True, truncated=False, reasoningBudgetExhausted=False
            )
        if operation == "check_finish":
            return dict(redirect=False, override=False)
        return None


@pytest_asyncio.fixture
async def client():
    client = EngineClient()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_shared_worker_preserves_each_turn_context(client):
    async def run(scope):
        token = SCOPE.set(scope)
        try:
            host = Host()
            state = await client.run(host, CONFIG)
            assert state["rounds"] == 1
            assert host.seen == [(op, scope) for op in ["call_round", "check_finish", "finish"]]
        finally:
            SCOPE.reset(token)

    await asyncio.gather(*(run(f"owner-{i}/workspace-{i}") for i in range(12)))
    assert client._runs == {}


@pytest.mark.asyncio
async def test_cancel_one_turn_does_not_cancel_or_replay_its_peer(client):
    host = Host(gate=asyncio.Event())
    waiting = asyncio.create_task(client.run(host, CONFIG))
    await host.entered.wait()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    survivor = Host()
    assert (await client.run(survivor, CONFIG))["rounds"] == 1
    assert [op for op, _ in host.seen] == ["call_round"]
    assert client._runs == {}


@pytest.mark.asyncio
async def test_typed_host_failure_is_preserved_across_bridge(client):
    error = ValueError("typed original exception")
    with pytest.raises(ValueError) as raised:
        await client.run(Host(failure=error), CONFIG)
    assert raised.value is error


@pytest.mark.asyncio
async def test_worker_failure_does_not_repeat_completed_side_effects(client):
    gate = asyncio.Event()
    host = Host(gate=gate)
    running = asyncio.create_task(client.run(host, CONFIG))
    await host.entered.wait()
    assert client._process is not None
    client._process.kill()
    await client._process.wait()
    with pytest.raises(EngineUnavailableError):
        await asyncio.wait_for(running, timeout=1)
    assert [op for op, _ in host.seen] == ["call_round"]
    # A new turn may create a fresh worker; the failed turn is not retried.
    assert (await client.run(Host(), CONFIG))["rounds"] == 1


@pytest.mark.asyncio
async def test_close_terminates_child_and_fails_pending_turn(client):
    await client._ensure_started()
    process = client._process
    await client.close()
    assert process is not None and process.returncode is not None


@pytest.mark.asyncio
async def test_idle_worker_releases_memory_and_a_new_turn_restarts_it(client, monkeypatch):
    monkeypatch.setattr("deeptutor.runtime.ts_engine.client._IDLE_WORKER_SECONDS", 0.01)
    await client.run(Host(), CONFIG)
    first = client._process
    await asyncio.sleep(0.1)
    assert first is not None and first.returncode is not None
    await client.run(Host(), CONFIG)
    assert client._process is not None and client._process.pid != first.pid


@pytest.mark.asyncio
async def test_idle_cleanup_never_interrupts_a_waiting_peer(client, monkeypatch):
    monkeypatch.setattr("deeptutor.runtime.ts_engine.client._IDLE_WORKER_SECONDS", 0.01)
    gate = asyncio.Event()
    host = Host(gate=gate)
    waiting = asyncio.create_task(client.run(host, CONFIG))
    await host.entered.wait()
    process = client._process
    await client.run(Host(), CONFIG)
    await asyncio.sleep(0.03)
    assert process is not None and process.returncode is None
    gate.set()
    assert (await waiting)["rounds"] == 1


@pytest.mark.asyncio
async def test_mid_turn_prerequisite_failure_never_salvages_across_bridge(client):
    from deeptutor.core.capability_protocol import CapabilityPrerequisiteError

    error = CapabilityPrerequisiteError("source unavailable")
    operations = []

    class PrerequisiteHost:
        async def invoke(self, operation, args, state):
            operations.append(operation)
            if operation == "call_round":
                if state["rounds"]:
                    raise error
                return dict(
                    hasTools=True, hasText=False, truncated=False, reasoningBudgetExhausted=False
                )
            if operation == "dispatch_tools":
                return {"pause": False}
            if operation == "after_tools":
                return {"override": False, "terminate": False}
            raise AssertionError(f"Unexpected operation: {operation}")

    with pytest.raises(CapabilityPrerequisiteError) as raised:
        await client.run(PrerequisiteHost(), CONFIG)
    assert raised.value is error
    assert operations == ["call_round", "dispatch_tools", "after_tools", "call_round"]
