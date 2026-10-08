"""Task board persistence, validation and authenticated workspace isolation."""

from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, task_board
from deeptutor.services.auth import TokenPayload
from deeptutor.services.task_board import (
    CreateCard,
    LinkStatus,
    LinkTasks,
    StatusColors,
    TaskBoard,
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


def test_learning_policy_allows_board_reads_and_writes_only_with_chat_surface(client, monkeypatch):
    from deeptutor.multi_user.grants import learner_grant, save_grant
    from deeptutor.multi_user.identity import save_user

    save_user("admin", "placeholder", role="admin")
    learner = save_user("alice", "placeholder", preset="learner")
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token: (
            TokenPayload(username="alice", role="user", user_id=learner["id"])
            if token == "alice"
            else None
        ),
    )

    grant = learner_grant(learner["id"])
    save_grant(learner["id"], grant)

    assert client.get("/api/task-board", headers=headers()).status_code == 200
    created = client.post("/api/task-board/cards", json={"title": "Practice"}, headers=headers())
    assert created.status_code == 201
    card_id = created.json()["cards"][0]["id"]
    updated = client.patch(
        f"/api/task-board/cards/{card_id}", json={"status": "doing"}, headers=headers()
    )
    assert updated.status_code == 200
    assert updated.json()["cards"][0]["status"] == "doing"

    grant["learning_policy"]["allowed_surfaces"] = ["reading"]
    save_grant(learner["id"], grant)
    assert client.get("/api/task-board", headers=headers()).status_code == 403
    assert (
        client.post("/api/task-board/cards", json={"title": "Hidden"}, headers=headers())
    ).status_code == 403
    assert (
        client.patch(f"/api/task-board/cards/{card_id}", json={"status": "done"}, headers=headers())
    ).status_code == 403


def test_create_edit_move_archive_restore_and_reload(client):
    assert (
        client.get("/api/task-board", headers=headers()).json() == TaskBoard(cards=[]).model_dump()
    )
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
    assert (
        client.get("/api/task-board", headers=headers()).json() == TaskBoard(cards=[]).model_dump()
    )


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
    assert (
        client.get("/api/task-board", headers=headers("bob")).json()
        == TaskBoard(cards=[]).model_dump()
    )
    response = client.patch(
        f"/api/task-board/cards/{card['id']}", json={"archived": True}, headers=headers("bob")
    )
    assert response.status_code == 404
    assert client.get("/api/task-board", headers=headers()).json()["cards"] == [card]


