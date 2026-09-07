"""The backend contract: drive one connected agent as a subagent.

A backend knows how to report whether its local or remote runtime is usable
(:meth:`detect`), and how to put one question to it while streaming native
events (:meth:`consult`). Runtime-specific flags, protocols, event schemas, and
session resumption live behind this interface.
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
    """Drive one subagent through a local CLI, remote API, or Partner."""

    kind: str
    display_name: str
    cli_command: str
    # Local-CLI backends are detected on this machine. A non-local backend can
    # opt into connection discovery with ``detectable``; Partners use their
    # own list and sit out detection.
    local_cli: bool = True
    detectable: bool = False

    @abstractmethod
    async def detect(self) -> DetectResult:
        """Report whether this backend is configured and usable."""

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
        backend (the other backends ignore it). Waits unconditionally for the
        subagent to finish — only its own exit (clean or error) ends the consult.
        """


__all__ = ["OnEvent", "SubagentBackend"]
