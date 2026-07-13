"""Per-user session isolation on the PocketBase backend (issue #596).

PocketBase is a single shared server with no filesystem-level isolation, so
``PocketBaseSessionStore`` must scope every session row by ``user_id`` (derived
from the request-scoped current-user ContextVar). These tests stand up a tiny
in-memory fake of the PocketBase SDK — the real ``pocketbase`` package is not a
test dependency — and assert that one user can never see or mutate another
user's sessions.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import re

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.session.pocketbase_store import PocketBaseSessionStore

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
    def __init__(self, items: list[_Record]) -> None:
        self.items = items


class _Collection:
    """In-memory stand-in for a PocketBase collection (equality filters only)."""

    def __init__(self) -> None:
        self._rows: list[_Record] = []
        self._seq = 0

    def _matches(self, record: _Record, query_params: dict | None) -> bool:
        flt = (query_params or {}).get("filter") or ""
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
        start = (page - 1) * per_page
        return _Result(matched[start : start + per_page])

    def update(self, pb_id: str, data: dict) -> _Record:
        record = next(r for r in self._rows if r.id == pb_id)
        for key, value in data.items():
            setattr(record, key, value)
        return record

    def delete(self, pb_id: str) -> None:
        self._rows = [r for r in self._rows if r.id != pb_id]


class _FakeClient:
    def __init__(self) -> None:
        self._collections: dict[str, _Collection] = {}

    def collection(self, name: str) -> _Collection:
        return self._collections.setdefault(name, _Collection())


@pytest.fixture
def fake_pb(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.get_pb_client", lambda: client, raising=True
    )
    return client


async def test_create_session_stamps_current_user(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="A's chat", session_id="s_alice")
    [row] = fake_pb.collection("sessions").get_full_list()
    assert row.user_id == "alice"
    assert row.session_id == "s_alice"


async def test_list_sessions_only_returns_own(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="a1", session_id="s_a1")
        await store.create_session(title="a2", session_id="s_a2")
    with as_user("bob"):
        await store.create_session(title="b1", session_id="s_b1")

        bob_sessions = await store.list_sessions()
    assert {s["session_id"] for s in bob_sessions} == {"s_b1"}

    with as_user("alice"):
        alice_sessions = await store.list_sessions()
    assert {s["session_id"] for s in alice_sessions} == {"s_a1", "s_a2"}


async def test_get_session_404s_for_other_user(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="secret", session_id="s_secret")

    # Bob must not be able to read Alice's session by id.
    with as_user("bob"):
        assert await store.get_session("s_secret") is None
        assert await store.get_session_with_messages("s_secret") is None

    # The owner still reads it fine.
    with as_user("alice"):
        own = await store.get_session("s_secret")
    assert own is not None and own["session_id"] == "s_secret"


async def test_mutations_are_scoped_to_owner(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="orig", session_id="s_m")

    with as_user("bob"):
        assert await store.update_session_title("s_m", "hijacked") is False
        assert await store.delete_session("s_m") is False
        assert await store.update_summary("s_m", "x", 1) is False

    # Alice's row is untouched and still present.
    with as_user("alice"):
        assert await store.update_session_title("s_m", "renamed") is True
        session = await store.get_session("s_m")
    assert session is not None and session["title"] == "renamed"


async def test_create_turn_rejects_foreign_session(fake_pb) -> None:
    store = PocketBaseSessionStore()
    with as_user("alice"):
        await store.create_session(title="orig", session_id="s_t")

    with as_user("bob"):
        with pytest.raises(ValueError, match="Session not found"):
            await store.create_turn("s_t")

    with as_user("alice"):
        turn = await store.create_turn("s_t")
    assert turn["session_id"] == "s_t"
