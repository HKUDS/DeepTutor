"""Contract tests for the Question Notebook API (issue #1244 ground work).

Pins three contract surfaces of ``POST /api/question-notebook/entries/upsert``
and the listing filter: AssessmentSource validation, identity dedup, and
concurrent-write behaviour.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient
notebook_router = pytest.importorskip("deeptutor.api.routers.question_notebook").router

from deeptutor.core.assessment import ASSESSMENT_SOURCES
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

PREFIX = "/api/question-notebook"

PINNED_SOURCES = {
    "deep_question",
    "mastery_path",
    "immersive_reading",
    "book",
    "partner_chat",
    "import",
}


def _build_app(store: SQLiteSessionStore) -> FastAPI:
    app = FastAPI()
    app.include_router(notebook_router, prefix=PREFIX)
    return app


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> SQLiteSessionStore:
    instance = SQLiteSessionStore(db_path=tmp_path / "notebook-contract.db")
    monkeypatch.setattr(
        "deeptutor.api.routers.question_notebook.get_sqlite_session_store",
        lambda: instance,
    )
    return instance


@pytest.fixture
def client(store: SQLiteSessionStore):
    with TestClient(_build_app(store)) as test_client:
        yield test_client


@pytest.fixture
def session_id(store: SQLiteSessionStore) -> str:
    return asyncio.run(store.create_session(title="Notebook contract"))["id"]


def _conversation_payload(session_id: str, **overrides):
    payload = {
        "session_id": session_id,
        "origin_type": "conversation",
        "question_id": "q1",
        "question": "Capital of France?",
        "user_answer": "A",
        "correct_answer": "B",
        "is_correct": False,
        "source": "deep_question",
    }
    payload.update(overrides)
    return payload


def test_assessment_source_catalog_is_pinned() -> None:
    assert ASSESSMENT_SOURCES == PINNED_SOURCES


@pytest.mark.parametrize("source", sorted(PINNED_SOURCES))
def test_upsert_accepts_every_valid_source(client, session_id: str, source: str) -> None:
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json=_conversation_payload(session_id, question_id=f"q-{source}", source=source),
    )
    assert response.status_code == 200
    assert response.json()["source"] == source


@pytest.mark.parametrize("source", ["wechat_chat", "partner", "Partner_Chat", "deepquest", ""])
def test_upsert_rejects_unlisted_source(
    client, store: SQLiteSessionStore, session_id: str, source: str
) -> None:
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json=_conversation_payload(session_id, question_id="q-rejected", source=source),
    )
    assert response.status_code == 422
    detail = response.json()["detail"][0]
    assert detail["type"] == "literal_error"
    assert detail["loc"] == ["body", "source"]
    listing = client.get(f"{PREFIX}/entries").json()
    assert listing["total"] == 0


def test_entries_filter_rejects_unlisted_source(client) -> None:
    response = client.get(f"{PREFIX}/entries", params={"source": "wechat_chat"})
    assert response.status_code == 422


def test_partner_chat_entry_roundtrip_and_filter(client, session_id: str) -> None:
    created = client.post(
        f"{PREFIX}/entries/upsert",
        json=_conversation_payload(
            session_id,
            question_id="q-partner",
            question=" Photographed wrong question ",
            source="partner_chat",
            user_answer="42",
            is_correct=False,
            result="incorrect",
        ),
    )
    assert created.status_code == 200
    entry = created.json()
    assert entry["source"] == "partner_chat"
    assert entry["user_answer"] == "42"
    assert entry["is_correct"] is False

    by_id = client.get(f"{PREFIX}/entries/{entry['id']}")
    assert by_id.status_code == 200
    assert by_id.json()["source"] == "partner_chat"

    filtered = client.get(f"{PREFIX}/entries", params={"source": "partner_chat"})
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == entry["id"]


def test_upsert_dedupes_identity_and_updates_content(client, session_id: str) -> None:
    first = client.post(
        f"{PREFIX}/entries/upsert",
        json=_conversation_payload(
            session_id,
            question_id="q-dup",
            turn_id="turn-1",
            user_answer="A",
            is_correct=True,
        ),
    )
    assert first.status_code == 200
    assert first.json()["score_trend"] == "new"

    second = client.post(
        f"{PREFIX}/entries/upsert",
        json=_conversation_payload(
            session_id,
            question_id="q-dup",
            turn_id="turn-1",
            user_answer="C",
            is_correct=False,
        ),
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["user_answer"] == "C"
    assert second.json()["is_correct"] is False
    assert second.json()["score_trend"] == "declined"

    listing = client.get(f"{PREFIX}/entries").json()
    assert listing["total"] == 1


def test_upsert_identity_is_turn_scoped(client, session_id: str) -> None:
    for turn_id in ("turn-1", "turn-2"):
        response = client.post(
            f"{PREFIX}/entries/upsert",
            json=_conversation_payload(session_id, question_id="q-turns", turn_id=turn_id),
        )
        assert response.status_code == 200
    listing = client.get(f"{PREFIX}/entries").json()
    assert listing["total"] == 2
    assert {item["turn_id"] for item in listing["items"]} == {"turn-1", "turn-2"}


def test_upsert_rejects_conversation_origin_ref_mismatch(client, session_id: str) -> None:
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json=_conversation_payload(session_id, origin_ref="not-this-session"),
    )
    assert response.status_code == 422
    assert client.get(f"{PREFIX}/entries").json()["total"] == 0


def test_upsert_requires_origin_ref_for_non_conversation(client, session_id: str) -> None:
    response = client.post(
        f"{PREFIX}/entries/upsert",
        json=_conversation_payload(session_id, origin_type="external_import", source="import"),
    )
    assert response.status_code == 422
    assert client.get(f"{PREFIX}/entries").json()["total"] == 0


def test_concurrent_identical_upserts_keep_single_row(
    store: SQLiteSessionStore, session_id: str
) -> None:
    app = _build_app(store)

    async def fire() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

            async def one(index: int) -> httpx.Response:
                return await client.post(
                    f"{PREFIX}/entries/upsert",
                    json=_conversation_payload(
                        session_id,
                        question_id="q-race",
                        turn_id="turn-race",
                        user_answer=f"answer-{index}",
                        is_correct=index % 2 == 0,
                    ),
                )

            return list(await asyncio.gather(*(one(i) for i in range(8))))

    responses = asyncio.run(fire())
    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]

    listing = store_list(store)
    race_rows = [
        item
        for item in listing
        if item["question_id"] == "q-race" and item["turn_id"] == "turn-race"
    ]
    assert len(race_rows) == 1
    assert race_rows[0]["user_answer"] in {f"answer-{i}" for i in range(8)}


def test_concurrent_distinct_turns_create_distinct_rows(
    store: SQLiteSessionStore, session_id: str
) -> None:
    app = _build_app(store)

    async def fire() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

            async def one(index: int) -> httpx.Response:
                return await client.post(
                    f"{PREFIX}/entries/upsert",
                    json=_conversation_payload(
                        session_id,
                        question_id="q-fanout",
                        turn_id=f"turn-{index}",
                        user_answer=f"answer-{index}",
                    ),
                )

            return list(await asyncio.gather(*(one(i) for i in range(8))))

    responses = asyncio.run(fire())
    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]

    listing = store_list(store)
    fanout = {item["turn_id"] for item in listing if item["question_id"] == "q-fanout"}
    assert fanout == {f"turn-{i}" for i in range(8)}


def store_list(store: SQLiteSessionStore) -> list[dict]:
    return asyncio.run(store.list_notebook_entries(limit=200))["items"]