def test_independent_board_and_assignment_workspace_guards(client, as_user):
    with as_user("alice"):
        service = get_content_workspace_service()
        first = service.create_workspace("First")
        second = service.create_workspace("Second")
    card = client.post(
        "/api/task-board/cards",
        json={"title": "Independent task"},
        headers=headers(),
        params={"dt_workspace": first["workspace_id"]},
    ).json()["cards"][0]
    assert card["workspace_id"] is None
    for workspace in ("", first["workspace_id"], second["workspace_id"]):
        assert client.get(
            "/api/task-board", headers=headers(), params={"dt_workspace": workspace}
        ).json()["cards"] == [card]
    url = f"/api/task-board/cards/{card['id']}"
    assigned = client.patch(
        url, json={"workspace_id": first["workspace_id"]}, headers=headers()
    ).json()["cards"][0]
    assert assigned["workspace_id"] == first["workspace_id"]
    assert client.patch(url, json={"workspace_id": "missing"}, headers=headers()).status_code == 404
    with as_user("bob"):
        other = get_content_workspace_service().create_workspace("Private")
    assert (
        client.patch(
            url, json={"workspace_id": other["workspace_id"]}, headers=headers()
        ).status_code
        == 404
    )
    with as_user("alice"):
        service.update_workspace(first["workspace_id"], archived=True)
    assert (
        client.patch(
            url, json={"workspace_id": first["workspace_id"]}, headers=headers()
        ).status_code
        == 404
    )
    # Selecting an archived workspace does not lock the independent board.
    assert (
        client.patch(
            url,
            json={"status": "done"},
            headers=headers(),
            params={"dt_workspace": first["workspace_id"]},
        ).status_code
        == 200
    )
    assert (
        client.patch(url, json={"workspace_id": None}, headers=headers()).json()["cards"][0][
            "workspace_id"
        ]
        is None
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


def test_associations_preserve_latest_order_and_independent_status_switch(tmp_path):
    store = TaskBoardStore(tmp_path / "tasks.sqlite")
    first = store.create(CreateCard(title="First")).cards[0]
    second = store.create(CreateCard(title="Second")).cards[1]
    linked = store.link_tasks(
        "chat", LinkTasks(workspace_id="study", task_ids=[first.id, second.id])
    )
    assert linked.session_links[0].task_ids == [first.id, second.id]
    reordered = store.link_tasks(
        "chat", LinkTasks(workspace_id="study", task_ids=[second.id, first.id])
    )
    assert reordered.session_links[0].task_ids == [first.id, second.id]
    disabled = store.link_status("chat", LinkStatus(workspace_id="study", enabled=False))
    assert not disabled.session_links[0].status_link_enabled
    assert disabled.session_links[0].task_ids == [first.id, second.id]
    removed = store.link_tasks("chat", LinkTasks(workspace_id="study", task_ids=[first.id]))
    assert removed.session_links[0].task_ids == [first.id]
    relinked = store.link_tasks(
        "chat", LinkTasks(workspace_id="study", task_ids=[first.id, second.id])
    )
    assert relinked.session_links[0].status_link_enabled
    assert relinked.session_links[0].task_ids[-1] == second.id
    store.move_session_links(["chat"], "study", "other")
    assert store.read().session_links[0].workspace_id == "other"


def test_workspace_task_context_and_linked_context_use_live_cards(tmp_path):
    store = TaskBoardStore(tmp_path / "tasks.sqlite")
    assigned = store.create(CreateCard(title="Workspace task")).cards[0]
    linked = store.create(CreateCard(title="Linked task")).cards[1]
    store.update(assigned.id, UpdateCard(workspace_id="study"))
    store.link_tasks("chat-one", LinkTasks(workspace_id="study", task_ids=[linked.id]))
    assert "Workspace task" in store.context_text("study", "chat-two")
    assert "Linked task" not in store.context_text("study", "chat-two")
    assert "Linked task" in store.context_text("study", "chat-one")
    store.update(linked.id, UpdateCard(status="done", note="Newest note"))
    assert "Newest note" in store.context_text("study", "chat-one")
    assert '"status": "done"' in store.context_text("study", "chat-one")
    assert store.context_text("other", "chat-one") == ""
    store.update(assigned.id, UpdateCard(archived=True))
    assert store.context_text("study", "chat-two") == ""


def test_link_validation_is_transactional_and_colors_are_durable(tmp_path):
    store = TaskBoardStore(tmp_path / "tasks.sqlite")
    card = store.create(CreateCard(title="Keep")).cards[0]
    original = store.link_tasks("chat", LinkTasks(task_ids=[card.id]))
    with pytest.raises(KeyError):
        store.link_tasks("chat", LinkTasks(task_ids=["missing"]))
    assert store.read() == original
    colors = StatusColors(todo="#123456", doing="#abcdef", done="#777777")
    saved = store.set_colors(colors)
    assert TaskBoardStore(store.path).read().colors == colors
    assert saved.revision > original.revision
    store.update(card.id, UpdateCard(archived=True))
    with pytest.raises(KeyError):
        store.link_tasks("other-chat", LinkTasks(task_ids=[card.id]))


def test_legacy_workspace_tasks_are_imported_once_without_losing_archive_state(as_user):
    from deeptutor.services.path_service import get_path_service

    with as_user("alice"):
        service = get_content_workspace_service()
        workspace = service.create_workspace("Original")
        with workspace_context(workspace["workspace_id"]):
            legacy_path = get_path_service().get_workspace_dir() / "task-board" / "cards.sqlite"
            legacy = TaskBoardStore(legacy_path)
            card = legacy.create(CreateCard(title="Legacy task")).cards[0]
            legacy.update(card.id, UpdateCard(status="done", archived=True))
        store = get_task_board_store()
        imported = store.read().cards[0]
        assert imported.title == "Legacy task"
        assert imported.archived and imported.status == "done"
        assert imported.workspace_id == workspace["workspace_id"]
        store.update(imported.id, UpdateCard(title="New title", archived=False))
        assert len(get_task_board_store().read().cards) == 1
        assert get_task_board_store().read().cards[0].title == "New title"
        assert legacy_path.exists()


def test_session_link_routes_validate_session_and_account(client, as_user):
    import asyncio

    from deeptutor.services.session import get_session_store

    with as_user("alice"):
        session = asyncio.run(get_session_store().create_session())
    card = client.post("/api/task-board/cards", json={"title": "Task"}, headers=headers()).json()[
        "cards"
    ][0]
    url = f"/api/task-board/sessions/{session['id']}"
    assert client.put(url, json={"task_ids": [card["id"]]}, headers=headers()).status_code == 200
    assert (
        client.put(url, json={"task_ids": [card["id"]]}, headers=headers("bob")).status_code == 404
    )
    assert (
        client.put(
            "/api/task-board/sessions/missing", json={"task_ids": [card["id"]]}, headers=headers()
        ).status_code
        == 404
    )
    updated = client.patch(url + "/status", json={"enabled": False}, headers=headers()).json()
    assert not updated["session_links"][0]["status_link_enabled"]
    assert (
        client.put(
            "/api/task-board/colors", json={"todo": "not-a-color"}, headers=headers()
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/task-board/colors",
            json={"todo": "#111111", "doing": "#222222", "done": "#333333"},
            headers=headers(),
        ).status_code
        == 200
    )
    assert (
        client.get("/api/task-board", headers=headers("bob")).json()["colors"]
        == StatusColors().model_dump()
    )


@pytest.mark.asyncio
async def test_events_observe_commits_from_another_store_connection(as_user):
    import json

    class Request:
        async def is_disconnected(self):
            return False

    with as_user("alice"):
        stream = await task_board.board_events(Request())
        assert "no-transform" in stream.headers["cache-control"]
        assert stream.headers["content-encoding"] == "identity"
        events = stream.body_iterator
        first = await anext(events)
        assert json.loads(first.split("data: ")[1])["revision"] == 0
        writer = TaskBoardStore(get_task_board_store().path)
        writer.create(CreateCard(title="Other worker"))
        second = await anext(events)
        snapshot = json.loads(second.split("data: ")[1])
        assert snapshot["cards"][0]["title"] == "Other worker"
        assert snapshot["revision"] == 1
        await events.aclose()
