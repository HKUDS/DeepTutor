"""Review, revocation, recovery and bounded execution workflows (#1307)."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from deeptutor.plugins.registry import PluginStateError
from deeptutor.plugins.runtime import PluginRuntimeError
from tests.plugins.test_lifecycle import _manager, _wheel
from tests.plugins.test_registry_gating import _EchoTool, _patch_entry_points, _plugin_registry


def test_external_upgrade_requires_review_even_when_permissions_are_unchanged(tmp_path):
    registry = _plugin_registry(tmp_path)
    registry.approve("org.author.gated")
    source = tmp_path / "package" / "deeptutor.plugin.json"
    manifest = json.loads(source.read_text())
    manifest["version"] = "1.1.0"
    source.write_text(json.dumps(manifest))
    record = registry.get_plugin("org.author.gated")
    assert record.version == "1.1.0" and record.status == "approval-required"
    original = registry.state_path.read_bytes()
    with pytest.raises(PluginStateError, match="snapshot changed"):
        registry.approve(record.id, expected_digest="0" * 64)
    assert registry.state_path.read_bytes() == original


@pytest.mark.asyncio
async def test_unapproved_entry_point_never_imports_and_cached_tool_remains_revocable(
    tmp_path, monkeypatch
):
    import deeptutor.plugins.entry_points as loader
    from deeptutor.plugins.entry_points import load_entry_point_group
    import deeptutor.plugins.runtime as runtime

    registry = _plugin_registry(tmp_path)
    monkeypatch.setattr(runtime, "get_plugin_registry", lambda: registry)
    calls = []
    ep = SimpleNamespace(name="declared_tool", load=lambda: calls.append("import") or _EchoTool)
    monkeypatch.setattr(loader, "entry_points", lambda **kwargs: [ep])
    assert not load_entry_point_group("deeptutor.tools", lambda name, target: target())
    assert not calls
    registry.approve("org.author.gated")
    tool = load_entry_point_group("deeptutor.tools", lambda name, target: target())[0]
    assert (await tool.execute()).content == "ok"
    registry.set_enabled("org.author.gated", False)
    with pytest.raises(PluginRuntimeError, match="disabled"):
        await tool.execute()


def test_corrupt_state_never_becomes_an_empty_writable_registry(tmp_path):
    manager = _manager(tmp_path)
    manager.registry.state_path.write_bytes(b"{broken")
    with pytest.raises(PluginStateError, match="preserved"):
        manager.install(_wheel(tmp_path, "1.0.0"))
    assert manager.registry.state_path.read_bytes() == b"{broken"


def test_failed_same_version_reinstall_preserves_current_environment_and_artifact(tmp_path):
    manager = _manager(tmp_path)
    artifact = _wheel(tmp_path, "1.0.0")
    manager.install(artifact)
    manager.registry.approve("org.author.example")
    record = manager.registry.get_plugin("org.author.example")
    before = record.installation.artifact_path.read_bytes()
    sentinel = record.installation.venv_path / "retained.txt"
    sentinel.write_text("old environment")
    with pytest.raises(Exception, match="install exited"):
        _manager(tmp_path, fail_install=True).install(artifact, allow_reinstall=True)
    assert sentinel.read_text() == "old environment"
    assert record.installation.artifact_path.read_bytes() == before
    assert manager.registry.get_plugin(record.id).status == "enabled"


def test_rollback_requires_the_retained_artifact_to_match_its_pin(tmp_path):
    manager = _manager(tmp_path)
    manager.install(_wheel(tmp_path, "1.0.0"))
    manager.install(_wheel(tmp_path, "1.1.0"))
    state = manager.registry.state_snapshot()
    original = manager.registry.state_path.read_bytes()
    Path(
        state["plugins"]["org.author.example"]["history"][0]["installation"]["artifact_path"]
    ).write_bytes(b"tampered")
    with pytest.raises(Exception, match="SHA-256"):
        manager.rollback("org.author.example")
    assert manager.registry.state_path.read_bytes() == original


def test_worker_output_is_bounded_while_the_child_is_running(tmp_path):
    from deeptutor.plugins.runtime import _run_worker

    with pytest.raises(PluginRuntimeError, match="budget"):
        _run_worker(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 3000000)"],
            input="{}",
            cwd=tmp_path,
            env={},
        )


def test_frontend_total_size_is_checked_beyond_the_requested_asset(tmp_path):
    from deeptutor.plugins.frontend import (
        FrontendPageError,
        parse_frontend_page_manifest,
        resolve_frontend_page_asset,
    )

    page = parse_frontend_page_manifest(
        {
            "schema_version": "deeptutor.plugin-frontend-page/v1",
            "entry": "index.html",
            "assets": ["index.html", "huge.js"],
        }
    )
    (tmp_path / "index.html").write_text("ok")
    with (tmp_path / "huge.js").open("wb") as handle:
        handle.truncate(6 * 1024 * 1024)
    with pytest.raises(FrontendPageError, match="5 MiB"):
        resolve_frontend_page_asset(page, tmp_path, "index.html")


def test_corrupt_plugin_state_blocks_plugins_without_hiding_builtins(tmp_path, monkeypatch):
    import deeptutor.plugins.runtime as runtime
    from deeptutor.runtime.registry.capability_registry import CapabilityRegistry

    registry = _plugin_registry(tmp_path)
    registry.state_path.write_text("{broken")
    monkeypatch.setattr(runtime, "get_plugin_registry", lambda: registry)
    capabilities = CapabilityRegistry()
    capabilities.load_builtins()
    assert "chat" in capabilities.list_capabilities()
    assert not runtime.load_enabled_workers(registry)
    assert registry.state_path.read_text() == "{broken"
