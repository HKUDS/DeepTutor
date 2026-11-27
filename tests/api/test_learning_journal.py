from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import learning_journal
from deeptutor.services.learning_journal.store import LearningJournalStore
from deeptutor.services.path_service import PathService
from deeptutor.services.workspace.context import WorkspacePathService, WorkspaceScope


def test_read_only_overview_is_scoped_and_preserves_corruption(tmp_path, monkeypatch):
    account = PathService(workspace_root=tmp_path / "account")
    a = WorkspacePathService(account, WorkspaceScope("a", account.workspace_root, tmp_path / "a"))
    b = WorkspacePathService(account, WorkspaceScope("b", account.workspace_root, tmp_path / "b"))
    active = [a]
    store = LearningJournalStore()
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.store.get_path_service", lambda: active[0]
    )
    monkeypatch.setattr(learning_journal, "get_learning_journal_store", lambda: store)
    app = FastAPI()
    app.include_router(learning_journal.router, prefix="/api/learning-journal")
    client = TestClient(app)
    store.set_mission(topic="Workspace A")
    assert client.get("/api/learning-journal").json()["mission"]["topic"] == "Workspace A"
    active[0] = b
    assert client.get("/api/learning-journal").json()["mission"]["topic"] == ""
    assert not b.get_learning_journal_dir().exists()
    assert (
        client.post("/api/learning-journal", json={"mission": {"topic": "overwrite"}}).status_code
        == 405
    )
    b.get_learning_journal_dir().mkdir(parents=True)
    b.get_learning_journal_file().write_bytes(b"{corrupt")
    assert client.get("/api/learning-journal").status_code == 409
    assert b.get_learning_journal_file().read_bytes() == b"{corrupt"
    active[0] = a
    assert store.load().mission.topic == "Workspace A"
