"""Dataclasses for the learning journal aggregate."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class LearningMission:
    """Why the learner is studying — grounds subsequent sessions."""

    topic: str = ""
    why: str = ""
    level: str = ""
    updated_at: str = ""

    def is_empty(self) -> bool:
        return not (self.topic.strip() or self.why.strip() or self.level.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> LearningMission:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            topic=str(raw.get("topic") or "").strip(),
            why=str(raw.get("why") or "").strip(),
            level=str(raw.get("level") or "").strip(),
            updated_at=str(raw.get("updated_at") or "").strip(),
        )


@dataclass(slots=True)
class LearningSessionNote:
    """Handoff between sessions: what happened and what to do next."""

    summary: str = ""
    next_focus: str = ""
    updated_at: str = ""

    def is_empty(self) -> bool:
        return not (self.summary.strip() or self.next_focus.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> LearningSessionNote:
        if not isinstance(raw, dict):
            return cls()
        return cls(
            summary=str(raw.get("summary") or "").strip(),
            next_focus=str(raw.get("next_focus") or "").strip(),
            updated_at=str(raw.get("updated_at") or "").strip(),
        )


@dataclass(slots=True)
class LearningRecord:
    """One durable insight (ADR-style) that shapes the next lesson."""

    id: str
    title: str
    insight: str
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> LearningRecord | None:
        if not isinstance(raw, dict):
            return None
        record_id = str(raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        insight = str(raw.get("insight") or "").strip()
        if not record_id or not (title or insight):
            return None
        return cls(
            id=record_id,
            title=title,
            insight=insight,
            created_at=str(raw.get("created_at") or "").strip(),
        )


@dataclass(slots=True)
class LearningJournal:
    """Per-user soft learning state (mission + session + records)."""

    version: int = 1
    updated_at: str = ""
    mission: LearningMission = field(default_factory=LearningMission)
    last_session: LearningSessionNote = field(default_factory=LearningSessionNote)
    records: list[LearningRecord] = field(default_factory=list)

    def is_empty(self) -> bool:
        return self.mission.is_empty() and self.last_session.is_empty() and not self.records

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "mission": self.mission.to_dict(),
            "last_session": self.last_session.to_dict(),
            "records": [record.to_dict() for record in self.records],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> LearningJournal:
        if not isinstance(raw, dict):
            return cls()
        records: list[LearningRecord] = []
        for item in raw.get("records") or []:
            parsed = LearningRecord.from_dict(item)
            if parsed is not None:
                records.append(parsed)
        return cls(
            version=int(raw.get("version") or 1),
            updated_at=str(raw.get("updated_at") or "").strip(),
            mission=LearningMission.from_dict(raw.get("mission")),
            last_session=LearningSessionNote.from_dict(raw.get("last_session")),
            records=records,
        )

    def touch(self) -> None:
        self.updated_at = _utc_now()


__all__ = [
    "LearningJournal",
    "LearningMission",
    "LearningRecord",
    "LearningSessionNote",
]
