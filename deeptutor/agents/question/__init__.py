"""Question generation package.

The main entry point is :class:`~deeptutor.agents.question.pipeline.QuestionPipeline`.
Lightweight names (``FollowupAgent``, ``QuizTemplate``, ``QuizPair``, etc.)
are resolved lazily so callers that only need one symbol don't eagerly
import the full pipeline + its LLM dependencies.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "AgentCoordinator",
    "FollowupAgent",
    "QuestionPipeline",
    "QuizTemplate",
    "QuizPair",
    "QuizPlan",
    "QuizHistoryEntry",
]


def __getattr__(name: str) -> Any:
    if name == "AgentCoordinator":
        module = import_module("deeptutor.agents.question.coordinator")
        return getattr(module, name)
    if name == "FollowupAgent":
        module = import_module("deeptutor.agents.question.agents.followup_agent")
        return getattr(module, name)
    if name in {"QuestionPipeline", "QuizTemplate", "QuizPair", "QuizPlan", "QuizHistoryEntry"}:
        module = import_module("deeptutor.agents.question.pipeline")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
