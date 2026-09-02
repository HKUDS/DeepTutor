"""Agent-loop submission tool for validated visualization envelopes."""

from __future__ import annotations

from typing import Any

from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

from .protocol import (
    REQUESTED_VISUALIZER_KEY,
    VISUALIZATION_RESULT_KEY,
    RendererRef,
    VisualizationEnvelope,
    VisualizationInteraction,
    VisualizationPayload,
    VisualizationPresentation,
)
from .registry import VisualizerRegistry, get_visualizer_registry


class SubmitVisualizationTool(BaseTool):
    """The only commit point from the chat loop into the canvas protocol."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="submit_visualization",
            description=(
                "Validate and submit one complete visualization to DeepTutor's canvas. "
                "Call this after choosing an installed visualizer and generating its exact "
                "payload. If validation fails, repair the payload and call again."
            ),
            parameters=[
                ToolParameter(
                    name="visualizer",
                    type="string",
                    description=(
                        "Installed visualization type to render. Use one exact id "
                        "from the visualization protocol in the system prompt."
                    ),
                ),
                ToolParameter(
                    name="payload",
                    type="string",
                    description=(
                        "Complete raw payload in the selected type's declared format. "
                        "Do not wrap it in Markdown fences."
                    ),
                ),
                ToolParameter(name="title", type="string", description="Short title."),
                ToolParameter(
                    name="description",
                    type="string",
                    description="One sentence explaining what to explore or notice.",
                ),
                ToolParameter(
                    name="alt_text",
                    type="string",
                    description="Accessible description of the important visual content.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        context = kwargs.get("_visualize_context")
        if not isinstance(context, UnifiedContext):
            return ToolResult(content="Visualization context is unavailable.", success=False)
        registry = kwargs.get("_visualizer_registry")
        if not isinstance(registry, VisualizerRegistry):
            registry = get_visualizer_registry()

        visualizer_id = str(kwargs.get("visualizer") or "").strip().lower()
        requested = (
            str(
                kwargs.get("_requested_visualizer")
                or context.metadata.get(REQUESTED_VISUALIZER_KEY)
                or "auto"
            )
            .strip()
            .lower()
        )
        if requested != "auto" and visualizer_id != requested:
            return ToolResult(
                content=(
                    f"The user fixed the visualization type to '{requested}', but the "
                    f"submission used '{visualizer_id}'. Regenerate it as '{requested}'."
                ),
                success=False,
            )
        plugin = registry.get(visualizer_id)
        if plugin is None or not plugin.manifest.agentic:
            available = ", ".join(item.manifest.id for item in registry.agentic())
            return ToolResult(
                content=f"Visualizer '{visualizer_id}' is unavailable. Available: {available}",
                success=False,
            )

        ok, data, error = plugin.validate_payload(str(kwargs.get("payload") or ""))
        if not ok:
            return ToolResult(
                content=(
                    f"{plugin.manifest.display_name} payload validation failed: {error}. "
                    "Repair the concrete issue and submit the complete payload again."
                ),
                success=False,
                metadata={"visualizer": visualizer_id, "validation_error": error},
            )

        entry_url = ""
        if plugin.manifest.render_target == "iframe":
            entry_url = (
                f"/api/visualizers/{plugin.manifest.id}/assets/{plugin.manifest.renderer_entry}"
            )
        envelope = VisualizationEnvelope(
            render_type=plugin.manifest.id,
            renderer=RendererRef(
                id=plugin.manifest.id,
                version=plugin.manifest.version,
                target=plugin.manifest.render_target,
                native_renderer=plugin.manifest.native_renderer,
                entry_url=entry_url,
            ),
            payload=VisualizationPayload(format=plugin.manifest.payload_format, data=data),
            presentation=VisualizationPresentation(
                title=str(kwargs.get("title") or "").strip()[:160],
                description=str(kwargs.get("description") or "").strip()[:1000],
                alt_text=str(kwargs.get("alt_text") or "").strip()[:2000],
            ),
            interaction=VisualizationInteraction(
                events=["prompt", "resize"] if plugin.manifest.render_target == "iframe" else [],
            ),
            fallback={"renderer": "svg"} if visualizer_id != "svg" else {},
        )
        context.metadata[VISUALIZATION_RESULT_KEY] = envelope.model_dump(mode="json")
        return ToolResult(
            content=(
                f"Visualization accepted as {visualizer_id}. The canvas payload is committed. "
                "Finish without repeating the payload."
            ),
            metadata={
                "visualizer": visualizer_id,
                "schema_version": envelope.schema_version,
                "visualization_submitted": True,
            },
        )


VISUALIZER_TOOL_TYPES: tuple[type[BaseTool], ...] = (SubmitVisualizationTool,)

__all__ = ["SubmitVisualizationTool", "VISUALIZER_TOOL_TYPES"]
