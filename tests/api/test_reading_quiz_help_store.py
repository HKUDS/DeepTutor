"""Help receipts serialize independent store connections and survive retries."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from deeptutor.services.session.reading_quiz_help import QuizHelpConflict
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def stores(tmp_path):
    a = SQLiteSessionStore(db_path=tmp_path / "account.db")
    b = SQLiteSessionStore(db_path=tmp_path / "account.db")
    asyncio.run(
        a.put_reading_quiz_pending(
            "material",
            1,
            [
                {"id": "q1", "_help_count": 100, "_help_requests": {"fake": {}}},
                {"id": "q2"},
            ],
        )
    )
    return a, b


def call(store, request="r1", token="t1", operation="claim", **kwargs):
    return asyncio.run(
        store.reading_quiz_help(
            "material",
            1,
            "q1",
            request,
            "fingerprint",
            token,
            operation,
            **kwargs,
        )
    )


def test_two_connections_cannot_claim_same_request(stores):
    def claim(store):
        try:
            call(store)
            return "claimed"
        except QuizHelpConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, stores)) == ["claimed", "conflict"]


def test_independent_help_completions_do_not_lose_counts_or_sibling(stores):
    a, b = stores
    call(a)
    call(b, request="r2", token="t2")

    def finish(args):
        store, request, token = args
        return call(
            store, request=request, token=token, operation="complete", result={"type": "card"}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finish, [(a, "r1", "t1"), (b, "r2", "t2")]))
    assert sorted(r["quiz_help"]["hints_used"] for r in results) == [1, 2]
    questions = asyncio.run(a.get_reading_quiz_pending("material", 1))
    assert questions["q2"] == {"id": "q2"}
    assert questions["q1"]["_help_count"] == 2
    assert "fake" not in questions["q1"]["_help_requests"]


def test_expired_owner_cannot_finish_or_abort_reclaimed_request(stores):
    a, b = stores
    call(a, lease_seconds=-1)
    call(b, token="replacement")
    with pytest.raises(QuizHelpConflict):
        call(a, operation="complete", result={"type": "card"})
    call(a, operation="abort")
    result = call(b, token="replacement", operation="complete", result={"type": "card"})
    assert result["quiz_help"]["hints_used"] == 1
    assert call(a) == result


def test_oversize_result_is_not_counted_and_can_retry(stores):
    a, _ = stores
    call(a)
    with pytest.raises(ValueError, match="too large"):
        call(a, operation="complete", result={"text": "x" * 262145})
    call(a, operation="abort")
    call(a)
    assert call(a, operation="complete", result={})["quiz_help"]["hints_used"] == 1


def test_receipt_limit_preserves_existing_replay(stores):
    a, _ = stores
    for i in range(50):
        call(a, request=str(i))
        call(a, request=str(i), operation="abort")
    with pytest.raises(QuizHelpConflict, match="limit"):
        call(a, request="overflow")
    call(a, request="0")
    assert call(a, request="0", operation="complete", result={})["quiz_help"]["hints_used"] == 1


def test_successful_help_survives_regeneration_without_an_answer(stores):
    a, _ = stores
    call(a)
    call(a, operation="complete", result={"payload": {"secret": "not archived"}})
    call(a)  # replay must not append another event
    call(a, request="failed")
    call(a, request="failed", operation="abort")
    asyncio.run(a.put_reading_quiz_pending("material", 1, [{"id": "new:q1"}]))
    events = asyncio.run(a.list_reading_quiz_help_events("material"))
    assert len(events) == 1
    assert events[0]["question_id"] == "q1"
    assert set(events[0]) == {
        "material_id",
        "locator",
        "question_id",
        "request_id",
        "help_kind",
        "question",
        "created_at",
    }
    assert asyncio.run(a.list_reading_quiz_help_events("other-material")) == []


def test_event_storage_failure_rolls_back_completion_and_count(stores):
    a, _ = stores
    call(a)
    with sqlite3.connect(a.db_path) as conn:
        conn.execute(
            "CREATE TRIGGER fail_help_event BEFORE INSERT ON reading_quiz_help_events "
            "BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="synthetic storage failure"):
        call(a, operation="complete", result={})
    pending = asyncio.run(a.get_reading_quiz_pending("material", 1))["q1"]
    assert pending.get("_help_count", 0) == 0
    assert pending["_help_requests"]["r1"]["state"] == "pending"
    assert asyncio.run(a.list_reading_quiz_help_events("material")) == []


def test_existing_account_database_gets_help_events_table(stores):
    a, _ = stores
    with sqlite3.connect(a.db_path) as conn:
        conn.execute("DROP TABLE reading_quiz_help_events")
    reopened = SQLiteSessionStore(db_path=a.db_path)
    call(reopened)
    call(reopened, operation="complete", result={})
    assert len(asyncio.run(reopened.list_reading_quiz_help_events("material"))) == 1
