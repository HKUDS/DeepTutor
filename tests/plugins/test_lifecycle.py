"""Offline lifecycle tests for managed plugin wheels."""

from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from deeptutor.plugins.lifecycle import (
    LifecycleResult,
    PluginLifecycleError,
    PluginLifecycleManager,
)
from deeptutor.plugins.manifest import parse_manifest
from deeptutor.plugins.registry import PluginRegistry


def _raw_manifest(version: str = "1.0.0") -> dict:
    return {
        "schema_version": "deeptutor.plugin/v1",
        "id": "org.author.example",
        "name": "Example Plugin",
        "version": version,
        "description_i18n": {"en": "Example"},
        "author": "Author",
        "license": "Apache-2.0",
        "homepage": "https://example.com",
        "source_url": "https://example.com/source",
        "compatibility": {"deeptutor": ">=1.6,<3", "api": {"tool": "1"}},
        "permissions": {"network": []},
        "dependencies": ["helper==2.0"],
        "extensions": [
            {"type": "tool", "id": "example_tool", "entry_point": "example_plugin.worker"}
        ],
    }


def _wheel(tmp_path: Path, version: str) -> Path:
    path = tmp_path / f"example-plugin-{version}-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("example_plugin/deeptutor.plugin.json", json.dumps(_raw_manifest(version)))
        archive.writestr("example_plugin-1.dist-info/METADATA", "Name: example-plugin\n")
    return path


def _manager(tmp_path: Path, *, fail_install: bool = False) -> PluginLifecycleManager:
    registry = PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[],
        deeptutor_version="1.6.0",
    )

    def runner(argv: list[str], *, env=None) -> tuple[int, str]:
        if fail_install and argv[2:4] == ["pip", "install"]:
            return 3, "simulated dependency failure"
        if argv[1:3] == ["-m", "venv"]:
            root = Path(argv[-1])
            (root / "bin").mkdir(parents=True, exist_ok=True)
            python = root / "bin" / "python"
            python.write_text("#!python\n", encoding="utf-8")
            return 0, ""
        return 0, ""

    return PluginLifecycleManager(
        registry,
        root=tmp_path / "plugin-root",
        runner=runner,
    )


def test_install_requires_permission_approval_and_isolates_dependencies(tmp_path) -> None:
    manager = _manager(tmp_path)

    result = manager.install(_wheel(tmp_path, "1.0.0"))

    registry = manager.registry
    record = registry.get_plugin("org.author.example")
    assert result.action == "installed"
    assert record is not None
    assert record.status == "approval-required"
    assert record.installation is not None
    assert record.installation.dependencies == ("helper==2.0",)
    assert record.installation.venv_path.is_dir()
    assert record.installation.artifact_path.is_file()


def test_upgrade_rollback_and_uninstall(tmp_path) -> None:
    manager = _manager(tmp_path)
    manager.install(_wheel(tmp_path, "1.0.0"))
    manager.registry.approve("org.author.example")

    upgraded = manager.install(_wheel(tmp_path, "1.1.0"))
    record = manager.registry.get_plugin("org.author.example")
    assert upgraded.version == "1.1.0"
    assert record is not None
    assert record.status == "approval-required"
    assert record.version == "1.1.0"

    rolled_back = manager.rollback("org.author.example")
    record = manager.registry.get_plugin("org.author.example")
    assert rolled_back.version == "1.0.0"
    assert record is not None
    assert record.version == "1.0.0"
    assert record.status == "approval-required"
    assert (manager.root / "org.author.example" / "versions" / "1.1.0").is_dir()

    uninstalled = manager.uninstall("org.author.example")
    assert uninstalled.action == "uninstalled"
    assert manager.registry.get_plugin("org.author.example") is None
    assert not (manager.root / "org.author.example").exists()


def test_failed_upgrade_preserves_current_version_and_approval(tmp_path) -> None:
    manager = _manager(tmp_path)
    manager.install(_wheel(tmp_path, "1.0.0"))
    manager.registry.approve("org.author.example")

    with pytest.raises(PluginLifecycleError, match="isolated dependency install exited 3"):
        _manager(tmp_path, fail_install=True).install(_wheel(tmp_path, "1.1.0"))

    record = manager.registry.get_plugin("org.author.example")
    assert record is not None
    assert record.version == "1.0.0"
    assert record.status == "enabled"


def test_digest_mismatch_is_rejected_before_install(tmp_path) -> None:
    manager = _manager(tmp_path)
    artifact = _wheel(tmp_path, "1.0.0")

    with pytest.raises(PluginLifecycleError, match="SHA-256"):
        manager.install(artifact, expected_sha256="0" * 64)


def test_manifest_from_wheel_is_parsed_without_importing_plugin(tmp_path) -> None:
    artifact = _wheel(tmp_path, "1.0.0")
    manager = _manager(tmp_path)

    result = manager.install(artifact)

    assert isinstance(result, LifecycleResult)
    record = manager.registry.get_plugin(result.plugin_id)
    assert record is not None and record.manifest is not None
    assert parse_manifest(record.manifest.to_dict()).id == "org.author.example"
