"""Where a Codex login is stored on disk — and how an old one gets there.

The sandbox runner bind-mounts the workspace subtrees (``docker-compose.yml``),
and every authenticated account gets ``exec`` by default, so a refresh token
kept inside a user root was readable by every other account. These tests pin
the credential path to ``data/system``, which is never mounted.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from deeptutor.services.codex_auth import service as service_module
from deeptutor.services.codex_auth.storage import CodexCredentialStore

_STORE_FILES = ("credentials.v1.json", "state.v1.json", "models-cache.v1.json", "auth.lock")


@pytest.fixture
def isolated_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect every ``multi_user`` global path under ``tmp_path``.

    Also clears the per-process caches so each test resolves the store from
    scratch instead of inheriting an instance an earlier test created.
    """
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    monkeypatch.setattr(service_module, "_SERVICE_INSTANCES", {})
    monkeypatch.setattr(service_module, "_RELOCATED_SECRET_ROOTS", set())

    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root


@pytest.fixture
def as_learner(isolated_roots: Path):
    """Run the body inside a non-admin scope rooted at ``data/users/<uid>``."""
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    scope = UserScope(kind="user", user_id="u_ada", root=(isolated_roots / "users" / "u_ada"))
    token = set_current_user(
        CurrentUser(id="u_ada", username="ada", role="user", scope=scope),
    )
    try:
        yield scope
    finally:
        reset_current_user(token)


def _seed_store(root: Path) -> Path:
    """Write a full four-file store below *root* and return its directory."""
    store = CodexCredentialStore(root)
    store.root.mkdir(parents=True, exist_ok=True)
    for name in _STORE_FILES:
        (store.root / name).write_text(f"legacy-{name}", encoding="utf-8")
    return store.root


def test_credentials_never_land_in_a_sandbox_mounted_tree(
    isolated_roots: Path,
    as_learner: object,
) -> None:
    store = CodexCredentialStore(service_module._codex_secrets_root())

    assert store.credentials_path.is_relative_to(isolated_roots / "system" / "user-secrets")
    # The two paths ``docker-compose.yml`` bind-mounts into the sandbox runner.
    assert not store.credentials_path.is_relative_to(isolated_roots / "users")
    assert not store.credentials_path.is_relative_to(service_module._codex_user_root())


def test_each_owner_gets_a_distinct_secrets_directory(
    isolated_roots: Path,
    as_learner: object,
) -> None:
    """A token authorizes one person's plan, so the relocation must not pool them."""
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    learner_root = service_module._codex_secrets_root()
    other = UserScope(kind="user", user_id="u_bob", root=(isolated_roots / "users" / "u_bob"))
    token = set_current_user(CurrentUser(id="u_bob", username="bob", role="user", scope=other))
    try:
        assert service_module._codex_secrets_root() != learner_root
    finally:
        reset_current_user(token)


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX permission bits are not authoritative on Windows"
)
def test_secrets_directory_is_owner_only(isolated_roots: Path, as_learner: object) -> None:
    secrets_root = service_module._codex_secrets_root()

    assert stat.S_IMODE(secrets_root.stat().st_mode) == stat.S_IRWXU
    assert stat.S_IMODE(secrets_root.parent.stat().st_mode) == stat.S_IRWXU


def test_partner_turn_uses_its_owner_secrets_directory(isolated_roots: Path) -> None:
    """A partner has a workspace but no account, so it borrows its owner's login."""
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.paths import get_owner_secrets_dir
    from deeptutor.services.partners.scope import partner_user

    owner_secrets = get_owner_secrets_dir()
    token = set_current_user(partner_user("ada"))
    try:
        assert service_module._codex_secrets_root() == owner_secrets
    finally:
        reset_current_user(token)
    assert not owner_secrets.is_relative_to(isolated_roots / "partners")


def test_legacy_login_is_moved_out_of_the_workspace_tree(
    isolated_roots: Path,
    as_learner: object,
) -> None:
    legacy = _seed_store(service_module._codex_user_root())

    secrets_root = service_module._codex_secrets_root()

    moved = CodexCredentialStore(secrets_root).root
    assert {path.name for path in moved.iterdir()} == set(_STORE_FILES)
    assert moved.joinpath("credentials.v1.json").read_text(encoding="utf-8") == (
        "legacy-credentials.v1.json"
    )
    # Copying would leave the plaintext refresh token exactly where it was.
    assert not legacy.exists()


def test_relocation_is_idempotent(isolated_roots: Path, as_learner: object) -> None:
    from deeptutor.multi_user.paths import get_owner_secrets_dir

    user_root = service_module._codex_user_root()
    _seed_store(user_root)
    secrets_root = get_owner_secrets_dir()

    service_module._relocate_legacy_store(user_root, secrets_root)
    service_module._relocate_legacy_store(user_root, secrets_root)

    moved = CodexCredentialStore(secrets_root).root
    assert {path.name for path in moved.iterdir()} == set(_STORE_FILES)


