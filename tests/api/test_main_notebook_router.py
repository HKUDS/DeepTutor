"""Tests for the main notebook router (/api/v1/notebook).

Verifies that records can only be saved using real notebook UUIDs
(from /api/v1/notebook/list), not question-notebook category integer IDs.
Regression test for issue #301 (Co-Writer save to notebook).
"""

from __future__ import annotations

import importlib

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
        "deeptutor.api.routers.notebook.notebook_manager", instance,
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
                "record_type": "co_writer",
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
                "record_type": "co_writer",
                "title": "Lost draft",
                "summary": "This should not be saved anywhere",
                "user_query": "...",
                "output": "...",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["added_to_notebooks"] == []
