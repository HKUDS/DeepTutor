"""Workspace file tools for chat skill/script workflows."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.tools.prompting import load_prompt_hints


def _resolve_workspace_path(path: str, workspace: str, allowed_dir: str) -> Path:
    if not workspace or not allowed_dir:
        raise PermissionError("workspace file tools are not available for this turn")
    raw = Path(str(path or ".")).expanduser()
    root = Path(workspace).expanduser().resolve()
    allowed = Path(allowed_dir).expanduser().resolve()
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise PermissionError(f"path is outside the turn workspace: {path}") from exc
    return resolved


class _WorkspaceTool(BaseTool):
    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)

    @staticmethod
    def _resolve(kwargs: dict[str, Any], path: str) -> Path:
        return _resolve_workspace_path(
            path,
            str(kwargs.get("_workspace_dir") or ""),
            str(kwargs.get("_allowed_dir") or ""),
        )


class ReadFileTool(_WorkspaceTool):
    _DEFAULT_LIMIT = 2000
    _MAX_CHARS = 128_000

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_file",
            description="Read a text file from this turn's workspace with line pagination.",
            parameters=[
                ToolParameter(name="path", type="string", description="Path inside the workspace."),
                ToolParameter(
                    name="offset",
                    type="integer",
                    description="1-indexed line number to start from.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Maximum lines to return.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs.get("path") or "")
        try:
            fp = self._resolve(kwargs, path)
            if not fp.exists():
                return ToolResult(content=f"Error: file not found: {path}", success=False)
            if not fp.is_file():
                return ToolResult(content=f"Error: not a file: {path}", success=False)
            try:
                offset = max(1, int(kwargs.get("offset") or 1))
            except (TypeError, ValueError):
                offset = 1
            try:
                limit = max(1, int(kwargs.get("limit") or self._DEFAULT_LIMIT))
            except (TypeError, ValueError):
                limit = self._DEFAULT_LIMIT
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            if total == 0:
                return ToolResult(content=f"(empty file: {path})")
            if offset > total:
                return ToolResult(
                    content=f"Error: offset {offset} is beyond end of file ({total} lines)",
                    success=False,
                )
            start = offset - 1
            end = min(start + limit, total)
            numbered = [f"{start + i + 1}| {line}" for i, line in enumerate(lines[start:end])]
            text = "\n".join(numbered)
            if len(text) > self._MAX_CHARS:
                text = text[: self._MAX_CHARS].rstrip() + "\n...[truncated]"
            suffix = (
                f"\n\n(showing lines {offset}-{end} of {total}; use offset={end + 1} to continue)"
                if end < total
                else f"\n\n(end of file; {total} lines total)"
            )
            return ToolResult(content=text + suffix)
        except PermissionError as exc:
            return ToolResult(content=f"Error: {exc}", success=False)
        except Exception as exc:
            return ToolResult(content=f"Error reading file: {exc}", success=False)


class WriteFileTool(_WorkspaceTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_file",
            description="Write a UTF-8 text file inside this turn's workspace.",
            parameters=[
                ToolParameter(name="path", type="string", description="Path inside the workspace."),
                ToolParameter(name="content", type="string", description="File contents."),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs.get("path") or "")
        content = str(kwargs.get("content") or "")
        try:
            fp = self._resolve(kwargs, path)
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return ToolResult(content=f"Successfully wrote {len(content)} bytes to {fp.name}")
        except PermissionError as exc:
            return ToolResult(content=f"Error: {exc}", success=False)
        except Exception as exc:
            return ToolResult(content=f"Error writing file: {exc}", success=False)


class EditFileTool(_WorkspaceTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="edit_file",
            description="Edit a workspace text file by replacing old_text with new_text.",
            parameters=[
                ToolParameter(name="path", type="string", description="Path inside the workspace."),
                ToolParameter(name="old_text", type="string", description="Text to replace."),
                ToolParameter(name="new_text", type="string", description="Replacement text."),
                ToolParameter(
                    name="replace_all",
                    type="boolean",
                    description="Replace all occurrences instead of one.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs.get("path") or "")
        old_text = str(kwargs.get("old_text") or "")
        new_text = str(kwargs.get("new_text") or "")
        replace_all = bool(kwargs.get("replace_all") or False)
        try:
            fp = self._resolve(kwargs, path)
            if not fp.exists():
                return ToolResult(content=f"Error: file not found: {path}", success=False)
            content = fp.read_text(encoding="utf-8", errors="replace")
            if old_text not in content:
                return ToolResult(
                    content=_not_found_message(path, old_text, content),
                    success=False,
                )
            count = content.count(old_text)
            if count > 1 and not replace_all:
                return ToolResult(
                    content=(
                        f"Warning: old_text appears {count} times. Provide more context "
                        "or set replace_all=true."
                    ),
                    success=False,
                )
            updated = (
                content.replace(old_text, new_text)
                if replace_all
                else content.replace(old_text, new_text, 1)
            )
            fp.write_text(updated, encoding="utf-8")
            return ToolResult(content=f"Successfully edited {fp.name}")
        except PermissionError as exc:
            return ToolResult(content=f"Error: {exc}", success=False)
        except Exception as exc:
            return ToolResult(content=f"Error editing file: {exc}", success=False)


class ListDirTool(_WorkspaceTool):
    _DEFAULT_MAX = 200
    _IGNORE = {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".pytest_cache",
        ".ruff_cache",
    }

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_dir",
            description="List files under this turn's workspace.",
            parameters=[
                ToolParameter(
                    name="path",
                    type="string",
                    description="Directory path inside the workspace.",
                    required=False,
                    default=".",
                ),
                ToolParameter(
                    name="recursive",
                    type="boolean",
                    description="Recursively list nested paths.",
                    required=False,
                ),
                ToolParameter(
                    name="max_entries",
                    type="integer",
                    description="Maximum entries to return.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = str(kwargs.get("path") or ".")
        recursive = bool(kwargs.get("recursive") or False)
        try:
            cap = max(1, int(kwargs.get("max_entries") or self._DEFAULT_MAX))
        except (TypeError, ValueError):
            cap = self._DEFAULT_MAX
        try:
            dp = self._resolve(kwargs, path)
            if not dp.exists():
                return ToolResult(content=f"Error: directory not found: {path}", success=False)
            if not dp.is_dir():
                return ToolResult(content=f"Error: not a directory: {path}", success=False)
            items: list[str] = []
            total = 0
            iterator = dp.rglob("*") if recursive else dp.iterdir()
            for item in sorted(iterator):
                if any(part in self._IGNORE for part in item.relative_to(dp).parts):
                    continue
                total += 1
                if len(items) < cap:
                    rel = item.relative_to(dp)
                    items.append(f"{rel}/" if item.is_dir() else str(rel))
            if not items and total == 0:
                return ToolResult(content=f"Directory {path} is empty")
            text = "\n".join(items)
            if total > cap:
                text += f"\n\n(truncated, showing first {cap} of {total} entries)"
            return ToolResult(content=text)
        except PermissionError as exc:
            return ToolResult(content=f"Error: {exc}", success=False)
        except Exception as exc:
            return ToolResult(content=f"Error listing directory: {exc}", success=False)


def _not_found_message(path: str, old_text: str, content: str) -> str:
    lines = content.splitlines(keepends=True)
    old_lines = old_text.splitlines(keepends=True)
    window = max(1, len(old_lines))
    best_ratio = 0.0
    best_start = 0
    for idx in range(max(1, len(lines) - window + 1)):
        ratio = difflib.SequenceMatcher(None, old_lines, lines[idx : idx + window]).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = idx
    if best_ratio > 0.5:
        diff = "\n".join(
            difflib.unified_diff(
                old_lines,
                lines[best_start : best_start + window],
                fromfile="old_text",
                tofile=f"{path} actual line {best_start + 1}",
                lineterm="",
            )
        )
        return f"Error: old_text not found. Best match ({best_ratio:.0%} similar):\n{diff}"
    return "Error: old_text not found. Verify the file content."


__all__ = ["EditFileTool", "ListDirTool", "ReadFileTool", "WriteFileTool"]
