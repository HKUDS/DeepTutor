"""CLI and launcher home switches must refresh pre-imported account paths."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize("entrypoint", ["deeptutor_cli.init_cmd", "deeptutor.runtime.launcher"])
def test_home_switch_rebinds_existing_account_path_services(tmp_path, monkeypatch, entrypoint):
    from deeptutor.multi_user import paths

    old_home = tmp_path / "old"
    new_home = tmp_path / "new"
    # Restore every modified module cache when the test ends.
    for name, value in {
        "PROJECT_ROOT": old_home,
        "ADMIN_WORKSPACE_ROOT": old_home / "data",
        "USERS_ROOT": old_home / "data" / "users",
        "SYSTEM_ROOT": old_home / "data" / "system",
        "LEGACY_MULTI_USER_ROOT": old_home / "multi-user",
        "_path_services": {},
        "_legacy_migration_done": True,
    }.items():
        monkeypatch.setattr(paths, name, value)
    previous = paths.get_admin_path_service()
    monkeypatch.setenv("DEEPTUTOR_HOME", str(new_home))

    importlib.import_module(entrypoint)._reset_runtime_singletons()

    selected = paths.get_admin_path_service()
    assert selected is not previous
    assert selected.get_settings_file("system.json").is_relative_to(new_home / "data")
    assert paths.SYSTEM_ROOT == new_home / "data" / "system"
    assert paths.USERS_ROOT == new_home / "data" / "users"
    assert paths.LEGACY_MULTI_USER_ROOT == new_home / "multi-user"
    assert paths._legacy_migration_done is False
