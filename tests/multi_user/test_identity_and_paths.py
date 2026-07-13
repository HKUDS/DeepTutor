from pathlib import Path

from deeptutor.multi_user import identity, paths
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.path_service import get_path_service


def test_identity_migrates_legacy_users_with_stable_uid(tmp_path, monkeypatch):
    legacy = tmp_path / "data" / "user" / "auth_users.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"alice":{"hash":"h1","role":"admin","created_at":"t"},"bob":"h2"}')
    users_file = tmp_path / "data" / "system" / "auth" / "users.json"

    monkeypatch.setattr(identity, "USERS_FILE", users_file)
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", legacy)

    users = identity.load_users()

    assert users["alice"]["id"].startswith("u_")
    assert users["alice"]["role"] == "admin"
    assert users["bob"]["role"] == "user"
    assert users_file.exists()


def test_path_service_uses_current_user_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ensure_user_workspace", lambda _uid: tmp_path)
    user_root = tmp_path / "data" / "users" / "u_alice"
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


def test_legacy_multi_user_tree_migrates_into_data(tmp_path, monkeypatch):
    legacy = tmp_path / "multi-user"
    (legacy / "_system" / "auth").mkdir(parents=True)
    (legacy / "_system" / "auth" / "users.json").write_text("{}")
    (legacy / "u_alice" / "user").mkdir(parents=True)
    (legacy / "u_alice" / "user" / "chat_history.db").write_text("x")

    users_root = tmp_path / "data" / "users"
    system_root = tmp_path / "data" / "system"
    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", legacy)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(paths, "_legacy_migration_done", False)

    paths.migrate_legacy_multi_user_tree()

    assert (system_root / "auth" / "users.json").read_text() == "{}"
    assert (users_root / "u_alice" / "user" / "chat_history.db").read_text() == "x"
    assert not legacy.exists()


def test_legacy_migration_never_overwrites_existing_targets(tmp_path, monkeypatch):
    legacy = tmp_path / "multi-user"
    (legacy / "u_alice").mkdir(parents=True)
    (legacy / "u_alice" / "old.txt").write_text("legacy")
    (legacy / "u_bob").mkdir(parents=True)
    (legacy / "u_bob" / "data.txt").write_text("bob")

    users_root = tmp_path / "data" / "users"
    (users_root / "u_alice").mkdir(parents=True)
    (users_root / "u_alice" / "new.txt").write_text("current")

    monkeypatch.setattr(paths, "LEGACY_MULTI_USER_ROOT", legacy)
    monkeypatch.setattr(paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(paths, "SYSTEM_ROOT", tmp_path / "data" / "system")
    monkeypatch.setattr(paths, "_legacy_migration_done", False)

    paths.migrate_legacy_multi_user_tree()

    # Existing target untouched; the colliding legacy dir stays for manual
    # reconciliation while non-colliding siblings still migrate.
    assert (users_root / "u_alice" / "new.txt").read_text() == "current"
    assert (legacy / "u_alice" / "old.txt").read_text() == "legacy"
    assert (users_root / "u_bob" / "data.txt").read_text() == "bob"
    assert legacy.exists()
