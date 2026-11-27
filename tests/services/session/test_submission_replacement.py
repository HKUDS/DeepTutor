import asyncio

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.mark.asyncio
async def test_replacement_fences_delayed_original_at_reserve_and_admission(tmp_path):
    store = SQLiteSessionStore(tmp_path / "recovery.db")
    sid = await store.reserve_submission("original", "old")
    receipt = await store.replace_submission("original", "edited", "new", sid)
    assert receipt == {"status": "reserved", "session_id": sid, "submission_id": "edited"}
    with pytest.raises(RuntimeError, match="superseded"):
        await store.reserve_submission("original", "old", sid)
    with pytest.raises(RuntimeError, match="superseded"):
        await store.begin_turn(sid, submission_id="original")
    assert await store.reserve_submission("edited", "new", sid) == sid
    assert await store.replace_submission("original", "edited", "new", sid) == receipt
    with pytest.raises(RuntimeError):
        await store.replace_submission("original", "edited", "changed", sid)


@pytest.mark.asyncio
async def test_replacement_before_original_arrives_fences_it(tmp_path):
    store = SQLiteSessionStore(tmp_path / "recovery.db")
    receipt = await store.replace_submission("late", "edited", "new", None)
    with pytest.raises(RuntimeError, match="superseded"):
        await store.reserve_submission("late", "old")
    await store.begin_turn(receipt["session_id"], submission_id="edited")


@pytest.mark.asyncio
async def test_admission_replacement_race_has_one_winner(tmp_path):
    a = SQLiteSessionStore(tmp_path / "race.db")
    b = SQLiteSessionStore(tmp_path / "race.db")
    sid = await a.reserve_submission("old", "old-digest")
    admitted, replaced = await asyncio.gather(
        a.begin_turn(sid, submission_id="old"),
        b.replace_submission("old", "new", "new-digest", sid),
        return_exceptions=True,
    )
    if isinstance(admitted, Exception):
        assert "superseded" in str(admitted)
        assert replaced["status"] == "reserved"
        await b.begin_turn(sid, submission_id="new")
    else:
        assert replaced["status"] == "admitted"
        assert replaced["turn"]["id"] == admitted["id"]
        assert replaced["user_message_id"] is None


@pytest.mark.asyncio
async def test_replacement_cannot_cross_workspace_or_session(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from deeptutor.services.workspace import context

    scope = {"id": "one"}
    monkeypatch.setattr(
        context, "get_workspace_scope", lambda: SimpleNamespace(workspace_id=scope["id"])
    )
    store = SQLiteSessionStore(tmp_path / "scope.db")
    sid = await store.reserve_submission("old", "digest")
    other = await store.reserve_submission("other", "digest")
    with pytest.raises(RuntimeError):
        await store.replace_submission("old", "new", "new", other)
    scope["id"] = "two"
    with pytest.raises(RuntimeError):
        await store.replace_submission("old", "new", "new", sid)
