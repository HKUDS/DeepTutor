"""M5 regression — first user becomes admin atomically; concurrent races safe."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor


def test_first_save_user_promotes_to_admin(mu_isolated_root):
    from deeptutor.multi_user.identity import list_user_info, save_user

    save_user("alice", "$2b$12$placeholder", role="user")
    users = {u["username"]: u for u in list_user_info()}
    assert users["alice"]["role"] == "admin"


def test_second_save_user_keeps_user_role(mu_isolated_root):
    from deeptutor.multi_user.identity import list_user_info, save_user

    save_user("alice", "$2b$12$placeholder", role="user")
    save_user("bob", "$2b$12$placeholder", role="user")
    users = {u["username"]: u for u in list_user_info()}
    assert users["alice"]["role"] == "admin"
    assert users["bob"]["role"] == "user"


def test_concurrent_first_save_only_one_admin(mu_isolated_root):
    """``_USERS_WRITE_LOCK`` must serialise read-modify-write so only one
    concurrent first-time registration can flip the empty-store branch."""
    from deeptutor.multi_user.identity import list_user_info, save_user

    def _save(name):
        try:
            save_user(name, "$2b$12$placeholder", role="user")
            return True
        except Exception:
            return False

    names = [f"u{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(_save, names))

    users = list_user_info()
    admins = [u for u in users if u["role"] == "admin"]
    assert len(admins) == 1
    assert len(users) == 8
