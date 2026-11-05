"""Customizable review interval strategies for mastery paths (#1908).

A strategy template names one interval sequence per knowledge type, where
every review round carries its own interval in days. Four preset templates
ship with the product; learners create, edit, duplicate, and delete custom
ones through the learning store, and each mastery path binds the strategy it
schedules with (sessions bound to the path follow it automatically).

The binding on ``LearningProgress`` is a frozen snapshot of the template, so
editing or deleting a template never rewrites the scheduling of paths that
already chose it — they keep working until they switch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deeptutor.learning.models import (
    KnowledgeType,
    LearningProgress,
    ReviewStrategyTemplate,
)
from deeptutor.learning.scheduler import INTERVAL_SEQUENCES, SpacedRepetitionScheduler

if TYPE_CHECKING:  # pragma: no cover - typing only
    from deeptutor.learning.storage import LearningStore

#: The daily long-term preset is the historical fixed template. Paths without
#: a binding and every aggregate persisted before strategies behave exactly
#: like it, which is the compatibility guarantee for #1908.
_DAILY_LONG_TERM_INTERVALS: dict[KnowledgeType, list[int]] = {
    knowledge_type: list(rounds) for knowledge_type, rounds in INTERVAL_SEQUENCES.items()
}

_PRESET_DESCRIPTIONS = {
    "preset-daily-long-term": (
        "Steady long-term learning: expanding intervals from a same-day first "
        "round up to two months."
    ),
    "preset-exam-cramming": (
        "Exam sprint: dense short intervals and a high recall target, front-loading "
        "repetition into the days before the exam."
    ),
    "preset-language": (
        "Language subjects: vocabulary-grade repetition for memory with moderately "
        "tight concept rounds."
    ),
    "preset-science": (
        "Science subjects: longer reasoning-friendly intervals once an objective is understood."
    ),
}


def _preset(
    template_id: str,
    name: str,
    desired_retention: float,
    intervals: dict[str, list[int]],
) -> ReviewStrategyTemplate:
    return ReviewStrategyTemplate(
        template_id=template_id,
        name=name,
        description=_PRESET_DESCRIPTIONS[template_id],
        builtin=True,
        desired_retention=desired_retention,
        intervals={KnowledgeType(kt): rounds for kt, rounds in intervals.items()},
    )


def _builtin_templates() -> dict[str, ReviewStrategyTemplate]:
    return {
        template.template_id: template
        for template in (
            _preset(
                "preset-daily-long-term",
                "Daily Long-term Learning",
                0.9,
                {kt.value: rounds for kt, rounds in _DAILY_LONG_TERM_INTERVALS.items()},
            ),
            _preset(
                "preset-exam-cramming",
                "Exam Cramming",
                0.95,
                {
                    "memory": [0, 1, 1, 2, 3, 4, 7],
                    "concept": [1, 2, 3, 5, 7],
                    "procedure": [1, 2, 3, 5],
                    "design": [3, 7, 14],
                },
            ),
            _preset(
                "preset-language",
                "Language Subjects",
                0.9,
                {
                    "memory": [0, 1, 2, 4, 7, 15, 30],
                    "concept": [2, 4, 8, 15],
                    "procedure": [2, 4, 8],
                    "design": [10, 21],
                },
            ),
            _preset(
                "preset-science",
                "Science Subjects",
                0.85,
                {
                    "memory": [1, 3, 7, 14, 30, 60, 120],
                    "concept": [5, 12, 25, 50],
                    "procedure": [5, 12, 25],
                    "design": [21, 45],
                },
            ),
        )
    }


def builtin_templates() -> dict[str, ReviewStrategyTemplate]:
    """The four shipped strategy templates, keyed by template id."""
    return _builtin_templates()


#: Preset ids in their stable listing order (custom strategies list after them).
BUILTIN_TEMPLATE_IDS: tuple[str, ...] = tuple(sorted(_builtin_templates()))


def scheduler_for_progress(progress: LearningProgress) -> SpacedRepetitionScheduler:
    """The scheduler a path schedules with: its bound strategy or the default."""
    binding = progress.review_strategy
    if binding is None:
        return SpacedRepetitionScheduler()
    return SpacedRepetitionScheduler(interval_sequences=binding.intervals)


def scheduler_for_path(store: LearningStore, path_id: str) -> SpacedRepetitionScheduler:
    """Resolve a path's scheduler from the store, defaulting when unbound.

    Callers that already hold the aggregate should prefer
    :func:`scheduler_for_progress`; this helper serves call sites that only
    know the path id (capability tools).
    """
    progress = store.load(path_id)
    if progress is None:
        return SpacedRepetitionScheduler()
    return scheduler_for_progress(progress)
