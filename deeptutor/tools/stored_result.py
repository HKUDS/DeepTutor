"""Read a character range from a tool result already stored for this session."""

from __future__ import annotations

from typing import Any

from deeptutor.agents.loop.stored_results import slice_stored
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult


class ReadStoredResultTool(BaseTool):
    """Slice a stored result. This never re-runs the tool that produced it."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_stored_result",
            description=(
                "Read a character range of a long tool result that was stored "
                "instead of being placed in full in the conversation. Pass the "
                "result_id from the preview, plus offset and limit. "
                "limit is capped to a share of this turn's model input window; "
                "the preview states that cap. "
                "Do not call the original tool again just to see the rest."
            ),
            parameters=[
                ToolParameter(
                    name="result_id",
                    type="string",
                    description="The result_id from the stored-result preview. Copy it verbatim.",
                ),
                ToolParameter(
                    name="offset",
                    type="integer",
                    required=False,
                    description="Character offset to start at. 0 is the beginning.",
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    required=False,
                    description=(
                        "How many characters to return. The server caps this "
                        "to a share of the current model's input window."
                    ),
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        store = kwargs.get("_stored_results")
        result_id = str(kwargs.get("result_id") or "").strip()
        if not isinstance(store, dict) or not store:
            return ToolResult(
                content="No stored results are available in this session.",
                success=False,
            )
        if not result_id:
            return ToolResult(content="result_id is required.", success=False)
        # The injected map contains only this session. An unknown id is not a
        # lookup into any other session.
        body = store.get(result_id)
        if not isinstance(body, str):
            return ToolResult(
                content=f"Unknown result_id {result_id!r} for this session.",
                success=False,
            )
        return ToolResult(
            content=slice_stored(
                body,
                kwargs.get("offset"),
                kwargs.get("limit"),
                max_chars=kwargs.get("_observation_chars"),
            ),
            metadata={"result_id": result_id},
            public_result={"content": "Stored result read privately."},
        )
