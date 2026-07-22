"""SolveSession — single-turn, in-memory state for the solve loop capability.

Unlike mastery's learning service (disk-backed, multi-session), a solve turn
is one-shot: the session lives only for the turn, keyed by the id the pipeline
injects as ``_solve_session_id``. It holds the model-authored plan, per-step
completion, and the replan budget gate — the deterministic "spine" the chat
loop drives against. The plan also rides in the conversation (the
``solve_plan`` tool result), so a follow-up chat turn stays grounded even
though the session itself does not persist.

The store is a bounded, process-local dict: a solve turn runs in one process,
sessions are small and short-lived, and the bound stops a long-running server
from leaking. Concurrent turns use distinct ids, so they never race.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field

DEFAULT_MAX_REPLANS = 2
_MAX_STEPS = 12


@dataclass
class SolveStep:
    """One plan step. ``done`` flips when the model calls ``solve_finish_step``."""

    id: str
    goal: str
    done: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "goal": self.goal, "done": self.done}


@dataclass
class SolveSession:
    """The plan + progress + replan budget for one solve turn."""

    session_id: str
    analysis: str = ""
    steps: list[SolveStep] = field(default_factory=list)
    replans: int = 0
    max_replans: int = DEFAULT_MAX_REPLANS

    def set_plan(self, analysis: str, steps: list[tuple[str, str]]) -> None:
        self.analysis = analysis
        self.steps = [SolveStep(id=sid, goal=goal) for sid, goal in steps][:_MAX_STEPS]

    def replan(self, analysis: str, steps: list[tuple[str, str]]) -> bool:
        """Replace the plan, bumping the replan counter. Returns ``False`` (and
        leaves the plan untouched) once the budget is spent."""
        if self.replans >= self.max_replans:
            return False
        self.replans += 1
        self.set_plan(analysis, steps)
        return True

    def mark_done(self, step_id: str, summary: str) -> SolveStep | None:
        for step in self.steps:
            if step.id == step_id:
                step.done = True
                step.summary = summary.strip()
                return step
        return None

    def next_step(self) -> SolveStep | None:
        return next((step for step in self.steps if not step.done), None)

    def map(self) -> list[dict[str, object]]:
        return [step.to_dict() for step in self.steps]

    def all_done(self) -> bool:
        return bool(self.steps) and all(step.done for step in self.steps)


_SESSIONS: "OrderedDict[str, SolveSession]" = OrderedDict()
_MAX_SESSIONS = 256


def get_session(session_id: str) -> SolveSession:
    """Fetch (or lazily create) the turn's session, evicting oldest past cap."""
    sid = (session_id or "").strip() or "default"
    session = _SESSIONS.get(sid)
    if session is None:
        session = SolveSession(session_id=sid)
        _SESSIONS[sid] = session
        while len(_SESSIONS) > _MAX_SESSIONS:
            _SESSIONS.popitem(last=False)
    return session


__all__ = [
    "DEFAULT_MAX_REPLANS",
    "SolveSession",
    "SolveStep",
    "get_session",
]
