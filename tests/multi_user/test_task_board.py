"""Task board persistence, validation and authenticated workspace isolation."""

from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, task_board
from deeptutor.services.auth import TokenPayload
from deeptutor.services.task_board import (
    CreateCard,
    TaskBoardStore,
    UpdateCard,
    get_task_board_store,
)
from deeptutor.services.workspace import get_content_workspace_service
from deeptutor.services.workspace.activity import WorkspaceActivityMiddleware
from deeptutor.services.workspace.context import workspace_context


@pytest.fixture
def client(mu_isolated_root, monkeypatch):
    """Use real auth/scope dependencies, with fixture identities and isolated disk."""
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token: (
            TokenPayload(username=token, role="user", user_id=token)
            if token in {"alice", "bob"}
            else None
        ),
    )
    app = FastAPI()
    app.add_middleware(WorkspaceActivityMiddleware)
    app.include_router(
        task_board.router,
        prefix="/api/task-board",
        dependencies=[Depends(auth.require_learning_surface)],
    )
    with TestClient(app) as result:
        yield result


def headers(user="alice"):
    return {"Authorization": f"Bearer {user}"}


def test_authentication_is_required_for_reads_and_writes(client):
    for authorization in ({}, headers("invalid")):
        assert client.get("/api/task-board", headers=authorization).status_code == 401
        assert (
            client.post("/api/task-board/cards", json={"title": "Review"}, headers=authorization)
        ).status_code == 401
        assert (
            client.patch("/api/task-board/cards/unknown", json={}, headers=authorization)
        ).status_code == 401


def test_create_edit_move_archive_restore_and_reload(client):
    assert client.get("/api/task-board", headers=headers()).json() == {"cards": []}
    response = client.post(
        "/api/task-board/cards", json={"title": "  Review derivatives  "}, headers=headers()
    )
    assert response.status_code == 201
    card = response.json()["cards"][0]
    assert card["title"] == "Review derivatives"
    assert card["status"] == "todo"
    url = f"/api/task-board/cards/{card['id']}"
    for changes in (
        {"note": "Try three examples", "title": "Practice derivatives"},
        {"status": "doing"},
        {"status": "done"},
        {"archived": True},
        {"archived": False},
    ):
        response = client.patch(url, json=changes, headers=headers())
        assert response.status_code == 200
        assert all(response.json()["cards"][0][key] == value for key, value in changes.items())
    saved = client.get("/api/task-board", headers=headers()).json()["cards"][0]
    assert saved["title"] == "Practice derivatives"
    assert saved["note"] == "Try three examples"
    assert saved["status"] == "done"
    assert not saved["archived"]
    assert saved["created_at"] == card["created_at"]
    assert saved["updated_at"] >= card["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [{"title": " "}, {"title": "x" * 161}, {"title": "Valid", "note": "x" * 2001}, {"id": "x"}],
)
def test_rejects_invalid_new_cards(client, payload):
    assert client.post("/api/task-board/cards", json=payload, headers=headers()).status_code == 422
    assert client.get("/api/task-board", headers=headers()).json() == {"cards": []}


@pytest.mark.parametrize(
    "payload",
    [{"status": "invalid"}, {"title": None}, {"note": None}, {"archived": None}, {"id": "x"}],
)
def test_invalid_changes_do_not_modify_existing_cards(client, payload):
    board = client.post("/api/task-board/cards", json={"title": "Review"}, headers=headers()).json()
    card_id = board["cards"][0]["id"]
    response = client.patch(f"/api/task-board/cards/{card_id}", json=payload, headers=headers())
    assert response.status_code == 422
    assert client.get("/api/task-board", headers=headers()).json() == board


def test_other_accounts_cannot_read_or_modify_cards(client):
    card = client.post(
        "/api/task-board/cards", json={"title": "Private task"}, headers=headers()
    ).json()["cards"][0]
    assert client.get("/api/task-board", headers=headers("bob")).json() == {"cards": []}
    response = client.patch(
        f"/api/task-board/cards/{card['id']}", json={"archived": True}, headers=headers("bob")
    )
    assert response.status_code == 404
    assert client.get("/api/task-board", headers=headers()).json()["cards"] == [card]


def test_workspace_selection_and_archived_workspace_guard(client, as_user):
    with as_user("alice"):
        service = get_content_workspace_service()
        first = service.create_workspace("First")
        second = service.create_workspace("Second")
    first_query = {"dt_workspace": first["workspace_id"]}
    second_query = {"dt_workspace": second["workspace_id"]}
    card = client.post(
        "/api/task-board/cards",
        json={"title": "Scoped task"},
        headers=headers(),
        params=first_query,
    ).json()["cards"][0]
    assert client.get("/api/task-board", headers=headers(), params=second_query).json() == {
        "cards": []
    }
    assert client.get("/api/task-board", headers=headers()).json() == {"cards": []}
    assert (
        client.patch(
            f"/api/task-board/cards/{card['id']}",
            json={"status": "done"},
            headers=headers(),
            params=second_query,
        ).status_code
        == 404
    )
    assert client.get(
        "/api/task-board", headers=headers("bob"), params=first_query
    ).status_code in {403, 404, 409}
    with as_user("alice"):
        with workspace_context(first["workspace_id"]):
            assert get_task_board_store().read().cards[0].id == card["id"]
        service.update_workspace(first["workspace_id"], archived=True)
    assert (
        client.patch(
            f"/api/task-board/cards/{card['id']}",
            json={"status": "done"},
            headers=headers(),
            params=first_query,
        ).status_code
        == 404
    )


def test_concurrent_connections_preserve_cards_and_independent_fields(tmp_path):
    path = tmp_path / "task-board" / "cards.sqlite"
    assert TaskBoardStore(path).read().cards == []
    assert not path.exists()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(
            pool.map(
                lambda i: TaskBoardStore(path).create(CreateCard(title=f"Task {i}")), range(24)
            )
        )
    cards = TaskBoardStore(path).read().cards
    assert len(cards) == 24
    assert len({card.id for card in cards}) == 24
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                TaskBoardStore(path).update, cards[0].id, UpdateCard(note="Keep this note")
            ),
            pool.submit(TaskBoardStore(path).update, cards[0].id, UpdateCard(status="done")),
        ]
        for future in futures:
            future.result()
    updated = TaskBoardStore(path).read().cards[0]
    assert updated.note == "Keep this note"
    assert updated.status == "done"
