"""Question-bank API surface added for triage: search, sort, inbox, bulk, stats."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
notebook_router = importlib.import_module("deeptutor.api.routers.question_notebook").router

from deeptutor.services.session.sqlite_store import SQLiteSessionStore

PREFIX = "/api/v1/question-notebook"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    store = SQLiteSessionStore(db_path=tmp_path / "bank.db")
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_sqlite_session_store",
        lambda: store,
    )
    app = FastAPI()
    app.include_router(notebook_router, prefix=PREFIX)
    with TestClient(app) as test_client:
        test_client.store = store  # type: ignore[attr-defined]
        yield test_client


def _seed(client) -> list[int]:
    store: SQLiteSessionStore = client.store

    async def run() -> list[int]:
        session_id = (await store.create_session(title="Drill"))["id"]
        await store.upsert_notebook_entries(
            session_id,
            [
                {
                    "turn_id": "t1",
                    "question_id": "q1",
                    "question": "What is 50% of 8?",
                    "correct_answer": "4",
                    "user_answer": "5",
                    "is_correct": False,
                },
                {
                    "turn_id": "t1",
                    "question_id": "q2",
                    "question": "Name the a_b convention",
                    "correct_answer": "snake_case",
                    "user_answer": "snake_case",
                    "is_correct": True,
                },
            ],
        )
        listing = await store.list_notebook_entries()
        return [int(i["id"]) for i in listing["items"]]

    return asyncio.run(run())


def test_stats_reports_the_triage_counts(client):
    _seed(client)
    body = client.get(f"{PREFIX}/stats").json()
    assert body == {"total": 2, "wrong": 1, "bookmarked": 0, "uncategorized": 2}


def test_listing_carries_each_entry_categories(client):
    ids = _seed(client)
    category_id = client.post(f"{PREFIX}/categories", json={"name": "Set A"}).json()["id"]
    client.post(f"{PREFIX}/entries/{ids[0]}/categories", json={"category_id": category_id})

    items = client.get(f"{PREFIX}/entries").json()["items"]
    by_id = {item["id"]: item for item in items}
    assert [c["name"] for c in by_id[ids[0]]["categories"]] == ["Set A"]
    assert by_id[ids[1]]["categories"] == []


def test_search_treats_wildcards_literally(client):
    _seed(client)
    hits = client.get(f"{PREFIX}/entries", params={"search": "50%"}).json()
    assert hits["total"] == 1
    assert "50%" in hits["items"][0]["question"]

    underscore = client.get(f"{PREFIX}/entries", params={"search": "a_b"}).json()
    assert underscore["total"] == 1


def test_uncategorized_filter_is_the_inbox(client):
    ids = _seed(client)
    category_id = client.post(f"{PREFIX}/categories", json={"name": "Set A"}).json()["id"]
    client.post(f"{PREFIX}/entries/{ids[0]}/categories", json={"category_id": category_id})

    inbox = client.get(f"{PREFIX}/entries", params={"uncategorized": True}).json()
    assert [item["id"] for item in inbox["items"]] == [ids[1]]


def test_explicit_category_wins_over_uncategorized(client):
    ids = _seed(client)
    category_id = client.post(f"{PREFIX}/categories", json={"name": "Set A"}).json()["id"]
    client.post(f"{PREFIX}/entries/{ids[0]}/categories", json={"category_id": category_id})

    both = client.get(
        f"{PREFIX}/entries", params={"uncategorized": True, "category_id": category_id}
    ).json()
    assert [item["id"] for item in both["items"]] == [ids[0]]


def test_sort_is_stable_across_a_same_timestamp_batch(client):
    _seed(client)
    recent = [
        i["id"] for i in client.get(f"{PREFIX}/entries", params={"sort": "recent"}).json()["items"]
    ]
    oldest = [
        i["id"] for i in client.get(f"{PREFIX}/entries", params={"sort": "oldest"}).json()["items"]
    ]
    assert recent == list(reversed(oldest))


def test_bulk_link_and_unlink(client):
    ids = _seed(client)
    category_id = client.post(f"{PREFIX}/categories", json={"name": "Set A"}).json()["id"]

    added = client.post(
        f"{PREFIX}/entries/categories/bulk",
        json={"entry_ids": ids, "category_id": category_id},
    ).json()
    assert added["changed"] == len(ids)

    repeat = client.post(
        f"{PREFIX}/entries/categories/bulk",
        json={"entry_ids": ids, "category_id": category_id},
    ).json()
    assert repeat["changed"] == 0

    removed = client.post(
        f"{PREFIX}/entries/categories/bulk",
        json={"entry_ids": ids, "category_id": category_id, "link": False},
    ).json()
    assert removed["changed"] == len(ids)


def test_bulk_route_is_not_shadowed_by_the_per_entry_route(client):
    ids = _seed(client)
    category_id = client.post(f"{PREFIX}/categories", json={"name": "Set A"}).json()["id"]
    response = client.post(
        f"{PREFIX}/entries/categories/bulk",
        json={"entry_ids": ids, "category_id": category_id},
    )
    # A shadowed literal path would try to parse "categories" as an int id.
    assert response.status_code == 200


def test_bulk_rejects_an_empty_batch(client):
    _seed(client)
    response = client.post(
        f"{PREFIX}/entries/categories/bulk", json={"entry_ids": [], "category_id": 1}
    )
    assert response.status_code == 422


def test_invalid_sort_is_rejected(client):
    _seed(client)
    assert client.get(f"{PREFIX}/entries", params={"sort": "sideways"}).status_code == 422


def test_case_only_duplicate_category_is_rejected(client):
    assert client.post(f"{PREFIX}/categories", json={"name": "Math"}).status_code == 201
    clash = client.post(f"{PREFIX}/categories", json={"name": "  math  "})
    # "Math" and "math" read as one pile to a learner, and the agent resolves
    # names case-insensitively — allowing both makes the two disagree.
    assert clash.status_code == 409
    assert "already exists" in clash.json()["detail"]
    assert len(client.get(f"{PREFIX}/categories").json()) == 1


def test_rename_onto_an_existing_name_is_a_conflict_not_a_crash(client):
    first = client.post(f"{PREFIX}/categories", json={"name": "Math"}).json()
    second = client.post(f"{PREFIX}/categories", json={"name": "Physics"}).json()

    clash = client.patch(f"{PREFIX}/categories/{second['id']}", json={"name": "Math"})
    # The UNIQUE index used to raise straight through as a 500.
    assert clash.status_code == 409
    assert "already exists" in clash.json()["detail"]

    # Renaming a category to the name it already has is not a clash.
    same = client.patch(f"{PREFIX}/categories/{first['id']}", json={"name": "Math"})
    assert same.status_code == 200

    moved = client.patch(f"{PREFIX}/categories/{first['id']}", json={"name": "Calculus"})
    assert moved.status_code == 200
    assert sorted(c["name"] for c in client.get(f"{PREFIX}/categories").json()) == [
        "Calculus",
        "Physics",
    ]


def test_renaming_a_missing_category_is_404(client):
    assert client.patch(f"{PREFIX}/categories/9999", json={"name": "Ghost"}).status_code == 404
