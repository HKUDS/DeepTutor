from pathlib import Path

from deeptutor.multi_user import identity, paths
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.path_service import get_path_service


def test_identity_migrates_legacy_users_with_stable_uid(tmp_path, monkeypatch):
    legacy = tmp_path / "data" / "user" / "auth_users.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"alice":{"hash":"h1","role":"admin","created_at":"t"},"bob":"h2"}')
    users_file = tmp_path / "multi-user" / "_system" / "auth" / "users.json"

    monkeypatch.setattr(identity, "USERS_FILE", users_file)
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", legacy)

    users = identity.load_users()

    assert users["alice"]["id"].startswith("u_")
    assert users["alice"]["role"] == "admin"
    assert users["bob"]["role"] == "user"
    assert users_file.exists()


def test_path_service_uses_current_user_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ensure_user_workspace", lambda _uid: tmp_path)
    user_root = tmp_path / "multi-user" / "u_alice"
    user = CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=user_root),
    )

    token = set_current_user(user)
    try:
        service = get_path_service()
        assert service.workspace_root == user_root.resolve()
        assert service.get_chat_history_db() == user_root.resolve() / "user" / "chat_history.db"
        assert service.get_knowledge_bases_root() == user_root.resolve() / "knowledge_bases"
    finally:
        reset_current_user(token)
