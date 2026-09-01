"""CLI visibility for the unified plugin package registry."""

from __future__ import annotations

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
