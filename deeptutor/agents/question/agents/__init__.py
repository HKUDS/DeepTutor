"""Question generation sub-agents.

Currently only the standalone single-call ``FollowupAgent`` lives here —
the per-question / per-batch agents (idea_agent, generator) were
replaced by the single :mod:`deeptutor.agents.question.pipeline` module
during the Phase A → C refactor.
"""

from importlib import import_module
from typing import Any

__all__ = ["FollowupAgent"]


def __getattr__(name: str) -> Any:
    if name == "FollowupAgent":
        module = import_module("deeptutor.agents.question.agents.followup_agent")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
