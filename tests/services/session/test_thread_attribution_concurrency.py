from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.thread_attribution import (
    BACKFILL_ATTEMPTED_KEY,
    TUTOR_SOURCE_KEY,
    backfill_thread_sources,
)

PARENT_ID = "shared-parent"
THREAD_ID = "shared-thread"


async def _seed(
    path,
    *,
    quote: str = "It returns twice.",
    filler: bool = False,
) -> tuple[SQLiteSessionStore, int]:
    store = SQLiteSessionStore(path)
    parent = await store.create_session(session_id=PARENT_ID)
    if filler:
        await store.add_message(parent["id"], "user", "A different opening question.")
    source = await store.add_message(parent["id"], "assistant", quote)
    child = await store.create_session(session_id=THREAD_ID)
    await store.update_session_preferences(
        child["id"],
        {
            "parent_session_id": parent["id"],
            "session_kind": "selection_tutor",
        },
    )
    await store.add_message(
        child["id"], "user", "Why?", attachments=[{"type": "quote", "extracted_text": quote}]
    )
    return store, source


async def _anchor(store: SQLiteSessionStore) -> object:
    thread = await store.get_session(THREAD_ID)
    assert thread is not None
    return thread["preferences"].get(TUTOR_SOURCE_KEY)


class _PausingStore:
    """Delegates to a real store, pausing the first thread transcript read."""

    def __init__(self, store: SQLiteSessionStore, thread_id: str) -> None:
        self.store = store
        self.thread_id = thread_id
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()
        self.thread_reads = 0

    async def get_messages(self, session_id: str):
        if session_id == self.thread_id:
            self.thread_reads += 1
            if not self.release.is_set():
                self.arrived.set()
                await self.release.wait()
        return await self.store.get_messages(session_id)

    def __getattr__(self, name: str):
        return getattr(self.store, name)


@pytest.mark.asyncio
async def test_a_detach_that_lands_during_the_scan_is_not_undone(tmp_path) -> None:
    store, _ = await _seed(tmp_path / "detach-race.db")
    thread = await store.get_session(THREAD_ID)
    assert thread is not None
    wrapper = _PausingStore(store, THREAD_ID)

    task = asyncio.create_task(backfill_thread_sources(wrapper, PARENT_ID, [thread]))
    await wrapper.arrived.wait()
    await store.update_session_preferences(
        THREAD_ID,
        {TUTOR_SOURCE_KEY: "", BACKFILL_ATTEMPTED_KEY: True},
        touch=False,
    )
    wrapper.release.set()
    await task

    assert await _anchor(store) == ""


@pytest.mark.asyncio
async def test_a_move_that_lands_during_the_scan_keeps_the_new_anchor(tmp_path) -> None:
    store, _ = await _seed(tmp_path / "move-race.db")
    thread = await store.get_session(THREAD_ID)
    assert thread is not None
    wrapper = _PausingStore(store, THREAD_ID)

    task = asyncio.create_task(backfill_thread_sources(wrapper, PARENT_ID, [thread]))
    await wrapper.arrived.wait()
    await store.update_session_preferences(THREAD_ID, {TUTOR_SOURCE_KEY: 99}, touch=False)
    wrapper.release.set()
    await task

    assert await _anchor(store) == 99


@pytest.mark.asyncio
async def test_concurrent_backfills_of_one_parent_scan_once(tmp_path) -> None:
    store, source = await _seed(tmp_path / "same-parent.db")
    thread = await store.get_session(THREAD_ID)
    assert thread is not None
    copy = {**thread, "preferences": dict(thread["preferences"])}
    wrapper = _PausingStore(store, THREAD_ID)
    wrapper.release.set()

    first, second = await asyncio.gather(
        backfill_thread_sources(wrapper, PARENT_ID, [thread]),
        backfill_thread_sources(wrapper, PARENT_ID, [copy]),
    )

    assert first[0]["preferences"][TUTOR_SOURCE_KEY] == source
    assert second[0]["preferences"][TUTOR_SOURCE_KEY] == source
    # The second caller waited for the first, then saw the attempted flag and
    # never re-read the thread transcript.
    assert wrapper.thread_reads == 1


@pytest.mark.asyncio
async def test_two_users_with_the_same_parent_id_stay_isolated(tmp_path) -> None:
    store_a, source_a = await _seed(tmp_path / "user-a.db", filler=False)
    store_b, source_b = await _seed(tmp_path / "user-b.db", filler=True)
    assert source_a != source_b
    thread_a = await store_a.get_session(THREAD_ID)
    thread_b = await store_b.get_session(THREAD_ID)
    assert thread_a is not None and thread_b is not None

    await asyncio.gather(
        backfill_thread_sources(store_a, PARENT_ID, [thread_a]),
        backfill_thread_sources(store_b, PARENT_ID, [thread_b]),
    )

    assert await _anchor(store_a) == source_a
    assert await _anchor(store_b) == source_b


def _run_in_own_loop(path, *, filler: bool) -> object:
    async def scenario():
        store, source = await _seed(path, filler=filler)
        thread = await store.get_session(THREAD_ID)
        assert thread is not None
        await backfill_thread_sources(store, PARENT_ID, [thread])
        assert await _anchor(store) == source
        return source

    return asyncio.run(scenario())


def test_sync_callers_in_separate_loops_do_not_share_a_parent_lock(tmp_path) -> None:
    """Two threads (two event loops) recover the same parent id independently."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_run_in_own_loop, tmp_path / "loop-a.db", filler=False),
            pool.submit(_run_in_own_loop, tmp_path / "loop-b.db", filler=True),
        ]
        sources = [future.result(timeout=30) for future in futures]

    assert sources[0] != sources[1]


@pytest.mark.asyncio
async def test_conditional_write_never_overwrites_a_newer_anchor(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "conditional.db")
    session = await store.ensure_session(None)
    await store.update_session_preferences(session["id"], {TUTOR_SOURCE_KEY: 9}, touch=False)

    claimed = await store.update_session_preferences_if_unset(
        session["id"],
        {TUTOR_SOURCE_KEY: 2, BACKFILL_ATTEMPTED_KEY: True},
        unset=(TUTOR_SOURCE_KEY, BACKFILL_ATTEMPTED_KEY),
        touch=False,
    )

    assert claimed is False
    persisted = await store.get_session(session["id"])
    assert persisted is not None
    assert persisted["preferences"][TUTOR_SOURCE_KEY] == 9
    assert BACKFILL_ATTEMPTED_KEY not in persisted["preferences"]


@pytest.mark.asyncio
async def test_deleting_a_source_message_detaches_its_threads(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "deleted-source.db")
    parent = await store.ensure_session(None)
    user = await store.add_message(parent["id"], "user", "Why?")
    answer = await store.add_message(parent["id"], "assistant", "It returns twice.")
    child = await store.ensure_session(None)
    await store.update_session_preferences(
        child["id"],
        {
            "parent_session_id": parent["id"],
            "session_kind": "selection_tutor",
            TUTOR_SOURCE_KEY: answer,
        },
        touch=False,
    )

    result = await store.delete_turn_by_message(parent["id"], answer)

    assert result["deleted"] is True
    assert result["detached_thread_ids"] == [child["id"]]
    assert set(result["deleted_message_ids"]) == {user, answer}
    persisted = await store.get_session(child["id"])
    assert persisted is not None
    assert persisted["preferences"][TUTOR_SOURCE_KEY] == ""
    assert persisted["preferences"][BACKFILL_ATTEMPTED_KEY] is True
    assert await store.get_session(parent["id"]) is not None
    assert user is not None
