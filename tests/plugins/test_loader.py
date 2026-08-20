"""Tests for the neutral deeptutor.plugins.loader entry-point discovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
import deeptutor.core.entry_points as ep_module
from deeptutor.core.stream_bus import StreamBus


class _DemoCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="demo_cap",
        description="Demo capability from a plugin EP.",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None


def _ep(name: str, load):
    return SimpleNamespace(name=name, load=load)


def test_discover_plugins_from_capability_class(monkeypatch):
    from deeptutor.plugins import loader

    def fake_entry_points(*, group: str):
        assert group == "deeptutor.plugins"
        return [_ep("demo_cap", lambda: _DemoCapability)]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)

    manifests = loader.discover_plugins()
    assert len(manifests) == 1
    m = manifests[0]
    assert m.name == "demo_cap"
    assert m.type == "capability"
    assert m.description.startswith("Demo")
    assert m.stages == ["responding"]
    assert ":_DemoCapability" in m.entry or m.entry.endswith("_DemoCapability")


def test_discover_skips_broken_entry_points(monkeypatch):
    from deeptutor.plugins import loader

    def boom():
        raise RuntimeError("boom")

    def fake_entry_points(*, group: str):
        return [
            _ep("bad", boom),
            _ep("demo_cap", lambda: _DemoCapability),
        ]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)
    manifests = loader.discover_plugins()
    assert [m.name for m in manifests] == ["demo_cap"]


def test_load_plugin_capability_instantiates(monkeypatch):
    from deeptutor.plugins import loader

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        lambda *, group: [_ep("demo_cap", lambda: _DemoCapability)],
    )
    manifests = loader.discover_plugins()
    cap = loader.load_plugin_capability(manifests[0])
    assert isinstance(cap, _DemoCapability)
    assert cap.name == "demo_cap"


def test_load_plugin_capability_skips_tool_entry():
    from deeptutor.plugins.loader import PluginManifest, load_plugin_capability

    manifest = PluginManifest(
        name="some_tool",
        type="tool",
        description="",
        entry="path/to/tool.py",
    )
    assert load_plugin_capability(manifest) is None


def test_discover_from_manifest_factory(monkeypatch):
    from deeptutor.plugins import loader
    from deeptutor.plugins.loader import PluginManifest

    def factory():
        return PluginManifest(
            name="from_factory",
            type="capability",
            description="via factory",
            stages=["a"],
            entry="tests.plugins.test_loader:_DemoCapability",
        )

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        lambda *, group: [_ep("from_factory", factory)],
    )
    manifests = loader.discover_plugins()
    assert manifests[0].name == "from_factory"
    cap = loader.load_plugin_capability(manifests[0])
    assert isinstance(cap, _DemoCapability)


def test_capability_registry_loads_plugins(monkeypatch):
    from deeptutor.plugins import loader
    from deeptutor.runtime.registry import capability_registry as cr

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        lambda *, group: [_ep("demo_cap", lambda: _DemoCapability)],
    )
    # Fresh registry instance (avoid process-global singleton pollution)
    reg = cr.CapabilityRegistry()
    reg.load_plugins()
    assert reg.get("demo_cap") is not None
    assert reg.get("demo_cap").name == "demo_cap"
