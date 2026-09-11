"""Course Study capability: strict binding, bounded state, tools, and hand-offs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import deeptutor.capabilities.course_study as course_study_package
from deeptutor.capabilities.course_study import (
    COURSE_HANDOFF_TARGETS,
    COURSE_ID_KWARG,
    COURSE_STUDY_TOOL_NAMES,
    COURSE_STUDY_TOOL_TYPES,
    SUMMARY_CHAR_LIMIT,
    CourseStudyLoopCapability,
)
from deeptutor.capabilities.course_study.capability import summarize_course_state
from deeptutor.capabilities.course_study.mode import CourseStudyCapability
from deeptutor.capabilities.course_study.tools import (
    CourseEditTool,
    CourseHandoffTool,
    CourseMaterialTool,
    CourseOverviewTool,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus


def _context(*, mode: str = "course_study", course_id: str = "") -> UnifiedContext:
    metadata = {"course_id": course_id} if course_id else {}
    return UnifiedContext(
        active_capability=mode,
        user_message="What should I do next?",
        metadata=metadata,
    )


def _course_state() -> dict[str, object]:
    return {
        "course": {
            "id": "course-1",
            "name": "Linear Algebra",
            "description": "Matrices and vector spaces",
            "instructions": "Use the lecturer's notation.",
            "agent_notes": "Needs more eigenvalue practice.",
            "default_capability": "course_study",
            "default_persona": "coach",
        },
        "syllabus": {
            "total": 2,
            "covered": 1,
            # Positions are 0-based, matching what ``_parse_syllabus`` stores.
            # The summary adds one so the tutor's "unit 2" matches the "2." the
            # course page prints beside the same row.
            "next": {"id": "unit-2", "title": "Eigenvalues", "position": 1},
            "units": [
                {
                    "id": "unit-1",
                    "position": 0,
                    "title": "Vectors",
                    "topics": ["vectors", "span"],
                    "covered": True,
                    "wrong_questions": 0,
                },
                {
                    "id": "unit-2",
                    "position": 1,
                    "title": "Eigenvalues",
                    "topics": ["eigenvalues", "diagonalization"],
                    "covered": False,
                    "wrong_questions": 5,
                },
            ],
        },
        "resources": [
            {
                "id": "res-book",
                "kind": "book",
                "ref_id": "book-1",
                "label": "Course text",
                "position": 0,
                "added_at": 1.0,
                "available": True,
                "detail": {
                    "title": "Course text",
                    "secret_full_detail": "x" * 5000,
                },
            },
            {
                "id": "res-reading",
                "kind": "reading_workspace",
                "ref_id": "read-1",
                "label": "Week 4 reading",
                "position": 1,
                "added_at": 2.0,
                "available": True,
                "detail": {
                    "title": "Week 4 reading",
                    "last_position": "page 42",
                    "last_read_at": 20.0,
                },
            },
        ],
        "sessions": {
            "active": 2,
            "archived": 1,
            "recent": [
                {
                    "session_id": "session-private",
                    "title": "FULL SESSION DETAIL MUST NOT ENTER THE SUMMARY",
                    "updated_at": 99.0,
                }
            ],
        },
        "mastery": {
            "paths": [
                {
                    "path_id": "path-1",
                    "name": "Matrix Mastery",
                    "objectives_total": 10,
                    "objectives_mastered": 6,
                    "stage": "learning",
                    "weak_points": ["determinants", "eigenvalues"],
                }
            ]
        },
        "question_bank": {
            "total": 40,
            "wrong": 9,
            "weak_categories": [
                {"name": "Eigenvalues", "wrong": 5},
                {"name": "Determinants", "wrong": 3},
                {"name": "Vectors", "wrong": 1},
            ],
        },
        "reading": {
            "workspaces": [
                {
                    "workspace_id": "read-old",
                    "title": "Week 2 reading",
                    "materials": 1,
                    "last_position": "page 8",
                    "last_read_at": 10.0,
                }
            ]
        },
    }


def _syllabus_unit(
    *,
    unit_id: str = "unit-2",
    position: int = 2,
    title: str = "Eigenvalues",
    topics: list[str] | None = None,
    covered: bool = False,
) -> SimpleNamespace:
    unit = SimpleNamespace(
        id=unit_id,
        position=position,
        title=title,
        topics=list(topics or ["eigenvalues"]),
        covered=covered,
    )

    def to_dict() -> dict[str, object]:
        return {
            "id": unit.id,
            "position": unit.position,
            "title": unit.title,
            "topics": unit.topics,
            "covered": unit.covered,
        }

    unit.to_dict = to_dict
    return unit


def _course_resource(
    *,
    resource_id: str,
    kind: str,
    ref_id: str,
    label: str,
    position: int = 0,
) -> SimpleNamespace:
    resource = SimpleNamespace(
        id=resource_id,
        kind=kind,
        ref_id=ref_id,
        label=label,
        position=position,
        added_at=1.0,
    )

    def to_dict() -> dict[str, object]:
        return {
            "id": resource.id,
            "kind": resource.kind,
            "ref_id": resource.ref_id,
            "label": resource.label,
            "position": resource.position,
            "added_at": resource.added_at,
        }

    resource.to_dict = to_dict
    return resource


def _study_course(
    *,
    resources: list[SimpleNamespace] | None = None,
    syllabus: list[SimpleNamespace] | None = None,
    default_capability: str = "course_study",
    default_persona: str = "coach",
) -> SimpleNamespace:
    course = SimpleNamespace(
        id="course-1",
        name="Linear Algebra",
        description="Matrices and vector spaces",
        color="#4f46e5",
        created_at=1.0,
        updated_at=2.0,
        instructions="Use the lecturer's notation.",
        agent_notes="Needs more eigenvalue practice.",
        default_capability=default_capability,
        default_persona=default_persona,
        resources=list(resources or []),
        syllabus=list(syllabus or []),
        status="active",
        archived_at=0.0,
    )

    def to_dict() -> dict[str, object]:
        return {
            "id": course.id,
            "name": course.name,
            "description": course.description,
            "color": course.color,
            "created_at": course.created_at,
            "updated_at": course.updated_at,
            "instructions": course.instructions,
            "agent_notes": course.agent_notes,
            "default_capability": course.default_capability,
            "default_persona": course.default_persona,
            "resources": course.resources,
            "syllabus": [unit.to_dict() for unit in course.syllabus],
            "status": course.status,
            "archived_at": course.archived_at,
        }

    course.to_dict = to_dict
    return course


def test_package_does_not_reexport_mode_class() -> None:
    assert not hasattr(course_study_package, "CourseStudyCapability")


def test_is_active_requires_mode_and_course_binding() -> None:
    capability = CourseStudyLoopCapability()

    assert capability.is_active(_context(course_id="course-1"))
    assert capability.is_active(
        UnifiedContext(
            active_capability="course_study",
            metadata={"course_id": "course-2"},
        )
    )
    assert not capability.is_active(_context())
    assert not capability.is_active(_context(mode="chat", course_id="course-1"))
    assert not capability.is_active(_context(mode="immersive_reading", course_id="course-1"))


def test_prompt_uses_active_and_no_course_variants() -> None:
    capability = CourseStudyLoopCapability()

    active = capability.system_block(
        _context(course_id="course-1"),
        language="en",
        prompts={},
    )
    assert active is not None
    assert "do not teach, explain, solve, quiz, summarize, or lecture" in active.content
    assert "Course id: course-1" in active.content

    no_course = capability.system_block(_context(), language="en", prompts={})
    assert no_course is not None
    assert "no course is bound" in no_course.content
    assert "Do not invent" in no_course.content
    assert "do not teach, explain, solve, quiz, summarize, or lecture" in no_course.content

    assert (
        capability.system_block(
            _context(mode="chat", course_id="course-1"),
            language="en",
            prompts={},
        )
        is None
    )


def test_playbook_makes_syllabus_coverage_the_learners_decision() -> None:
    capability = CourseStudyLoopCapability()
    context = _context(course_id="course-1")

    en = capability.system_block(context, language="en", prompts={})
    zh = capability.system_block(context, language="zh", prompts={})

    assert en is not None
    assert zh is not None
    assert "Covered is the learner's decision, not the model's." in en.content
    assert "“已覆盖”由学习者决定，而不是由模型决定。" in zh.content


def test_course_state_summary_reports_syllabus_or_its_absence_within_limit() -> None:
    with_syllabus = summarize_course_state(_course_state())
    assert "Syllabus: 1/2 units covered; next up: Eigenvalues (unit 2)." in with_syllabus
    assert len(with_syllabus) < SUMMARY_CHAR_LIMIT

    no_syllabus_state = _course_state()
    no_syllabus_state.pop("syllabus")
    without_syllabus = summarize_course_state(no_syllabus_state)
    assert "Syllabus: none set." in without_syllabus
    assert len(without_syllabus) < SUMMARY_CHAR_LIMIT


@pytest.mark.asyncio
async def test_mode_injects_no_course_prompt_without_mounting_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.capabilities.course_study.mode as mode_module

    observed: dict[str, UnifiedContext] = {}

    class FakePipeline:
        def __init__(self, *, language: str) -> None:
            assert language == "en"

        async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
            del stream
            observed["context"] = context

    monkeypatch.setattr(mode_module, "_register_course_tools", lambda: None)
    monkeypatch.setattr(mode_module, "AgenticChatPipeline", FakePipeline)

    context = UnifiedContext(user_message="Teach me eigenvalues")
    await CourseStudyCapability().run(context, StreamBus())

    assert context.active_capability == "course_study"
    assert not CourseStudyLoopCapability().is_active(context)
    assert "no course is bound" in observed["context"].sidebar_context
    assert "do not teach, explain, solve, quiz, summarize, or lecture" in (
        observed["context"].sidebar_context
    )


def test_capability_binds_course_id_only_to_its_owned_tools() -> None:
    capability = CourseStudyLoopCapability()
    context = _context(course_id="course-1")

    bound = capability.augment_kwargs("course_material", {"resource_id": "res-book"}, context)
    assert bound[COURSE_ID_KWARG] == "course-1"
    assert COURSE_ID_KWARG not in capability.augment_kwargs("rag", {"query": "q"}, context)
    assert COURSE_ID_KWARG not in capability.augment_kwargs(
        "course_material",
        {},
        _context(),
    )


@pytest.mark.asyncio
async def test_pre_loop_summary_is_bounded_and_omits_full_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services import courses_state

    calls: list[str] = []

    async def fake_build_course_state(course_id: str) -> dict[str, object]:
        calls.append(course_id)
        return _course_state()

    monkeypatch.setattr(courses_state, "build_course_state", fake_build_course_state)

    block = await CourseStudyLoopCapability().pre_loop(
        _context(course_id="course-1"),
        StreamBus(),
        usage=None,
    )

    assert calls == ["course-1"]
    assert block is not None
    assert block.name == "course_state_summary"
    assert "Course text [book; id=res-book; available]" in block.content
    assert "Matrix Mastery 6/10 modules (learning)" in block.content
    assert "9 wrong of 40" in block.content
    assert "Eigenvalues (5 wrong)" in block.content
    assert "Determinants (3 wrong)" in block.content
    assert "Vectors" not in block.content
    assert "Week 4 reading — page 42" in block.content
    assert "secret_full_detail" not in block.content
    assert "FULL SESSION DETAIL" not in block.content
    assert len(block.content) < 1000


def test_reading_position_fallback_uses_latest_attached_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor import reading
    import deeptutor.capabilities.course_study.capability as capability_module

    materials = {
        "workspace-old": SimpleNamespace(
            workspace_id="workspace-old",
            title="Older workspace",
            active_material_id="material-old",
            updated_at=10.0,
            tabs=(
                SimpleNamespace(
                    material=SimpleNamespace(
                        material_id="material-old",
                        title="Old paper",
                        last_opened_at=10.0,
                    )
                ),
            ),
        ),
        "workspace-new": SimpleNamespace(
            workspace_id="workspace-new",
            title="Current workspace",
            active_material_id="material-new",
            updated_at=20.0,
            tabs=(
                SimpleNamespace(
                    material=SimpleNamespace(
                        material_id="material-new",
                        title="Eigenvalue notes",
                        last_opened_at=30.0,
                    )
                ),
            ),
        ),
    }
    catalog = SimpleNamespace(get_workspace=lambda workspace_id: materials[workspace_id])
    store = SimpleNamespace(
        position=lambda material_id: SimpleNamespace(
            locator=7 if material_id == "material-old" else 42
        ),
        manifest=lambda material_id: SimpleNamespace(unit="page"),
    )
    monkeypatch.setattr(reading, "ReadingCatalogStore", lambda: catalog)
    monkeypatch.setattr(reading, "ReadingStore", lambda: store)

    state = {
        "reading": {
            "workspaces": [
                {"workspace_id": "workspace-old"},
                {"workspace_id": "workspace-new"},
            ]
        },
        "resources": [],
    }
    assert capability_module._durable_reading_position(state) == (
        "Current workspace / Eigenvalue notes — page 42"
    )


@pytest.mark.asyncio
async def test_pre_loop_is_inactive_without_both_gate_signals() -> None:
    capability = CourseStudyLoopCapability()
    assert await capability.pre_loop(_context(), StreamBus(), usage=None) is None
    assert (
        await capability.pre_loop(
            _context(mode="chat", course_id="course-1"),
            StreamBus(),
            usage=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_course_overview_happy_path_and_missing_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.capabilities.course_study.tools as tools_module

    async def fake_build_course_state(course_id: str) -> dict[str, object]:
        assert course_id == "course-1"
        return _course_state()

    monkeypatch.setattr(tools_module, "_build_course_state", fake_build_course_state)

    result = await CourseOverviewTool().execute(_course_id="course-1")
    assert result.success
    assert "Course: Linear Algebra" in result.content
    assert "Resources (2)" in result.content
    assert "Question bank: 40 total, 9 wrong" in result.content
    assert "Syllabus (1/2 units covered)" in result.content
    assert (
        'id=unit-1; position=1; title=Vectors; topics=["vectors", "span"]; '
        "covered=true; wrong_questions=0"
    ) in result.content
    assert "id=unit-2; position=2; title=Eigenvalues" in result.content
    assert (
        'topics=["eigenvalues", "diagonalization"]; covered=false; wrong_questions=5'
        in result.content
    )

    with pytest.raises(ValueError, match="requires a course"):
        await CourseOverviewTool().execute()


@pytest.mark.asyncio
async def test_course_material_happy_path_and_unknown_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.capabilities.course_study.tools as tools_module

    async def fake_build_course_state(course_id: str) -> dict[str, object]:
        assert course_id == "course-1"
        return _course_state()

    monkeypatch.setattr(tools_module, "_build_course_state", fake_build_course_state)

    result = await CourseMaterialTool().execute(
        _course_id="course-1",
        resource_id="res-book",
    )
    assert result.success
    assert "Course resource: Course text" in result.content
    assert "secret_full_detail" in result.content
    assert result.metadata["resource_id"] == "res-book"

    with pytest.raises(ValueError, match="was not found"):
        await CourseMaterialTool().execute(
            _course_id="course-1",
            resource_id="missing",
        )


@pytest.mark.asyncio
async def test_course_edit_forwards_all_actions_and_rejects_bad_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.capabilities.course_study.tools as tools_module
    from deeptutor.services import courses

    service = Mock()
    service.attach_resource.return_value = {
        "id": "res-new",
        "kind": "book",
        "ref_id": "book-2",
        "label": "Second book",
    }
    service.update.return_value = {"id": "course-1", "instructions": "New notation"}
    service.append_agent_note.return_value = {
        "id": "course-1",
        "agent_notes": "- Review eigenvalues",
    }
    monkeypatch.setattr(courses, "get_course_service", lambda: service)

    attached = await CourseEditTool().execute(
        _course_id="course-1",
        action="attach",
        kind="book",
        ref_id="book-2",
        label="Second book",
    )
    assert attached.success
    service.attach_resource.assert_called_once_with(
        "course-1",
        kind="book",
        ref_id="book-2",
        label="Second book",
    )

    await CourseEditTool().execute(
        _course_id="course-1",
        action="detach",
        resource_id="res-old",
    )
    service.detach_resource.assert_called_once_with("course-1", "res-old")

    await CourseEditTool().execute(
        _course_id="course-1",
        action="set_instructions",
        instructions="New notation",
    )
    service.update.assert_called_once_with("course-1", instructions="New notation")

    await CourseEditTool().execute(
        _course_id="course-1",
        action="note",
        note="Review   eigenvalues",
    )
    service.append_agent_note.assert_called_once_with(
        "course-1",
        "Review eigenvalues",
    )

    with pytest.raises(ValueError, match="Unknown course_edit action"):
        await tools_module.course_edit("delete", _course_id="course-1")

    with pytest.raises(ValueError, match="requires kind and ref_id"):
        await CourseEditTool().execute(
            _course_id="course-1",
            action="attach",
            kind="book",
        )


@pytest.mark.asyncio
async def test_course_edit_syllabus_forwards_whole_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services import courses

    units: list[dict[str, object]] = [
        {"id": "unit-1", "title": "Vectors", "topics": ["span", "basis"]},
        {"title": "Eigenvalues", "topics": ["diagonalization"]},
    ]
    calls: list[tuple[str, list[dict[str, object]]]] = []
    course = _study_course(syllabus=[_syllabus_unit(unit_id="unit-1")])

    def set_syllabus(
        course_id: str,
        supplied_units: list[dict[str, object]],
    ) -> SimpleNamespace:
        calls.append((course_id, supplied_units))
        return course

    service = SimpleNamespace(set_syllabus=set_syllabus)
    monkeypatch.setattr(courses, "get_course_service", lambda: service)

    result = await CourseEditTool().execute(
        _course_id="course-1",
        action="syllabus",
        units=units,
    )

    assert result.success
    assert calls == [("course-1", units)]
    assert result.metadata["course"]["status"] == "active"


@pytest.mark.asyncio
async def test_course_edit_cover_forwards_and_reports_unknown_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services import courses

    calls: list[tuple[str, str, bool]] = []
    covered_unit = _syllabus_unit(covered=True)

    def set_unit_covered(course_id: str, unit_id: str, covered: bool) -> SimpleNamespace:
        calls.append((course_id, unit_id, covered))
        if unit_id == "unknown-unit":
            raise courses.SyllabusUnitNotFoundError(unit_id)
        return covered_unit

    service = SimpleNamespace(set_unit_covered=set_unit_covered)
    monkeypatch.setattr(courses, "get_course_service", lambda: service)

    result = await CourseEditTool().execute(
        _course_id="course-1",
        action="cover",
        unit_id="unit-2",
        covered=True,
    )

    assert result.success
    assert calls == [("course-1", "unit-2", True)]
    assert result.metadata["unit"] == covered_unit.to_dict()

    with pytest.raises(
        ValueError,
        match="Course syllabus unit 'unknown-unit' was not found",
    ):
        await CourseEditTool().execute(
            _course_id="course-1",
            action="cover",
            unit_id="unknown-unit",
            covered=True,
        )


@pytest.mark.asyncio
async def test_course_handoff_metadata_contract_and_target_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from deeptutor.services import courses

    # The label is read straight off the attached resource in the registry.
    # Going through the full course aggregate would walk every session page and
    # query four other subsystems to recover one string.
    course = _study_course(
        resources=[
            _course_resource(
                resource_id="res_path1",
                kind="mastery_path",
                ref_id="path-1",
                label="Eigenvalues mastery path",
            )
        ],
    )
    seen: list[str] = []

    def fake_get(course_id: str) -> SimpleNamespace:
        seen.append(course_id)
        return course

    monkeypatch.setattr(courses, "get_course_service", lambda: SimpleNamespace(get=fake_get))
    tool = CourseHandoffTool()
    result = await tool.execute(
        _course_id="course-1",
        target="mastery_path",
        prompt="Continue with the eigenvalues module.",
        reason="Your question-bank errors cluster around eigenvalues.",
        ref_id="path-1",
    )

    handoff = result.metadata["course_handoff"]
    assert tuple(handoff) == (
        "target",
        "prompt",
        "reason",
        "ref_id",
        "label",
        "course_id",
    )
    assert handoff == {
        "target": "mastery_path",
        "prompt": "Continue with the eigenvalues module.",
        "reason": "Your question-bank errors cluster around eigenvalues.",
        "ref_id": "path-1",
        "label": "Eigenvalues mastery path",
        "course_id": "course-1",
    }
    assert handoff["course_id"]
    assert seen == ["course-1"]
    # The result text names the destination, so the next round knows what was
    # offered rather than only that "a handoff" happened.
    assert "Mastery Path" in result.content
    assert "Eigenvalues mastery path" in result.content

    unmatched = await tool.execute(
        _course_id="course-1",
        target="notebook",
        prompt="Organize your notes.",
        reason="Your notes are scattered.",
        ref_id="missing-resource",
    )
    assert unmatched.metadata["course_handoff"]["label"] == ""
    target_parameter = next(
        parameter for parameter in tool.get_definition().parameters if parameter.name == "target"
    )
    assert target_parameter.enum == list(COURSE_HANDOFF_TARGETS)

    with pytest.raises(ValueError, match="Unknown course handoff target"):
        await tool.execute(
            _course_id="course-1",
            target="https://evil.example/redirect",
            prompt="leave",
            reason="malicious",
        )

    with pytest.raises(ValueError, match="requires a reason"):
        await tool.execute(
            _course_id="course-1",
            target="chat",
            prompt="Continue",
            reason="",
        )


@pytest.mark.asyncio
async def test_course_handoff_accepts_either_identifier_for_a_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The turn's state summary lists resources by ``resource_id`` while the
    frontend routes on ``ref_id``. Reaching for the id that is actually in front
    of the model must not produce a link to a path that does not exist."""
    import deeptutor.capabilities.course_study.tools as tools_module
    from deeptutor.services import courses

    course = _study_course(
        resources=[
            _course_resource(
                resource_id="res_98342ab27051",
                kind="mastery_path",
                ref_id="path-1",
                label="Eigenvalues mastery path",
            )
        ],
    )
    monkeypatch.setattr(
        courses, "get_course_service", lambda: SimpleNamespace(get=lambda _: course)
    )
    tool = CourseHandoffTool()

    async def handoff(ref_id: str) -> dict[str, str]:
        result = await tool.execute(
            _course_id="course-1",
            target="mastery_path",
            prompt="Continue with eigenvalues.",
            reason="Errors cluster there.",
            ref_id=ref_id,
        )
        return result.metadata["course_handoff"]

    by_resource_id = await handoff("res_98342ab27051")
    by_ref_id = await handoff("path-1")
    assert by_resource_id["ref_id"] == by_ref_id["ref_id"] == "path-1"
    assert by_resource_id["label"] == by_ref_id["label"] == "Eigenvalues mastery path"

    # A path the course has not attached, but which really exists, stays exactly
    # as given: the tutor may legitimately point at one the learner built
    # elsewhere. What is checked is existence, not membership of this course.
    monkeypatch.setattr(
        tools_module,
        "_resolve_reference",
        _resolver({"mastery_path": {"something-else": {"name": "Elsewhere"}}}),
    )
    unattached = await handoff("something-else")
    assert unattached["ref_id"] == "something-else"
    # Named from the owning subsystem, so the card can say what it is opening
    # even though this course has never referenced it.
    assert unattached["label"] == "Elsewhere"


