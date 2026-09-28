"""Discovery spans workspaces; material reads and review writes keep their origin."""

import asyncio
import time

import pytest

from deeptutor.api.routers import dashboard, practice
from deeptutor.book.inputs import build_book_inputs
from deeptutor.learning.models import TopicSource
from deeptutor.learning.topic_materials import build_topic_materials, render_topic_manifest
from deeptutor.services.practice.storage import PracticeStore
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import current_workspace_id, workspace_context
from tests.services.workspace.test_data_scope import account as account
from tests.services.workspace.test_http_scope import scoped_client as scoped_client


async def seed_question(origin, text):
    with workspace_context(origin):
        store = get_sqlite_session_store()
        await store.ensure_notebook_session("lesson", "Lesson")
        await store.upsert_notebook_entries(
            "lesson",
            [
                {
                    "question_id": "q1",
                    "question": text,
                    "question_type": "single_choice",
                    "options": {"A": "3", "B": "4"},
                    "correct_answer": "B",
                    "result": "ungraded",
                    "user_answer": "",
                    "is_correct": False,
                }
            ],
        )
        return await store.find_notebook_entry("lesson", "q1")


@pytest.mark.asyncio
async def test_selected_materials_are_read_from_their_origin_without_moving_destination(account):
    other = account.create_workspace("Other")["workspace_id"]
    for scope, text in (("", "Original arithmetic question"), (other, "Other geometry question")):
        await seed_question(scope, text)
    with workspace_context(other):
        catalog = await dashboard.get_source_library("practice")
        assert catalog["unavailable_workspaces"] == []
        assert len(catalog["items"]) == 2
        assert {row["id"] for row in catalog["items"]} == {1}
        refs = [
            {
                "kind": "question_bank",
                "source_id": str(row["id"]),
                "label": row["question"],
                "metadata": {"content_workspace_id": row["content_workspace_id"]},
            }
            for row in catalog["items"]
        ]
        materials = await asyncio.to_thread(
            build_topic_materials, [TopicSource(id=str(i), **row) for i, row in enumerate(refs)]
        )
        _, readable = render_topic_manifest(materials)
        assert len(readable) == 2  # Equal IDs cannot overwrite one another.
        assert any("Original arithmetic" in text for text in readable.values())
        assert any("Other geometry" in text for text in readable.values())
        inputs, ideation = await build_book_inputs(user_intent="Study", source_refs=refs[:1])
        assert "Original arithmetic" in ideation.render()
        assert "Other geometry" not in inputs.source_context
        assert inputs.source_refs == refs[:1]
        assert current_workspace_id() == other


@pytest.mark.asyncio
async def test_created_book_keeps_source_snapshot_in_destination(account, monkeypatch):
    from deeptutor.book.engine import BookEngine
    from deeptutor.book.models import BookProposal
    from deeptutor.book.storage import get_book_storage

    await seed_question("", "Original source material")
    target = account.create_workspace("Books")["workspace_id"]

    async def ideate(self, context, language):
        assert "Original source material" in context.render()
        return BookProposal(title="From my materials", estimated_chapters=1)

    monkeypatch.setattr(BookEngine, "_run_ideation", ideate)
    with workspace_context(target):
        engine = BookEngine()
        book, _ = await engine.create_book(
            user_intent="Learn",
            source_refs=[
                {
                    "kind": "question_bank",
                    "source_id": "1",
                    "label": "Original question",
                    "metadata": {"content_workspace_id": ""},
                }
            ],
        )
        assert get_book_storage().load_book(book.id) is not None
        assert "Original source material" in get_book_storage().load_inputs(book.id).source_context
    with workspace_context(""):
        assert get_book_storage().load_book(book.id) is None


def test_recent_system_assessed_correct_question_is_scheduled_for_later(account):
    entry = asyncio.run(seed_question("", "Arithmetic"))
    with workspace_context(""):
        store = get_sqlite_session_store()
        asyncio.run(store.update_notebook_entry(entry["id"], {"is_correct": True}))
        repo = PracticeStore(store.db_path)
        now = time.time()
        assert repo.queue("UTC", now=now) == []
        assert repo.queue("UTC", now=now + 4 * 86400) == [entry["id"]]


def test_all_workspace_review_keeps_duplicate_ids_distinct_and_updates_only_the_source(
    account, scoped_client
):
    scoped_client.app.include_router(practice.router, prefix="/practice")
    other = account.create_workspace("Other")["workspace_id"]
    for scope in ("", other):
        asyncio.run(seed_question(scope, f"Question in {scope or 'default'}"))
    query = {"all_workspaces": "true", "dt_workspace": other}
    rows = scoped_client.get("/practice/queue", params=query).json()
    assert {(row["content_workspace_id"], row["entry"]["id"]) for row in rows} == {
        ("", 1),
        (other, 1),
    }
    assert scoped_client.get("/practice/summary", params=query).json()["due"] == 2
    response = scoped_client.post(
        "/practice/questions/1/review?dt_workspace=",
        json={
            "request_id": "known_by_learner_0001",
            "version": 0,
            "answer": "",
            "rating": "good",
            "self_report": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["correct"] is None  # Self-report is not fabricated grading evidence.
    assert response.json()["mastered"] is True
    summary = scoped_client.get("/practice/summary", params=query).json()
    assert summary["due"] == 1 and summary["total"] == 2
    assert [
        row["content_workspace_id"]
        for row in scoped_client.get("/practice/queue", params=query).json()
    ] == [other]
    with workspace_context(""):
        repo = PracticeStore(get_sqlite_session_store().db_path)
        due = response.json()["due_at"]
        assert repo.queue("UTC", now=due - 1) == []
        assert repo.queue("UTC", now=due + 1) == [1]
    with workspace_context(other):
        assert PracticeStore(get_sqlite_session_store().db_path).state(1)["review_count"] == 0


def test_correct_answers_leave_queue_and_forgotten_questions_return_soon(account):
    entry = asyncio.run(seed_question("", "Arithmetic"))
    with workspace_context(""):
        repo = PracticeStore(get_sqlite_session_store().db_path)
        now = time.time()
        failed = repo.review(entry["id"], "wrong", 0, "again", "A", now=now)
        assert 0 < failed["due_at"] - now < 15 * 60
        assert repo.queue("UTC", now=now + 15 * 60) == [entry["id"]]
        mastered = repo.review(entry["id"], "correct", 1, "good", "B", now=now + 15 * 60)
        assert mastered["correct"] is True and mastered["mastered"] is True
        assert repo.queue("UTC", now=now + 16 * 60) == []
        assert repo.overview("UTC", now=now + 16 * 60)["total"] == 1


@pytest.mark.parametrize("endpoint", ["summary", "queue", "analytics"])
def test_all_workspace_queries_validate_timezone_before_aggregating(
    account, scoped_client, endpoint
):
    scoped_client.app.include_router(practice.router, prefix="/practice")
    result = scoped_client.get(f"/practice/{endpoint}?all_workspaces=true&timezone=invalid")
    assert result.status_code == 422
