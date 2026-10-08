"""Failure-branch tests for the PocketBase session store (audit gap #13).

Covers the three arms of the coverage card in
``evidence/coverage-2026-10-02/top15-gaps.md`` (item 13):

1. write/upsert degradation — every failing backend write must return the
   documented sentinel (``False`` / ``0`` / ``[]`` / ``None``) instead of
   raising, a failed write must leave the stored row untouched, and a retry
   after the backend recovers must succeed. One test pins the known
   silent-orphan risk in ``add_message`` for the fix card.
2. missing-field defaults — rows written by older PocketBase schemas (no
   title/status/preferences/JSON columns) must read back with the same
   defaults the SQLite backend guarantees.
3. list pagination boundaries — offset clamping, the page+1 skip fetch,
   recycle-bin ordering slices, and the defensive soft-delete re-check.

The real ``pocketbase`` package is not a test dependency; these tests stand up
the same in-memory fake used by ``test_pocketbase_isolation.py`` plus a flaky
wrapper that raises once on named ``<collection>.<op>`` calls.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.pocketbase_store import (
    PocketBaseSessionStore,
    _json_loads,
    _to_float,
)

pytestmark = pytest.mark.asyncio

_CLAUSE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


@contextmanager
def as_user(uid: str, *, role: str = "user"):
    scope = UserScope(kind=role, user_id=uid, root=Path("/tmp") / uid)  # noqa: S108
    token = set_current_user(CurrentUser(id=uid, username=uid, role=role, scope=scope))
    try:
        yield
    finally:
        reset_current_user(token)


class _Record:
    def __init__(self, pb_id: str, data: dict) -> None:
        self.id = pb_id
        for key, value in data.items():
            setattr(self, key, value)


class _Result:
    def __init__(self, items: list[_Record], total_items: int) -> None:
        self.items = items
        self.total_items = total_items


class _Collection:
    """In-memory stand-in for a PocketBase collection (equality filters only)."""

    def __init__(self) -> None:
        self._rows: list[_Record] = []
        self._seq = 0

    def _matches(self, record: _Record, query_params: dict | None) -> bool:
        flt = (query_params or {}).get("filter") or ""
        workspace = re.search(r'preferences_json\.workspace_id=("(?:\\.|[^"\\])*"|null)', flt)
        if workspace:
            expected = json.loads(workspace.group(1)) or ""
            prefs = getattr(record, "preferences_json", {}) or {}
            if isinstance(prefs, str):
                prefs = json.loads(prefs)
            if (prefs.get("workspace_id") or "") != expected:
                return False
            flt = re.sub(r'preferences_json\.workspace_id=("(?:\\.|[^"\\])*"|null)', "", flt)
        role_pair = '(role="user" || role="assistant")'
        if role_pair in flt:
            if str(getattr(record, "role", "")) not in {"user", "assistant"}:
                return False
            flt = flt.replace(role_pair, "")
        contains = re.search(r"content~(\"(?:\\.|[^\"])*\")", flt)
        if contains is not None:
            needle = json.loads(contains.group(1))
            if needle.casefold() not in str(getattr(record, "content", "")).casefold():
                return False
            flt = flt.replace(contains.group(0), "")
        for field, expected in _CLAUSE.findall(flt):
            if str(getattr(record, field, "")) != expected:
                return False
        return True

    def create(self, data: dict) -> _Record:
        self._seq += 1
        record = _Record(f"pb{self._seq:04d}", data)
        self._rows.append(record)
        return record

    def get_full_list(self, query_params: dict | None = None) -> list[_Record]:
        return [r for r in self._rows if self._matches(r, query_params)]

    def get_list(self, page: int, per_page: int, query_params: dict | None = None) -> _Result:
        matched = self.get_full_list(query_params)
        sort = str((query_params or {}).get("sort") or "")
        if sort:
            for part in reversed(sort.split(",")):
                field = part.lstrip("-")
                matched.sort(
                    key=lambda record: getattr(
                        record, field, record.id if field == "created" else 0
                    ),
                    reverse=part.startswith("-"),
                )
        start = (page - 1) * per_page
        return _Result(matched[start : start + per_page], len(matched))

    def update(self, pb_id: str, data: dict) -> _Record:
        record = next(r for r in self._rows if r.id == pb_id)
        for key, value in data.items():
            setattr(record, key, value)
        return record

    def get_one(self, pb_id: str) -> _Record:
        return next(row for row in self._rows if row.id == pb_id)

    def delete(self, pb_id: str) -> None:
        self._rows = [r for r in self._rows if r.id != pb_id]


class _FlakyCollection:
    """Delegates to a real collection; popped ``<name>.<op>`` keys raise once."""

    def __init__(self, name: str, inner: _Collection, failures: dict[str, Exception]) -> None:
        self._name = name
        self._inner = inner
        self._failures = failures

    def _gate(self, op: str, *args, **kwargs):
        exc = self._failures.pop(f"{self._name}.{op}", None)
        if exc is not None:
            raise exc
        return getattr(self._inner, op)(*args, **kwargs)

    def create(self, data: dict) -> _Record:
        return self._gate("create", data)

    def update(self, pb_id: str, data: dict) -> _Record:
        return self._gate("update", pb_id, data)

    def delete(self, pb_id: str) -> None:
        return self._gate("delete", pb_id)

    def get_one(self, pb_id: str) -> _Record:
        return self._gate("get_one", pb_id)

    def get_full_list(self, query_params: dict | None = None) -> list[_Record]:
        return self._gate("get_full_list", query_params)

    def get_list(self, page: int, per_page: int, query_params: dict | None = None) -> _Result:
        return self._gate("get_list", page, per_page, query_params)


class _FakeClient:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def collection(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())


class _FlakyClient(_FakeClient):
    """Fake client whose named ``<collection>.<op>`` calls fail exactly once.

    Clearing ``failures`` (or letting the gate pop the key) simulates the
    backend recovering, so tests can exercise retry-after-failure.
    """

    def __init__(self, failures: dict[str, Exception] | None = None) -> None:
        super().__init__()
        self.failures: dict[str, Exception] = failures or {}

    def collection(self, name: str):
        inner = super().collection(name)
        if any(key.startswith(f"{name}.") for key in self.failures):
            return _FlakyCollection(name, inner, self.failures)
        return inner


def _install_client(monkeypatch, failures: dict[str, Exception] | None = None) -> _FlakyClient:
    client = _FlakyClient(failures)
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.get_pb_client", lambda: client, raising=True
    )
    return client


@pytest.fixture
def fake_pb(monkeypatch) -> _FlakyClient:
    return _install_client(monkeypatch)


@pytest.fixture
def flaky_pb(monkeypatch):
    def install(failures: dict[str, Exception]) -> _FlakyClient:
        return _install_client(monkeypatch, failures)

    return install


# ----------------------------------------------------------------------
# 1. Upsert / write degradation — soft-fail contract, then retry succeeds
# ----------------------------------------------------------------------


async def test_update_session_title_fails_soft_then_retry_succeeds(flaky_pb) -> None:
    client = flaky_pb({"sessions.update": ConnectionError("pb down")})
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="orig", session_id="s_title")
        assert await store.update_session_title("s_title", "renamed") is False
        client.failures.clear()  # backend recovers
        assert await store.update_session_title("s_title", "renamed") is True
        session = await store.get_session("s_title")
    assert session is not None and session["title"] == "renamed"


async def test_update_summary_degrades_to_false_and_keeps_old_value(flaky_pb) -> None:
    client = flaky_pb({"sessions.update": ConnectionError("pb down")})
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_sum")
        assert await store.update_summary("s_sum", "summary text", 3) is False
        session = await store.get_session("s_sum")
    assert session is not None
    assert session["compressed_summary"] == ""
    assert session["summary_up_to_msg_id"] == 0


async def test_update_session_preferences_preserves_existing_on_failure(flaky_pb) -> None:
    client = flaky_pb({"sessions.update": ConnectionError("pb down")})
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_pref")
        assert await store.update_session_preferences("s_pref", {"pinned": True}) is False
        session = await store.get_session("s_pref")
    assert session is not None
    assert "pinned" not in session["preferences"]
    [row] = client.collection("sessions").get_full_list()
    assert row.preferences_json.get("pinned") is None


async def test_add_message_returns_zero_when_create_fails(flaky_pb) -> None:
    client = flaky_pb({"messages.create": ConnectionError("pb down")})
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_msg")
        assert await store.add_message("s_msg", "user", "hello") == 0
    assert client.collection("messages").get_full_list() == []


async def test_add_message_touch_failure_orphans_persisted_row(flaky_pb) -> None:
    """Pins the silent-orphan risk named by the audit card.

    ``add_message`` persists the message row before stamping the session; when
    the stamp fails the caller still sees the ``0`` sentinel while the row
    lives on in the backend. A fix that cleans up the orphan row must update
    this assertion together with its own regression test.
    """
    client = flaky_pb({"sessions.update": ConnectionError("pb down")})
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_orphan")
        [session_row] = client.collection("sessions").get_full_list()
        stamped_at = session_row.session_updated_at
        assert await store.add_message("s_orphan", "user", "hello") == 0
    rows = client.collection("messages").get_full_list()
    assert len(rows) == 1
    assert rows[0].content == "hello"
    assert session_row.session_updated_at == stamped_at


async def test_recycle_bin_writes_degrade_to_false_then_retry(flaky_pb) -> None:
    client = flaky_pb({"sessions.update": ConnectionError("pb down")})
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_bin")
        assert await store.soft_delete_session("s_bin") is False
        client.failures.clear()
        assert await store.soft_delete_session("s_bin") is True
        client.failures["sessions.update"] = ConnectionError("pb down")
        assert await store.restore_session("s_bin") is False
        client.failures.clear()
        assert await store.restore_session("s_bin") is True
        client.failures["sessions.delete"] = ConnectionError("pb down")
        assert await store.soft_delete_session("s_bin") is True
        assert await store.hard_delete_session("s_bin") is False
        [row] = client.collection("sessions").get_full_list()
    assert bool(row.deleted_at)


async def test_delete_session_degrades_and_preserves_every_row(flaky_pb) -> None:
    client = flaky_pb({"messages.delete": ConnectionError("pb down")})
    store = PocketBaseSessionStore()
    with as_user("alice"):
        session = await store.create_session(session_id="s_del")
        await store.add_message(session["id"], "user", "keep me")
        assert await store.delete_session("s_del") is False
    assert len(client.collection("sessions").get_full_list()) == 1
    assert len(client.collection("messages").get_full_list()) == 1


async def test_session_reads_degrade_to_empty_when_backend_fails(flaky_pb) -> None:
    flaky_pb(
        {
            "sessions.get_full_list": ConnectionError("pb down"),
            "sessions.get_list": ConnectionError("pb down"),
        }
    )
    store = PocketBaseSessionStore()
    with as_user("alice"):
        assert await store.get_session("s_any") is None
        assert await store.list_sessions() == []
        assert await store.list_deleted_sessions() == []
        assert await store.search_sessions("anything") == {"sessions": [], "total": 0}


async def test_message_reads_degrade_to_empty_when_backend_fails(flaky_pb) -> None:
    flaky_pb(
        {
            "messages.get_full_list": ConnectionError("pb down"),
            "messages.get_list": ConnectionError("pb down"),
        }
    )
    store = PocketBaseSessionStore()
    with as_user("alice"):
        session = await store.create_session(session_id="s_reads")
        assert await store.get_messages(session["id"]) == []
        assert await store.get_last_message(session["id"]) is None
        [summary] = await store.get_session_summaries([session["id"]])
    assert summary["message_count"] == 0
    assert summary["last_message"] == ""


async def test_turn_event_reads_degrade_to_empty_when_backend_fails(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        session = await store.create_session(session_id="s_evt")
        turn = await store.begin_turn(session["id"])
        assert len(await store.append_events(turn["id"], [{"type": "delta"}])) == 1
        fake_pb.failures["turn_events.get_full_list"] = ConnectionError("pb down")
        assert await store.get_turn_events(turn["id"]) == []


async def test_append_events_retry_is_idempotent(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        session = await store.create_session(session_id="s_idem")
        turn = await store.begin_turn(session["id"])
        batch = [
            {
                "seq": 1,
                "type": "delta",
                "source": "llm",
                "stage": "answer",
                "content": "hi",
                "metadata": {},
                "timestamp": 100.0,
            }
        ]
        first = await store.append_events(turn["id"], batch)
        retry = await store.append_events(turn["id"], batch)
        [row] = fake_pb.collection("turn_events").get_full_list()
    assert first[0]["seq"] == 1
    assert retry == first
    assert row.seq == 1
    assert row.event_timestamp == 100.0


async def test_append_events_conflicting_retry_raises(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        session = await store.create_session(session_id="s_conflict")
        turn = await store.begin_turn(session["id"])
        await store.append_events(turn["id"], [{"seq": 1, "type": "delta", "content": "a"}])
        with pytest.raises(ValueError, match="Turn event conflict"):
            await store.append_events(turn["id"], [{"seq": 1, "type": "delta", "content": "b"}])
    assert len(fake_pb.collection("turn_events").get_full_list()) == 1


async def test_append_events_with_stale_fencing_token_raises(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        session = await store.create_session(session_id="s_lease")
        turn = await store.begin_turn(session["id"])
        with pytest.raises(RuntimeError, match="lease lost"):
            await store.append_events(turn["id"], [{"type": "delta"}], fencing_token=99)
    assert fake_pb.collection("turn_events").get_full_list() == []


# ----------------------------------------------------------------------
# 2. Missing-field defaults at the read boundary
# ----------------------------------------------------------------------


async def test_session_reads_fill_defaults_for_missing_fields(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        fake_pb.collection("sessions").create({"session_id": "s_min", "user_id": "alice"})
        session = await store.get_session("s_min")
    assert session is not None
    assert session["session_id"] == "s_min"
    assert session["title"] == "New conversation"
    assert session["status"] == "idle"
    assert session["capability"] == ""
    assert session["compressed_summary"] == ""
    assert session["summary_up_to_msg_id"] == 0
    assert session["preferences"] == {}
    assert session["active_turn_id"] == ""
    assert session["is_deleted"] is False
    assert session["deleted_at"] is None
    assert session["created_at"] > 0
    assert session["updated_at"] > 0


async def test_legacy_empty_deleted_at_reads_as_not_deleted(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        fake_pb.collection("sessions").create(
            {"session_id": "s_legacy", "user_id": "alice", "deleted_at": ""}
        )
        session = await store.get_session("s_legacy")
    assert session is not None
    assert session["is_deleted"] is False
    assert session["deleted_at"] is None


async def test_message_reads_fill_defaults_for_missing_fields(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        fake_pb.collection("sessions").create({"session_id": "s_mmin", "user_id": "alice"})
        fake_pb.collection("messages").create({"session_id": "s_mmin", "role": "user"})
        [message] = await store.get_messages("s_mmin")
    assert message["content"] == ""
    assert message["capability"] == ""
    assert message["events"] == []
    assert message["attachments"] == []
    assert message["metadata"] == {}
    assert message["created_at"] == 0.0
    assert "parent_message_id" not in message


def test_json_loads_tolerates_missing_and_corrupt_values() -> None:
    assert _json_loads(None, []) == []
    assert _json_loads("", {}) == {}
    assert _json_loads("not json", {"a": 1}) == {"a": 1}
    assert _json_loads('{"ok": true}', {}) == {"ok": True}
    assert _json_loads({"a": 1}, {}) == {"a": 1}
    assert _json_loads([1, 2], []) == [1, 2]


def test_to_float_tolerates_missing_and_corrupt_values() -> None:
    assert _to_float(None) == 0.0
    assert _to_float(None, 5.0) == 5.0
    assert _to_float("junk") == 0.0
    assert _to_float(7) == 7.0
    iso = _to_float("2026-10-02T00:00:00Z")
    assert iso > 0
    assert _to_float("2026-10-02T00:00:00+00:00") == iso


# ----------------------------------------------------------------------
# 3. List pagination boundaries
# ----------------------------------------------------------------------


async def test_list_sessions_offset_beyond_total_returns_empty(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        for i in range(3):
            await store.create_session(session_id=f"pg-{i}")
        assert await store.list_sessions(limit=5, offset=10) == []


async def test_list_sessions_clamps_zero_limit_and_negative_offset(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        for i in range(4):
            await store.create_session(session_id=f"clamp-{i}")
        one = await store.list_sessions(limit=0, offset=-3)
        full = await store.list_sessions(limit=10)
    assert len(one) == 1
    assert [row["session_id"] for row in one] == [row["session_id"] for row in full[:1]]


async def test_list_sessions_page_boundaries_match_full_listing(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        for i in range(5):
            await store.create_session(session_id=f"edge-{i}")
        full = await store.list_sessions(limit=20)
        mid = await store.list_sessions(limit=2, offset=1)
        tail = await store.list_sessions(limit=2, offset=4)
        beyond = await store.list_sessions(limit=2, offset=6)
    ids = [row["session_id"] for row in full]
    assert [row["session_id"] for row in mid] == ids[1:3]
    assert [row["session_id"] for row in tail] == ids[4:6]
    assert beyond == []


async def test_list_deleted_sessions_orders_and_paginates(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        for i in range(4):
            await store.create_session(session_id=f"bin-{i}")
        rows = fake_pb.collection("sessions").get_full_list()
        for i, row in enumerate(rows):
            row.deleted_at = 1000.0 + i
        page = await store.list_deleted_sessions(limit=2, offset=1)
        beyond = await store.list_deleted_sessions(limit=2, offset=10)
    assert [row["session_id"] for row in page] == ["bin-2", "bin-1"]
    assert beyond == []


async def test_list_sessions_defensively_hides_soft_deleted_rows(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(session_id="s_live")
        await store.create_session(session_id="s_gone")
        assert await store.soft_delete_session("s_gone") is True
        listed = await store.list_sessions(limit=10)
    assert {row["session_id"] for row in listed} == {"s_live"}


async def test_search_sessions_offset_beyond_total_keeps_count(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        for sid in ("q-1", "q-2"):
            await store.create_session(title="Riemann hypothesis", session_id=sid)
        await store.create_session(title="Other topic", session_id="q-3")
        result = await store.search_sessions("riemann", limit=1, offset=5)
    assert result == {"sessions": [], "total": 2}