def test_all_four_course_tools_are_declared() -> None:
    assert tuple(tool_type().name for tool_type in COURSE_STUDY_TOOL_TYPES) == (
        COURSE_STUDY_TOOL_NAMES
    )


def test_course_defaults_fill_absent_fields_and_preserve_explicit_choices() -> None:
    from deeptutor.services.session.turn_runtime import _apply_course_defaults

    course = _study_course(
        default_capability="mastery_path",
        default_persona="course-coach",
        resources=[
            _course_resource(
                resource_id="res-kb-1",
                kind="knowledge_base",
                ref_id="algebra-kb",
                label="Algebra KB",
            ),
            _course_resource(
                resource_id="res-book-1",
                kind="book",
                ref_id="book-1",
                label="Course book",
                position=1,
            ),
            _course_resource(
                resource_id="res-kb-duplicate",
                kind="knowledge_base",
                ref_id="algebra-kb",
                label="Algebra KB duplicate",
                position=2,
            ),
            _course_resource(
                resource_id="res-kb-2",
                kind="knowledge_base",
                ref_id="exercises-kb",
                label="Exercises KB",
                position=3,
            ),
        ],
    )

    inherited = _apply_course_defaults({"content": "hello"}, course)
    assert inherited["capability"] == "mastery_path"
    assert inherited["persona"] == "course-coach"
    assert inherited["knowledge_bases"] == ["algebra-kb", "exercises-kb"]

    explicit = {
        "capability": "chat",
        "persona": "",
        "knowledge_bases": [],
    }
    assert _apply_course_defaults(explicit, course) == explicit

    active_session = _apply_course_defaults(
        {"content": "continue"},
        course,
        preferences={
            "capability": "chat",
            "persona": "learner-choice",
            "knowledge_bases": ["learner-kb"],
        },
    )
    assert active_session["capability"] == "chat"
    assert active_session["persona"] == "learner-choice"
    assert active_session["knowledge_bases"] == ["learner-kb"]
    assert active_session["content"] == "continue"


