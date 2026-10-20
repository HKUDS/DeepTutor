"""A lost-ack resend must reuse the original conversation and its message.

When the worker owning a turn dies (or the reply/cancel acknowledgement is
lost), recovery fails the zombie with ``worker_lost`` and tells the learner
to resend their answer as a new message. The resend contract: the resent
submission lands in the ORIGINAL conversation, reuses the ORIGINAL user
message row (never a duplicate), and never forks the session into a second
conversation — the guarantee the submission reservation (#1793) exists to
uphold. Resending while the original is still parked replays it instead of
starting a competing turn.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.app.service import TurnApplicationService
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.runtime.coordination import MemoryCoordinator
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


class _ContextBuilder:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def build(self, **_kwargs):
        return SimpleNamespace(
            conversation_history=[],
            conversation_summary="",
            context_text="",
            token_count=0,
            budget=0,
        )


class _PausableEngine:
    """First run parks the turn on a waiting card; later runs answer at once.

    The parked run is the submission whose worker is about to be "lost":
    the learner's answer is persisted, the row sits in ``waiting_input``,
    and the answer never reaches the conversation.
    """

    def __init__(self) -> None:
        self.parked = asyncio.Event()
        self.started = 0
        self.finish_without_waiting = False

    async def execute(self, context):
        self.started += 1
        if not self.finish_without_waiting:
            yield StreamEvent(
                type=StreamEventType.WAIT_FOR_INPUT,
                source="chat",
                content="Continue?",
            )
            self.parked.set()
            reply = await context.runtime.wait_for_user_reply()
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                content=f"reply:{reply['text']}",
            )
        else:
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                content="Recovered answer",
            )
        yield StreamEvent(type=StreamEventType.DONE, source="chat")


def _payload() -> dict:
    return {
        "content": "my original answer",
        "client_submission_id": "lost-ack-resend-1",
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "attachments": [],
        "language": "en",
        "config": {},
    }


@pytest.fixture(autouse=True)
def _workspace_root(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Isolate the runtime home and workspace binding for this test.

    Without ``DEEPTUTOR_HOME`` the runtime resolves paths from the current
    working directory, so a catalog row written by an earlier process would
    point later runs at a deleted folder ("The selected workspace folder
    does not exist"). A private home plus a fresh ``PathService`` keeps
    settings, the workspace catalog, and the deployment root tmp-scoped.
    """
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    from deeptutor.services.path_service import PathService

    monkeypatch.setattr(PathService, "_instance", PathService(workspace_root=tmp_path / "data"))
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.setenv("DEEPTUTOR_WORKSPACE_ROOT", str(root))
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)


@pytest.fixture
def llm_and_context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", _ContextBuilder
    )


def _service(
    store: SQLiteSessionStore,
    coordinator: MemoryCoordinator,
    worker_id: str,
    engine: _PausableEngine,
) -> TurnApplicationService:
    runtime = TurnRuntimeManager(
        store, coordinator=coordinator, owner_id=worker_id, turn_engine=engine
    )
    return TurnApplicationService(
        SimpleNamespace(get=lambda: store),
        SimpleNamespace(get=lambda _store: runtime),
        coordinator,
    )


async def _wait_for_status(store: SQLiteSessionStore, turn_id: str, status: str) -> dict:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while loop.time() < deadline:
        row = await store.get_turn(turn_id)
        if row is not None and str(row.get("status")) == status:
            return row
        await asyncio.sleep(0.02)
    raise AssertionError(f"turn {turn_id} never reached {status}")


async def _park_lost_submission(
    tmp_path, engine: _PausableEngine
) -> tuple[SQLiteSessionStore, dict, dict]:
    """Run the first submission for real, then drop the worker's lease view.

    A fresh coordinator for the recovery worker mirrors the restarted
    process: its lease view is empty, so the parked ``waiting_input`` row is
    exactly the unowned zombie a dead process leaves behind.
    """
    coordinator_a = MemoryCoordinator(lease_ttl_seconds=30)
    store = SQLiteSessionStore(tmp_path / "shared.sqlite3")
    app_a = _service(store, coordinator_a, "worker-a", engine)
    session, turn = await app_a.start_turn(_payload())
    await asyncio.wait_for(engine.parked.wait(), timeout=5)
    await _wait_for_status(store, turn["id"], "waiting_input")
    return store, session, turn


