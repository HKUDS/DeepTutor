from __future__ import annotations

from dataclasses import dataclass

from .models import DifficultyLevel


@dataclass(frozen=True)
class DifficultyPreset:
    level: DifficultyLevel
    page_window: int
    depth_instruction: str
    compression_instruction: str
    placeholder_purpose: str


PRESETS: dict[DifficultyLevel, DifficultyPreset] = {
    DifficultyLevel.SIMPLE: DifficultyPreset(
        level=DifficultyLevel.SIMPLE,
        page_window=10,
        depth_instruction=(
            "Simple controls how much to cover: keep only the core thread, key concepts, "
            "essential conclusions, and any indispensable bridge needed to understand them. "
            "Short does not mean shallow."
        ),
        compression_instruction=(
            "Compress by deleting repeated background, template transitions, low-information summaries, "
            "and meta commentary. Preserve precise definitions, key mechanisms, critical formulas or "
            "arguments, and the shortest logical bridge between ideas."
        ),
        placeholder_purpose="key_figure",
    ),
    DifficultyLevel.MEDIUM: DifficultyPreset(
        level=DifficultyLevel.MEDIUM,
        page_window=10,
        depth_instruction=(
            "Medium controls how much to cover: include the main knowledge points and the core logic chain "
            "needed for a normal classroom handout."
        ),
        compression_instruction=(
            "Compress by merging duplicated examples and background while retaining the main concepts, "
            "mechanisms, evidence, and topic-to-topic reasoning."
        ),
        placeholder_purpose="supporting_figure",
    ),
    DifficultyLevel.DETAILED: DifficultyPreset(
        level=DifficultyLevel.DETAILED,
        page_window=6,
        depth_instruction=(
            "Detailed controls how much to cover: preserve a fuller knowledge structure, including "
            "intermediate steps, boundary cases, supporting examples, and derivation or argument details "
            "when they are present in the evidence."
        ),
        compression_instruction=(
            "Compress only low-value repetition and boilerplate. Keep the complete conceptual chain, "
            "important qualifications, examples, mechanisms, and source-supported derivation details."
        ),
        placeholder_purpose="detailed_figure",
    ),
}


def get_difficulty_preset(level: DifficultyLevel) -> DifficultyPreset:
    return PRESETS[level]