def test_summary_carries_learner_conventions_without_a_tool_call() -> None:
    """The course page promises every conversation begins knowing these.

    Before this they lived only in ``course_overview``'s output, so a turn the
    model answered straight from the summary silently ignored what the learner
    had written about how to teach them.
    """
    state = _course_state()
    state["course"]["instructions"] = "Always use C. We follow POSIX."
    state["course"]["agent_notes"] = "Keeps mixing up preemptive scheduling."

    summary = summarize_course_state(state)

    assert "Always use C. We follow POSIX." in summary
    assert "Keeps mixing up preemptive scheduling." in summary
    assert len(summary) <= SUMMARY_CHAR_LIMIT


def test_summary_says_so_when_no_conventions_are_written() -> None:
    state = _course_state()
    state["course"].pop("instructions", None)
    state["course"].pop("agent_notes", None)

    assert "none written yet" in summarize_course_state(state)


def test_long_conventions_are_clipped_and_point_at_the_tool() -> None:
    """A term's worth of rules must not crowd out the state it contextualises."""
    state = _course_state()
    state["course"]["instructions"] = "x" * 4000

    summary = summarize_course_state(state)

    assert "clipped; full text via course_overview" in summary
    assert len(summary) <= SUMMARY_CHAR_LIMIT


@pytest.mark.asyncio
async def test_course_edit_create_refuses_kinds_it_cannot_make() -> None:
    """A mastery path costs a model round and produces a whole module tree.

    Creating one is a deliberate act on its own surface, not something a routing
    turn decides to spend; the error names what *is* creatable so the model
    redirects instead of retrying.
    """
    import deeptutor.capabilities.course_study.tools as tools_module

    with pytest.raises(ValueError) as excinfo:
        await tools_module.course_edit(
            "create",
            _course_id="course-1",
            kind="mastery_path",
            label="Deadlocks",
        )

    message = str(excinfo.value)
    assert "notebook" in message
    assert "reading_workspace" in message


