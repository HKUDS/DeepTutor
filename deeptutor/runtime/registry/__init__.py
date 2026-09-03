"""Runtime registries for capabilities and tools, exported lazily."""

from __future__ import annotations

import importlib

_EXPORTS = {
    "CapabilityRegistry": (".capability_registry", "CapabilityRegistry"),
    "get_capability_registry": (".capability_registry", "get_capability_registry"),
    "ToolRegistry": (".tool_registry", "ToolRegistry"),
    "get_tool_registry": (".tool_registry", "get_tool_registry"),
}

__all__ = [
    "CapabilityRegistry",
    "ToolRegistry",
    "get_capability_registry",
    "get_tool_registry",
]


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(importlib.import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
