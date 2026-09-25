"""Regression tests for learner surfaces and restriction preset changes.

Two failure modes covered:

1. Knowledge Center browsing needs a precise GET allowlist. Admin diagnostics
   and engine configuration endpoints share the same URL prefix.
2. Assigning guardian restrictions to a `standard`-preset account left the
   account in a `standard` preset + `learning_policy` mix: the frontend then
   rendered the full admin shell and every surface request 403'd. The PUT
   restrictions handler now seeds the default policy and flips the preset to
   ``learner``.
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.auth import _learning_surface_for_path


@pytest.mark.parametrize(
    ("path", "method", "expected"),
    [
        # Pre-existing mappings keep working.
        ("/api/reading/materials", "GET", "reading"),
        ("/api/courses", "GET", "reading"),
        ("/api/chat/sessions", "GET", "chat"),
        ("/api/question/generate", "POST", "chat"),
        ("/api/sessions/abc", "GET", "chat"),
        # Mastery Path: the learner's own per-user progress, all methods.
        ("/api/mastery-paths/topics", "GET", "chat"),
        ("/api/mastery-paths/topics/index", "GET", "chat"),
        ("/api/mastery-paths/progress/book-1", "GET", "chat"),
        ("/api/mastery-paths/progress/book-1", "PATCH", "chat"),
        ("/api/mastery-paths/progress/book-1/redo", "POST", "chat"),
        # KB writes stay denied, even when the route is otherwise browsable.
        ("/api/knowledge-bases", "POST", ""),
        ("/api/knowledge-bases/kb1/upload", "POST", ""),
        ("/api/knowledge-bases/kb1/files/a.pdf", "DELETE", ""),
        # Everything else still default-denies.
        ("/api/settings", "GET", ""),
        ("/api/system/status", "GET", ""),
        ("/api/partners", "GET", ""),
        ("/api/memory/overview", "GET", ""),
        ("", "GET", ""),
    ],
)
def test_learning_surface_map(path: str, method: str, expected: str) -> None:
    assert _learning_surface_for_path(path, method) == expected


@pytest.mark.parametrize(
    ("path", "route_path", "expected"),
    [
        ("/api/knowledge-bases", "/api/knowledge-bases", "reading"),
        ("/api/knowledge-bases/kb1", "/api/knowledge-bases/{kb_name}", "reading"),
        ("/api/knowledge-bases/kb1/files", "/api/knowledge-bases/{kb_name}/files", "reading"),
        (
            "/api/knowledge-bases/kb1/files/a.pdf",
            "/api/knowledge-bases/{kb_name}/files/{filename:path}",
            "reading",
        ),
        (
            "/api/knowledge-bases/kb1/file-preview-text/a.pdf",
            "/api/knowledge-bases/{kb_name}/file-preview-text/{filename:path}",
            "reading",
        ),
        ("/api/knowledge-bases/kb1/progress", "/api/knowledge-bases/{kb_name}/progress", "reading"),
        ("/api/knowledge-bases/health", "/api/knowledge-bases/health", ""),
        ("/api/knowledge-bases/configs", "/api/knowledge-bases/configs", ""),
        ("/api/knowledge-bases/default", "/api/knowledge-bases/default", ""),
        (
            "/api/knowledge-bases/rag-pipelines/lightrag/config",
            "/api/knowledge-bases/rag-pipelines/lightrag/config",
            "",
        ),
        ("/api/knowledge-bases/kb1/config", "/api/knowledge-bases/{kb_name}/config", ""),
        (
            "/api/knowledge-bases/kb1/reindex-config",
            "/api/knowledge-bases/{kb_name}/reindex-config",
            "",
        ),
        (
            "/api/knowledge-bases/kb1/linked-folders",
            "/api/knowledge-bases/{kb_name}/linked-folders",
            "",
        ),
        (
            "/api/knowledge-bases/kb1/github-sources",
            "/api/knowledge-bases/{kb_name}/github-sources",
            "",
        ),
        (
            "/api/knowledge-bases/kb1/web-sources",
            "/api/knowledge-bases/{kb_name}/web-sources",
            "",
        ),
    ],
)
def test_learner_kb_get_allowlist(path: str, route_path: str, expected: str) -> None:
    assert _learning_surface_for_path(path, "GET", route_path=route_path) == expected
    if expected:
        assert _learning_surface_for_path(path, "HEAD", route_path=route_path) == ""
        assert _learning_surface_for_path(path, "OPTIONS", route_path=route_path) == ""
        assert _learning_surface_for_path(path, "POST", route_path=route_path) == ""
        assert _learning_surface_for_path(path, "GET") == ""


def test_route_template_is_passed_to_surface_guard(monkeypatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from deeptutor.api.routers.auth import require_learning_surface
    from deeptutor.multi_user import learning_access

    observed = []
    monkeypatch.setattr(learning_access, "assert_learning_surface", observed.append)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/knowledge-bases/health",
        "headers": [],
        "route": SimpleNamespace(path="/api/knowledge-bases/health"),
    }
    asyncio.run(require_learning_surface(Request(scope), None))
    assert observed == [""]


def test_fastapi_guard_denies_kb_diagnostics_but_allows_browsing(monkeypatch) -> None:
    from deeptutor.api.routers.auth import require_auth, require_learning_surface
    from deeptutor.multi_user import learning_access

    def deny_unmapped(surface: str) -> None:
        if not surface:
            raise PermissionError("denied")

    monkeypatch.setattr(learning_access, "assert_learning_surface", deny_unmapped)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: None

    @app.get("/api/knowledge-bases/health", dependencies=[Depends(require_learning_surface)])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/knowledge-bases/{kb_name}", dependencies=[Depends(require_learning_surface)])
    def details(kb_name: str) -> dict[str, str]:
        return {"name": kb_name}

    client = TestClient(app)
    assert client.get("/api/knowledge-bases/health").status_code == 403
    assert client.get("/api/knowledge-bases/kb1").json() == {"name": "kb1"}


def test_put_restrictions_flips_standard_preset_to_learner(
    mu_isolated_root, seed_user, monkeypatch
):
    """PUT restrictions on a standard-preset account seeds the policy and
    flips the account preset to ``learner`` (#1222 preset/policy mix)."""
    import asyncio
    from types import SimpleNamespace

    from deeptutor.api.routers import multi_user
    from deeptutor.api.routers.multi_user import (
        GuardianRestrictionsPayload,
        put_guardian_restrictions,
    )
    from deeptutor.multi_user.grants import load_grant
    from deeptutor.multi_user.identity import get_user_by_id

    # The first account in an empty store is promoted to admin by save_user;
    # seed a bootstrap account first so the learner keeps role="user".
    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    learner_user_id = record["id"]
    admin = SimpleNamespace(user_id="u_admin", role="admin")

    payload = GuardianRestrictionsPayload(
        age_band="13-15",
        allow_upload=True,
        allowed_surfaces=["chat", "reading"],
        extensions=[],
    )

    original_set_preset = multi_user.set_preset

    def set_preset_after_grant(
        username: str, preset: str, *, expected_user_id: str | None = None
    ) -> bool:
        assert load_grant(learner_user_id)["learning_policy"]["age_band"] == "13-15"
        assert expected_user_id == learner_user_id
        return original_set_preset(username, preset, expected_user_id=expected_user_id)

    monkeypatch.setattr(multi_user, "set_preset", set_preset_after_grant)

    result = asyncio.run(put_guardian_restrictions(learner_user_id, payload, admin))
    assert result["restrictions"]["age_band"] == "13-15"

    _username, updated = get_user_by_id(learner_user_id)
    assert updated.get("preset") == "learner"


def test_failed_grant_save_does_not_change_standard_preset(
    mu_isolated_root, seed_user, monkeypatch
) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from deeptutor.api.routers import multi_user
    from deeptutor.multi_user.grants import load_grant
    from deeptutor.multi_user.identity import get_user_by_id

    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    learner_user_id = record["id"]
    payload = multi_user.GuardianRestrictionsPayload(
        age_band="13-15",
        allow_upload=True,
        allowed_surfaces=["chat", "reading"],
        extensions=[],
    )

    def fail_save_grant(*_args, **_kwargs):
        raise ValueError("Grant store unavailable")

    monkeypatch.setattr(multi_user, "save_grant_with_receipt", fail_save_grant)
    with pytest.raises(HTTPException, match="Grant store unavailable"):
        asyncio.run(
            multi_user.put_guardian_restrictions(
                learner_user_id, payload, SimpleNamespace(user_id="u_admin", role="admin")
            )
        )

    _username, updated = get_user_by_id(learner_user_id)
    assert updated.get("preset") == "standard"
    assert load_grant(learner_user_id).get("learning_policy") is None


def test_failed_grant_io_reports_error_without_preset_change(
    mu_isolated_root, seed_user, monkeypatch
) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from deeptutor.api.routers import multi_user
    from deeptutor.multi_user import grants
    from deeptutor.multi_user.identity import get_user_by_id

    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    learner_user_id = record["id"]
    payload = multi_user.GuardianRestrictionsPayload(
        age_band="13-15",
        allow_upload=True,
        allowed_surfaces=["chat", "reading"],
        extensions=[],
    )

    def fail_write(_path, _text):
        raise OSError("grant storage unavailable")

    monkeypatch.setattr(grants, "atomic_write_text", fail_write)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            multi_user.put_guardian_restrictions(
                learner_user_id, payload, SimpleNamespace(user_id="u_admin", role="admin")
            )
        )

    assert error.value.status_code == 500
    assert error.value.detail == "Learner grant could not be saved"
    _username, updated = get_user_by_id(learner_user_id)
    assert updated["preset"] == "standard"
    assert not grants.grant_path(learner_user_id).exists()