@pytest.mark.asyncio
async def test_course_edit_create_requires_a_name() -> None:
    import deeptutor.capabilities.course_study.tools as tools_module

    with pytest.raises(ValueError, match="label"):
        await tools_module.course_edit(
            "create",
            _course_id="course-1",
            kind="notebook",
            label="   ",
        )


@pytest.mark.asyncio
async def test_course_edit_create_makes_it_and_attaches_it_in_one_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A course with nowhere to put notes was blocked on a manual detour."""
    import deeptutor.capabilities.course_study.tools as tools_module
    from deeptutor.services import courses

    service = Mock()
    service.attach_resource.return_value = {
        "id": "res-new",
        "kind": "notebook",
        "ref_id": "nb-1",
        "label": "OS notes",
    }
    monkeypatch.setattr(courses, "get_course_service", lambda: service)

    async def fake_create(kind: str, label: str) -> str:
        assert (kind, label) == ("notebook", "OS notes")
        return "nb-1"

    monkeypatch.setattr(tools_module, "_create_resource", fake_create)

    result = await tools_module.course_edit(
        "create",
        _course_id="course-1",
        kind="notebook",
        label="OS notes",
    )

    service.attach_resource.assert_called_once()
    assert service.attach_resource.call_args.kwargs["ref_id"] == "nb-1"
    assert result.metadata["created"] is True


def _resolver(registry: dict[str, dict[str, dict[str, str]]]):
    """Stand in for the destination subsystem's own index."""

    async def resolve(kind: str, ref_id: str) -> dict[str, str] | None:
        return registry.get(kind, {}).get(ref_id)

    return resolve


