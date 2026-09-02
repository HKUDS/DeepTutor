"""Course-orchestration tools for the Course Study mode.

The course id is never model-authored. The loop capability injects it through
``_course_id`` after checking that this is a Course Study turn bound to a real
course. Imports of the course-state aggregator and course service stay inside
call paths: those services reach learning and retrieval subsystems, which must
not be imported while the capability/tool registries are bootstrapping.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
import json
from typing import Any, Literal

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

COURSE_ID_KWARG = "_course_id"

COURSE_STUDY_TOOL_NAMES: tuple[str, ...] = (
    "course_overview",
    "course_material",
    "course_edit",
    "course_handoff",
)

CourseEditAction = Literal[
    "attach",
    "create",
    "detach",
    "set_instructions",
    "note",
    "syllabus",
    "cover",
]
COURSE_EDIT_ACTIONS: tuple[str, ...] = (
    "attach",
    "create",
    "detach",
    "set_instructions",
    "note",
    "syllabus",
    "cover",
)

#: Resource kinds ``course_edit action="create"`` may bring into existence.
#:
#: Deliberately not every kind a course can reference. A notebook and a reading
#: workspace are one-call creations whose whole content is a name — making one
#: is exactly as reversible as attaching one, and a course with nowhere to put
#: notes is blocked on a step the learner has no reason to perform by hand. A
#: mastery path is not in that class: it is generated from a topic through a
#: wizard that costs a model round and produces a whole module tree, so it stays
#: a deliberate act on its own surface rather than something a routing turn can
#: decide to spend. Knowledge bases and books need ingestion, and partners need
#: authoring; none of those collapse into one argument.
COURSE_CREATABLE_KINDS: tuple[str, ...] = ("notebook", "reading_workspace")

CourseHandoffTarget = Literal[
    "immersive_reading",
    "mastery_path",
    "question_bank",
    "notebook",
    "chat",
]
COURSE_HANDOFF_TARGETS: tuple[str, ...] = (
    "immersive_reading",
    "mastery_path",
    "question_bank",
    "notebook",
    "chat",
)
#: Targets whose route names a specific resource, and the kind that resource is.
#:
#: The others route on the course alone — the question bank and notebook filter
#: by it, and chat simply belongs to it — so there is no id to check.
HANDOFF_REF_KINDS: dict[str, str] = {
    "immersive_reading": "reading_workspace",
    "mastery_path": "mastery_path",
}
COURSE_HANDOFF_LABELS: dict[str, str] = {
    "immersive_reading": "Immersive Reading",
    "mastery_path": "Mastery Path",
    "question_bank": "Question Bank",
    "notebook": "Notebook",
    "chat": "Chat",
}


async def _build_course_state(course_id: str) -> dict[str, Any]:
    """Deferred bridge to the parallel-authored course-state aggregator."""
    from deeptutor.services.courses_state import build_course_state

    return await build_course_state(course_id)


async def _resolve_reference(kind: str, ref_id: str) -> dict[str, Any] | None:
    """Deferred bridge to the aggregator's single-reference lookup."""
    from deeptutor.services.courses_state import resolve_resource_reference

    return await resolve_resource_reference(kind, ref_id)


async def _create_resource(kind: str, label: str) -> str:
    """Create one empty resource of ``kind`` and return its reference id.

    Imports are deferred per branch: this module is loaded whenever the course
    tools register, and the reading catalog opens a SQLite connection on import
    of its package.
    """
    if kind == "notebook":
        from deeptutor.services.notebook.service import get_notebook_manager

        notebook = await asyncio.to_thread(get_notebook_manager().create_notebook, label)
        return str(_mapping(notebook).get("id") or "")

    from deeptutor.reading import ReadingCatalogStore

    workspace = await asyncio.to_thread(ReadingCatalogStore().create_workspace, label)
    return str(getattr(workspace, "workspace_id", "") or "")


def _require_course_id(course_id: str) -> str:
    clean = str(course_id or "").strip()
    if not clean:
        raise ValueError("Course Study requires a course bound to this turn.")
    return clean


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return result if isinstance(result, dict) else {}
    if is_dataclass(value) and not isinstance(value, type):
        result = asdict(value)
        return result if isinstance(result, dict) else {}
    return {}


