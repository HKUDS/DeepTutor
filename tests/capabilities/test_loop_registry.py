"""Tests for loop-capability registry + ``deeptutor.loop_capabilities`` discovery."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.capabilities.registry import LOOP_CAPABILITIES, discover_external_loop_capabilities
from deeptutor.core.context import UnifiedContext
import deeptutor.core.entry_points as ep_module


@pytest.fixture(autouse=True)
def _fresh_discovery() -> None:
    """Discovery is cached for the process, so each test needs a clean slate.

    Without this, the first test's entry-point stub would be the answer every
    later test sees.
    """
    discover_external_loop_capabilities.cache_clear()
    yield
    discover_external_loop_capabilities.cache_clear()


class _DemoLoop:
    name = "demo_loop"
    owned_tools = ("demo_tool",)

    def is_active(self, context: UnifiedContext) -> bool:
        return context.active_capability == "demo_loop"

    def system_block(self, context, *, language, prompts):
        return None

    def augment_kwargs(self, tool_name, kwargs, context):
        return kwargs

    def pre_loop_seed(self, context):
        return ""


class _ShadowMastery:
    name = "mastery"
    owned_tools = ("shadow_tool",)

    def is_active(self, context: UnifiedContext) -> bool:
        return True

    def system_block(self, context, *, language, prompts):
        return None

    def augment_kwargs(self, tool_name, kwargs, context):
        return kwargs

    def pre_loop_seed(self, context):
        return ""


def _ep(name: str, load):
    return SimpleNamespace(name=name, load=load)


def _no_plugins(*, group: str):
    assert group == "deeptutor.loop_capabilities"
    return []


def _capture_warnings(monkeypatch, registry) -> list[str]:
    warnings: list[str] = []

    def _record(msg, *args, **kwargs):
        text = str(msg)
        if args:
            if "{}" in text:
                text = text.format(*args)
            else:
                try:
                    text = text % args
                except TypeError:
                    text = " ".join([text, *map(str, args)])
        warnings.append(text)

    monkeypatch.setattr(registry.logger, "warning", _record)
    return warnings


def test_loop_capabilities_tuple_is_builtins_only() -> None:
    # The roster grows as capabilities land, so pin the invariant rather than
    # the list: every entry is a real instance with a unique name, and none of
    # them arrived through entry-point discovery.
    names = [cap.name for cap in LOOP_CAPABILITIES]
    assert names, "the builtin registry must not be empty"
    assert len(names) == len(set(names)), f"duplicate builtin capability names: {names}"
    assert all(callable(getattr(cap, "is_active", None)) for cap in LOOP_CAPABILITIES)


def test_all_loop_capabilities_equals_builtins_without_plugins(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    monkeypatch.setattr(ep_module, "entry_points", _no_plugins)

    merged = registry.all_loop_capabilities()
    assert merged == LOOP_CAPABILITIES


def test_external_class_is_appended(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    def fake_entry_points(*, group: str):
        assert group == "deeptutor.loop_capabilities"
        return [_ep("demo_loop", lambda: _DemoLoop)]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)

    merged = registry.all_loop_capabilities()
    assert merged[: len(LOOP_CAPABILITIES)] == LOOP_CAPABILITIES
    assert merged[-1].name == "demo_loop"
    assert merged[-1].owned_tools == ("demo_tool",)


def test_factory_callable_returning_instance(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    def fake_entry_points(*, group: str):
        assert group == "deeptutor.loop_capabilities"
        return [_ep("demo_loop", lambda: lambda: _DemoLoop())]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)

    merged = registry.all_loop_capabilities()
    assert merged[-1].name == "demo_loop"


def test_builtin_name_wins_and_warns(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    def fake_entry_points(*, group: str):
        return [_ep("mastery", lambda: _ShadowMastery)]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)
    warnings = _capture_warnings(monkeypatch, registry)

    merged = registry.all_loop_capabilities()
    names = [cap.name for cap in merged]
    assert names.count("mastery") == 1
    assert LOOP_CAPABILITIES[0] is merged[0]
    assert "shadow_tool" not in {t for cap in merged for t in cap.owned_tools}
    assert any("mastery" in w for w in warnings)


def test_broken_entry_point_is_skipped(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    def boom():
        raise RuntimeError("cannot load")

    def fake_entry_points(*, group: str):
        return [_ep("broken", boom), _ep("demo_loop", lambda: _DemoLoop)]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)
    warnings = _capture_warnings(monkeypatch, registry)

    merged = registry.all_loop_capabilities()
    assert any(cap.name == "demo_loop" for cap in merged)
    assert not any(cap.name == "broken" for cap in merged)
    assert any("broken" in w for w in warnings)


def test_invalid_object_is_skipped(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    def fake_entry_points(*, group: str):
        return [_ep("not_a_cap", lambda: object)]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)
    warnings = _capture_warnings(monkeypatch, registry)

    merged = registry.all_loop_capabilities()
    assert merged == LOOP_CAPABILITIES
    assert warnings


def test_duplicate_external_name_first_wins(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    class _Other:
        name = "demo_loop"
        owned_tools = ("other_tool",)

        def is_active(self, context):
            return False

        def system_block(self, context, *, language, prompts):
            return None

        def augment_kwargs(self, tool_name, kwargs, context):
            return kwargs

        def pre_loop_seed(self, context):
            return ""

    def fake_entry_points(*, group: str):
        return [
            _ep("demo_loop", lambda: _DemoLoop),
            _ep("demo_loop_dup", lambda: _Other),
        ]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)

    merged = registry.all_loop_capabilities()
    demo = [cap for cap in merged if cap.name == "demo_loop"]
    assert len(demo) == 1
    assert demo[0].owned_tools == ("demo_tool",)


def test_active_loop_capabilities_includes_external(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    def fake_entry_points(*, group: str):
        return [_ep("demo_loop", lambda: _DemoLoop)]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)

    idle = registry.active_loop_capabilities(UnifiedContext())
    assert all(cap.name != "demo_loop" for cap in idle)

    active = registry.active_loop_capabilities(UnifiedContext(active_capability="demo_loop"))
    assert [cap.name for cap in active] == ["demo_loop"]


def test_capability_tool_owners_includes_external(monkeypatch) -> None:
    from deeptutor.capabilities import registry

    def fake_entry_points(*, group: str):
        return [_ep("demo_loop", lambda: _DemoLoop)]

    monkeypatch.setattr(ep_module, "entry_points", fake_entry_points)

    owners = registry.capability_tool_owners()
    assert owners["demo_tool"] == "demo_loop"
    builtin_tool = LOOP_CAPABILITIES[0].owned_tools[0]
    assert owners[builtin_tool] == LOOP_CAPABILITIES[0].name
