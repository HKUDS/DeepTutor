"""Only the lesson page is public, and it is served sandboxed."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.path_service import PathService


def test_only_the_lesson_page_is_public(tmp_path: Path) -> None:
    service = PathService(workspace_root=tmp_path / "data")
    turn = service.get_agent_dir("video_lesson") / "turn-1"
    page = turn / "artifacts" / "lesson.html"
    source = turn / "source" / "Lesson.tsx"
    stray = turn / "artifacts" / "notes.html"
    for path in (page, source, stray):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    assert service.resolve_public_output_path(page) == page.resolve()
    assert service.resolve_public_output_path(source) is None
    assert service.resolve_public_output_path(stray) is None


def test_lesson_page_is_served_sandboxed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import outputs
    from deeptutor.multi_user import paths as multi_user_paths

    admin_root = tmp_path / "data"
    monkeypatch.setattr(multi_user_paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(multi_user_paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(multi_user_paths, "_path_services", {})
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", False)
    service = PathService(workspace_root=admin_root)
    page = service.get_agent_dir("video_lesson") / "turn-1" / "artifacts" / "lesson.html"
    page.parent.mkdir(parents=True)
    page.write_text("<!doctype html><script>1</script>", encoding="utf-8")

    app = FastAPI()
    app.include_router(outputs.router, prefix="/files/outputs")
    rel = page.relative_to(service.get_public_outputs_root()).as_posix()
    response = TestClient(app).get(f"/files/outputs/{rel}")

    assert response.status_code == 200
    assert response.headers["content-security-policy"].startswith("sandbox allow-scripts")