def _compact_json(value: Any, *, limit: int = 420) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return rendered if len(rendered) <= limit else rendered[: limit - 1] + "…"


def _render_course_overview(state: dict[str, Any]) -> str:
    """Render the whole aggregate compactly without returning a raw JSON dump."""
    course = _mapping(state.get("course"))
    course_id = str(course.get("id") or "")
    name = str(course.get("name") or course_id or "Untitled course")
    lines = [f"Course: {name} (id={course_id or 'unknown'})"]

    description = str(course.get("description") or "").strip()
    if description:
        lines.append(f"Description: {description}")
    defaults = [
        f"capability={course.get('default_capability')}"
        if course.get("default_capability")
        else "",
        f"persona={course.get('default_persona')}" if course.get("default_persona") else "",
    ]
    clean_defaults = [item for item in defaults if item]
    if clean_defaults:
        lines.append(f"Defaults: {', '.join(clean_defaults)}")
    instructions = str(course.get("instructions") or "").strip()
    if instructions:
        lines.append(f"Learner instructions: {instructions}")
    notes = str(course.get("agent_notes") or "").strip()
    if notes:
        lines.append(f"Agent notes: {notes}")

    syllabus = _mapping(state.get("syllabus") or {})
    syllabus_units = [_mapping(item) for item in syllabus.get("units", [])]
    syllabus_total = int(syllabus.get("total") or 0)
    syllabus_covered = int(syllabus.get("covered") or 0)
    if syllabus_total <= 0 and not syllabus_units:
        lines.append("Syllabus: none set.")
    else:
        lines.append(f"Syllabus ({syllabus_covered}/{syllabus_total} units covered):")
        for unit in syllabus_units:
            position = unit.get("position")
            # Numbered from 1, like the state summary and the course page. Three
            # surfaces describing the same unit must not each pick their own
            # base, or "unit 2" means a different row depending on who says it.
            position_text = int(position) + 1 if isinstance(position, int) else "?"
            topics = json.dumps(unit.get("topics") or [], ensure_ascii=False, default=str)
            lines.append(
                f"- id={unit.get('id') or '?'}; position={position_text}; "
                f"title={unit.get('title') or 'Untitled unit'}; topics={topics}; "
                f"covered={str(bool(unit.get('covered'))).lower()}; "
                f"wrong_questions={int(unit.get('wrong_questions') or 0)}"
            )
        if not syllabus_units:
            lines.append("- no unit details available")

    resources = [_mapping(item) for item in state.get("resources", [])]
    lines.append(f"Resources ({len(resources)}):")
    if not resources:
        lines.append("- none attached")
    for resource in resources:
        label = str(resource.get("label") or resource.get("ref_id") or resource.get("id") or "?")
        kind = str(resource.get("kind") or "unknown")
        availability = "available" if resource.get("available", True) else "unavailable"
        identity = f"id={resource.get('id') or '?'}, ref_id={resource.get('ref_id') or '?'}"
        detail = resource.get("detail")
        suffix = f"; detail={_compact_json(detail)}" if detail not in (None, {}, []) else ""
        lines.append(f"- {label} [{kind}; {identity}; {availability}{suffix}]")

    sessions = _mapping(state.get("sessions"))
    recent = [_mapping(item) for item in sessions.get("recent", [])]
    lines.append(
        "Sessions: "
        f"{int(sessions.get('active') or 0)} active, "
        f"{int(sessions.get('archived') or 0)} archived"
    )
    for session in recent[:5]:
        lines.append(
            f"- recent: {session.get('title') or session.get('session_id') or 'untitled'} "
            f"(id={session.get('session_id') or '?'})"
        )

    mastery = _mapping(state.get("mastery"))
    paths = [_mapping(item) for item in mastery.get("paths", [])]
    lines.append(f"Mastery paths ({len(paths)}):")
    if not paths:
        lines.append("- none")
    for path in paths:
        lines.append(
            f"- {path.get('name') or path.get('path_id') or '?'}: "
            f"{int(path.get('objectives_mastered') or 0)}/{int(path.get('objectives_total') or 0)} "
            f"modules; stage={path.get('stage') or 'unknown'}; "
            f"weak_points={_compact_json(path.get('weak_points') or [], limit=240)}"
        )

    question_bank = _mapping(state.get("question_bank"))
    weak_categories = [_mapping(item) for item in question_bank.get("weak_categories", [])]
    lines.append(
        "Question bank: "
        f"{int(question_bank.get('total') or 0)} total, "
        f"{int(question_bank.get('wrong') or 0)} wrong"
    )
    if weak_categories:
        lines.append(
            "- weak categories: "
            + ", ".join(
                f"{item.get('name') or '?'} ({int(item.get('wrong') or 0)} wrong)"
                for item in weak_categories
            )
        )

    reading = _mapping(state.get("reading"))
    workspaces = [_mapping(item) for item in reading.get("workspaces", [])]
    lines.append(f"Reading workspaces ({len(workspaces)}):")
    if not workspaces:
        lines.append("- none")
    for workspace in workspaces:
        lines.append(
            f"- {workspace.get('title') or workspace.get('workspace_id') or '?'}: "
            f"{int(workspace.get('materials') or 0)} material(s); "
            f"id={workspace.get('workspace_id') or '?'}"
        )
    return "\n".join(lines)


