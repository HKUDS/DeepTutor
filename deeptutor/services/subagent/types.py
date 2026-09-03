"""Value types for the subagent driver layer.

These are the only shapes that cross the boundary between a backend (which
knows how to drive one local agent CLI) and the rest of the app (the consult
tool, the API, the tests). Keeping them dependency-free lets the backends stay
small and the capability layer stay ignorant of CLI specifics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Coarse channels the UI groups streamed events by. A backend maps each native
# event onto exactly one of these so the sidebar renders a CLI-faithful trace
# without knowing whether it came from Claude Code or Codex.
EVENT_TEXT = "text"  # an assistant message / answer fragment
EVENT_REASONING = "reasoning"  # the agent's thinking / plan
EVENT_TOOL = "tool"  # the agent invoked a tool / ran a command
EVENT_TOOL_RESULT = "tool_result"  # the result of that tool / command
EVENT_LOG = "log"  # progress / status / stderr — the CLI's incidental logs
EVENT_RESULT = "result"  # the final answer marker
EVENT_ERROR = "error"  # the subagent reported a failure

KNOWN_EVENT_KINDS = frozenset(
    {
        EVENT_TEXT,
        EVENT_REASONING,
        EVENT_TOOL,
        EVENT_TOOL_RESULT,
        EVENT_LOG,
        EVENT_RESULT,
        EVENT_ERROR,
    }
)


@dataclass(slots=True)
class SubagentEvent:
    """One native event captured from a subagent's streamed output.

    ``kind`` is the coarse channel above; ``text`` is the human-readable line
    rendered in the sidebar; ``raw`` keeps the original parsed JSON object so
    nothing the CLI emitted is discarded.

    ``meta`` carries optional UI hints surfaced to the frontend. The only one
    today is ``merge_id``: a stable id correlating a tool's start/finish events
    so the transcript collapses them into one evolving row (e.g. a web search
    that shows "web search" on start, then fills in its query on completion).
    """

    kind: str
    text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConsultResult:
    """Outcome of one consult — one question put to the subagent.

    ``session_id`` is the backend's own session/thread id, threaded back into
    the next consult of the same turn so the subagent keeps its context across
    DeepTutor's successive questions.
    """

    final_text: str = ""
    session_id: str | None = None
    success: bool = True
    error: str = ""
    event_count: int = 0


@dataclass(slots=True)
class DetectResult:
    """Whether a subagent backend is usable on the current machine."""

    kind: str
    display_name: str
    available: bool
    version: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "display_name": self.display_name,
            "available": self.available,
            "version": self.version,
            "detail": self.detail,
        }


__all__ = [
    "EVENT_TEXT",
    "EVENT_REASONING",
    "EVENT_TOOL",
    "EVENT_TOOL_RESULT",
    "EVENT_LOG",
    "EVENT_RESULT",
    "EVENT_ERROR",
    "KNOWN_EVENT_KINDS",
    "SubagentEvent",
    "ConsultResult",
    "DetectResult",
]
