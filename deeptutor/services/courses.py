"""Per-user study course registry for organizing learning resources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import threading
import time
import uuid

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service

COURSE_COLORS: tuple[str, ...] = (
    "#C65D2E",
    "#3F6F8F",
    "#4F7655",
    "#8A6543",
    "#705B8E",
    "#A04F5F",
)


class CourseNotFoundError(Exception):
    pass


class CourseNameConflictError(Exception):
    pass


@dataclass(slots=True)
class StudyCourse:
    id: str
    name: str
    description: str
    color: str
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_LOCKS_GUARD = threading.Lock()
_LOCKS: dict[str, threading.RLock] = {}


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


class CourseService:
    """Small durable registry stored inside the active user's workspace."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (get_path_service().get_workspace_dir() / "courses")
        self.index_file = self.root / "courses.json"
        self._lock = _lock_for(self.index_file)

    @staticmethod
    def _clean_name(value: str) -> str:
        name = " ".join(str(value or "").split()).strip()
        if not name:
            raise ValueError("Course name is required.")
        return name[:60]

    @staticmethod
    def _clean_description(value: str) -> str:
        return str(value or "").strip()[:300]

    @staticmethod
    def _clean_color(value: str, fallback_index: int = 0) -> str:
        candidate = str(value or "").strip().upper()
        allowed = {color.upper(): color for color in COURSE_COLORS}
        return allowed.get(candidate, COURSE_COLORS[fallback_index % len(COURSE_COLORS)])

    def _load(self) -> list[StudyCourse]:
        try:
            raw = json.loads(self.index_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError):
            return []
        rows = raw.get("courses", []) if isinstance(raw, dict) else []
        courses: list[StudyCourse] = []
        for index, row in enumerate(rows if isinstance(rows, list) else []):
            if not isinstance(row, dict):
                continue
            course_id = str(row.get("id") or "").strip()
            name = str(row.get("name") or "").strip()
            if not course_id or not name:
                continue
            created_at = float(row.get("created_at") or time.time())
            courses.append(
                StudyCourse(
                    id=course_id,
                    name=name[:60],
                    description=self._clean_description(str(row.get("description") or "")),
                    color=self._clean_color(str(row.get("color") or ""), index),
                    created_at=created_at,
                    updated_at=float(row.get("updated_at") or created_at),
                )
            )
        return courses

    def _save(self, courses: list[StudyCourse]) -> None:
        atomic_write_json(self.index_file, {"courses": [course.to_dict() for course in courses]})

    @staticmethod
    def _assert_unique(courses: list[StudyCourse], name: str, except_id: str = "") -> None:
        folded = name.casefold()
        if any(course.id != except_id and course.name.casefold() == folded for course in courses):
            raise CourseNameConflictError(f"A course named {name!r} already exists.")

    def list_courses(self) -> list[StudyCourse]:
        with self._lock:
            return sorted(
                self._load(), key=lambda course: (course.created_at, course.name.casefold())
            )

    def get(self, course_id: str) -> StudyCourse:
        target = str(course_id or "").strip()
        with self._lock:
            for course in self._load():
                if course.id == target:
                    return course
        raise CourseNotFoundError(target)

    def create(self, *, name: str, description: str = "", color: str = "") -> StudyCourse:
        with self._lock:
            courses = self._load()
            clean_name = self._clean_name(name)
            self._assert_unique(courses, clean_name)
            now = time.time()
            course = StudyCourse(
                id=f"course_{uuid.uuid4().hex[:12]}",
                name=clean_name,
                description=self._clean_description(description),
                color=self._clean_color(color, len(courses)),
                created_at=now,
                updated_at=now,
            )
            courses.append(course)
            self._save(courses)
            return course

    def update(
        self,
        course_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
    ) -> StudyCourse:
        target = str(course_id or "").strip()
        with self._lock:
            courses = self._load()
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            if name is not None:
                clean_name = self._clean_name(name)
                self._assert_unique(courses, clean_name, except_id=target)
                course.name = clean_name
            if description is not None:
                course.description = self._clean_description(description)
            if color is not None:
                course.color = self._clean_color(color)
            course.updated_at = time.time()
            self._save(courses)
            return course

    def delete(self, course_id: str) -> None:
        target = str(course_id or "").strip()
        with self._lock:
            courses = self._load()
            kept = [course for course in courses if course.id != target]
            if len(kept) == len(courses):
                raise CourseNotFoundError(target)
            self._save(kept)


def get_course_service() -> CourseService:
    return CourseService()


__all__ = [
    "COURSE_COLORS",
    "CourseNameConflictError",
    "CourseNotFoundError",
    "CourseService",
    "StudyCourse",
    "get_course_service",
]
