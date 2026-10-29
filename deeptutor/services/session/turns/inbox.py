"""Messages the learner sends to a turn that is still running.

The composer does not wait for a turn to end: what the learner sends while
the agent is working is delivered to the running turn's inbox, and the agent
loop reads the inbox at its next step boundary — after the tool batch in
flight, before the next model call — so the message steers the rest of the
turn. Whatever the turn never reads (it ended first, or its capability has no
step boundary) the client sends as the next turn; the inbox is dropped with
the turn and nothing in it is persisted on its own.
"""

from __future__ import annotations

from typing import Any


class TurnInbox:
    """Queued learner messages for one turn, in arrival order."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def put(self, command_id: str, content: str) -> None:
        text = content.strip()
        # A retried delivery of the same message keeps its first place.
        if text and command_id not in self._items:
            self._items[command_id] = text

    def withdraw(self, command_id: str) -> bool:
        """Take back a message the loop has not read yet."""
        return self._items.pop(command_id, None) is not None

    def drain(self) -> list[dict[str, Any]]:
        items = [{"command_id": key, "content": text} for key, text in self._items.items()]
        self._items.clear()
        return items


__all__ = ["TurnInbox"]
