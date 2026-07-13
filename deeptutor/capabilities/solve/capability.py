"""Deep Solve capability — problem solving driven by the chat agent loop.

There is no bespoke pipeline anymore. The chat agent loop IS the solver: this
capability marks the turn as solve mode and resolves a session id, then runs
the standard agentic chat pipeline. The solve loop capability
(:class:`deeptutor.capabilities.solve.loop.SolveLoopCapability`) mounts the
solve tools (``solve_plan`` / ``solve_finish_step`` / ``solve_replan``) plus a
curated built-in toolset
(``rag`` / ``code_execution`` / ``geogebra_analysis`` / …) and injects the
solver playbook; the in-memory :class:`SolveSession` holds the plan, the
per-step gate, and the replan budget.

Design axiom (shared with chat / mastery): the intelligence lives at the
loop's exit — the model plans and solves — while the deterministic spine
(commit to a plan, don't skip steps, bounded replan) is engine state read and
written through tools.
"""

from __future__ import annotations

import logging
import re

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.solve.session import DEFAULT_MAX_REPLANS
from deeptutor.capabilities.solve.tools import SOLVE_TOOL_NAMES
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.runtime.request_contracts import get_capability_request_schema
from deeptutor.services.config.capabilities_settings import get_solve_params

logger = logging.getLogger(__name__)

_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize(raw: str) -> str:
    cleaned = _UNSAFE_ID_CHARS.sub("_", raw).strip("_")
    return cleaned or "default"


def resolve_solve_session_id(context: UnifiedContext) -> str:
    """Resolve the in-memory session key for this solve turn.

    A solve turn is one-shot, so the turn id (falling back to the session /
    message id) is enough to scope the plan + replan budget; concurrent turns
    get distinct keys and never race.
    """
    raw = str(
        context.metadata.get("turn_id")
        or context.session_id
        or context.metadata.get("message_id")
        or "default"
    )
    return _sanitize(raw)


class DeepSolveCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="deep_solve",
        description="Multi-step problem solving driven by the chat agent loop.",
        stages=["responding"],
        tools_used=[*SOLVE_TOOL_NAMES, "rag", "code_execution", "geogebra_analysis", "reason"],
        cli_aliases=["solve"],
        request_schema=get_capability_request_schema("deep_solve"),
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        context.metadata["solve_mode"] = True
        context.metadata["solve_session_id"] = resolve_solve_session_id(context)
        # Read the solve settings and forward them so the page actually drives
        # the loop: max_rounds → the loop's round budget, max_replans → the
        # SolveSession gate (via metadata, read in SolveLoopCapability),
        # temperature / max_tokens → the LLM calls.
        try:
            params = get_solve_params()
        except Exception as exc:  # pragma: no cover - defensive config read
            logger.warning("Failed to load solve params, using defaults: %s", exc)
            params = {}
        context.metadata["solve_max_replans"] = int(params.get("max_replans", DEFAULT_MAX_REPLANS))
        pipeline = AgenticChatPipeline(
            language=context.language,
            max_rounds=params.get("max_rounds"),
            temperature=params.get("temperature"),
            max_tokens=params.get("max_tokens"),
        )
        await pipeline.run(context, stream)


__all__ = ["DeepSolveCapability", "resolve_solve_session_id"]
