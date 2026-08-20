"""Mastery Path capability — mastery-based tutoring driven by the chat loop.

There is no bespoke state machine here anymore. The chat agent loop IS the
tutor: this capability only marks the turn as mastery mode and resolves the
*initial* active path id, then runs the standard agentic chat pipeline. The
pipeline mounts the mastery tools — the gate tools (``mastery_status`` /
``mastery_quiz`` / ``mastery_grade`` / ``mastery_assess`` / ``mastery_build``)
and the binding tools (``mastery_paths`` / ``mastery_switch`` /
``mastery_leave``), through which the tutor can move the conversation between
paths mid-turn — and injects the tutor playbook; the pure engine in
:mod:`deeptutor.learning` owns the hard, per-type mastery gate and the
spaced-repetition arithmetic.

Design axiom (shared with chat): the intelligence lives at the loop's exit —
the model decides what to teach and how to question — while the gate that
decides *whether the learner may advance* is a deterministic engine call.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.learning.identity import resolve_mastery_path_binding


def resolve_mastery_path_id(context: UnifiedContext) -> str:
    """Resolve which learner-path the turn operates on.

    Prefers an explicit ``mastery_path_id`` set by the frontend (so the tutor
    and the build wizard / dashboard agree on one storage key), then a book
    reference, then the session id for an ad-hoc path built inside a chat.
    """
    binding = resolve_mastery_path_binding(
        configured_path_id=str(context.metadata.get("mastery_path_id") or ""),
        book_references=(context.metadata or {}).get("book_references", []),
        session_id=str(context.session_id or ""),
    )
    return binding.path_id


class MasteryPathCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="mastery_path",
        description=(
            "Mastery-based tutoring: the chat agent loop drives an adaptive "
            "mastery path with a hard, per-type mastery gate and spaced review."
        ),
        stages=["responding"],
        tools_used=[*MASTERY_TOOL_NAMES, "rag", "read_source", "ask_user"],
        cli_aliases=["mastery"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        binding = resolve_mastery_path_binding(
            configured_path_id=str(context.metadata.get("mastery_path_id") or ""),
            book_references=(context.metadata or {}).get("book_references", []),
            session_id=str(context.session_id or ""),
        )
        context.metadata["mastery_mode"] = True
        context.metadata["mastery_path_id"] = binding.path_id
        pipeline = AgenticChatPipeline(language=context.language)
        if context.metadata.get("mastery_path_lease_managed"):
            await pipeline.run(context, stream)
            return

        # CLI and SDK calls bypass TurnRuntimeManager, so the capability owns
        # the same path lease for those entry points. Runtime-managed web turns
        # keep their lease until message/event persistence has also completed.
        from deeptutor.learning.storage import LearningStore

        store = LearningStore()
        turn_id = str(context.metadata.get("turn_id") or f"direct-{uuid.uuid4().hex}")
        context.metadata["turn_id"] = turn_id
        await asyncio.to_thread(
            store.bind_session,
            binding.path_id,
            str(context.session_id or "direct"),
            owns_path=binding.owned_by_session,
        )
        await asyncio.to_thread(
            store.acquire_path_lease,
            binding.path_id,
            str(context.session_id or "direct"),
            turn_id,
        )
        try:
            await pipeline.run(context, stream)
        finally:
            # Released by turn: ``mastery_switch`` may have moved this turn onto
            # a different path since the lease was taken.
            with contextlib.suppress(Exception):
                await asyncio.shield(asyncio.to_thread(store.release_leases_for_turn, turn_id))


__all__ = ["MasteryPathCapability", "resolve_mastery_path_id"]
