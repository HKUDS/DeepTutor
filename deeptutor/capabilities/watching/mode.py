"""Immersive Watching mode using the standard agentic chat loop."""

from __future__ import annotations

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus

from .capability import MATERIAL_ID_KEY, MODE_KEY, resolve_material_id


class ImmersiveWatchingCapability(BaseCapability):
    manifest = CapabilityManifest(
        name="immersive_watching",
        description="Learn alongside a YouTube video with timestamp-grounded tutoring.",
        stages=["responding"],
        tools_used=["web_search", "code_execution", "reason"],
        cli_aliases=["watching", "watch"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        context.metadata[MATERIAL_ID_KEY] = resolve_material_id(context)
        context.metadata[MODE_KEY] = True
        await AgenticChatPipeline(language=context.language).run(context, stream)


__all__ = ["ImmersiveWatchingCapability"]