async def course_overview(*, _course_id: str) -> ToolResult:
    """Return a compact rendering of the bound course's aggregate state."""
    course_id = _require_course_id(_course_id)
    state = await _build_course_state(course_id)
    return ToolResult(
        content=_render_course_overview(state),
        metadata={"course_id": course_id},
    )


async def course_material(resource_id: str, *, _course_id: str) -> ToolResult:
    """Return the resolved state of one course resource."""
    course_id = _require_course_id(_course_id)
    wanted = str(resource_id or "").strip()
    if not wanted:
        raise ValueError("course_material requires a resource_id.")
    state = await _build_course_state(course_id)
    resource = next(
        (
            row
            for item in state.get("resources", [])
            if (row := _mapping(item))
            and wanted in {str(row.get("id") or ""), str(row.get("ref_id") or "")}
        ),
        None,
    )
    if resource is None:
        raise ValueError(f"Course resource {wanted!r} was not found.")
    label = str(resource.get("label") or resource.get("ref_id") or wanted)
    content = (
        f"Course resource: {label}\n"
        f"kind: {resource.get('kind') or 'unknown'}\n"
        f"resource_id: {resource.get('id') or ''}\n"
        f"ref_id: {resource.get('ref_id') or ''}\n"
        f"available: {bool(resource.get('available', True))}\n"
        f"detail: {_compact_json(resource.get('detail') or {}, limit=4000)}"
    )
    return ToolResult(
        content=content,
        metadata={
            "course_id": course_id,
            "resource_id": str(resource.get("id") or ""),
            "kind": str(resource.get("kind") or ""),
        },
    )