@pytest.mark.asyncio
async def test_handoff_drops_a_ref_that_matches_nothing_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observed live: a syllabus unit id handed in as a mastery path.

    Both namespaces appear in the state summary and look alike. Passing the id
    through builds a card pointing at /mastery/u2/sessions — a page that does not
    exist — and, being non-empty, also tells the client the destination has a
    composer, so the prepared opening line is stored for a surface that never
    consumes it.
    """
    import deeptutor.capabilities.course_study.tools as tools_module
    from deeptutor.services import courses

    service = Mock()
    service.get.return_value = SimpleNamespace(resources=[])
    monkeypatch.setattr(courses, "get_course_service", lambda: service)
    # No mastery path anywhere answers to "u2" — it is a syllabus unit id.
    monkeypatch.setattr(tools_module, "_resolve_reference", _resolver({}))

    result = await tools_module.course_handoff(
        "mastery_path",
        "Explain processes",
        "Exam only covers processes and memory",
        ref_id="u2",
        _course_id="course-1",
    )

    assert result.metadata["course_handoff"]["ref_id"] == ""
    # Said out loud, so a later round does not describe a destination the
    # learner is not being sent to.
    assert "u2" in result.content
    assert "index" in result.content


@pytest.mark.asyncio
async def test_handoff_keeps_a_real_resource_the_course_has_not_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existence, not membership, is what makes a link work."""
    import deeptutor.capabilities.course_study.tools as tools_module
    from deeptutor.services import courses

    service = Mock()
    service.get.return_value = SimpleNamespace(resources=[])
    monkeypatch.setattr(courses, "get_course_service", lambda: service)
    monkeypatch.setattr(
        tools_module,
        "_resolve_reference",
        _resolver({"mastery_path": {"path_elsewhere": {"name": "Built elsewhere"}}}),
    )

    result = await tools_module.course_handoff(
        "mastery_path",
        "Continue",
        "Already underway",
        ref_id="path_elsewhere",
        _course_id="course-1",
    )

    handoff = result.metadata["course_handoff"]
    assert handoff["ref_id"] == "path_elsewhere"
    assert handoff["label"] == "Built elsewhere"