@pytest.mark.parametrize(
    ("preset_failure", "existing_grant", "status_code"),
    [("returns_false", True, 409), ("raises", False, 500)],
)
def test_failed_preset_update_restores_previous_grant(
    mu_isolated_root,
    seed_user,
    monkeypatch,
    preset_failure: str,
    existing_grant: bool,
    status_code: int,
) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from deeptutor.api.routers import multi_user
    from deeptutor.multi_user.grants import grant_path, load_grant, save_grant
    from deeptutor.multi_user.identity import get_user_by_id

    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    learner_user_id = record["id"]
    if existing_grant:
        save_grant(learner_user_id, {"enabled_tools": ["reason"]})
    path = grant_path(learner_user_id)
    previous_grant_text = path.read_text(encoding="utf-8") if path.exists() else None
    payload = multi_user.GuardianRestrictionsPayload(
        age_band="13-15",
        allow_upload=True,
        allowed_surfaces=["chat", "reading"],
        extensions=[],
    )

    def fail_set_preset(
        _username: str, _preset: str, *, expected_user_id: str | None = None
    ) -> bool:
        assert expected_user_id == learner_user_id
        assert load_grant(learner_user_id)["learning_policy"]["age_band"] == "13-15"
        if preset_failure == "raises":
            raise OSError("users file is unavailable")
        return False

    monkeypatch.setattr(multi_user, "set_preset", fail_set_preset)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            multi_user.put_guardian_restrictions(
                learner_user_id,
                payload,
                SimpleNamespace(user_id="u_admin", role="admin"),
            )
        )

    assert error.value.status_code == status_code
    assert "prior grant was restored" in error.value.detail
    _username, updated = get_user_by_id(learner_user_id)
    assert updated["preset"] == "standard"
    if previous_grant_text is None:
        assert not path.exists()
    else:
        assert path.read_text(encoding="utf-8") == previous_grant_text


