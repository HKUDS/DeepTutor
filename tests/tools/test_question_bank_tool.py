"""The ``question_bank`` tool: the agent's only writable handle on the bank.

Regression cover for the reported failure — "file my wrong answers into
my new mistakes set" ended up in a notebook because no tool could reach
the question bank. These tests pin the shape that makes the ask a single
call: list gives ids, organize files them under a *name* and creates the
category when it is new.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


# ── record (#1244): partner conversations file wrong questions ────────────


class _FakePartnerContext:
    """Duck-typed stand-in for PartnerTurnContext (only the fields the tool
    reads via getattr: partner_id / actor_id / partner_name / shared_memory)."""

    def __init__(self, shared_memory: Any, partner_id: str = "p1") -> None:
        self.partner_id = partner_id
        self.actor_id = "user-42"
        self.partner_name = "Study Buddy"
        self.shared_memory = shared_memory


@pytest.mark.asyncio
async def test_record_files_a_partner_mistake_into_a_browsable_session(
    store: SQLiteSessionStore,
) -> None:
    outcome = await run_question_bank(
        action="record",
        question="  What is 7 × 8? ",
        user_answer="54",
        correct_answer="56",
        explanation="7×8 = 56, not 54 — the 7× row is easy to off-by-one.",
        category="Multiplication drills",
        store=store,
    )

    assert outcome.ok, outcome.error
    session_id = outcome.summary["session_id"]
    assert outcome.summary["source"] == "partner_chat"
    # The placeholder session exists so the entry is browsable, and the
    # mistake landed in it, labelled as coming from a partner conversation.
    stats = await store.question_bank_stats()
    assert stats["total"] == 1
    entry = await store.find_notebook_entry(session_id, outcome.summary["question_id"])
    assert entry is not None
    assert entry["source"] == "partner_chat"
    assert entry["question"] == "What is 7 × 8?"
    # The optional category was created and the entry filed into it.
    assert "Filed under 'Multiplication drills'" in outcome.text


@pytest.mark.asyncio
async def test_record_same_question_twice_updates_instead_of_duplicating(
    store: SQLiteSessionStore,
) -> None:
    first = await run_question_bank(action="record", question="What is 7 × 8?", store=store)
    again = await run_question_bank(
        action="record",
        question="WHAT  is 7 × 8?",  # different case/spacing, same question
        correct_answer="56",
        store=store,
    )

    assert first.ok and again.ok
    assert again.summary["question_id"] == first.summary["question_id"]
    assert (await store.question_bank_stats())["total"] == 1


@pytest.mark.asyncio
async def test_record_requires_the_question(store: SQLiteSessionStore) -> None:
    outcome = await run_question_bank(action="record", question="   ", store=store)
    assert not outcome.ok
    assert "`question` is required" in outcome.error


@pytest.mark.asyncio
async def test_record_routes_to_the_bank_the_family_browses(
    store: SQLiteSessionStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.path_service import PathService
    from deeptutor.services.session.sqlite_store import (
        get_sqlite_session_store_for,
    )

    learner_paths = PathService(workspace_root=tmp_path / "learner-scope")
    fake_context = _FakePartnerContext(shared_memory=learner_paths)
    monkeypatch.setattr(
        "deeptutor.services.partners.interaction.get_partner_turn_context",
        lambda: fake_context,
    )

    # No explicit store: inside a partner turn the tool must resolve the
    # learner-facing bank (the shared scope), not the partner's own.
    outcome = await run_question_bank(action="record", question="Define entropy.")

    assert outcome.ok, outcome.error
    partner_bank = get_sqlite_session_store_for(learner_paths)
    assert (await partner_bank.question_bank_stats())["total"] == 1
    # …and nothing leaked into the current (partner-scope) store.
    assert (await store.question_bank_stats())["total"] == 0


@pytest.mark.asyncio
async def test_partner_turns_mount_the_bank_even_when_it_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.agents._shared.tool_composition import partner_can_record_questions
    from deeptutor.services.path_service import PathService

    assert partner_can_record_questions() is False

    fake_context = _FakePartnerContext(
        shared_memory=PathService(workspace_root=Path(tmp_path) / "scope")
    )
    monkeypatch.setattr(
        "deeptutor.services.partners.interaction.get_partner_turn_context",
        lambda: fake_context,
    )
    assert partner_can_record_questions() is True


@pytest.mark.asyncio
async def test_ensure_notebook_session_is_idempotent(store: SQLiteSessionStore) -> None:
    assert await store.ensure_notebook_session("partner-notebook:p1:admin", "T (Partner)") is True
    assert await store.ensure_notebook_session("partner-notebook:p1:admin", "T (Partner)") is False
