"""Prompt hint loading and rendering helpers for tools."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import yaml

from deeptutor.core.tool_protocol import ToolAlias, ToolPromptHints

ToolHintEntry = tuple[str, ToolPromptHints]

_GUIDELINE_HEADER = {
    "en": (
        "**Autonomously decide which tool to use** based on the current sub-goal "
        "and the evidence gathered so far. Consider all available options:"
    ),
    "zh": ("**根据当前子目标和已收集的证据，自主决定使用哪个工具**。请综合考虑所有可用选项："),
}

_PHASE_LABELS = {
    "en": {
        "exploration": "Phase 1: Exploration",
        "expansion": "Phase 2: Expansion",
        "synthesis": "Phase 3: Synthesis",
        "verification": "Phase 4: Verification",
        "other": "Other Tools",
    },
    "zh": {
        "exploration": "阶段 1：基础探索",
        "expansion": "阶段 2：扩展补充",
        "synthesis": "阶段 3：综合推理",
        "verification": "阶段 4：验证核查",
        "other": "其他工具",
    },
}

_PHASE_ORDER = ["exploration", "expansion", "synthesis", "verification", "other"]


def _normalize_language(language: str) -> str:
    normalized = language.lower()
    if normalized.startswith("zh"):
        return "zh"
    if normalized.startswith("en"):
        return "en"
    return normalized


def load_prompt_hints(tool_name: str, language: str = "en") -> ToolPromptHints:
    """Load per-tool prompt hints from YAML with zh/en fallback."""
    normalized_language = _normalize_language(language)
    base_dir = Path(__file__).parent / "hints"
    candidates = [base_dir / normalized_language / f"{tool_name}.yaml"]
    if normalized_language != "en":
        candidates.append(base_dir / "en" / f"{tool_name}.yaml")

    for path in candidates:
        if not path.is_file():
            continue
        with open(path, encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        aliases = [
            ToolAlias(
                name=str(item.get("name", "")).strip(),
                description=str(item.get("description", "")).strip(),
                input_format=str(item.get("input_format", "")).strip(),
                when_to_use=str(item.get("when_to_use", "")).strip(),
                phase=str(item.get("phase", "")).strip(),
            )
            for item in data.get("aliases", [])
            if str(item.get("name", "")).strip()
        ]
        return ToolPromptHints(
            short_description=str(data.get("short_description", "")).strip(),
            when_to_use=str(data.get("when_to_use", "")).strip(),
            input_format=str(data.get("input_format", "")).strip(),
            guideline=str(data.get("guideline", "")).strip(),
            note=str(data.get("note", "")).strip(),
            phase=str(data.get("phase", "")).strip(),
            aliases=aliases,
        )

    return ToolPromptHints()


class ToolPromptComposer:
    """Render prompt metadata into reusable prompt fragments."""

    def __init__(self, language: str = "en") -> None:
        self.language = _normalize_language(language)

    def format_list(self, hints: list[ToolHintEntry]) -> str:
        lines: list[str] = []
        for name, hint in hints:
            if hint.short_description:
                lines.append(f"- {name}: {hint.short_description}")
        return "\n".join(lines)

    def format_list_with_usage(self, hints: list[ToolHintEntry]) -> str:
        """Per-tool bullet that includes ``when_to_use`` and ``input_format``.

        Used by the chat persona prompt so the LLM has enough per-tool
        guidance to decide *whether* to call it, not just *what it is*.
        Tools without a ``short_description`` are skipped entirely so the
        block never carries empty bullets.
        """
        when_label = "When to use" if self.language != "zh" else "适用场景"
        input_label = "Input" if self.language != "zh" else "参数格式"
        blocks: list[str] = []
        for name, hint in hints:
            if not hint.short_description:
                continue
            entry: list[str] = [f"- `{name}` — {hint.short_description}"]
            if hint.when_to_use:
                entry.append(f"    {when_label}: {hint.when_to_use}")
            if hint.input_format:
                entry.append(f"    {input_label}: {hint.input_format}")
            blocks.append("\n".join(entry))
        return "\n".join(blocks)

    def format_table(
        self,
        hints: list[ToolHintEntry],
        control_actions: list[dict[str, str]] | None = None,
    ) -> str:
        parts: list[str] = []
        table_lines = [
            "| action | When to use | action_input |",
            "|--------|------------|--------------|",
        ]
        for name, hint in hints:
            if hint.when_to_use or hint.input_format:
                table_lines.append(f"| `{name}` | {hint.when_to_use} | {hint.input_format} |")
        for control in control_actions or []:
            table_lines.append(
                f"| `{control['name']}` | {control['when_to_use']} | {control['input_format']} |"
            )
        parts.append("\n".join(table_lines))

        guidelines = [f"  - `{name}` {hint.guideline}" for name, hint in hints if hint.guideline]
        if guidelines:
            header = _GUIDELINE_HEADER.get(self.language, _GUIDELINE_HEADER["en"])
            parts.append(f"{header}\n" + "\n".join(guidelines))

        notes = [f"- {hint.note}" for _, hint in hints if hint.note]
        if notes:
            parts.append("\n".join(notes))

        return "\n\n".join(parts)

    def format_aliases(self, hints: list[ToolHintEntry]) -> str:
        lines: list[str] = []
        for name, hint in hints:
            if hint.aliases:
                for alias in hint.aliases:
                    description = alias.description or hint.short_description
                    input_format = alias.input_format or hint.input_format or "Natural language"
                    lines.append(f"- {alias.name}: {description} | Query format: {input_format}")
                continue
            if hint.short_description:
                lines.append(
                    f"- {name}: {hint.short_description} | Query format: {hint.input_format or 'Natural language'}"
                )
        return "\n".join(lines)

    def format_phased(self, hints: list[ToolHintEntry]) -> str:
        grouped: OrderedDict[str, list[str]] = OrderedDict((phase, []) for phase in _PHASE_ORDER)
        for name, hint in hints:
            phase = hint.phase or "other"
            grouped.setdefault(phase, [])
            if hint.aliases:
                for alias in hint.aliases:
                    alias_phase = alias.phase or phase
                    grouped.setdefault(alias_phase, [])
                    alias_text = (
                        alias.when_to_use
                        or alias.description
                        or hint.guideline
                        or hint.short_description
                    )
                    if alias_text:
                        grouped[alias_phase].append(f"- `{alias.name}`: {alias_text}")
                continue
            if hint.guideline:
                grouped[phase].append(f"- `{name}`: {hint.guideline}")
            elif hint.short_description:
                grouped[phase].append(f"- `{name}`: {hint.short_description}")

        labels = _PHASE_LABELS.get(self.language, _PHASE_LABELS["en"])
        sections: list[str] = []
        for phase in _PHASE_ORDER:
            items = grouped.get(phase) or []
            if not items:
                continue
            label = labels.get(phase, labels["other"])
            sections.append(f"**{label}**\n" + "\n".join(items))
        return "\n\n".join(sections)


__all__ = ["ToolPromptComposer", "load_prompt_hints"]
