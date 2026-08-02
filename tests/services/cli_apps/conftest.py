"""Redirect every root a CLI app touches into ``tmp_path``.

Two roots, because the feature deliberately splits its state across two trees:
installs under ``data/cli-apps`` (the sandbox reads it) and per-account
preferences under ``data/system`` (the sandbox never sees it). A test that
redirected only one would write the other into the developer's real tree — which
the root conftest's guard now fails on rather than allowing silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def cli_app_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from deeptutor.multi_user import paths

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root
