"""Contract tests for the plugins entry-point loader.

These pin the *current* behaviour of the three layers that turn entry-point
registrations into registered capabilities — the shared plumbing in
``deeptutor.core.entry_points``, the neutral discovery in
``deeptutor.plugins.loader``, and ``CapabilityRegistry.load_plugins`` — so the
managed-plugin slices (upstream #961 / #1307) extend a documented contract
instead of an accident.

Five path families are covered:

* normal loading
* missing dependencies
* load-error isolation
* duplicate registration
* disable-gating status quo (structural gates only, no user toggle)
"""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace

import pytest

from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import UnifiedContext
import deeptutor.core.entry_points as ep_module
from deeptutor.plugins.loader import (
    PluginManifest,
    discover_plugins,
    load_plugin_capability,
)
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.stream_bus import StreamBus

PLUGINS_GROUP = "deeptutor.plugins"
EXTENSIONS_GROUP = "deeptutor.extensions"
PLUGINS_LOGGER = "deeptutor.plugins.loader"
PLUMBING_LOGGER = "deeptutor.core.entry_points"
REGISTRY_LOGGER = "deeptutor.runtime.registry.capability_registry"


class _PluginCap(TurnCapability):
    manifest = CapabilityManifest(
        name="plugin_cap",
        description="Capability provided by a plugin entry point.",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None


class _PluginCapBis(TurnCapability):
    """Different plugin class, same declared capability name as _PluginCap."""

    manifest = CapabilityManifest(
        name="plugin_cap",
        description="Second plugin shipping the same capability name.",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None


class _OtherCap(TurnCapability):
    manifest = CapabilityManifest(
        name="other_cap",
        description="Second plugin capability with its own name.",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None


def _make_missing_module_capability() -> type[TurnCapability]:
    """Capability class whose qualified entry points at a module that is not installed."""

    async def _run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None

    cls = type(
        "_MissingModuleCap",
        (TurnCapability,),
        {
            "manifest": CapabilityManifest(
                name="missing_cap",
                description="Capability whose module cannot be imported.",
                stages=["responding"],
            ),
            "run": _run,
        },
    )
    cls.__module__ = "tests.plugins._no_such_module"
    return cls


def _ep(name: str, load):
    return SimpleNamespace(name=name, load=load)


def _fake_groups(groups: dict[str, list]):
    def fake_entry_points(*, group: str):
        return list(groups.get(group, []))

    return fake_entry_points


# ---------------------------------------------------------------------------
# Normal loading
# ---------------------------------------------------------------------------


def test_load_entry_point_group_returns_coerced_values_in_order(monkeypatch):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups({"g": [_ep("a", lambda: "A"), _ep("b", lambda: "B")]}),
    )
    loaded = ep_module.load_entry_point_group("g", lambda _name, obj: obj)
    assert loaded == ["A", "B"]


def test_discover_plugins_normal_load_from_class_and_instance(monkeypatch):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                PLUGINS_GROUP: [
                    _ep("plugin_cap", lambda: _PluginCap),
                    _ep("other_cap", lambda: _OtherCap()),
                ]
            }
        ),
    )
    manifests = discover_plugins()
    assert [m.name for m in manifests] == ["plugin_cap", "other_cap"]
    by_name = {m.name: m for m in manifests}
    for manifest in by_name.values():
        assert manifest.type == "capability"
        assert manifest.stages == ["responding"]
        assert ":" in manifest.entry
    assert by_name["plugin_cap"].entry.endswith("_PluginCap")
    assert by_name["other_cap"].entry.endswith("_OtherCap")


def test_registry_load_plugins_loads_canonical_extensions_group(monkeypatch):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups({EXTENSIONS_GROUP: [_ep("plugin_cap", lambda: _PluginCap)]}),
    )
    reg = CapabilityRegistry()
    reg.load_plugins()
    assert isinstance(reg.get("plugin_cap"), _PluginCap)


# ---------------------------------------------------------------------------
# Missing dependencies
# ---------------------------------------------------------------------------


def test_missing_dependency_entry_point_is_skipped_others_still_load(monkeypatch, caplog):
    def _missing_dep():
        raise ModuleNotFoundError("No module named 'plugin_dep'")

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                PLUGINS_GROUP: [
                    _ep("needs_dep", _missing_dep),
                    _ep("plugin_cap", lambda: _PluginCap),
                ]
            }
        ),
    )
    with caplog.at_level(logging.WARNING, logger=PLUGINS_LOGGER):
        manifests = discover_plugins()
    assert [m.name for m in manifests] == ["plugin_cap"]
    assert any("needs_dep" in record.getMessage() for record in caplog.records)


def test_load_plugin_capability_propagates_missing_module():
    """Discovery isolates import failures; instantiation does not (current contract)."""

    manifest = PluginManifest(
        name="gone_cap",
        type="capability",
        entry="tests.plugins._no_such_module:Cap",
    )
    with pytest.raises(ModuleNotFoundError):
        load_plugin_capability(manifest)


