"""Mode strategy abstraction for deep research.

Each research mode (notes, report, comparison, learning_path) is represented
as a ``ModeStrategy`` dataclass.  ``STRATEGIES`` acts as the single source of
truth that ``request_config._build_mode_policy`` delegates to.

``validate_output`` provides lightweight post-generation checks so callers can
surface warnings when the LLM drifted away from the mode contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Literal

ResearchMode = Literal["notes", "report", "comparison", "learning_path"]
ResearchDepth = Literal["quick", "standard", "deep", "manual"]

_MANUAL_SUBTOPICS: dict[str, int] = {"quick": 2, "standard": 3, "deep": 4}
_AUTO_SUBTOPICS: dict[str, int] = {"quick": 2, "standard": 4, "deep": 6}


@dataclass(frozen=True)
class ModeStrategy:
    name: ResearchMode
    style: str
    rephrase_enabled: bool
    decompose_mode: str  # "auto" | "manual"
    single_pass_threshold: int
    min_section_length: int
    enable_citation_list: bool = True
    enable_inline_citations: bool = True
    deduplicate_enabled: bool = False
    allow_code_execution_on_deep: bool = False
    _rephrase_iterations_by_depth: dict[str, int] = field(
        default_factory=lambda: {
            "quick": 1,
            "standard": 1,
            "deep": 1,
            "manual": 1,
        }
    )

    def rephrase_iterations(self, depth: str) -> int:
        return self._rephrase_iterations_by_depth.get(depth, 1)

    def subtopic_count(self, depth: str) -> int:
        table = _AUTO_SUBTOPICS if self.decompose_mode == "auto" else _MANUAL_SUBTOPICS
        return table.get(depth, 3)

    def build_policy(self, depth: str) -> dict[str, object]:
        if self.decompose_mode == "auto":
            initial = None
            auto_max = _AUTO_SUBTOPICS.get(depth, 4)
        else:
            initial = _MANUAL_SUBTOPICS.get(depth, 3)
            if self.name == "comparison":
                initial = max(2, initial)
            auto_max = None

        return {
            "rephrase_enabled": self.rephrase_enabled,
            "rephrase_iterations": self.rephrase_iterations(depth),
            "decompose_mode": self.decompose_mode,
            "initial_subtopics": initial,
            "auto_max_subtopics": auto_max,
            "min_section_length": self.min_section_length,
            "report_single_pass_threshold": self.single_pass_threshold,
            "enable_citation_list": self.enable_citation_list,
            "enable_inline_citations": self.enable_inline_citations,
            "deduplicate_enabled": self.deduplicate_enabled,
            "style": self.style,
        }

    def validate_output(self, report: str) -> list[str]:
        """Return a list of warnings if the report deviates from mode expectations."""
        warnings: list[str] = []
        if not report or not report.strip():
            warnings.append("Report is empty.")
            return warnings

        if self.name == "notes":
            if not re.search(r">\s*\*\*Definition", report):
                warnings.append("Study notes: missing Definition box (> **Definition — ...).")
            if not re.search(r"Key Takeaway", report, re.IGNORECASE):
                warnings.append("Study notes: missing Key Takeaway block.")
        elif self.name == "comparison":
            if not re.search(r"\|.*\|.*\|", report):
                warnings.append("Comparison: no Markdown table detected.")
        elif self.name == "learning_path":
            if not re.search(r"Checkpoint", report, re.IGNORECASE):
                warnings.append("Learning path: missing Checkpoint block.")

        return warnings


STRATEGIES: dict[ResearchMode, ModeStrategy] = {
    "notes": ModeStrategy(
        name="notes",
        style="study_notes",
        rephrase_enabled=True,
        decompose_mode="manual",
        single_pass_threshold=99,
        min_section_length=260,
    ),
    "report": ModeStrategy(
        name="report",
        style="report",
        rephrase_enabled=True,
        decompose_mode="auto",
        single_pass_threshold=2,
        min_section_length=650,
    ),
    "comparison": ModeStrategy(
        name="comparison",
        style="comparison",
        rephrase_enabled=True,
        decompose_mode="manual",
        single_pass_threshold=2,
        min_section_length=520,
        allow_code_execution_on_deep=True,
        _rephrase_iterations_by_depth={
            "quick": 1,
            "standard": 1,
            "deep": 2,
            "manual": 1,
        },
    ),
    "learning_path": ModeStrategy(
        name="learning_path",
        style="learning_path",
        rephrase_enabled=True,
        decompose_mode="auto",
        single_pass_threshold=99,
        min_section_length=420,
    ),
}


def get_strategy(mode: str) -> ModeStrategy:
    return STRATEGIES[mode]  # type: ignore[index]


__all__ = [
    "ModeStrategy",
    "STRATEGIES",
    "get_strategy",
]
