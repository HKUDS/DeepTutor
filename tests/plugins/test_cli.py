"""CLI visibility for the unified plugin package registry."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import typer
from typer.testing import CliRunner

import deeptutor.plugins.catalog as plugin_catalog
import deeptutor.plugins.registry as plugin_registry
from deeptutor_cli.plugin import register


def _plugin_cli(monkeypatch) -> typer.Typer:
    app = typer.Typer()
    register(app)
    return app


def test_plugin_state_lists_package_status(monkeypatch) -> None:
    monkeypatch.setattr(
        plugin_registry,
        "get_plugin_registry",
        lambda: SimpleNamespace(
            list_plugins=lambda: [
                SimpleNamespace(
                    id="org.author.example",
                    version="1.0.0",
                    status="enabled",
                    description="Example package",
                )
            ]
        ),
    )
    app = _plugin_cli(monkeypatch)

    result = CliRunner().invoke(app, ["state"])

    assert result.exit_code == 0, result.output
    assert "org.author.example" in result.output
    assert "enabled" in result.output


def test_plugin_search_uses_official_catalog(monkeypatch) -> None:
    monkeypatch.setattr(
        plugin_catalog,
        "search_catalog",
        lambda query: [
            SimpleNamespace(
                id="org.author.example",
                version="1.0.0",
                status="available",
                description_i18n={"en": "Example package"},
            )
        ],
    )
    app = _plugin_cli(monkeypatch)

    result = CliRunner().invoke(app, ["search", "example"])

    assert result.exit_code == 0, result.output
    assert "org.author.example" in result.output
    assert "available" in result.output


def test_plugin_disable_and_enable_write_state(monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []

    def set_enabled(plugin_id: str, enabled: bool):
        calls.append((plugin_id, enabled))
        return SimpleNamespace(id=plugin_id, status="enabled" if enabled else "disabled")

    monkeypatch.setattr(
        plugin_registry,
        "get_plugin_registry",
        lambda: SimpleNamespace(set_enabled=set_enabled),
    )
    app = _plugin_cli(monkeypatch)

    disabled = CliRunner().invoke(app, ["disable", "org.author.example"])
    enabled = CliRunner().invoke(app, ["enable", "org.author.example"])

    assert disabled.exit_code == 0, disabled.output
    assert enabled.exit_code == 0, enabled.output
    assert calls == [("org.author.example", False), ("org.author.example", True)]


def test_plugin_show_outputs_package_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        plugin_registry,
        "get_plugin_registry",
        lambda: SimpleNamespace(
            get_plugin=lambda plugin_id: SimpleNamespace(
                to_dict=lambda: {
                    "id": plugin_id,
                    "status": "enabled",
                    "manifest": {"schema_version": "deeptutor.plugin/v1"},
                }
            )
        ),
    )
    app = _plugin_cli(monkeypatch)

    result = CliRunner().invoke(app, ["show", "org.author.example"])

    assert result.exit_code == 0, result.output
    assert '"schema_version": "deeptutor.plugin/v1"' in result.output


def test_plugin_approve_writes_permission_state(monkeypatch) -> None:
    calls: list[str] = []

    def approve(plugin_id: str):
        calls.append(plugin_id)
        return SimpleNamespace(id=plugin_id, status="enabled")

    monkeypatch.setattr(
        plugin_registry,
        "get_plugin_registry",
        lambda: SimpleNamespace(approve=approve),
    )
    app = _plugin_cli(monkeypatch)

    result = CliRunner().invoke(app, ["approve", "org.author.example"])

    assert result.exit_code == 0, result.output
    assert calls == ["org.author.example"]
    assert "permissions approved" in result.output


def test_plugin_install_reports_reviewed_wheel(monkeypatch) -> None:
    calls: list[tuple[Path, str]] = []

    class FakeManager:
        def install(self, artifact: Path, *, expected_sha256: str):
            calls.append((artifact, expected_sha256))
            return SimpleNamespace(
                plugin_id="org.author.example",
                version="1.0.0",
                action="installed",
                artifact_sha256="0" * 64,
                venv_path=Path("/tmp/plugins/org.author.example/versions/1.0.0/venv"),
            )

    monkeypatch.setattr("deeptutor.plugins.lifecycle.PluginLifecycleManager", FakeManager)
    app = _plugin_cli(monkeypatch)

    result = CliRunner().invoke(
        app,
        [
            "install",
            "/tmp/example-1.0.0.whl",
            "--sha256",
            "0" * 64,
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [(Path("/tmp/example-1.0.0.whl"), "0" * 64)]
    assert '"plugin": "org.author.example"' in result.output
    assert '"next_step": "review permissions' in result.output


def test_plugin_rollback_and_uninstall_use_managed_lifecycle(monkeypatch) -> None:
    actions: list[str] = []

    class FakeManager:
        def rollback(self, plugin_id: str):
            actions.append(("rollback", plugin_id))
            return SimpleNamespace(
                plugin_id=plugin_id,
                version="1.0.0",
                artifact_sha256="0" * 64,
                venv_path=Path("/tmp/plugins/org.author.example/versions/1.0.0/venv"),
            )

        def uninstall(self, plugin_id: str):
            actions.append(("uninstall", plugin_id))
            return SimpleNamespace(
                plugin_id=plugin_id,
                version="1.1.0",
                artifact_sha256="0" * 64,
                venv_path=Path("/tmp/plugins/org.author.example"),
            )

    monkeypatch.setattr("deeptutor.plugins.lifecycle.PluginLifecycleManager", FakeManager)
    app = _plugin_cli(monkeypatch)

    rollback = CliRunner().invoke(app, ["rollback", "org.author.example"])
    uninstall = CliRunner().invoke(app, ["uninstall", "org.author.example"])

    assert rollback.exit_code == 0, rollback.output
    assert uninstall.exit_code == 0, uninstall.output
    assert actions == [
        ("rollback", "org.author.example"),
        ("uninstall", "org.author.example"),
    ]
    assert "rolled back to 1.0.0" in rollback.output
    assert "1.1.0 removed" in uninstall.output
