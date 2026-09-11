"""Immersive Watching mode using the standard agentic chat loop."""

from __future__ import annotations

from typing import cast

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import (
    CapabilityManifest,
    StreamBusProtocol,
    TurnCapability,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus

from .capability import MATERIAL_ID_KEY, MODE_KEY, resolve_material_id


class ImmersiveWatchingCapability(TurnCapability):
    manifest = CapabilityManifest(
        name="immersive_watching",
        description="Learn alongside a YouTube video with timestamp-grounded tutoring.",
        stages=["responding"],
        tools_used=["web_search", "exec", "reason"],
        cli_aliases=["watching", "watch"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        context.metadata[MATERIAL_ID_KEY] = resolve_material_id(context)
        context.metadata[MODE_KEY] = True
        await AgenticChatPipeline(language=context.language).run(context, cast(StreamBus, stream))


__all__ = ["ImmersiveWatchingCapability"]
