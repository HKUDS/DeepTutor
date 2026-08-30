"""Per-user study course registry — the container every learning surface hangs off.

A course owns three things beyond its name: the *resources* it references
(knowledge bases, books, notebooks, mastery paths, reading workspaces,
partners), the *conventions* that shape every conversation inside it, and the
defaults a new conversation inherits.

Resources are held as a reference set, not as ownership. One textbook can be
the reading for two courses, and one partner can assist all of them, so the
edge lives here rather than as a ``course_id`` column on six other systems.
Detaching a resource — or deleting the course — therefore never destroys what
it pointed at, mirroring the existing rule that deleting a course only makes
its conversations unclassified.

Conversations are the one deliberate exception: they carry
``preferences.course_id`` pointing back here, because a conversation is
*produced by* a course and belongs to exactly one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


#: Kinds of resource a course may reference. Each maps to a system that owns the
#: thing itself; the course only stores a pointer plus a display snapshot.
COURSE_RESOURCE_KINDS: tuple[str, ...] = (
    "knowledge_base",
    "book",
    "notebook",
    "mastery_path",
    "reading_workspace",
    "partner",
    "partner_group",
)

#: A course is either in play or put away. Archiving is reversible and never
#: touches what the course references.
COURSE_STATUSES: tuple[str, ...] = ("active", "archived")

#: Ceiling on the assistant-maintained learner notes. These accumulate across a
#: whole term and are injected into every turn's system prompt, so they are
#: bounded here rather than trusted to stay short.
AGENT_NOTES_LIMIT = 4000

#: Ceiling on learner-authored course conventions, for the same reason.
INSTRUCTIONS_LIMIT = 4000


class CourseNotFoundError(Exception):
    pass


class CourseResourceNotFoundError(Exception):
    pass


class SyllabusUnitNotFoundError(Exception):
    pass


class UnknownResourceKindError(Exception):
    pass


@dataclass(slots=True)
class SyllabusUnit:
    """One ordered unit of what this course is supposed to cover.

    The syllabus is what gives progress a denominator. Without it "you have
    done 6 questions" answers nothing — six out of what? A course that declares
    twelve weeks can finally say which of them are still untouched.

    ``covered`` is set by the learner, never inferred. Matching a unit's topics
    against mastered knowledge points would take a guess and render it as a
    number, and a progress bar that quietly guesses is worse than no progress
    bar. The evidence is shown next to the checkbox instead, so the learner
    decides with the numbers in front of them.
    """

    id: str
    position: int
    title: str
    topics: list[str] = field(default_factory=list)
    covered: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class CourseResource:
    """One reference from a course to something another system owns.

    ``label`` is a snapshot taken at attach time so a course page stays readable
    when the target is renamed or removed; ``ref_id`` remains the only identity
    used to resolve it.
    """

    id: str
    kind: str
    ref_id: str
    label: str
    position: int
    added_at: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class CourseNameConflictError(Exception):
    pass


@dataclass(slots=True)
class StudyCourse:
    """A course and everything a conversation inside it inherits.

    ``instructions`` is authored by the learner — the conventions of this
    subject (notation, the way the teacher frames things, how they want to be
    taught). ``agent_notes`` is the assistant's own accumulating read on the
    learner within this course. Both reach the model, but they are stored apart
    so that the assistant can never quietly rewrite what the learner declared.
    """

    id: str
    name: str
    description: str
    color: str
    created_at: float
    updated_at: float
    instructions: str = ""
    agent_notes: str = ""
    default_capability: str = ""
    default_persona: str = ""
    resources: list[CourseResource] = field(default_factory=list)
    syllabus: list[SyllabusUnit] = field(default_factory=list)
    #: ``"active"`` or ``"archived"``. A term ends but its material, questions
    #: and paths stay exactly where they are — archiving only moves the course
    #: out of the way, and is reversible.
    status: str = "active"
    #: When it was archived, so a review can state the span it covers.
    archived_at: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _clip(value: str, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _parse_syllabus(raw: object) -> list[SyllabusUnit]:
    """Read the stored syllabus, renumbering so positions stay 0..n-1."""
    if not isinstance(raw, list):
        return []
    units: list[SyllabusUnit] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        title = " ".join(str(row.get("title") or "").split()).strip()
        if not title:
            continue
        topics = row.get("topics")
        units.append(
            SyllabusUnit(
                id=str(row.get("id") or "").strip() or f"unit_{uuid.uuid4().hex[:12]}",
                position=int(row.get("position") or index),
                title=title[:160],
                topics=[
                    " ".join(str(topic).split()).strip()[:80]
                    for topic in (topics if isinstance(topics, list) else [])
                    if str(topic).strip()
                ][:20],
                covered=bool(row.get("covered")),
            )
        )
    units.sort(key=lambda unit: unit.position)
    for position, unit in enumerate(units):
        unit.position = position
    return units


def _parse_resources(raw: object) -> list[CourseResource]:
    """Read the stored reference set, dropping rows that cannot be resolved.

    Unknown kinds are dropped rather than kept: a kind is what tells the reader
    which system to ask about the target, so a row without a recognised one has
    no way to ever be rendered or resolved.
    """
    if not isinstance(raw, list):
        return []
    resources: list[CourseResource] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip()
        ref_id = str(row.get("ref_id") or "").strip()
        if kind not in COURSE_RESOURCE_KINDS or not ref_id:
            continue
        resource_id = str(row.get("id") or "").strip() or f"res_{uuid.uuid4().hex[:12]}"
        added_at = float(row.get("added_at") or time.time())
        resources.append(
            CourseResource(
                id=resource_id,
                kind=kind,
                ref_id=ref_id,
                label=str(row.get("label") or ref_id)[:120],
                position=int(row.get("position") or index),
                added_at=added_at,
            )
        )
    resources.sort(key=lambda item: (item.position, item.added_at))
    for position, resource in enumerate(resources):
        resource.position = position
    return resources


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
                    # Courses written before these fields existed simply have
                    # none of them; a course is still perfectly usable as the
                    # plain folder it was created as.
                    instructions=_clip(str(row.get("instructions") or ""), INSTRUCTIONS_LIMIT),
                    agent_notes=_clip(str(row.get("agent_notes") or ""), AGENT_NOTES_LIMIT),
                    default_capability=str(row.get("default_capability") or "").strip(),
                    default_persona=str(row.get("default_persona") or "").strip(),
                    resources=_parse_resources(row.get("resources")),
                    syllabus=_parse_syllabus(row.get("syllabus")),
                    status=(
                        "archived"
                        if str(row.get("status") or "").strip() == "archived"
                        else "active"
                    ),
                    archived_at=float(row.get("archived_at") or 0.0),
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

    def create(
        self,
        *,
        name: str,
        description: str = "",
        color: str = "",
        instructions: str = "",
        default_capability: str = "",
        default_persona: str = "",
    ) -> StudyCourse:
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
                instructions=_clip(instructions, INSTRUCTIONS_LIMIT),
                default_capability=str(default_capability or "").strip()[:64],
                default_persona=str(default_persona or "").strip()[:80],
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
        instructions: str | None = None,
        default_capability: str | None = None,
        default_persona: str | None = None,
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
            if instructions is not None:
                course.instructions = _clip(instructions, INSTRUCTIONS_LIMIT)
            if default_capability is not None:
                course.default_capability = str(default_capability).strip()
            if default_persona is not None:
                course.default_persona = str(default_persona).strip()
            course.updated_at = time.time()
            self._save(courses)
            return course

    def attach_resource(
        self,
        course_id: str,
        *,
        kind: str,
        ref_id: str,
        label: str = "",
    ) -> CourseResource:
        """Reference something this course studies with.

        Attaching the same target twice is a no-op that returns the existing
        reference: the course page reads as a set, and a duplicate row would
        show the same textbook twice while doubling what the assistant is told
        about it.
        """
        clean_kind = str(kind or "").strip()
        if clean_kind not in COURSE_RESOURCE_KINDS:
            raise UnknownResourceKindError(clean_kind)
        clean_ref = str(ref_id or "").strip()
        if not clean_ref:
            raise ValueError("A resource reference is required.")
        target = str(course_id or "").strip()
        with self._lock:
            courses = self._load()
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            existing = next(
                (
                    item
                    for item in course.resources
                    if item.kind == clean_kind and item.ref_id == clean_ref
                ),
                None,
            )
            if existing is not None:
                return existing
            resource = CourseResource(
                id=f"res_{uuid.uuid4().hex[:12]}",
                kind=clean_kind,
                ref_id=clean_ref,
                label=(str(label or "").strip() or clean_ref)[:120],
                position=len(course.resources),
                added_at=time.time(),
            )
            course.resources.append(resource)
            course.updated_at = resource.added_at
            self._save(courses)
            return resource

    def detach_resource(self, course_id: str, resource_id: str) -> None:
        """Drop a reference. What it pointed at is left untouched."""
        target = str(course_id or "").strip()
        wanted = str(resource_id or "").strip()
        with self._lock:
            courses = self._load()
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            kept = [item for item in course.resources if item.id != wanted]
            if len(kept) == len(course.resources):
                raise CourseResourceNotFoundError(wanted)
            for position, resource in enumerate(kept):
                resource.position = position
            course.resources = kept
            course.updated_at = time.time()
            self._save(courses)

    def append_agent_note(self, course_id: str, note: str) -> StudyCourse:
        """Add one assistant observation about the learner in this course.

        Kept append-only and trimmed from the *front* when it overflows, so the
        record ages out oldest-first instead of the newest observation being
        silently dropped for being last.
        """
        clean_note = " ".join(str(note or "").split()).strip()
        if not clean_note:
            raise ValueError("A note is required.")
        target = str(course_id or "").strip()
        with self._lock:
            courses = self._load()
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            merged = (
                f"{course.agent_notes}\n- {clean_note}".strip()
                if course.agent_notes
                else f"- {clean_note}"
            )
            if len(merged) > AGENT_NOTES_LIMIT:
                merged = merged[-AGENT_NOTES_LIMIT:]
                # Never leave a half-eaten first line behind.
                newline = merged.find("\n")
                if newline != -1:
                    merged = merged[newline + 1 :]
            course.agent_notes = merged.strip()
            course.updated_at = time.time()
            self._save(courses)
            return course

    def set_syllabus(
        self,
        course_id: str,
        units: list[dict[str, object]],
    ) -> StudyCourse:
        """Replace the syllabus wholesale.

        Whole-list replacement rather than per-unit CRUD: a syllabus arrives as
        a document — pasted, or read out of the course outline — and is revised
        the same way. Units keep their ``id`` when one is supplied, so a rewrite
        that preserves ids also preserves which units were already covered.
        """
        target = str(course_id or "").strip()
        with self._lock:
            courses = self._load()
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            course.syllabus = _parse_syllabus(units)
            course.updated_at = time.time()
            self._save(courses)
            return course

    def set_unit_covered(self, course_id: str, unit_id: str, covered: bool) -> SyllabusUnit:
        """Mark one unit done, or undo that."""
        target = str(course_id or "").strip()
        wanted = str(unit_id or "").strip()
        with self._lock:
            courses = self._load()
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            unit = next((item for item in course.syllabus if item.id == wanted), None)
            if unit is None:
                raise SyllabusUnitNotFoundError(wanted)
            unit.covered = bool(covered)
            course.updated_at = time.time()
            self._save(courses)
            return unit

    def set_status(self, course_id: str, status: str) -> StudyCourse:
        """Archive a course or bring it back.

        Nothing it references is touched: archiving a finished term must not
        make its textbook, notebooks or question history harder to reach from
        anywhere else in the app.
        """
        clean = str(status or "").strip()
        if clean not in COURSE_STATUSES:
            raise ValueError(f"Unknown course status {clean!r}; expected active or archived.")
        target = str(course_id or "").strip()
        with self._lock:
            courses = self._load()
            course = next((item for item in courses if item.id == target), None)
            if course is None:
                raise CourseNotFoundError(target)
            now = time.time()
            course.status = clean
            course.archived_at = now if clean == "archived" else 0.0
            course.updated_at = now
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
    "AGENT_NOTES_LIMIT",
    "COURSE_COLORS",
    "COURSE_RESOURCE_KINDS",
    "COURSE_STATUSES",
    "INSTRUCTIONS_LIMIT",
    "CourseNameConflictError",
    "CourseNotFoundError",
    "CourseResource",
    "CourseResourceNotFoundError",
    "SyllabusUnit",
    "SyllabusUnitNotFoundError",
    "CourseService",
    "StudyCourse",
    "UnknownResourceKindError",
    "get_course_service",
]