def test_relocation_never_clobbers_a_login_already_at_the_safe_location(
    isolated_roots: Path,
    as_learner: object,
) -> None:
    from deeptutor.multi_user.paths import get_owner_secrets_dir

    user_root = service_module._codex_user_root()
    legacy = _seed_store(user_root)
    secrets_root = get_owner_secrets_dir()
    current = CodexCredentialStore(secrets_root)
    current.root.mkdir(parents=True, exist_ok=True)
    current.credentials_path.write_text("current", encoding="utf-8")

    service_module._relocate_legacy_store(user_root, secrets_root)

    assert current.credentials_path.read_text(encoding="utf-8") == "current"
    assert legacy.exists()


def test_relocation_ignores_a_symlinked_legacy_directory(
    isolated_roots: Path,
    as_learner: object,
) -> None:
    """The legacy path sits in a subtree the sandbox can write, so links are not followed."""
    from deeptutor.multi_user.paths import get_owner_secrets_dir

    user_root = service_module._codex_user_root()
    outside = _seed_store(isolated_roots / "elsewhere")
    legacy = CodexCredentialStore(user_root).root
    legacy.parent.mkdir(parents=True, exist_ok=True)
    try:
        legacy.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")
    secrets_root = get_owner_secrets_dir()

    service_module._relocate_legacy_store(user_root, secrets_root)

    assert not CodexCredentialStore(secrets_root).root.exists()
    assert {path.name for path in outside.iterdir()} == set(_STORE_FILES)


def test_relocation_refuses_a_symlinked_private_parent(
    isolated_roots: Path,
    as_learner: object,
) -> None:
    """Checking only the leaf is not enough — the parent is the attack.

    ``private/`` is inside the subtree every account's sandboxed ``exec`` can
    write. Pointing one's own ``private/`` at another account's would otherwise
    relocate the victim's store into the attacker's secrets directory, where the
    server then uses it as the attacker's login (and the victim is logged out).
    """
    from deeptutor.multi_user.paths import get_owner_secrets_dir

    victim_store = _seed_store(isolated_roots / "users" / "u_victim" / "user")
    attacker_root = service_module._codex_user_root()
    attacker_private = CodexCredentialStore(attacker_root).root.parent
    attacker_private.parent.mkdir(parents=True, exist_ok=True)
    try:
        attacker_private.symlink_to(victim_store.parent, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")
    secrets_root = get_owner_secrets_dir()

    service_module._relocate_legacy_store(attacker_root, secrets_root)

    assert not CodexCredentialStore(secrets_root).root.exists()
    assert (victim_store / "credentials.v1.json").read_text(encoding="utf-8") == (
        "legacy-credentials.v1.json"
    )


def test_each_account_gets_its_own_secrets_directory_even_via_a_symlinked_root(
    isolated_roots: Path,
    as_learner: object,
) -> None:
    """Identity comes from the account, never from reversing a resolved path.

    An operator moving one user's workspace to another disk makes
    ``data/users/<uid>`` a symlink. Recovering the owner by resolving that path
    and relative-ising it against ``data/users`` then fails — and failing open
    onto the admin id would pool every account onto the admin's directory.
    """
    from deeptutor.multi_user.paths import get_owner_secrets_dir

    users_root = isolated_roots / "users"
    users_root.mkdir(parents=True, exist_ok=True)
    elsewhere = (isolated_roots / "elsewhere" / "u_ada").resolve()
    elsewhere.mkdir(parents=True, exist_ok=True)
    try:
        (users_root / "u_ada").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this platform")

    assert get_owner_secrets_dir().name == "u_ada"


def test_relocation_failure_is_retried_on_the_next_resolution(
    isolated_roots: Path,
    as_learner: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed move must not be remembered as done.

    Memoising it would leave the token in the sandbox-visible tree while the
    account reads as signed out, with no further attempt for the process's life.
    """
    _seed_store(service_module._codex_user_root())

    # A togglable failure rather than ``monkeypatch.undo()``: the fixtures above
    # share this test's monkeypatch instance, so undoing would also revert their
    # root redirection — and the second half of the test would then write into
    # the developer's real ``data/system``.
    failing = {"on": True}
    real_move = service_module.shutil.move

    def _move(*args: object, **kwargs: object) -> object:
        if failing["on"]:
            raise OSError("permission denied")
        return real_move(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service_module.shutil, "move", _move)
    service_module._codex_secrets_root()
    assert service_module._RELOCATED_SECRET_ROOTS == set()

    failing["on"] = False
    secrets_root = service_module._codex_secrets_root()
    assert CodexCredentialStore(secrets_root).credentials_path.exists()
    assert service_module._RELOCATED_SECRET_ROOTS == {str(secrets_root)}
