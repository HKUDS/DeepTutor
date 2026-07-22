"""The backend contract: drive one local agent CLI as a subagent.

A backend knows two things about its CLI: how to tell whether it's installed
and usable on this machine (:meth:`detect`), and how to put one question to it
and stream back every native event (:meth:`consult`). Everything CLI-specific —
flags, the JSON event schema, session resumption — lives behind this interface,
so the capability layer drives Claude Code and Codex through the exact same
three lines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from deeptutor.services.subagent.config import BackendConfig
from deeptutor.services.subagent.types import ConsultResult, DetectResult, SubagentEvent

# Called once per native event as it streams in. Backends must await it so
# backpressure (e.g. a slow WebSocket consumer) is respected.
OnEvent = Callable[[SubagentEvent], Awaitable[None]]


class SubagentBackend(ABC):
    """Drive one subagent (a local CLI, or one of the user's partners)."""

    kind: str
    display_name: str
    cli_command: str
    # Local-CLI backends (Claude Code, Codex) are detected on this machine and
    # offered in the connect-CLI modal. Non-CLI backends (a Partner) are
    # connected from their own list, so they sit out machine detection.
    local_cli: bool = True

    @abstractmethod
    async def detect(self) -> DetectResult:
        """Report whether this CLI is installed and usable on this machine."""

    @abstractmethod
    async def consult(
        self,
        question: str,
        *,
        on_event: OnEvent,
        cwd: str | None = None,
        session_id: str | None = None,
        config: BackendConfig | None = None,
        images: list[str] | None = None,
        partner_id: str | None = None,
    ) -> ConsultResult:
        """Put one question to the subagent and stream every native event.

        ``session_id`` resumes the backend's prior session for this turn (so the
        subagent keeps context across DeepTutor's successive questions); the
        returned :class:`ConsultResult` carries the session id to thread into the
        next consult. ``images`` are local file paths the user forwarded with the
        question (Codex attaches them with ``-i``; Claude Code is pointed at them
        for its Read tool). ``partner_id`` names the bound partner for the partner
        backend (the CLI backends ignore it). Waits unconditionally for the
        subagent to finish — only its own exit (clean or error) ends the consult.
        """


__all__ = ["OnEvent", "SubagentBackend"]
