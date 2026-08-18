"""Built-in loop-capability registry plus optional entry-point plugins."""

from __future__ import annotations

from importlib.metadata import entry_points
import inspect
from typing import Any

from loguru import logger

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

LOOP_CAPABILITIES_GROUP = "deeptutor.loop_capabilities"

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


def _coerce_loop_capability(loaded: object) -> LoopCapability | None:
    """Turn an entry-point target into a loop-capability instance, or None."""
    obj: Any = loaded
    if inspect.isclass(obj):
        try:
            obj = obj()
        except Exception:
            return None
    elif callable(obj) and getattr(obj, "owned_tools", None) is None:
        try:
            obj = obj()
        except Exception:
            return None
        if inspect.isclass(obj):
            try:
                obj = obj()
            except Exception:
                return None
    name = getattr(obj, "name", None)
    if not isinstance(name, str) or not name.strip():
        return None
    tools = getattr(obj, "owned_tools", None)
    try:
        if tools is None:
            return None
        tuple(tools)
    except TypeError:
        return None
    if not callable(getattr(obj, "is_active", None)):
        return None
    return obj


def discover_external_loop_capabilities() -> tuple[LoopCapability, ...]:
    """Load third-party loop capabilities from ``deeptutor.loop_capabilities``.

    Built-in names (and earlier plugins) win. Broken or invalid entry points are
    skipped with a warning so a bad plugin cannot take down the chat loop.
    """
    found: list[LoopCapability] = []
    seen = {cap.name for cap in LOOP_CAPABILITIES}
    try:
        discovered = entry_points(group=LOOP_CAPABILITIES_GROUP)
    except Exception as exc:
        logger.warning("Failed to read {} entry points: {}", LOOP_CAPABILITIES_GROUP, exc)
        return ()

    for ep in discovered:
        try:
            cap = _coerce_loop_capability(ep.load())
        except Exception as exc:
            logger.warning("Failed to load loop capability plugin '{}': {}", ep.name, exc)
            continue
        if cap is None:
            logger.warning(
                "Ignoring loop capability plugin '{}': not a LoopCapability class or factory",
                ep.name,
            )
            continue
        if cap.name in seen:
            logger.warning(
                "Loop capability plugin '{}' shadowed by built-in or earlier plugin (ignored)",
                cap.name,
            )
            continue
        seen.add(cap.name)
        found.append(cap)
    return tuple(found)


def all_loop_capabilities() -> tuple[LoopCapability, ...]:
    """Built-ins first, then external entry-point plugins (no name shadowing)."""
    return LOOP_CAPABILITIES + discover_external_loop_capabilities()


def active_loop_capabilities(context: UnifiedContext) -> tuple[LoopCapability, ...]:
    """Return the loop capabilities active for this turn in stable registry order."""
    return tuple(cap for cap in all_loop_capabilities() if cap.is_active(context))


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
    return {name: cap.name for cap in all_loop_capabilities() for name in cap.owned_tools}


__all__ = [
    "LOOP_CAPABILITIES",
    "LOOP_CAPABILITIES_GROUP",
    "all_loop_capabilities",
    "active_loop_capabilities",
    "any_exclusive_capability_active",
    "capability_tool_owners",
    "discover_external_loop_capabilities",
]