@pytest.mark.parametrize("newer_age_band", ["6-8", "13-15"])
def test_preset_failure_keeps_a_later_grant_write(
    mu_isolated_root, seed_user, monkeypatch, newer_age_band: str
) -> None:
    import asyncio
    from threading import Thread
    from types import SimpleNamespace

    from fastapi import HTTPException

    from deeptutor.api.routers import multi_user
    from deeptutor.multi_user.grants import load_grant, save_grant
    from deeptutor.multi_user.identity import get_user_by_id

    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    learner_user_id = record["id"]
    payload = multi_user.GuardianRestrictionsPayload(
        age_band="13-15",
        allow_upload=True,
        allowed_surfaces=["chat", "reading"],
        extensions=[],
    )
    writer_errors: list[Exception] = []

    def write_newer_grant() -> None:
        try:
            changed = load_grant(learner_user_id)
            changed["learning_policy"]["age_band"] = newer_age_band
            save_grant(learner_user_id, changed)
        except Exception as exc:
            writer_errors.append(exc)

    def fail_set_preset(
        _username: str, _preset: str, *, expected_user_id: str | None = None
    ) -> bool:
        assert expected_user_id == learner_user_id
        writer = Thread(target=write_newer_grant, daemon=True)
        writer.start()
        writer.join(timeout=5)
        assert not writer.is_alive()
        assert not writer_errors
        return False

    monkeypatch.setattr(multi_user, "set_preset", fail_set_preset)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            multi_user.put_guardian_restrictions(
                learner_user_id, payload, SimpleNamespace(user_id="u_admin", role="admin")
            )
        )

    assert error.value.status_code == 409
    assert "later grant change was preserved" in error.value.detail
    assert load_grant(learner_user_id)["learning_policy"]["age_band"] == newer_age_band
    _username, updated = get_user_by_id(learner_user_id)
    assert updated["preset"] == "standard"


def test_failed_grant_rollback_reports_storage_error(
    mu_isolated_root, seed_user, monkeypatch
) -> None:
    import asyncio
    from types import SimpleNamespace

    from fastapi import HTTPException

    from deeptutor.api.routers import multi_user
    from deeptutor.multi_user import grants

    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    learner_user_id = record["id"]
    grants.save_grant(learner_user_id, {"enabled_tools": []})
    payload = multi_user.GuardianRestrictionsPayload(
        age_band="13-15",
        allow_upload=True,
        allowed_surfaces=["chat", "reading"],
        extensions=[],
    )
    original_write = grants.atomic_write_text
    write_count = 0

    def fail_rollback(path, text):
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise OSError("rollback unavailable")
        return original_write(path, text)

    monkeypatch.setattr(grants, "atomic_write_text", fail_rollback)
    monkeypatch.setattr(multi_user, "set_preset", lambda *_args, **_kwargs: False)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            multi_user.put_guardian_restrictions(
                learner_user_id, payload, SimpleNamespace(user_id="u_admin", role="admin")
            )
        )

    assert error.value.status_code == 500
    assert "could not be restored" in error.value.detail
    assert write_count == 2


def test_set_preset_checks_expected_user_id(mu_isolated_root, seed_user) -> None:
    from deeptutor.multi_user.identity import get_user_by_id, set_preset

    seed_user("bootstrap-admin")
    record = seed_user("student-standard")
    assert set_preset("student-standard", "learner", expected_user_id="different") is False
    _username, unchanged = get_user_by_id(record["id"])
    assert unchanged["preset"] == "standard"
