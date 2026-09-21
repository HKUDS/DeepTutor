"""The idle boundary between a live Group discussion and DeepTutor's answer."""

from dataclasses import dataclass, field
import math
import time

IDLE_SECONDS = 10.0
DRAFT_LEASE_SECONDS = 6.0


@dataclass
class ConsultationWindow:
    last_activity: float = field(default_factory=time.monotonic)
    idle_since: float | None = None
    revision: object = None
    drafts: dict[str, tuple[bool, float]] = field(default_factory=dict)

    def activity(self, client: str, *, has_draft: bool, active: bool) -> None:
        now = time.monotonic()
        self.drafts[client] = (has_draft, now)
        if active:
            self.last_activity = now

    def disconnect(self, client: str) -> None:
        if self.drafts.pop(client, None) is not None:
            self.last_activity = time.monotonic()

    def remaining(self, *, busy: bool, revision: object) -> int | None:
        now = time.monotonic()
        drafting = any(
            draft and now - seen < DRAFT_LEASE_SECONDS for draft, seen in self.drafts.values()
        )
        if busy or drafting or revision != self.revision:
            self.idle_since = None
        self.revision = revision
        if busy or drafting:
            return None
        if self.idle_since is None:
            self.idle_since = now
        return max(0, math.ceil(IDLE_SECONDS - (now - max(self.idle_since, self.last_activity))))
