"""Mastery Path capability — mastery-based tutoring driven by the chat loop.

There is no bespoke state machine here anymore. The chat agent loop IS the
tutor: this capability only marks the turn as mastery mode and resolves the
active path id, then runs the standard agentic chat pipeline. The pipeline
mounts the mastery tools (``mastery_status`` / ``mastery_quiz`` /
``mastery_grade`` / ``mastery_assess`` / ``mastery_build``) and injects the
tutor playbook; the pure engine in :mod:`deeptutor.learning` owns the hard,
per-type mastery gate and the spaced-repetition arithmetic.

Design axiom (shared with chat): the intelligence lives at the loop's exit —
the model decides what to teach and how to question — while the gate that
decides *whether the learner may advance* is a deterministic engine call.
"""

from __future__ import annotations

import re

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus

_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_path_id(raw: str) -> str:
    """Make *raw* a safe storage key (matches ``LearningStore`` path guard)."""
    cleaned = _UNSAFE_ID_CHARS.sub("_", raw).strip("_")
    return cleaned or "default"


def resolve_mastery_path_id(context: UnifiedContext) -> str:
    """Resolve which learner-path the turn operates on.

    Prefers an explicit ``mastery_path_id`` set by the frontend (so the tutor
    and the build wizard / dashboard agree on one storage key), then a book
    reference, then the session id for an ad-hoc path built inside a chat.
    """
    explicit = str(context.metadata.get("mastery_path_id") or "").strip()
    if explicit:
        return _sanitize_path_id(explicit)
    refs = (context.metadata or {}).get("book_references", [])
    if refs:
        ref = refs[0]
        if isinstance(ref, str) and ref.strip():
            return _sanitize_path_id(ref)
        if isinstance(ref, dict):
            candidate = str(ref.get("book_id") or ref.get("id") or "").strip()
            if candidate:
                return _sanitize_path_id(candidate)
    return _sanitize_path_id(str(context.session_id or "default"))


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
        context.metadata["mastery_mode"] = True
        context.metadata["mastery_path_id"] = resolve_mastery_path_id(context)
        pipeline = AgenticChatPipeline(language=context.language)
        await pipeline.run(context, stream)


__all__ = ["MasteryPathCapability", "resolve_mastery_path_id"]
