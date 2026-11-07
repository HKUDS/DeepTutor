"""
Tool registry — each tool owns its own prompt definition (YAML file).

The registry loads per-tool YAML files from a definitions directory,
maintains an ordered list of active tools, and composes the
``tools_description`` prompt variable for planner and solver agents.

Usage:
    registry = ToolRegistry.create_default(language="en")
    registry.unregister("web_search")          # disable a tool
    planner_desc = registry.build_planner_description(kb_name="physics")
    solver_desc  = registry.build_solver_description()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_SOLVER_GUIDELINE_HEADER = {
    "en": (
        "**Autonomously decide which tool to use** based on the nature "
        "of the sub-goal and the evidence gathered so far. Do not "
        "default to any single tool — consider all options:"
    ),
    "zh": (
        "**根据子目标的性质和已收集的证据，自主决定使用哪个工具**。"
        "不要默认只使用某一种工具 — 考虑所有选项："
    ),
}


@dataclass
class ToolDefinition:
    """Prompt-level definition of a single tool / control action."""

    name: str
    order: int = 0
    tool_type: str = "tool"  # "tool" | "control"

    # Planner prompt: one-liner
    planner_description: str = ""

    # Solver prompt: table row + optional guideline + optional note
    solver_when: str = ""
    solver_input: str = ""
    solver_guideline: str = ""
    solver_note: str = ""


class ToolRegistry:
    """Manages tool definitions and composes prompt fragments dynamically.

    Each tool has its own YAML definition file.  The registry loads them,
    maintains a sorted list, and provides methods to compose the
    ``{tools_description}`` template variable for planner and solver prompts.
    """

    def __init__(self, language: str = "en") -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self.language = language

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, tool: ToolDefinition) -> None:
        """Register (or replace) a tool definition."""
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s (type=%s)", tool.name, tool.tool_type)

    def unregister(self, name: str) -> None:
        """Remove a tool from the registry."""
        if self._tools.pop(name, None):
            logger.debug("Unregistered tool: %s", name)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    @property
    def _ordered(self) -> list[ToolDefinition]:
        return sorted(self._tools.values(), key=lambda t: t.order)

    @property
    def valid_actions(self) -> set[str]:
        """All registered action names (for response validation)."""
        return set(self._tools)

    @property
    def tool_names(self) -> list[str]:
        """Ordered list of registered tool names."""
        return [t.name for t in self._ordered]

    # ------------------------------------------------------------------
    # Prompt composition
    # ------------------------------------------------------------------

    def build_planner_description(self, kb_name: str = "") -> str:
        """One-liner list for the planner's ``{tools_description}`` variable."""
        lines: list[str] = []
        for tool in self._ordered:
            if tool.tool_type != "tool" or not tool.planner_description:
                continue
            desc = tool.planner_description
            if kb_name:
                desc = desc.replace(
                    "the uploaded knowledge base",
                    f'the knowledge base "{kb_name}"',
                )
                desc = desc.replace("the uploaded knowledge base", f'knowledge base "{kb_name}"')
            lines.append(f"- {tool.name}: {desc}")
        return "\n".join(lines)

    def build_solver_description(self) -> str:
        """Full tool section for the solver's ``{tools_description}`` variable.

        Includes: action table, tool-selection guidelines, tool-specific notes.
        """
        parts: list[str] = []
        ordered = self._ordered

        # --- action table ---
        table_lines = [
            "| action | When to use | action_input |",
            "|--------|------------|--------------|",
        ]
        for t in ordered:
            if t.solver_when:
                table_lines.append(
                    f"| `{t.name}` | {t.solver_when} | {t.solver_input} |"
                )
        parts.append("\n".join(table_lines))

        # --- tool-selection guidelines ---
        guidelines = [
            t for t in ordered if t.tool_type == "tool" and t.solver_guideline
        ]
        if guidelines:
            header = _SOLVER_GUIDELINE_HEADER.get(
                self.language, _SOLVER_GUIDELINE_HEADER["en"]
            )
            bullets = "\n".join(
                f"  - `{t.name}` {t.solver_guideline}" for t in guidelines
            )
            parts.append(f"{header}\n{bullets}")

        # --- tool-specific notes ---
        notes = [t for t in ordered if t.solver_note]
        if notes:
            parts.append("\n".join(f"- {t.solver_note}" for t in notes))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    @classmethod
    def load_from_directory(
        cls, directory: str | Path, language: str = "en",
    ) -> "ToolRegistry":
        """Load all ``*.yaml`` files from *directory* into a new registry."""
        registry = cls(language=language)
        directory = Path(directory)
        if not directory.is_dir():
            logger.warning("Tool definitions directory not found: %s", directory)
            return registry

        for yaml_file in sorted(directory.glob("*.yaml")):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                tool = cls._parse_definition(data)
                if tool:
                    registry.register(tool)
            except Exception as exc:
                logger.warning(
                    "Failed to load tool definition %s: %s", yaml_file.name, exc,
                )

        logger.info(
            "Loaded %d tool definitions from %s", len(registry._tools), directory,
        )
        return registry

    @classmethod
    def create_default(cls, language: str = "en") -> "ToolRegistry":
        """Load the default tool definitions shipped with the solve module."""
        definitions_dir = Path(__file__).parent / "definitions" / language
        if not definitions_dir.is_dir():
            definitions_dir = Path(__file__).parent / "definitions" / "en"
        return cls.load_from_directory(definitions_dir, language=language)

    @classmethod
    def create_from_names(
        cls,
        tool_names: list[str],
        language: str = "en",
    ) -> "ToolRegistry":
        """Load all default definitions, then keep only the listed tools.

        Control actions ``done`` and ``replan`` are always included.
        """
        registry = cls.create_default(language=language)
        keep = set(tool_names) | {"done", "replan"}
        for name in list(registry._tools):
            if name not in keep:
                registry.unregister(name)
        return registry

    @staticmethod
    def _parse_definition(data: dict) -> ToolDefinition | None:
        name = data.get("name")
        if not name:
            return None
        solver = data.get("solver") or {}
        return ToolDefinition(
            name=name,
            order=data.get("order", 99),
            tool_type=data.get("type", "tool"),
            planner_description=data.get("planner_description", ""),
            solver_when=solver.get("when_to_use", ""),
            solver_input=solver.get("action_input", ""),
            solver_guideline=solver.get("guideline", ""),
            solver_note=solver.get("note", ""),
        )
