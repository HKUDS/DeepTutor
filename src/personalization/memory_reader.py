from __future__ import annotations

import contextvars
import logging
from typing import Any, Optional

from .trace_forest import TraceForest
from .trace_tree import TraceNode

logger = logging.getLogger(__name__)

# Contextvar for workspace-scoped MemoryReader (used by simulator tools)
_workspace_reader_var: contextvars.ContextVar[Optional["MemoryReader"]] = (
    contextvars.ContextVar("_workspace_reader", default=None)
)
# Contextvar to explicitly disable memory reads in a request scope.
_workspace_memory_disabled_var: contextvars.ContextVar[bool] = (
    contextvars.ContextVar("_workspace_memory_disabled", default=False)
)


class MemoryReader:
    """Build role-specific memory contexts for solve/question agents.

    Reads from:
    * Trace forest (semantic search for relevant historical nodes)
    * ``memory.md`` — session summaries produced by SummaryAgent
    * ``weakness.md`` — knowledge weak points produced by WeaknessAgent
    * ``reflection.md`` — system quality reflection by ReflectionAgent
    """

    def __init__(
        self,
        forest: Optional[TraceForest] = None,
        max_items: int = 3,
    ) -> None:
        self._forest = forest or TraceForest()
        self._max_items = max(1, max_items)

    # ------------------------------------------------------------------
    # Context builders for different agent roles
    # ------------------------------------------------------------------

    async def get_planner_context(self, question: str) -> str:
        """Context for the planner: session history + trace search."""
        try:
            search_results = await self._forest.semantic_search(
                query=question, top_k=self._max_items,
            )
            lines: list[str] = []
            for idx, hit in enumerate(search_results, 1):
                lines.append(
                    f"{idx}. [{hit.get('node_type', '?')}] {hit.get('text', '')}"
                )

            memory_md = self._read_doc("memory.md")
            if memory_md:
                lines.append("\nSession History (from memory.md):")
                for line in memory_md.splitlines()[-20:]:
                    if line.strip():
                        lines.append(f"  {line}")

            weakness_md = self._read_doc("weakness.md")
            weak_ctx = self._extract_weakness_summary(weakness_md)
            body = "\n".join(lines) if lines else "(no similar historical traces)"
            result = f"{body}\n\n{weak_ctx}".strip()
            logger.info(
                "[MEM-READ] get_planner_context: hits=%d, total_len=%d",
                len(search_results), len(result),
            )
            return result
        except Exception:
            return ""

    async def get_solver_context(self, step_goal: str) -> str:
        """Context for the solver: weakness info + related trace notes."""
        try:
            search_results = await self._forest.semantic_search(
                query=step_goal, top_k=self._max_items,
            )
            notes: list[str] = []
            for hit in search_results:
                text = hit.get("text", "")
                if text:
                    notes.append(text)

            weakness_md = self._read_doc("weakness.md")
            if weakness_md:
                notes.append("[Weakness context]")
                for line in weakness_md.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("- **") or stripped.startswith("  -"):
                        notes.append(stripped)

            if not notes:
                logger.debug("[MEM-READ] get_solver_context: no notes for '%s'", step_goal[:60])
                return ""
            dedup = self._dedup_keep_order(notes)
            result = "\n".join(f"- {item}" for item in dedup[:8])
            logger.info(
                "[MEM-READ] get_solver_context: hits=%d, notes=%d",
                len(search_results), len(dedup),
            )
            return result
        except Exception:
            return ""

    def get_writer_context(self) -> str:
        """Context for the writer: reflection + weakness summary."""
        try:
            parts: list[str] = []
            reflection_md = self._read_doc("reflection.md")
            if reflection_md:
                lines = [l for l in reflection_md.splitlines()[-15:] if l.strip()]
                if lines:
                    parts.append("Recent reflections:\n" + "\n".join(f"  {l}" for l in lines))

            weakness_md = self._read_doc("weakness.md")
            weak_text = self._extract_weakness_summary(weakness_md)
            if weak_text and "none" not in weak_text.lower():
                parts.append(weak_text)

            result = "\n\n".join(parts)
            if result:
                logger.info("[MEM-READ] get_writer_context: len=%d", len(result))
            return result
        except Exception:
            return ""

    async def get_idea_context(self, topic: str) -> str:
        """Context for question idea generation."""
        try:
            search_results = await self._forest.semantic_search(
                query=topic, top_k=self._max_items, level=1,
            )
            lines: list[str] = []
            for idx, hit in enumerate(search_results, 1):
                lines.append(f"{idx}. Similar topic: {hit.get('text', '')}")
                tree = self._forest.load_tree(hit.get("trace_id", ""))
                if tree:
                    parent_id = hit.get("short_id", "")
                    parent_node = tree.nodes.get(parent_id)
                    if parent_node:
                        for child_id in parent_node.children:
                            child = tree.nodes.get(child_id)
                            if child and child.node_type == "template":
                                conc = child.data.get("concentration", child.text)
                                diff = child.data.get("difficulty", "?")
                                lines.append(f"   - [{diff}] {conc}")

            weakness_md = self._read_doc("weakness.md")
            weak_text = self._extract_weakness_summary(weakness_md)
            history_text = "\n".join(lines) if lines else "Historical question traces: (none)"
            result = f"{weak_text}\n\n{history_text}".strip()
            logger.info("[MEM-READ] get_idea_context: hits=%d", len(search_results))
            return result
        except Exception:
            return ""

    async def get_evaluator_context(self, topic: str) -> str:
        """Context for question evaluation."""
        try:
            search_results = await self._forest.semantic_search(
                query=topic, top_k=self._max_items, level=1,
            )
            concentrations: list[str] = []
            for hit in search_results:
                tree = self._forest.load_tree(hit.get("trace_id", ""))
                if not tree:
                    continue
                parent_node = tree.nodes.get(hit.get("short_id", ""))
                if not parent_node:
                    continue
                for child_id in parent_node.children:
                    child = tree.nodes.get(child_id)
                    if child and child.node_type == "template":
                        c = str(child.data.get("concentration", "") or child.text).strip()
                        if c:
                            concentrations.append(c)
            concentrations = self._dedup_keep_order(concentrations)[:8]

            parts: list[str] = []
            if concentrations:
                parts.append("Historical coverage:\n" + "\n".join(f"- {c}" for c in concentrations))
            else:
                parts.append("Historical coverage: (none)")

            result = "\n\n".join(parts).strip()
            logger.info("[MEM-READ] get_evaluator_context: concentrations=%d", len(concentrations))
            return result
        except Exception:
            return ""

    async def get_generator_context(self, concentration: str) -> str:
        """Context for question generation: historical wrong answers."""
        try:
            search_results = await self._forest.semantic_search(
                query=concentration, top_k=self._max_items, level=3,
            )
            patterns: list[str] = []
            for hit in search_results:
                tree = self._forest.load_tree(hit.get("trace_id", ""))
                if not tree:
                    continue
                node = tree.nodes.get(hit.get("short_id", ""))
                if not node or node.node_type != "answer":
                    continue
                judged = str(node.data.get("judged_result", "") or "unknown")
                if judged.lower() in {"wrong", "incorrect", "false"}:
                    patterns.append(node.text)

            patterns = self._dedup_keep_order([p.strip() for p in patterns if p.strip()])
            if not patterns:
                return ""
            return "Historical wrong-answer patterns:\n" + "\n".join(
                f"- {p[:180]}" for p in patterns[:5]
            )
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_doc(self, filename: str) -> str:
        """Read a document from the memory directory."""
        path = self._forest.memory_dir / filename
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _extract_weakness_summary(self, weakness_content: str | None) -> str:
        if not weakness_content:
            return "Weak points: (none)"
        lines: list[str] = []
        for line in weakness_content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- **"):
                lines.append(stripped)
        if lines:
            return "Weak points:\n" + "\n".join(lines[:5])
        return "Weak points: (none)"

    @staticmethod
    def _note_from_node(node: TraceNode) -> str:
        self_note = str(node.data.get("self_note", "") or "").strip()
        if self_note:
            return self_note
        return str(node.text or "").strip()

    @staticmethod
    def _dedup_keep_order(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            key = item.strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result


# =========================================================================
# Module-level shared accessor
# =========================================================================

_cached_reader: Optional[MemoryReader] = None


def get_memory_reader_instance() -> Optional[MemoryReader]:
    """Shared lazy accessor for MemoryReader.

    When a workspace-scoped reader is set via ``_workspace_reader_var``
    (e.g. by the simulator tools), it takes priority over the global
    singleton so that all agents read from the correct workspace.
    """
    if _workspace_memory_disabled_var.get(False):
        return None

    ws_reader = _workspace_reader_var.get(None)
    if ws_reader is not None:
        return ws_reader

    global _cached_reader
    if _cached_reader is not None:
        return _cached_reader
    try:
        from .service import get_personalization_service
        _cached_reader = get_personalization_service().get_memory_reader()
        return _cached_reader
    except Exception:
        logger.debug("get_memory_reader_instance: service not available")
        return None
