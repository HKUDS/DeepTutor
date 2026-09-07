"""Immersive Reading capability — the chat agent loop, reading a document.

There is no bespoke pipeline: the standard agentic chat loop IS the reader. This
capability only marks the turn and runs that pipeline. Everything specific to
reading is contributed by the loop capability
(:class:`deeptutor.capabilities.reading.capability.ReadingCapability`), which
mounts the five reading tools, binds the open material server-side, injects the
reading playbook and runs the deterministic locate pre-pass.

The split matters for a practical reason: the *mode* is what the user picks in
the composer, while the *loop capability* activates on whether a document is
actually open. Selecting the mode with no document open therefore still gives a
perfectly ordinary chat turn — the reader panel is showing its file picker, and
there is nothing to ground an answer in yet.

Design axiom (shared with chat / solve / mastery): the intelligence lives at the
loop's exit — the model decides what to read and what to cite — while the
deterministic parts (which units exist, whether a quote is really on the page it
claims) are engine calls behind tools.
"""

from __future__ import annotations

from typing import cast

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities.reading.capability import (
    MATERIAL_ID_KEY,
    MODE_KEY,
    resolve_material_id,
)
from deeptutor.capabilities.reading.tools import READING_TOOL_NAMES
from deeptutor.core.capability_protocol import (
    CapabilityManifest,
    StreamBusProtocol,
    TurnCapability,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus


class ImmersiveReadingCapability(TurnCapability):
    manifest = CapabilityManifest(
        name="immersive_reading",
        description=(
            "Read a document alongside the assistant, which cites the exact "
            "page or section behind every claim."
        ),
        stages=["responding"],
        tools_used=[*READING_TOOL_NAMES, "web_search", "exec", "reason"],
        cli_aliases=["reading", "read"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        # Normalised so the flag and the id can never disagree: the loop
        # capability keys off the id alone, and a turn with no document open is
        # deliberately just a normal chat turn.
        material_id = resolve_material_id(context)
        context.metadata[MATERIAL_ID_KEY] = material_id
        context.metadata[MODE_KEY] = True
        await AgenticChatPipeline(language=context.language).run(context, cast(StreamBus, stream))


__all__ = ["ImmersiveReadingCapability"]