@pytest.mark.asyncio
async def test_resend_while_submission_is_still_parked_replays_the_same_turn(
    tmp_path, llm_and_context
) -> None:
    """A client retry that races the parked original replays it, never forks.

    The learner's answer is persisted exactly once and no second turn is
    started for the same submission id while the first is still live — and
    the replay must not reap or otherwise disturb the parked original.
    """
    engine = _PausableEngine()
    store, session, turn = await _park_lost_submission(tmp_path, engine)
    app = _service(store, MemoryCoordinator(lease_ttl_seconds=30), "worker-b", engine)

    resent_session, resent_turn = await app.start_turn(_payload())

    assert resent_session["id"] == session["id"], "the retry must stay in its conversation"
    assert resent_turn["id"] == turn["id"], "the live original must be replayed, not raced"
    assert len(await store.list_sessions()) == 1
    rows = await store.get_messages(session["id"])
    assert [row["role"] for row in rows] == ["user"], "no duplicate answer may be recorded"
    assert rows[0]["metadata"]["client_submission_id"] == "lost-ack-resend-1"
    parked = await store.get_turn(turn["id"])
    assert parked["status"] == "waiting_input", "the replay must leave the original parked"
    assert engine.started == 1, "the replay must not execute the submission a second time"


@pytest.mark.asyncio
async def test_resend_after_worker_lost_reap_reuses_session_and_user_message(
    tmp_path, llm_and_context
) -> None:
    """After the zombie is reaped, the resend lands in the same conversation.

    The new turn reuses the original user row (no duplicate answer), the
    done event points back at it, and no second session is created.
    """
    engine = _PausableEngine()
    store, session, turn = await _park_lost_submission(tmp_path, engine)
    original_user = await store.get_last_message(session["id"], role="user")
    assert original_user is not None

    coordinator_b = MemoryCoordinator(lease_ttl_seconds=30)
    app_b = _service(store, coordinator_b, "worker-b", engine)

    # The learner's answer reaches the dead worker first: the reply ack is
    # rejected and the zombie is reaped synchronously.
    assert await app_b.submit_user_reply(turn["id"], text="my original answer") is False
    reaped = await _wait_for_status(store, turn["id"], "failed")
    assert reaped["failure_code"] == "worker_lost"
    assert reaped["retryable"] in (True, 1)

    engine.finish_without_waiting = True
    resent_session, resent_turn = await app_b.start_turn(_payload())

    assert resent_session["id"] == session["id"], "the resend must not fork the conversation"
    assert resent_turn["id"] != turn["id"]
    assert len(await store.list_sessions()) == 1
    async for _event in app_b.subscribe_turn(resent_turn["id"]):
        pass
    rows = await store.get_messages(session["id"])
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["id"] == original_user["id"], "the original answer must be reused verbatim"
    done = [
        event async for event in app_b.subscribe_turn(resent_turn["id"]) if event["type"] == "done"
    ]
    assert done and done[-1]["metadata"]["user_message_id"] == original_user["id"]
    assert engine.started == 2, "only the resend may execute; the replay must not re-run it"


@pytest.mark.asyncio
async def test_cancelling_the_zombie_opens_the_same_resend_path(tmp_path, llm_and_context) -> None:
    """A give-up cancel on the unowned zombie enables the same resend parity.

    Cancelling a turn nobody executes must reap it (not acknowledge into the
    void), and the following resend must reuse the conversation and the
    original user message exactly like the reply-ack path does.
    """
    engine = _PausableEngine()
    store, session, turn = await _park_lost_submission(tmp_path, engine)
    original_user = await store.get_last_message(session["id"], role="user")
    assert original_user is not None

    coordinator_b = MemoryCoordinator(lease_ttl_seconds=30)
    app_b = _service(store, coordinator_b, "worker-b", engine)

    assert await app_b.cancel_turn(turn["id"]) is True
    reaped = await _wait_for_status(store, turn["id"], "failed")
    assert reaped["failure_code"] == "worker_lost"
    assert reaped["retryable"] in (True, 1)

    engine.finish_without_waiting = True
    resent_session, resent_turn = await app_b.start_turn(_payload())

    assert resent_session["id"] == session["id"]
    assert resent_turn["id"] != turn["id"]
    assert len(await store.list_sessions()) == 1
    async for _event in app_b.subscribe_turn(resent_turn["id"]):
        pass
    rows = await store.get_messages(session["id"])
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["id"] == original_user["id"]


@pytest.mark.asyncio
async def test_resend_cannot_swap_content_after_the_zombie_failed(
    tmp_path, llm_and_context
) -> None:
    """The submission id stays bound to its content even after a lost ack.

    A reap makes the submission resendable, not hijackable: different
    content under the same id is refused and no fork session is created.
    """
    engine = _PausableEngine()
    store, session, turn = await _park_lost_submission(tmp_path, engine)

    coordinator_b = MemoryCoordinator(lease_ttl_seconds=30)
    app_b = _service(store, coordinator_b, "worker-b", engine)
    assert await app_b.submit_user_reply(turn["id"], text="my original answer") is False
    reaped = await _wait_for_status(store, turn["id"], "failed")
    assert reaped["failure_code"] == "worker_lost"

    with pytest.raises(RuntimeError, match="different request"):
        await app_b.start_turn({**_payload(), "content": "a different answer"})
    assert len(await store.list_sessions()) == 1
    rows = await store.get_messages(session["id"])
    assert [row["role"] for row in rows] == ["user"], "the refusal must not write messages"
    assert engine.started == 1
