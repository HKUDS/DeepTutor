"""The ``question_bank`` tool: the agent's only writable handle on the bank.

Regression cover for the reported failure — "file my wrong answers into
my new mistakes set" ended up in a notebook because no tool could reach
the question bank. These tests pin the shape that makes the ask a single
call: list gives ids, organize files them under a *name* and creates the
category when it is new.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.tools.question_bank import run_question_bank


@pytest.fixture
def store(tmp_path: Path) -> SQLiteSessionStore:
    return SQLiteSessionStore(db_path=tmp_path / "bank.db")


async def _seed(store: SQLiteSessionStore) -> str:
    session = await store.create_session(title="Drill")
    session_id = session["id"]
    await store.upsert_notebook_entries(
        session_id,
        [
            {
                "turn_id": "t1",
                "question_id": "q1",
                "question": "Derivative of sin(x)?",
                "correct_answer": "cos(x)",
                "user_answer": "-cos(x)",
                "is_correct": False,
            },
            {
                "turn_id": "t1",
                "question_id": "q2",
                "question": "Integral of 1/x?",
                "correct_answer": "ln|x| + C",
                "user_answer": "ln|x| + C",
                "is_correct": True,
            },
        ],
    )
    return session_id


@pytest.mark.asyncio
async def test_overview_on_empty_bank_is_explicit(store: SQLiteSessionStore) -> None:
    outcome = await run_question_bank(action="overview", store=store)
    assert outcome.ok
    assert "empty" in outcome.text


@pytest.mark.asyncio
async def test_list_wrong_exposes_ids_for_filing(store: SQLiteSessionStore) -> None:
    await _seed(store)
    outcome = await run_question_bank(action="list", filter_mode="wrong", store=store)
    assert outcome.ok
    assert outcome.summary["count"] == 1
    assert len(outcome.summary["entry_ids"]) == 1
    # The rendered id is what the model copies into ``organize``.
    assert f"[{outcome.summary['entry_ids'][0]}]" in outcome.text


@pytest.mark.asyncio
async def test_organize_creates_the_category_it_is_given(store: SQLiteSessionStore) -> None:
    await _seed(store)
    listing = await run_question_bank(action="list", filter_mode="wrong", store=store)
    ids = listing.summary["entry_ids"]

    outcome = await run_question_bank(
        action="organize", entry_ids=ids, category="微积分错题", store=store
    )
    assert outcome.ok
    assert outcome.summary["created_category"] is True
    assert outcome.summary["changed"] == len(ids)

    categories = await store.list_categories()
    assert [(c["name"], c["entry_count"]) for c in categories] == [("微积分错题", len(ids))]


@pytest.mark.asyncio
async def test_organize_is_idempotent_and_never_duplicates_a_category(
    store: SQLiteSessionStore,
) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]
    await run_question_bank(action="organize", entry_ids=ids, category="Mistakes", store=store)

    repeat = await run_question_bank(
        action="organize", entry_ids=ids, category="mistakes", store=store
    )
    assert repeat.ok
    assert repeat.summary["created_category"] is False
    assert repeat.summary["changed"] == 0
    assert len(await store.list_categories()) == 1


@pytest.mark.asyncio
async def test_uncategorized_is_the_triage_inbox(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", filter_mode="wrong", store=store)).summary[
        "entry_ids"
    ]
    await run_question_bank(action="organize", entry_ids=ids, category="Filed", store=store)

    inbox = await run_question_bank(action="list", filter_mode="uncategorized", store=store)
    assert inbox.summary["count"] == 1
    assert inbox.summary["entry_ids"] != ids


@pytest.mark.asyncio
async def test_bad_ids_do_not_sink_the_good_ones(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]

    outcome = await run_question_bank(
        action="organize",
        entry_ids=[ids[0], "not-an-id", 987654],
        category="Partial",
        store=store,
    )
    assert outcome.ok
    assert outcome.summary["changed"] == 1
    assert "not-an-id" in outcome.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs, fragment",
    [
        ({"action": "nope"}, "Unknown action"),
        ({"action": "list", "filter_mode": "weird"}, "Unknown filter"),
        ({"action": "organize", "entry_ids": [1], "category": ""}, "`category` is required"),
        ({"action": "organize", "entry_ids": [], "category": "X"}, "`entry_ids`"),
        ({"action": "unfile", "entry_ids": [1], "category": "ghost"}, "No category named"),
        ({"action": "list", "category": "ghost"}, "No category named"),
    ],
)
async def test_errors_are_actionable_sentences(
    store: SQLiteSessionStore, kwargs: dict, fragment: str
) -> None:
    await _seed(store)
    outcome = await run_question_bank(store=store, **kwargs)
    assert not outcome.ok
    assert fragment in outcome.error


@pytest.mark.asyncio
async def test_bookmark_round_trip(store: SQLiteSessionStore) -> None:
    await _seed(store)
    ids = (await run_question_bank(action="list", store=store)).summary["entry_ids"]

    starred = await run_question_bank(action="bookmark", entry_ids=ids, store=store)
    assert starred.ok
    assert (await store.question_bank_stats())["bookmarked"] == len(ids)

    cleared = await run_question_bank(
        action="bookmark", entry_ids=ids, bookmarked=False, store=store
    )
    assert cleared.ok
    assert (await store.question_bank_stats())["bookmarked"] == 0


@pytest.mark.asyncio
async def test_mount_gate_follows_the_data(store: SQLiteSessionStore) -> None:
    assert store.has_question_bank_entries() is False
    await _seed(store)
    assert store.has_question_bank_entries() is True
