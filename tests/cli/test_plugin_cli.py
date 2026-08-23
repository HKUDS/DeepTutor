"""CLI visibility for the fork-local Kids reward extension point."""

from __future__ import annotations

from types import SimpleNamespace

import typer
from typer.testing import CliRunner

import deeptutor.kids_rewards as kids_rewards
import deeptutor.runtime.registry.capability_registry as capability_registry
import deeptutor.runtime.registry.tool_registry as tool_registry
from deeptutor_cli.plugin import register


def _provider(name: str = "stars") -> SimpleNamespace:
    return SimpleNamespace(name=name, version="1.2.3")


def _register_cli(monkeypatch, providers):
    monkeypatch.setattr(
        tool_registry,
        "get_tool_registry",
        lambda: SimpleNamespace(get_definitions=lambda: [], get=lambda _name: None),
    )
    monkeypatch.setattr(
        capability_registry,
        "get_capability_registry",
        lambda: SimpleNamespace(get_manifests=lambda: [], get=lambda _name: None),
    )
    monkeypatch.setattr(kids_rewards, "get_kids_reward_providers", lambda: providers)
    monkeypatch.setattr(
        kids_rewards, "active_kids_reward_provider", lambda: providers[0] if providers else None
    )
    app = typer.Typer()
    register(app)
    return app


def test_plugin_list_marks_kids_reward_provider_fork_local(monkeypatch):
    app = _register_cli(monkeypatch, [_provider()])

    result = CliRunner().invoke(app, ["list"])

    assert result.exit_code == 0, result.output
    assert "stars" in result.output
    assert "fork-local kids reward" in result.output
    assert "active" in result.output


def test_plugin_info_describes_kids_reward_contract(monkeypatch):
    provider = _provider()
    app = _register_cli(monkeypatch, [provider])

    result = CliRunner().invoke(app, ["info", "stars"])

    assert result.exit_code == 0, result.output
    assert '"entry_point_group": "deeptutor.kids_reward_providers"' in result.output
    assert '"scope": "fork-local"' in result.output
    assert '"interface": [' in result.output