def test_legacy_instantiation_error_aborts_remaining_legacy_manifests(monkeypatch, caplog):
    """A legacy manifest that fails to instantiate drops every manifest after it."""

    missing_cls = _make_missing_module_capability()
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                EXTENSIONS_GROUP: [],
                PLUGINS_GROUP: [
                    _ep("good_first", lambda: _PluginCap),
                    _ep("needs_dep", lambda: missing_cls),
                    _ep("good_after", lambda: _OtherCap),
                ],
            }
        ),
    )
    reg = CapabilityRegistry()
    with caplog.at_level(logging.DEBUG, logger=REGISTRY_LOGGER):
        reg.load_plugins()
    assert isinstance(reg.get("plugin_cap"), _PluginCap)
    assert reg.get("other_cap") is None
    assert any(
        "Legacy plugin loader unavailable" in record.getMessage() for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Load-error isolation
# ---------------------------------------------------------------------------


def test_entry_point_load_error_is_isolated_and_named_in_warning(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("boom at import time")

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                PLUGINS_GROUP: [
                    _ep("bad", _boom),
                    _ep("plugin_cap", lambda: _PluginCap),
                    _ep("worse", _boom),
                ]
            }
        ),
    )
    with caplog.at_level(logging.WARNING, logger=PLUGINS_LOGGER):
        manifests = discover_plugins()
    assert [m.name for m in manifests] == ["plugin_cap"]
    assert any(
        PLUGINS_GROUP in message and "skipping" in message
        for message in (record.getMessage() for record in caplog.records)
    )


def test_group_read_failure_returns_empty_with_warning(monkeypatch, caplog):
    def _broken_reader(*, group: str):
        raise RuntimeError("metadata reader exploded")

    monkeypatch.setattr(ep_module, "entry_points", _broken_reader)
    with caplog.at_level(logging.WARNING, logger=PLUMBING_LOGGER):
        loaded = ep_module.load_entry_point_group(PLUGINS_GROUP, lambda _name, obj: obj)
    assert loaded == []
    assert any(PLUGINS_GROUP in record.getMessage() for record in caplog.records)


def test_coercer_none_rejects_entry_point_without_error(monkeypatch):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups({"g": [_ep("junk", lambda: object()), _ep("keep", lambda: "kept")]}),
    )
    loaded = ep_module.load_entry_point_group(
        "g", lambda name, obj: obj if name == "keep" else None
    )
    assert loaded == ["kept"]


# ---------------------------------------------------------------------------
# Duplicate registration
# ---------------------------------------------------------------------------


def test_duplicate_extension_registration_first_wins_with_warning(monkeypatch, caplog):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                EXTENSIONS_GROUP: [
                    _ep("first_ship", lambda: _PluginCap),
                    _ep("second_ship", lambda: _PluginCapBis),
                ]
            }
        ),
    )
    reg = CapabilityRegistry()
    with caplog.at_level(logging.WARNING, logger=REGISTRY_LOGGER):
        reg.load_plugins()
    assert reg.list_capabilities().count("plugin_cap") == 1
    cap = reg.get("plugin_cap")
    assert isinstance(cap, _PluginCap)
    assert any(
        "second_ship" in record.getMessage() and "already registered" in record.getMessage()
        for record in caplog.records
    )


def test_legacy_plugin_with_taken_name_is_ignored(monkeypatch):
    """Canonical registrations win; a same-named legacy plugin is skipped, and the
    legacy group's presence is announced with a DeprecationWarning."""

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                EXTENSIONS_GROUP: [_ep("plugin_cap", lambda: _PluginCap)],
                PLUGINS_GROUP: [_ep("legacy_dup", lambda: _PluginCapBis)],
            }
        ),
    )
    reg = CapabilityRegistry()
    with pytest.warns(DeprecationWarning, match="deprecated"):
        reg.load_plugins()
    assert reg.list_capabilities().count("plugin_cap") == 1
    assert isinstance(reg.get("plugin_cap"), _PluginCap)


# ---------------------------------------------------------------------------
# Disable-gating status quo
# ---------------------------------------------------------------------------


def test_plugin_manifest_has_no_enable_disable_gate():
    """Today a plugin cannot be disabled declaratively: PluginManifest carries no
    enabled/disabled flag, and the loader consults none."""

    field_names = {f.name for f in dataclasses.fields(PluginManifest)}
    assert field_names == {
        "name",
        "type",
        "description",
        "stages",
        "version",
        "author",
        "entry",
    }
    assert not field_names & {"enabled", "disabled"}


def test_structural_gates_short_circuit_before_resolving_entry():
    """The only gates are structural (entry / type) and run before any import, so a
    gated manifest never triggers its (here broken) entry point."""

    empty_entry = PluginManifest(name="t1", type="capability", entry="")
    tool_script = PluginManifest(name="t2", type="capability", entry="tests/plugins/tool.py")
    wrong_type = PluginManifest(
        name="t3",
        type="tool",
        entry="tests.plugins._no_such_module:Cap",
    )
    assert load_plugin_capability(empty_entry) is None
    assert load_plugin_capability(tool_script) is None
    assert load_plugin_capability(wrong_type) is None
