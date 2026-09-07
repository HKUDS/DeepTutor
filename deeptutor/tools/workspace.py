"""Universal tools for inspecting and presenting the active content workspace."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.services.workspace import WorkspaceError, get_content_workspace_service


def _binding(kwargs: dict[str, Any]):
    service = get_content_workspace_service()
    workspace_id = str(kwargs.get("_workspace_id") or "")
    return service, (
        service.binding_by_id(workspace_id) if workspace_id else service.current_binding()
    )


def _failure(exc: WorkspaceError) -> ToolResult:
    return ToolResult(content=str(exc), success=False, metadata={"workspace_error": str(exc)})


class WorkspaceListTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_list",
            description=(
                "List files and folders in the user's active workspace using relative paths. "
                "Use this before claiming that a local file is unavailable."
            ),
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Workspace-relative directory; defaults to the workspace root.",
                    required=False,
                ),
                ToolParameter(
                    name="depth",
                    type="integer",
                    description="Directory depth to include, from 1 to 5.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Maximum number of entries, up to 1000.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            service, binding = _binding(kwargs)
            page = await asyncio.to_thread(
                service.list_entries_page,
                binding,
                str(kwargs.get("path") or "."),
                depth=int(kwargs.get("depth") or 1),
                limit=int(kwargs.get("limit") or 200),
            )
        except WorkspaceError as exc:
            return _failure(exc)
        return ToolResult(
            content=json.dumps(page, ensure_ascii=False, indent=2),
            metadata={"workspace_id": binding.workspace_id, **page},
        )


class WorkspaceReadTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_read",
            description=(
                "Read a UTF-8 text file from the user's active workspace. Paths are relative "
                "to the workspace; use workspace_list or workspace_search to discover them."
            ),
            parameters=[
                ToolParameter(
                    name="path", type="string", description="Workspace-relative file path."
                ),
                ToolParameter(
                    name="offset",
                    type="integer",
                    description="Character offset for paginated reads.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Maximum characters to return, up to 100000.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            service, binding = _binding(kwargs)
            result = await asyncio.to_thread(
                service.read_text,
                binding,
                str(kwargs.get("path") or ""),
                offset=int(kwargs.get("offset") or 0),
                limit=int(kwargs.get("limit") or 20_000),
            )
        except WorkspaceError as exc:
            return _failure(exc)
        content = result.pop("content")
        return ToolResult(content=content, metadata={"workspace_read": result})


class WorkspaceSearchTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_search",
            description="Search filenames and UTF-8 text inside the user's active workspace.",
            parameters=[
                ToolParameter(name="query", type="string", description="Text to find."),
                ToolParameter(
                    name="path",
                    type="string",
                    description="Workspace-relative directory to search; defaults to root.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Maximum matches, up to 200.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            service, binding = _binding(kwargs)
            page = await asyncio.to_thread(
                service.search_page,
                binding,
                str(kwargs.get("query") or ""),
                path=str(kwargs.get("path") or "."),
                limit=int(kwargs.get("limit") or 50),
            )
        except WorkspaceError as exc:
            return _failure(exc)
        return ToolResult(
            content=json.dumps(page, ensure_ascii=False, indent=2),
            metadata={"workspace_id": binding.workspace_id, **page},
        )


class WorkspacePresentTool(BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_present",
            description=(
                "Present one or more workspace files to the user as openable previews/cards. "
                "Call this before linking a relative file path in Markdown. The returned path "
                "must be copied exactly into the final Markdown link."
            ),
            raw_parameters={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {
                                    "type": "string",
                                    "description": "Exact workspace-relative file path.",
                                },
                                "title": {"type": "string"},
                                "caption": {"type": "string"},
                            },
                            "required": ["path"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["items"],
                "additionalProperties": False,
            },
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        raw_items = kwargs.get("items")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
            return ToolResult(
                content="workspace_present requires between 1 and 20 items.", success=False
            )
        if any(not isinstance(item, dict) for item in raw_items):
            return ToolResult(
                content="Every workspace_present item must be an object.", success=False
            )
        try:
            service, binding = _binding(kwargs)
            items = await asyncio.to_thread(service.publish, binding, raw_items)
        except WorkspaceError as exc:
            return _failure(exc)
        rows = [item.to_dict() for item in items]
        lines = [
            f"Presented `{item.relative_path}`. Use exactly this relative path in Markdown."
            for item in items
        ]
        return ToolResult(
            content="\n".join(lines),
            sources=[{"type": "workspace_item", **row} for row in rows],
            metadata={"workspace_items": rows},
        )


class WorkspaceExportTool(BaseTool):
    """Request one explicit user-authorized copy outside ``outputs/``."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_export",
            description=(
                "Ask the user to authorize one exact copy of a generated file from outputs/ "
                "to another relative path in their workspace. Use only when the user asked "
                "to save or overwrite a specific workspace file. This never grants general "
                "write access and the copy is not performed until the user approves the card."
            ),
            parameters=[
                ToolParameter(
                    name="source_path",
                    type="string",
                    description="Exact workspace-relative source path under outputs/.",
                ),
                ToolParameter(
                    name="destination_path",
                    type="string",
                    description="Exact workspace-relative destination outside outputs/.",
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description="Short explanation shown to the user.",
                ),
                ToolParameter(
                    name="overwrite",
                    type="boolean",
                    description="Whether this approved operation may replace an existing file.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            service, binding = _binding(kwargs)
            request = await asyncio.to_thread(
                service.validate_export,
                binding,
                source_path=str(kwargs.get("source_path") or ""),
                destination_path=str(kwargs.get("destination_path") or ""),
                overwrite=bool(kwargs.get("overwrite", False)),
            )
        except WorkspaceError as exc:
            return _failure(exc)

        from deeptutor.tools.ask_user import build_ask_user_payload

        language = str(kwargs.get("_language") or "en").lower()
        chinese = language.startswith("zh")
        allow_label = "仅此次允许" if chinese else "Allow once"
        deny_label = "拒绝" if chinese else "Deny"
        action = "覆盖" if request["overwrite"] else "复制"
        prompt = (
            f"DeepTutor 请求将 `{request['source_path']}` {action}到 "
            f"`{request['destination_path']}`。是否仅允许这一次写入？"
            if chinese
            else (
                f"DeepTutor requests one {'overwrite' if request['overwrite'] else 'copy'} from "
                f"`{request['source_path']}` to `{request['destination_path']}`. Allow this "
                "single write?"
            )
        )
        reason = str(kwargs.get("reason") or "").strip()[:400]
        payload, error = build_ask_user_payload(
            intro=reason or None,
            questions=[
                {
                    "id": "workspace_export_authorization",
                    "header": "写入授权" if chinese else "Write access",
                    "prompt": prompt,
                    "options": [
                        {
                            "label": allow_label,
                            "description": (
                                "只执行卡片中列出的这一次操作。"
                                if chinese
                                else "Perform only the exact operation shown above."
                            ),
                        },
                        {
                            "label": deny_label,
                            "description": (
                                "不写入目标路径。"
                                if chinese
                                else "Do not write to the destination."
                            ),
                        },
                    ],
                    "allow_free_text": False,
                }
            ],
        )
        if payload is None:
            return ToolResult(
                content=error or "Could not create authorization request.", success=False
            )
        payload_dict = payload.to_dict()
        request["allow_label"] = allow_label
        request["question_id"] = "workspace_export_authorization"
        return ToolResult(
            content="[awaiting one-time workspace write authorization]",
            metadata={"ask_user": payload_dict, "workspace_export": request},
            pause_for_user=payload_dict,
        )


__all__ = [
    "WorkspaceExportTool",
    "WorkspaceListTool",
    "WorkspacePresentTool",
    "WorkspaceReadTool",
    "WorkspaceSearchTool",
]