async def course_edit(
    action: CourseEditAction,
    *,
    _course_id: str,
    kind: str = "",
    ref_id: str = "",
    label: str = "",
    resource_id: str = "",
    instructions: str = "",
    note: str = "",
    units: list[dict[str, object]] | None = None,
    unit_id: str = "",
    covered: bool = False,
) -> ToolResult:
    """Apply one closed-set edit to the bound course through CourseService."""
    course_id = _require_course_id(_course_id)
    clean_action = str(action or "").strip()
    if clean_action not in COURSE_EDIT_ACTIONS:
        allowed = ", ".join(COURSE_EDIT_ACTIONS)
        raise ValueError(
            f"Unknown course_edit action {clean_action!r}; expected one of: {allowed}."
        )

    from deeptutor.services.courses import (
        SyllabusUnitNotFoundError,
        get_course_service,
    )

    service = get_course_service()
    if clean_action == "attach":
        clean_kind = str(kind or "").strip()
        clean_ref = str(ref_id or "").strip()
        if not clean_kind or not clean_ref:
            raise ValueError("course_edit action 'attach' requires kind and ref_id.")
        resource = await asyncio.to_thread(
            service.attach_resource,
            course_id,
            kind=clean_kind,
            ref_id=clean_ref,
            label=str(label or "").strip(),
        )
        row = _mapping(resource)
        return ToolResult(
            content=f"Attached {row.get('label') or clean_ref} to the course.",
            metadata={"course_id": course_id, "action": clean_action, "resource": row},
        )

    if clean_action == "create":
        clean_kind = str(kind or "").strip()
        clean_label = " ".join(str(label or "").split())[:160]
        if clean_kind not in COURSE_CREATABLE_KINDS:
            allowed = ", ".join(COURSE_CREATABLE_KINDS)
            raise ValueError(
                f"course_edit action 'create' cannot make a {clean_kind!r}; "
                f"it supports: {allowed}. Anything else must be made on its own "
                "surface and then attached."
            )
        if not clean_label:
            raise ValueError("course_edit action 'create' requires a label to name the new one.")
        new_ref_id = await _create_resource(clean_kind, clean_label)
        resource = await asyncio.to_thread(
            service.attach_resource,
            course_id,
            kind=clean_kind,
            ref_id=new_ref_id,
            label=clean_label,
        )
        row = _mapping(resource)
        return ToolResult(
            content=f"Created {clean_label} and attached it to the course.",
            metadata={
                "course_id": course_id,
                "action": clean_action,
                "resource": row,
                "created": True,
            },
        )

    if clean_action == "detach":
        clean_resource_id = str(resource_id or "").strip()
        if not clean_resource_id:
            raise ValueError("course_edit action 'detach' requires resource_id.")
        await asyncio.to_thread(service.detach_resource, course_id, clean_resource_id)
        return ToolResult(
            content=f"Detached course resource {clean_resource_id}.",
            metadata={
                "course_id": course_id,
                "action": clean_action,
                "resource_id": clean_resource_id,
            },
        )

    if clean_action == "set_instructions":
        course = await asyncio.to_thread(
            service.update,
            course_id,
            instructions=str(instructions or ""),
        )
        return ToolResult(
            content="Updated the learner-authored course instructions.",
            metadata={"course_id": course_id, "action": clean_action, "course": _mapping(course)},
        )

    if clean_action == "syllabus":
        if units is None:
            raise ValueError("course_edit action 'syllabus' requires units.")
        if not isinstance(units, list) or any(not isinstance(item, dict) for item in units):
            raise ValueError(
                "course_edit action 'syllabus' requires units to be a list of objects."
            )
        course = await asyncio.to_thread(service.set_syllabus, course_id, units)
        return ToolResult(
            content=f"Replaced the course syllabus with {len(units)} unit(s).",
            metadata={"course_id": course_id, "action": clean_action, "course": _mapping(course)},
        )

    if clean_action == "cover":
        clean_unit_id = str(unit_id or "").strip()
        if not clean_unit_id:
            raise ValueError("course_edit action 'cover' requires unit_id.")
        try:
            unit = await asyncio.to_thread(
                service.set_unit_covered,
                course_id,
                clean_unit_id,
                bool(covered),
            )
        except SyllabusUnitNotFoundError as exc:
            raise ValueError(f"Course syllabus unit {clean_unit_id!r} was not found.") from exc
        row = _mapping(unit)
        status = "covered" if bool(row.get("covered")) else "not covered"
        return ToolResult(
            content=f"Marked syllabus unit {clean_unit_id} as {status}.",
            metadata={"course_id": course_id, "action": clean_action, "unit": row},
        )

    clean_note = " ".join(str(note or "").split())
    if not clean_note:
        raise ValueError("course_edit action 'note' requires note.")
    course = await asyncio.to_thread(service.append_agent_note, course_id, clean_note)
    return ToolResult(
        content="Added an assistant note to the course.",
        metadata={"course_id": course_id, "action": clean_action, "course": _mapping(course)},
    )


