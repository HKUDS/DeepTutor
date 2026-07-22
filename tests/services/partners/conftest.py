"""Fixtures for the partners service suite — isolate all paths under tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def partners_root(tmp_path, monkeypatch) -> Path:
    """Redirect the admin workspace (and multi-user roots) under ``tmp_path``.

    Everything the partners layer touches resolves through
    ``deeptutor.multi_user.paths`` — the partners data dir is anchored at the
    admin workspace root and partner scopes are synthetic ``UserScope``s — so
    patching that module is sufficient to keep tests off the real ``data/``.
    """
    from deeptutor.multi_user import paths

    project_root = tmp_path
    admin_root = (project_root / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})

    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root / "partners"
