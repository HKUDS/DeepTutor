# -*- coding: utf-8 -*-
"""
Trace Toolkit
=============

Five tools for memory agents to explore the trace forest and manage
documents.  Each tool is an async method on :class:`TraceToolkit`.  The
:class:`ReActRunner` dispatches action strings to these methods.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .trace_forest import TraceForest

logger = logging.getLogger(__name__)

TOOL_NAMES = frozenset({
    "search_traces",
    "list_traces",
    "get_trace_detail",
    "read_document",
    "write_document",
})


class TraceToolkit:
    """Expose five tools for memory agents.

    Parameters
    ----------
    forest:
        The shared :class:`TraceForest` instance.
    memory_dir:
        Root directory for memory documents (``reflection.md``, etc.).
        Defaults to ``forest.memory_dir``.
    """

    def __init__(
        self,
        forest: TraceForest,
        memory_dir: Path | None = None,
    ) -> None:
        self._forest = forest
        self._memory_dir = memory_dir or forest.memory_dir

    # ------------------------------------------------------------------
    # Dispatcher
    # ------------------------------------------------------------------

    async def call(self, tool: str, params: dict[str, Any]) -> str:
        """Dispatch a tool call and return the observation string."""
        if tool not in TOOL_NAMES:
            return f"[error] Unknown tool: {tool}"
        try:
            handler = getattr(self, tool)
            return await handler(**params)
        except TypeError as exc:
            return f"[error] Bad parameters for {tool}: {exc}"
        except Exception as exc:
            logger.warning("Tool %s failed: %s", tool, exc, exc_info=True)
            return f"[error] {tool} failed: {exc}"

    # ------------------------------------------------------------------
    # Tool 1: search_traces
    # ------------------------------------------------------------------

    async def search_traces(
        self,
        query: str,
        trace_type: str | None = None,
        level: int | None = None,
        top_k: int = 5,
    ) -> str:
        """Semantic search across all historical trace nodes."""
        results = await self._forest.semantic_search(
            query=query,
            top_k=top_k,
            level=level,
            trace_type=trace_type,
        )
        if not results:
            return "(no matching nodes found)"
        lines: list[str] = []
        for r in results:
            action_tag = f" [{r['action']}]" if r.get("action") else ""
            parent_tag = f" parent={r['parent_short_id']}" if r.get("parent_short_id") else ""
            lines.append(
                f"- [{r['short_id']}] ({r['node_type']}{action_tag}) "
                f"trace={r['trace_id']}{parent_tag}\n"
                f"  {r['text']}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tool 2: list_traces
    # ------------------------------------------------------------------

    async def list_traces(
        self,
        n: int = 10,
        trace_type: str | None = None,
    ) -> str:
        """List recent traces sorted by time (newest first)."""
        traces = self._forest.list_recent_traces(n=n, trace_type=trace_type)
        if not traces:
            return "(no traces found)"
        lines: list[str] = []
        for t in traces:
            ts = str(t.get("timestamp", ""))[:16].replace("T", " ")
            stats = t.get("stats", {})
            stats_str = ", ".join(f"{k}={v}" for k, v in stats.items()) if stats else ""
            tools = ", ".join(t.get("tools_used", [])) or "none"
            lines.append(
                f"- [{t['trace_id']}] {t.get('trace_type', '')} | {ts}\n"
                f"  Question: {t.get('root_text', '')}\n"
                f"  Answer: {t.get('answer_path', '(none)')}\n"
                f"  Tools: {tools} | Stats: {stats_str}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Tool 3: get_trace_detail
    # ------------------------------------------------------------------

    async def get_trace_detail(
        self,
        trace_id: str | None = None,
        short_id: str | None = None,
    ) -> str:
        """Load full trace outline *or* single node detail.

        * Pass only ``trace_id`` → compact text overview of the whole tree.
        * Pass ``trace_id`` + ``short_id`` → full detail of one node.
        """
        if not trace_id:
            return "[error] trace_id is required"

        tree = self._forest.load_tree(trace_id)
        if tree is None:
            return f"[error] trace {trace_id} not found"

        if not short_id:
            return tree.compact_text(max_chars=6000)

        node = tree.nodes.get(short_id)
        if node is None:
            return f"[error] node {short_id} not found in trace {trace_id}"

        parts: list[str] = [
            f"Node: [{node.short_id}] ({node.node_type}) in trace {trace_id}",
        ]
        if node.parent:
            parent_node = tree.nodes.get(node.parent)
            parent_text = parent_node.text[:80] if parent_node else "?"
            parts.append(f"Parent: [{node.parent}] {parent_text}")
        if node.children:
            parts.append(f"Children: {', '.join(f'[{c}]' for c in node.children)}")
        parts.append(f"Text: {node.text}")
        if node.action:
            parts.append(f"Action: {node.action}")

        data = node.data
        if data:
            for key in ("thought", "action_input", "self_note"):
                val = data.get(key, "")
                if val:
                    parts.append(f"{key}: {val}")
            observation = data.get("observation", "")
            if observation:
                parts.append(f"observation: {observation[:1500]}")
            sources = data.get("sources", [])
            if sources:
                src_strs = []
                for s in sources[:5]:
                    if isinstance(s, dict):
                        src_strs.append(
                            f"{s.get('type', '?')}:{s.get('file', s.get('value', '?'))}"
                        )
                parts.append(f"sources: {', '.join(src_strs)}")

            for key in ("status", "step_goal", "difficulty", "concentration",
                         "question_type", "judged_result", "question"):
                val = data.get(key, "")
                if val:
                    parts.append(f"{key}: {val}")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Tool 4: read_document
    # ------------------------------------------------------------------

    async def read_document(
        self,
        filename: str | None = None,
        path: str | None = None,
    ) -> str:
        """Read a .md file from memory directory or an absolute path."""
        if path:
            target = Path(path)
        elif filename:
            target = self._memory_dir / filename
        else:
            return "[error] filename or path is required"

        if not target.exists():
            return "(document not found)"
        try:
            content = target.read_text(encoding="utf-8")
            return content if content.strip() else "(document is empty)"
        except Exception as exc:
            return f"[error] Failed to read {target}: {exc}"

    # ------------------------------------------------------------------
    # Tool 5: write_document
    # ------------------------------------------------------------------

    async def write_document(
        self,
        filename: str,
        content: str,
        mode: str = "append",
    ) -> str:
        """Write or append to a .md file in the memory directory."""
        target = self._memory_dir / filename
        try:
            if mode == "overwrite":
                target.write_text(content, encoding="utf-8")
            else:
                existing = ""
                if target.exists():
                    existing = target.read_text(encoding="utf-8")
                if existing.strip():
                    new_content = existing.rstrip() + "\n\n" + content
                else:
                    new_content = content
                target.write_text(new_content, encoding="utf-8")
            logger.info("[TOOL] write_document: %s (mode=%s)", filename, mode)
            return "ok"
        except Exception as exc:
            return f"[error] Failed to write {filename}: {exc}"