async def course_handoff(
    target: CourseHandoffTarget,
    prompt: str,
    reason: str,
    ref_id: str = "",
    *,
    _course_id: str,
) -> ToolResult:
    """Create the frontend's closed-set course hand-off signal."""
    clean_target = str(target or "").strip()
    if clean_target not in COURSE_HANDOFF_TARGETS:
        allowed = ", ".join(COURSE_HANDOFF_TARGETS)
        raise ValueError(
            f"Unknown course handoff target {clean_target!r}; expected one of: {allowed}."
        )
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise ValueError("course_handoff requires a reason for the recommendation.")
    course_id = _require_course_id(_course_id)
    clean_ref_id = str(ref_id or "").strip()
    label = ""
    unresolved_ref = ""
    if clean_ref_id:
        # Read the registry directly rather than through ``build_course_state``:
        # what is needed is already stored on the attached resource, while the
        # full aggregate walks every session page and queries four other
        # subsystems — a heavy price for one lookup.
        from deeptutor.services.courses import get_course_service

        course = await asyncio.to_thread(get_course_service().get, course_id)
        # Accept either identifier. The state summary the model reads at the
        # top of a turn lists resources by ``resource_id``, so reaching for that
        # one here is the natural move — but the frontend builds the
        # destination URL from ``ref_id``, and the two are not interchangeable
        # (``res_9834…`` would route to a mastery path that does not exist).
        # Normalising server-side costs nothing and removes a whole class of
        # broken hand-off, instead of making the model spend a round on
        # ``course_material`` just to translate one id.
        match = next(
            (
                resource
                for resource in course.resources
                if clean_ref_id in (resource.ref_id, resource.id)
            ),
            None,
        )
        if match is not None:
            clean_ref_id = match.ref_id
            label = match.label
        elif clean_target in HANDOFF_REF_KINDS:
            # Not attached here — which is not the same as not existing. A
            # mastery path the learner built outside this course routes
            # perfectly well, so the question to ask is whether the destination
            # subsystem knows the id at all, not whether this course references
            # it. Observed live: "u2", a *syllabus unit* id handed in as a
            # mastery path, because both namespaces appear in the state summary
            # and look alike. Passed through it builds a card pointing at
            # /mastery/u2/sessions — a page that does not exist — and, being
            # non-empty, also tells the client that destination has a composer
            # waiting for the prepared opening line.
            detail = await _resolve_reference(HANDOFF_REF_KINDS[clean_target], clean_ref_id)
            if detail is None:
                unresolved_ref = clean_ref_id
                clean_ref_id = ""
            else:
                label = str(detail.get("title") or detail.get("name") or "")
    destination = COURSE_HANDOFF_LABELS[clean_target]
    # Said plainly rather than silently corrected: the model asked for something
    # specific, and a later round that assumes it was honoured would describe a
    # destination the learner is not being sent to.
    unresolved_note = (
        f" No {destination} exists with id {unresolved_ref!r}, so the card opens "
        "that surface's index instead; create the resource first if a specific "
        "one was meant, and do not pass syllabus unit ids here."
        if unresolved_ref
        else ""
    )
    return ToolResult(
        # Names the destination so the next round knows what was offered, and
        # states who decides — the card is a proposal the learner may decline.
        content=(
            f"Handoff card prepared: {destination}"
            f"{f' · {label}' if label else ''}. "
            "The learner chooses whether to take it."
            f"{unresolved_note}"
        ),
        metadata={
            "course_handoff": {
                "target": clean_target,
                "prompt": str(prompt or ""),
                "reason": clean_reason,
                "ref_id": clean_ref_id,
                "label": label,
                "course_id": course_id,
            }
        },
    )


