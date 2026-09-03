"""Turn-scoped chat-loop capabilities.

Each loop capability lives in its own subpackage under
:mod:`deeptutor.capabilities` (``solve``, ``mastery``). The chat loop imports
only the generic registry/protocol from this package; feature-specific prompts,
tools, and kwargs injection stay inside each capability subpackage.

A loop capability is "chat engine + decoupled capability logic": it reuses the
full chat tool surface and adds its own owned tools + a system prompt block on
top when active, instead of running a bespoke pipeline.
"""

from importlib import import_module

from deeptutor.capabilities.protocol import KnowledgeCapability, LoopExtension, PromptBlock

_REGISTRY_EXPORTS = {
    "LOOP_CAPABILITIES",
    "active_loop_capabilities",
    "all_loop_capabilities",
    "any_exclusive_capability_active",
    "capability_tool_owners",
}


def __getattr__(name: str):
    if name not in _REGISTRY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.registry"), name)
    globals()[name] = value
    return value


__all__ = [
    "LOOP_CAPABILITIES",
    "KnowledgeCapability",
    "LoopExtension",
    "PromptBlock",
    "active_loop_capabilities",
    "all_loop_capabilities",
    "any_exclusive_capability_active",
    "capability_tool_owners",
]
