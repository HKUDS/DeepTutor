"""Built-in loop-capability registry."""

from __future__ import annotations

from deeptutor.capabilities.explore_context import ExploreContextCapability
from deeptutor.capabilities.ima import ImaCapability
from deeptutor.capabilities.mastery import MasteryLoopCapability
from deeptutor.capabilities.obsidian import ObsidianCapability
from deeptutor.capabilities.protocol import LoopCapability
from deeptutor.capabilities.reading import ReadingCapability
from deeptutor.capabilities.setup import SetupCapability
from deeptutor.capabilities.solve import SolveLoopCapability
from deeptutor.capabilities.subagent import SubagentCapability
from deeptutor.core.context import UnifiedContext

LOOP_CAPABILITIES: tuple[LoopCapability, ...] = (
    MasteryLoopCapability(),
    SolveLoopCapability(),
    ObsidianCapability(),
    SubagentCapability(),
    # Additive (not a KnowledgeCapability): an IMA library is searchable over
    # HTTP, so ``rag`` keeps serving it and these tools only add what retrieval
    # cannot do. See ``capabilities/ima/capability.py``.
    ImaCapability(),
    # Additive: reading material is addressed by locator through this
    # capability's own store, so chat keeps its whole surface (web search, code,
    # rag over other KBs) while gaining the five reading tools on top.
    ReadingCapability(),
    ExploreContextCapability(),
    # Additive as well: configuring the app is something the user asks for in
    # the middle of other work, so the turn keeps its normal surface. Activation
    # is gated on objective signals, not on the model's sense of relevance —
    # see ``capabilities/setup/binding.py``.
    SetupCapability(),
)


def active_loop_capabilities(context: UnifiedContext) -> tuple[LoopCapability, ...]:
    """Return the loop capabilities active for this turn in stable registry order."""
    return tuple(cap for cap in LOOP_CAPABILITIES if cap.is_active(context))


def any_exclusive_capability_active(context: UnifiedContext) -> bool:
    """Whether an active capability *replaces* the tool surface (knowledge category).

    Drives the pipeline's exclusive-tools branch and the suppression of rag
    scaffolding (KB seed / kb note) — the turn runs only on the capability's
    own tools. ``getattr`` default keeps plain capabilities (solve / mastery)
    out of this path.
    """
    return any(getattr(cap, "exclusive_tools", False) for cap in active_loop_capabilities(context))


def capability_tool_owners() -> dict[str, str]:
    """Map each capability-owned tool name to its owning capability name.

    Static (independent of any turn) so the settings UI can group capability
    tools under their owner. Built-in/system tools are absent from the map.
    """
    return {name: cap.name for cap in LOOP_CAPABILITIES for name in cap.owned_tools}


__all__ = [
    "LOOP_CAPABILITIES",
    "active_loop_capabilities",
    "any_exclusive_capability_active",
    "capability_tool_owners",
]
