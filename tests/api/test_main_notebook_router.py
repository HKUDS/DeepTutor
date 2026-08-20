"""Tests for the main notebook router (/api/v1/notebook).

Verifies that records can only be saved using real notebook UUIDs
(from /api/v1/notebook/list), not question-notebook category integer IDs.
"""

from __future__ import annotations

import asyncio
import importlib
import json

import pytest

pytest.importorskip("fastapi")

FastAPI = pytest.importorskip("fastapi").FastAPI
TestClient = pytest.importorskip("fastapi.testclient").TestClient

notebook_router = importlib.import_module("deeptutor.api.routers.notebook").router

from deeptutor.services.notebook.service import NotebookManager


def _build_app(manager: NotebookManager) -> FastAPI:
    app = FastAPI()
    app.include_router(notebook_router, prefix="/api/v1/notebook")
    return app


@pytest.fixture
def manager(tmp_path, monkeypatch) -> NotebookManager:
    instance = NotebookManager(base_dir=str(tmp_path / "notebooks"))
    monkeypatch.setattr(
        "deeptutor.api.routers.notebook.notebook_manager",
        instance,
    )
    return instance


def test_list_notebooks_empty(manager: NotebookManager) -> None:
    with TestClient(_build_app(manager)) as client:
        resp = client.get("/api/v1/notebook/list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["notebooks"] == []
        assert data["total"] == 0


def test_create_and_list_notebook(manager: NotebookManager) -> None:
    with TestClient(_build_app(manager)) as client:
        create_resp = client.post(
            "/api/v1/notebook/create",
            json={"name": "Study Notes", "description": "Physics"},
        )
        assert create_resp.status_code == 200
        nb = create_resp.json()["notebook"]
        assert nb["name"] == "Study Notes"
        nb_id = nb["id"]

        listing = client.get("/api/v1/notebook/list").json()
        assert listing["total"] == 1
        assert listing["notebooks"][0]["id"] == nb_id


def test_add_record_with_valid_notebook_id(manager: NotebookManager) -> None:
    """Records saved with a real notebook UUID must appear in that notebook."""
    nb = manager.create_notebook(name="My Notes")
    nb_id = nb["id"]

    with TestClient(_build_app(manager)) as client:
        resp = client.post(
            "/api/v1/notebook/add_record",
            json={
                "notebook_ids": [nb_id],
                "record_type": "chat",
                "title": "Draft on Fourier",
                "summary": "Existing summary",
                "user_query": "Explain Fourier",
                "output": "Fourier transform is...",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert nb_id in body["added_to_notebooks"]

        detail = client.get(f"/api/v1/notebook/{nb_id}").json()
        assert len(detail["records"]) == 1
        assert detail["records"][0]["title"] == "Draft on Fourier"


def test_add_record_with_numeric_category_id_saves_nothing(manager: NotebookManager) -> None:
    """Using a question-notebook integer category ID must NOT match any notebook.

    This is the root cause of issue #301: the old SaveToNotebookModal sent
    numeric category IDs from /api/v1/question-notebook/categories instead of
    UUID notebook IDs from /api/v1/notebook/list.
    """
    manager.create_notebook(name="My Notes")

    with TestClient(_build_app(manager)) as client:
        resp = client.post(
            "/api/v1/notebook/add_record",
            json={
                "notebook_ids": ["1", "42"],
                "record_type": "chat",
                "title": "Lost draft",
                "summary": "This should not be saved anywhere",
                "user_query": "...",
                "output": "...",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added_to_notebooks"] == []


def test_stream_add_record_with_summary_strips_thinking_tags(
    manager: NotebookManager,
    monkeypatch,
) -> None:
    class FakeSummarizeAgent:
        def __init__(self, language: str = "en") -> None:
            self.language = language

        async def stream_summary(self, **_kwargs):
            yield "<thi"
            yield "nk>private reasoning</think>\n"
            yield "Final reusable summary."

    monkeypatch.setattr(
        "deeptutor.api.routers.notebook.NotebookSummarizeAgent",
        FakeSummarizeAgent,
    )
    nb = manager.create_notebook(name="My Notes")

    async def collect_events() -> list[dict]:
        request = importlib.import_module("deeptutor.api.routers.notebook").AddRecordRequest(
            notebook_ids=[nb["id"]],
            record_type="chat",
            title="Streaming save",
            user_query="Explain Fourier",
            output="Fourier transform is...",
        )
        events: list[dict] = []
        async for raw in importlib.import_module(
            "deeptutor.api.routers.notebook"
        )._stream_add_record_with_summary(request):
            assert "<think" not in raw.lower()
            assert "private reasoning" not in raw
            events.append(json.loads(raw.removeprefix("data: ").strip()))
        return events

    events = asyncio.run(collect_events())
    assert events[-1]["type"] == "result"
    assert events[-1]["summary"] == "Final reusable summary."

    detail = manager.get_notebook(nb["id"])
    assert detail is not None
    assert detail["records"][0]["summary"] == "Final reusable summary."


def test_health_is_not_shadowed_by_the_notebook_id_route(manager: NotebookManager) -> None:
    """`/health` is a literal path and must win over `/{notebook_id}`.

    Declared after the parameterised route it returned 404 "Notebook not
    found", because FastAPI matched `health` as an id.
    """
    with TestClient(_build_app(manager)) as client:
        resp = client.get("/api/v1/notebook/health")

    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_renaming_a_record_over_http_keeps_its_kb_name(manager: NotebookManager) -> None:
    """The PUT endpoint must forward only the fields the client sent."""
    notebook_id = manager.create_notebook("KB")["id"]
    record = manager.add_record(
        notebook_ids=[notebook_id],
        record_type="chat",
        title="Original",
        user_query="q",
        output="o",
        kb_name="physics",
    )["record"]

    with TestClient(_build_app(manager)) as client:
        resp = client.put(
            f"/api/v1/notebook/{notebook_id}/records/{record['id']}",
            json={"title": "Renamed"},
        )

    assert resp.status_code == 200
    updated = resp.json()["record"]
    assert updated["title"] == "Renamed"
    assert updated["kb_name"] == "physics"


def test_record_kb_name_can_still_be_cleared_explicitly(manager: NotebookManager) -> None:
    notebook_id = manager.create_notebook("KB")["id"]
    record = manager.add_record(
        notebook_ids=[notebook_id],
        record_type="chat",
        title="Original",
        user_query="q",
        output="o",
        kb_name="physics",
    )["record"]

    with TestClient(_build_app(manager)) as client:
        resp = client.put(
            f"/api/v1/notebook/{notebook_id}/records/{record['id']}",
            json={"kb_name": None},
        )

    assert resp.status_code == 200
    assert resp.json()["record"]["kb_name"] is None


def test_move_and_copy_endpoints(manager: NotebookManager) -> None:
    source = manager.create_notebook("Source")["id"]
    target = manager.create_notebook("Target")["id"]
    record = manager.add_record(
        notebook_ids=[source],
        record_type="chat",
        title="Travelling",
        user_query="q",
        output="o",
    )["record"]

    with TestClient(_build_app(manager)) as client:
        copy_resp = client.post(
            f"/api/v1/notebook/{source}/records/{record['id']}/copy",
            json={"target_notebook_id": target},
        )
        assert copy_resp.status_code == 200
        assert copy_resp.json()["record"]["id"] != record["id"]

        move_resp = client.post(
            f"/api/v1/notebook/{source}/records/{record['id']}/move",
            json={"target_notebook_id": target},
        )
        assert move_resp.status_code == 200

    assert manager.get_record(source, record["id"]) is None
    assert len(manager.get_records(target)) == 2


def test_export_returns_markdown(manager: NotebookManager) -> None:
    notebook_id = manager.create_notebook("Exported")["id"]
    manager.add_record(
        notebook_ids=[notebook_id],
        record_type="chat",
        title="First entry",
        user_query="q",
        output="Body text.",
    )

    with TestClient(_build_app(manager)) as client:
        resp = client.get(f"/api/v1/notebook/{notebook_id}/export")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "## First entry" in resp.text


def test_damaged_notebook_returns_a_named_conflict(manager: NotebookManager) -> None:
    (manager.base_dir / "broken01.json").write_text("{ not json", encoding="utf-8")

    with TestClient(_build_app(manager)) as client:
        resp = client.get("/api/v1/notebook/broken01")

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "notebook_unreadable"


def test_every_notebook_endpoint_reports_damage_as_409(manager: NotebookManager) -> None:
    """No endpoint may flatten a damaged file into an anonymous 500.

    Each endpoint wraps its body in `except Exception -> 500`, which swallows
    NotebookCorruptedError unless it is re-raised first. This walks the real
    request surface so an endpoint added later without that guard fails here
    rather than degrading quietly in production.
    """
    (manager.base_dir / "broken01.json").write_text("{ not json", encoding="utf-8")
    healthy = manager.create_notebook("Healthy")["id"]

    requests = [
        ("GET", "/api/v1/notebook/broken01", None),
        ("PUT", "/api/v1/notebook/broken01", {"name": "Renamed"}),
        ("GET", "/api/v1/notebook/broken01/export", None),
        ("DELETE", "/api/v1/notebook/broken01/records/whatever", None),
        ("PUT", "/api/v1/notebook/broken01/records/whatever", {"title": "x"}),
        (
            "POST",
            "/api/v1/notebook/broken01/records/whatever/copy",
            {"target_notebook_id": healthy},
        ),
        (
            "POST",
            "/api/v1/notebook/broken01/records/whatever/move",
            {"target_notebook_id": healthy},
        ),
    ]

    with TestClient(_build_app(manager)) as client:
        for method, url, body in requests:
            resp = client.request(method, url, json=body)
            assert resp.status_code == 409, f"{method} {url} returned {resp.status_code}"
            assert resp.json()["detail"]["code"] == "notebook_unreadable", (
                f"{method} {url} lost the structured reason"
            )
