"""Entry-point loading must honor approved manifest state."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.registry import discover_external_loop_capabilities
from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import UnifiedContext
import deeptutor.core.entry_points as entry_points
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolResult
from deeptutor.plugins.registry import PluginRegistry
from deeptutor.reading.extensions import ReadingExtensionRegistry
from deeptutor.reading.translation import TranslationExtension
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.runtime.stream_bus import StreamBus


class _EchoTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(name="declared_tool", description="Declared tool")

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(content="ok")


class _EchoCapability(TurnCapability):
    manifest = CapabilityManifest(name="declared_capability", description="Declared")

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None


class _DemoLoop:
    name = "demo_loop"
    owned_tools = ()

    def is_active(self, _context) -> bool:
        return False

    def system_block(self, _context, *, language, prompts):
        return None

    def augment_kwargs(self, _tool_name, kwargs, _context):
        return kwargs

    def pre_loop_seed(self, _context):
        return ""


def _plugin_registry(tmp_path: Path, extensions: list[dict] | None = None) -> PluginRegistry:
    manifest = {
        "schema_version": "deeptutor.plugin/v1",
        "id": "org.author.gated",
        "name": "Gated",
        "version": "1.0.0",
        "description_i18n": {"en": "Gated"},
        "author": "Author",
        "license": "Apache-2.0",
        "homepage": "https://example.com",
        "source_url": "https://example.com/source",
        "compatibility": {"deeptutor": ">=1.6,<3", "api": {"tool": "1", "capability": "1"}},
        "permissions": {"network": []},
        "dependencies": [],
        "extensions": [
            {"type": "tool", "id": "declared_tool", "entry_point": "declared_tool"},
            {
                "type": "capability",
                "id": "declared_capability",
                "entry_point": "declared_capability",
            },
        ],
    }
    package = tmp_path / "package"
    package.mkdir()
    if extensions is not None:
        manifest["extensions"] = extensions
        manifest["compatibility"]["api"] = {
            extension["type"]: "1" for extension in extensions
        }
    package.joinpath("deeptutor.plugin.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    file_ref = SimpleNamespace(name="deeptutor.plugin.json", path="deeptutor.plugin.json")
    dist = SimpleNamespace(
        files=[file_ref],
        locate_file=lambda ref: package / ref.path,
        metadata={"Name": "gated-plugin"},
    )
    return PluginRegistry(
        state_path=tmp_path / "plugins.json",
        installed_distributions=[dist],
        deeptutor_version="1.6.0",
    )


def _patch_plugin_registry(monkeypatch, registry: PluginRegistry) -> None:
    monkeypatch.setattr("deeptutor.plugins.registry.PluginRegistry", lambda: registry)
    monkeypatch.setattr(
        "deeptutor.plugins.runtime.load_enabled_tools", lambda _registry: ()
    )
    monkeypatch.setattr(
        "deeptutor.plugins.runtime.load_enabled_capabilities",
        lambda _registry: (),
    )


def _patch_entry_points(monkeypatch, expected_group: str, name: str, loaded) -> None:
    def fake_entry_points(*, group: str):
        assert group == expected_group
        return [SimpleNamespace(name=name, load=lambda: loaded)]

    monkeypatch.setattr(entry_points, "entry_points", fake_entry_points)


def test_tool_entry_point_waits_for_approval(monkeypatch, tmp_path) -> None:
    registry = _plugin_registry(tmp_path)
    _patch_plugin_registry(monkeypatch, registry)
    _patch_entry_points(
        monkeypatch, "deeptutor.tools", "declared_tool", _EchoTool
    )

    blocked = ToolRegistry()
    blocked.load_plugins()
    assert blocked.get("declared_tool") is None

    registry.approve("org.author.gated")
    allowed = ToolRegistry()
    allowed.load_plugins()
    assert isinstance(allowed.get("declared_tool"), _EchoTool)

    registry.set_enabled("org.author.gated", False)
    disabled = ToolRegistry()
    disabled.load_plugins()
    assert disabled.get("declared_tool") is None


@pytest.mark.asyncio
async def test_capability_entry_point_waits_for_approval(monkeypatch, tmp_path) -> None:
    registry = _plugin_registry(tmp_path)
    _patch_plugin_registry(monkeypatch, registry)
    _patch_entry_points(
        monkeypatch, "deeptutor.extensions", "declared_capability", _EchoCapability
    )

    blocked = CapabilityRegistry()
    blocked.load_plugins()
    assert blocked.get("declared_capability") is None

    registry.approve("org.author.gated")
    allowed = CapabilityRegistry()
    allowed.load_plugins()
    assert isinstance(allowed.get("declared_capability"), _EchoCapability)


def test_loop_entry_point_waits_for_approval(monkeypatch, tmp_path) -> None:
    registry = _plugin_registry(
        tmp_path,
        [{"type": "loop_capability", "id": "demo_loop", "entry_point": "demo_loop"}],
    )
    monkeypatch.setattr("deeptutor.plugins.registry.PluginRegistry", lambda: registry)
    _patch_entry_points(
        monkeypatch,
        "deeptutor.loop_capabilities",
        "demo_loop",
        _DemoLoop,
    )
    discover_external_loop_capabilities.cache_clear()
    try:
        blocked = discover_external_loop_capabilities()
        assert not any(item[0] == "demo_loop" for item in blocked)

        registry.approve("org.author.gated")
        discover_external_loop_capabilities.cache_clear()
        allowed = discover_external_loop_capabilities()
        assert any(item[0] == "demo_loop" for item in allowed)
    finally:
        discover_external_loop_capabilities.cache_clear()


def test_reading_entry_point_waits_for_approval(monkeypatch, tmp_path) -> None:
    registry = _plugin_registry(
        tmp_path,
        [{"type": "reading_extension", "id": "translation", "entry_point": "translation"}],
    )
    monkeypatch.setattr("deeptutor.plugins.registry.PluginRegistry", lambda: registry)
    _patch_entry_points(
        monkeypatch,
        "deeptutor.reading_extensions",
        "translation",
        TranslationExtension,
    )

    blocked = ReadingExtensionRegistry()
    assert blocked.get("translation") is None

    registry.approve("org.author.gated")
    allowed = ReadingExtensionRegistry()
    assert allowed.get("translation") is not None