class CourseOverviewTool(BaseTool):
    name = "course_overview"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=(
                "Show the bound course's syllabus units, resources, recent sessions, mastery "
                "progress, question-bank weaknesses, and reading workspaces."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await course_overview(_course_id=str(kwargs.get(COURSE_ID_KWARG) or ""))


class CourseMaterialTool(BaseTool):
    name = "course_material"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=(
                "Inspect one resource attached to the course. Use the resource_id from "
                "course_overview or the pre-loop course summary."
            ),
            parameters=[
                ToolParameter(
                    name="resource_id",
                    type="string",
                    description="Attached course resource id (or its underlying ref_id).",
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await course_material(
            str(kwargs.get("resource_id") or ""),
            _course_id=str(kwargs.get(COURSE_ID_KWARG) or ""),
        )


class CourseEditTool(BaseTool):
    name = "course_edit"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=(
                "Edit the bound course using one safe action: attach/detach a reference, "
                "create an empty notebook or reading workspace and attach it, "
                "replace learner instructions or the syllabus, toggle learner-directed unit "
                "coverage, or append an assistant learner note."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="The course mutation to apply.",
                    enum=list(COURSE_EDIT_ACTIONS),
                ),
                ToolParameter(
                    name="kind",
                    type="string",
                    description=(
                        "Resource kind for attach. For create, one of: "
                        f"{', '.join(COURSE_CREATABLE_KINDS)}."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="ref_id",
                    type="string",
                    description="Underlying resource id for attach.",
                    required=False,
                ),
                ToolParameter(
                    name="label",
                    type="string",
                    description=(
                        "Display label for attach (optional); the name of the new "
                        "resource for create (required)."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="resource_id",
                    type="string",
                    description="Course resource id for detach.",
                    required=False,
                ),
                ToolParameter(
                    name="instructions",
                    type="string",
                    description="Complete replacement text for set_instructions.",
                    required=False,
                ),
                ToolParameter(
                    name="note",
                    type="string",
                    description="Assistant observation to append for note.",
                    required=False,
                ),
                ToolParameter(
                    name="units",
                    type="array",
                    description=(
                        "Complete ordered syllabus for syllabus; each unit has title, optional "
                        "topics, and optional id."
                    ),
                    required=False,
                    items={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "topics": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["title"],
                    },
                ),
                ToolParameter(
                    name="unit_id",
                    type="string",
                    description="Syllabus unit id for cover.",
                    required=False,
                ),
                ToolParameter(
                    name="covered",
                    type="boolean",
                    description="Learner-decided coverage value for cover.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await course_edit(
            kwargs.get("action", ""),
            _course_id=str(kwargs.get(COURSE_ID_KWARG) or ""),
            kind=str(kwargs.get("kind") or ""),
            ref_id=str(kwargs.get("ref_id") or ""),
            label=str(kwargs.get("label") or ""),
            resource_id=str(kwargs.get("resource_id") or ""),
            instructions=str(kwargs.get("instructions") or ""),
            note=str(kwargs.get("note") or ""),
            units=kwargs.get("units"),
            unit_id=str(kwargs.get("unit_id") or ""),
            covered=bool(kwargs.get("covered", False)),
        )


class CourseHandoffTool(BaseTool):
    name = "course_handoff"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=(
                "Recommend the learner's next surface and create a hand-off card with a "
                "prefilled opening prompt. Never invent a target outside the closed list."
            ),
            parameters=[
                ToolParameter(
                    name="target",
                    type="string",
                    description="Destination learning surface.",
                    enum=list(COURSE_HANDOFF_TARGETS),
                ),
                ToolParameter(
                    name="prompt",
                    type="string",
                    description="Opening prompt prefilled at the destination.",
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description="Why this destination is the right next step now.",
                ),
                ToolParameter(
                    name="ref_id",
                    type="string",
                    description="Optional target material/workspace/path/resource id.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return await course_handoff(
            kwargs.get("target", ""),
            str(kwargs.get("prompt") or ""),
            str(kwargs.get("reason") or ""),
            str(kwargs.get("ref_id") or ""),
            _course_id=str(kwargs.get(COURSE_ID_KWARG) or ""),
        )


COURSE_STUDY_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    CourseOverviewTool,
    CourseMaterialTool,
    CourseEditTool,
    CourseHandoffTool,
)

__all__ = [
    "COURSE_EDIT_ACTIONS",
    "COURSE_HANDOFF_LABELS",
    "COURSE_HANDOFF_TARGETS",
    "COURSE_ID_KWARG",
    "COURSE_STUDY_TOOL_NAMES",
    "COURSE_STUDY_TOOL_TYPES",
    "CourseEditAction",
    "CourseEditTool",
    "CourseHandoffTarget",
    "CourseHandoffTool",
    "CourseMaterialTool",
    "CourseOverviewTool",
    "course_edit",
    "course_handoff",
    "course_material",
    "course_overview",
]
