import multiprocessing
from pathlib import Path

from fastapi import HTTPException
import pytest

from deeptutor.api.routers import settings as settings_router
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.grants import save_grant
from deeptutor.multi_user.models import CurrentUser, UserScope


def _hold_grant_file_lock(path: str, ready, release) -> None:
    from deeptutor.multi_user.grants import _grant_write_lock

    with _grant_write_lock(Path(path)):
        ready.set()
        assert release.wait(10)


def _wait_for_grant_file_lock(path: str, attempting, acquired) -> None:
    from deeptutor.multi_user.grants import _grant_write_lock

    attempting.set()
    with _grant_write_lock(Path(path)):
        acquired.set()


def make_user(tmp_path, role="user"):
    uid = "u_admin" if role == "admin" else "u_alice"
    return CurrentUser(
        id=uid,
        username="admin" if role == "admin" else "alice",
        role=role,
        scope=UserScope(
            kind="admin" if role == "admin" else "user", user_id=uid, root=tmp_path / uid
        ),
    )


def test_grants_reject_secret_material(tmp_path, monkeypatch):
    from deeptutor.multi_user import grants, identity

    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "grants")
    monkeypatch.setattr(
        identity, "get_user_by_id", lambda user_id: ("alice", {}) if user_id == "u_alice" else None
    )
    monkeypatch.setattr(
        grants, "get_user_by_id", lambda user_id: ("alice", {}) if user_id == "u_alice" else None
    )

    with pytest.raises(ValueError):
        save_grant("u_alice", {"models": {"llm": [{"profile_id": "p", "api_key": "sk"}]}})


def test_grants_reject_admin_users(tmp_path, monkeypatch):
    from deeptutor.multi_user import grants

    monkeypatch.setattr(grants, "GRANTS_DIR", tmp_path / "grants")
    monkeypatch.setattr(
        grants,
        "get_user_by_id",
        lambda user_id: ("admin", {"role": "admin"}) if user_id == "u_admin" else None,
    )

    with pytest.raises(ValueError, match="Admin users"):
        save_grant("u_admin", {"knowledge_bases": [{"resource_id": "admin:kb:demo"}]})


def test_failed_atomic_grant_replace_preserves_prior_file(mu_isolated_root, seed_user, monkeypatch):
    from deeptutor.multi_user.grants import grant_path, load_grant
    from deeptutor.services import file_io

    seed_user("bootstrap-admin")
    learner = seed_user("student-standard")
    user_id = learner["id"]
    save_grant(user_id, {"enabled_tools": []})
    path = grant_path(user_id)
    previous = path.read_bytes()
    previous_files = set(path.parent.iterdir())

    def fail_replace(_source, _target):
        raise OSError("replace failed")

    monkeypatch.setattr(file_io, "_atomic_replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        save_grant(user_id, {"enabled_tools": ["reason"]})

    assert path.read_bytes() == previous
    assert set(path.parent.iterdir()) == previous_files
    assert load_grant(user_id)["enabled_tools"] == []


@pytest.mark.parametrize(
    "contents",
    [
        "{broken",
        "[]",
        '{"enabled_tools": "reason"}',
        '{"learning_policy": {}}',
        '{"learning_policy": {"reading": {"allow_upload": "false"}}}',
    ],
)
def test_existing_invalid_grant_fails_closed(mu_isolated_root, seed_user, contents):
    from deeptutor.multi_user.grants import GrantStorageError, grant_path, load_grant
    from deeptutor.multi_user.learning_access import learning_policy_for_user

    seed_user("bootstrap-admin")
    learner = seed_user("student-standard")
    path = grant_path(learner["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(GrantStorageError):
        load_grant(learner["id"])
    with pytest.raises(GrantStorageError):
        learning_policy_for_user(learner["id"])


def test_grant_file_lock_serializes_processes(tmp_path):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    attempting = context.Event()
    acquired = context.Event()
    path = str(tmp_path / "grant.json")
    holder = context.Process(target=_hold_grant_file_lock, args=(path, ready, release))
    contender = context.Process(target=_wait_for_grant_file_lock, args=(path, attempting, acquired))
    try:
        holder.start()
        assert ready.wait(10)
        contender.start()
        assert attempting.wait(10)
        assert not acquired.wait(0.2)
        release.set()
        assert acquired.wait(10)
    finally:
        release.set()
        for process in (holder, contender):
            if process.pid is None:
                continue
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
    assert holder.exitcode == 0
    assert contender.exitcode == 0


def test_non_admin_settings_catalog_is_forbidden(tmp_path):
    token = set_current_user(make_user(tmp_path, role="user"))
    try:
        with pytest.raises(HTTPException) as exc:
            settings_router._require_settings_admin()
        assert exc.value.status_code == 403
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
async def test_personal_settings_drafts_are_private_and_do_not_grant_catalog_access(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from deeptutor.services.config.settings_draft import get_settings_draft_service

    monkeypatch.setattr(
        settings_router, "get_model_catalog_service", lambda: SimpleNamespace(load=lambda: {})
    )
    user = make_user(tmp_path, role="user")
    admin = make_user(tmp_path, role="admin")
    token = set_current_user(admin)
    try:
        get_settings_draft_service().save(
            {"extensions": {"mineru": {"api_token": "admin-draft-secret"}}}
        )
    finally:
        reset_current_user(token)
    token = set_current_user(user)
    try:
        assert await settings_router.get_settings_draft() == {"draft": None}
        payload = settings_router.SettingsDraftPayload(extensions={"ui": {"theme": "dark"}})
        saved = await settings_router.update_settings_draft(payload)
        assert saved["draft"]["extensions"] == {"ui": {"theme": "dark"}}
        assert (await settings_router.get_settings_draft())["draft"][
            "extensions"
        ] == payload.extensions
        with pytest.raises(HTTPException) as exc:
            await settings_router.update_settings_draft(
                settings_router.SettingsDraftPayload(catalog={"version": 1})
            )
        assert exc.value.status_code == 403
        await settings_router.discard_settings_draft()
        assert await settings_router.get_settings_draft() == {"draft": None}
    finally:
        reset_current_user(token)
    token = set_current_user(admin)
    try:
        assert (
            get_settings_draft_service().load()["extensions"]["mineru"]["api_token"]
            == "admin-draft-secret"
        )
    finally:
        reset_current_user(token)
