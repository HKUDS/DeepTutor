"""File-backed learning journal store (atomic JSON under workspace)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import threading
from typing import Literal

from deeptutor.services.learning_journal.models import (
    LearningJournal,
    LearningMission,
    LearningRecord,
    LearningSessionNote,
)
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)

JOURNAL_VERSION = 1
MAX_RECORDS = 50
MAX_TOPIC_CHARS = 200
MAX_WHY_CHARS = 800
MAX_LEVEL_CHARS = 40
MAX_SUMMARY_CHARS = 800
MAX_NEXT_FOCUS_CHARS = 400
MAX_TITLE_CHARS = 120
MAX_INSIGHT_CHARS = 800

UpdateOp = Literal["set_mission", "note_session", "add_record"]


def _clip(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _normalize_key(*parts: str) -> str:
    return " ".join(" ".join(parts).split()).casefold()


@dataclass(frozen=True, slots=True)
class JournalWriteResult:
    accepted: bool
    message: str
    journal: LearningJournal
    record_id: str | None = None
    deduplicated: bool = False


class LearningJournalStore:
    """Stateless facade; path resolves via the active PathService."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.Lock] = {}

    def journal_path(self) -> Path:
        return get_path_service().get_learning_journal_file()

    def load(self) -> LearningJournal:
        path = self.journal_path()
        if not path.exists():
            return LearningJournal(version=JOURNAL_VERSION)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("learning journal unreadable at %s: %s", path, exc)
            return LearningJournal(version=JOURNAL_VERSION)
        journal = LearningJournal.from_dict(raw)
        journal.version = JOURNAL_VERSION
        return journal

    def status_markdown(self, *, recent_records: int = 8) -> str:
        journal = self.load()
        if journal.is_empty():
            return (
                "(No learning journal yet. When the user wants to learn a topic "
                "across sessions, call learning_update with op=set_mission, then "
                "note_session / add_record as you teach. Prefer this soft journal "
                "for free-form multi-session study; use Mastery Path tools for "
                "hard curriculum gates.)\n"
            )

        lines: list[str] = ["# Learning journal", ""]
        mission = journal.mission
        if not mission.is_empty():
            lines.append("## Mission")
            lines.extend(self._mission_lines(mission))
            lines.append("")

        session = journal.last_session
        if not session.is_empty():
            lines.append("## Last session")
            lines.extend(self._session_lines(session))
            lines.append("")

        if journal.records:
            lines.append("## Recent learning records")
            for record in journal.records[-max(1, recent_records) :]:
                title = record.title or "(untitled)"
                lines.append(f"- `{record.id}` **{title}**: {record.insight}")
            lines.append("")

        lines.append(
            "_Use Mastery Path (`mastery_status` / Guided Learning) for scored "
            "curriculum progress; this journal is the soft mission + insight layer._"
        )
        return "\n".join(lines).rstrip() + "\n"

    def injection_markdown(self) -> str:
        """The resumable slice of the journal, for the per-turn system prompt.

        Records are left out on purpose, and an empty journal yields ``""`` so
        nothing is injected: both keep a turn's overhead from scaling with
        journal history. ``learning_status`` advertises the journal to the
        model through its own description, so an empty one needs no repeated
        advertisement, and the full history stays one tool call away.
        """
        journal = self.load()
        parts: list[list[str]] = []
        mission_lines = self._mission_lines(journal.mission)
        if mission_lines:
            parts.append(["## Mission", *mission_lines])
        session_lines = self._session_lines(journal.last_session)
        if session_lines:
            parts.append(["## Last session", *session_lines])
        if not parts:
            return ""
        body = "\n\n".join("\n".join(part) for part in parts)
        return (
            "# Learning journal (carried over from earlier sessions)\n\n"
            f"{body}\n\n"
            "_Pick up from where this leaves off, and record what this session "
            "changes with `learning_update`._\n"
        )

    @staticmethod
    def _mission_lines(mission: LearningMission) -> list[str]:
        lines: list[str] = []
        if mission.topic:
            lines.append(f"- Topic: {mission.topic}")
        if mission.why:
            lines.append(f"- Why: {mission.why}")
        if mission.level:
            lines.append(f"- Level: {mission.level}")
        if mission.updated_at:
            lines.append(f"- Updated: {mission.updated_at}")
        return lines

    @staticmethod
    def _session_lines(session: LearningSessionNote) -> list[str]:
        lines: list[str] = []
        if session.summary:
            lines.append(f"- Summary: {session.summary}")
        if session.next_focus:
            lines.append(f"- Next focus: {session.next_focus}")
        if session.updated_at:
            lines.append(f"- Updated: {session.updated_at}")
        return lines

    def set_mission(
        self,
        *,
        topic: str,
        why: str = "",
        level: str = "",
    ) -> JournalWriteResult:
        topic_c = _clip(topic, MAX_TOPIC_CHARS)
        why_c = _clip(why, MAX_WHY_CHARS)
        level_c = _clip(level, MAX_LEVEL_CHARS)
        if not topic_c:
            return JournalWriteResult(
                accepted=False,
                message="set_mission requires a non-empty topic.",
                journal=self.load(),
            )

        def mutate(journal: LearningJournal) -> JournalWriteResult:
            journal.mission = LearningMission(
                topic=topic_c,
                why=why_c,
                level=level_c,
                updated_at=journal.updated_at,
            )
            journal.mission.updated_at = journal.updated_at
            return JournalWriteResult(
                accepted=True,
                message=f"mission set for topic={topic_c!r}.",
                journal=journal,
            )

        return self._mutate(mutate)

    def note_session(
        self,
        *,
        summary: str,
        next_focus: str = "",
    ) -> JournalWriteResult:
        summary_c = _clip(summary, MAX_SUMMARY_CHARS)
        next_c = _clip(next_focus, MAX_NEXT_FOCUS_CHARS)
        if not summary_c and not next_c:
            return JournalWriteResult(
                accepted=False,
                message="note_session requires summary and/or next_focus.",
                journal=self.load(),
            )

        def mutate(journal: LearningJournal) -> JournalWriteResult:
            journal.last_session = LearningSessionNote(
                summary=summary_c,
                next_focus=next_c,
                updated_at=journal.updated_at,
            )
            return JournalWriteResult(
                accepted=True,
                message="session note saved.",
                journal=journal,
            )

        return self._mutate(mutate)

    def add_record(self, *, title: str, insight: str) -> JournalWriteResult:
        title_c = _clip(title, MAX_TITLE_CHARS)
        insight_c = _clip(insight, MAX_INSIGHT_CHARS)
        if not insight_c:
            return JournalWriteResult(
                accepted=False,
                message="add_record requires a non-empty insight.",
                journal=self.load(),
            )
        if not title_c:
            title_c = _clip(insight_c, 60)

        def mutate(journal: LearningJournal) -> JournalWriteResult:
            key = _normalize_key(title_c, insight_c)
            for existing in journal.records:
                if _normalize_key(existing.title, existing.insight) == key:
                    return JournalWriteResult(
                        accepted=True,
                        message=f"record already saved (id={existing.id}); skipped duplicate.",
                        journal=journal,
                        record_id=existing.id,
                        deduplicated=True,
                    )
            next_n = self._next_record_number(journal)
            record_id = f"lr_{next_n:04d}"
            journal.records.append(
                LearningRecord(
                    id=record_id,
                    title=title_c,
                    insight=insight_c,
                    created_at=journal.updated_at,
                )
            )
            if len(journal.records) > MAX_RECORDS:
                journal.records = journal.records[-MAX_RECORDS:]
            return JournalWriteResult(
                accepted=True,
                message=f"record added (id={record_id}).",
                journal=journal,
                record_id=record_id,
            )

        return self._mutate(mutate)

    def _next_record_number(self, journal: LearningJournal) -> int:
        highest = 0
        for record in journal.records:
            suffix = record.id.removeprefix("lr_")
            if suffix.isdigit():
                highest = max(highest, int(suffix))
        return highest + 1

    def _mutate(self, mutator) -> JournalWriteResult:  # noqa: ANN001
        path = self.journal_path()
        lock = self._lock_for(path)
        with lock:
            journal = self.load()
            journal.touch()
            result = mutator(journal)
            if not result.accepted:
                return result
            if not result.deduplicated:
                self._atomic_write(path, result.journal)
            return result

    def _lock_for(self, path: Path) -> threading.Lock:
        key = str(path.resolve())
        lock = self._locks.get(key)
        if lock is None:
            lock = threading.Lock()
            self._locks[key] = lock
        return lock

    def _atomic_write(self, path: Path, journal: LearningJournal) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(journal.to_dict(), ensure_ascii=False, indent=2) + "\n"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)


_STORE: LearningJournalStore | None = None


def get_learning_journal_store() -> LearningJournalStore:
    global _STORE
    if _STORE is None:
        _STORE = LearningJournalStore()
    return _STORE


__all__ = [
    "JOURNAL_VERSION",
    "JournalWriteResult",
    "LearningJournalStore",
    "MAX_RECORDS",
    "UpdateOp",
    "get_learning_journal_store",
]