@pytest.mark.asyncio
async def test_handoff_keeps_a_ref_that_resolves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import deeptutor.capabilities.course_study.tools as tools_module
    from deeptutor.services import courses

    service = Mock()
    service.get.return_value = SimpleNamespace(
        resources=[
            SimpleNamespace(id="res-1", ref_id="path_abc", label="Processes"),
        ]
    )
    monkeypatch.setattr(courses, "get_course_service", lambda: service)

    # The state summary lists resources by resource_id, so reaching for that one
    # is the natural move; it must still resolve to the routable ref_id.
    result = await tools_module.course_handoff(
        "mastery_path",
        "Continue",
        "Half finished",
        ref_id="res-1",
        _course_id="course-1",
    )

    handoff = result.metadata["course_handoff"]
    assert handoff["ref_id"] == "path_abc"
    assert handoff["label"] == "Processes"


def _course_context(**metadata: object) -> UnifiedContext:
    return UnifiedContext(
        active_capability="course_study",
        metadata={"course_id": "course-1", **metadata},
        config_overrides={},
    )


def test_recommendation_written_beside_the_handoff_becomes_the_answer() -> None:
    """Reproduces the turn that ended on "no usable response".

    This playbook asks the model to recommend, explain, and call
    `course_handoff` — one thought, which models write in one round. The loop's
    default treats prose beside a tool call as a preamble, so the whole
    recommendation was dropped from the answer and left collapsed in the trace.
    """
    capability = CourseStudyLoopCapability()
    context = _course_context()
    recommendation = "同学，考试只考进程与内存，建议直接从「进程管理」开始。"

    policy = capability.tool_round_output_policy(
        context,
        recommendation,
        ("course_handoff",),
    )

    assert policy == "publish"
    assert capability.final_text_override(context, "") == recommendation
    # Must NOT claim the answer was already published. That flag suppresses the
    # loop's final emit, and is only true for capabilities that buffer output
    # behind a protocol. This mode buffers nothing — its prose went out during a
    # tool round, which the transcript files under the collapsed trace, not as
    # the reply. Setting it leaves the message body empty with the whole
    # recommendation hidden a click away.
    assert context.capability_output.answer_published is False


def test_a_bare_handoff_call_leaves_the_loop_alone() -> None:
    """With nothing said there is no answer to rescue.

    Ending the turn here would replace a missing recommendation with silence;
    the model still gets its ordinary finish round to write one.
    """
    capability = CourseStudyLoopCapability()
    context = _course_context()

    assert capability.tool_round_output_policy(context, "   ", ("course_handoff",)) == ""
    assert capability.final_text_override(context, "") is None


def test_prose_beside_a_sensing_tool_stays_a_preamble() -> None:
    """`course_overview` fetches; its preamble is not the recommendation."""
    capability = CourseStudyLoopCapability()
    context = _course_context()

    assert capability.tool_round_output_policy(context, "Let me look.", ("course_overview",)) == ""
    assert capability.final_text_override(context, "") is None


def test_hooks_stay_inert_without_a_bound_course() -> None:
    """Loop capabilities are non-exclusive; an unbound turn is not ours."""
    capability = CourseStudyLoopCapability()
    context = SimpleNamespace(
        active_capability="chat",
        metadata={"course_id": "course-1"},
        config_overrides={},
    )

    assert capability.tool_round_output_policy(context, "text", ("course_handoff",)) == ""
    assert capability.final_text_override(context, "") is None
