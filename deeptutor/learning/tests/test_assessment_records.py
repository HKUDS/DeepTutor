"""Cross-session, bounded recall uses persisted records rather than summaries."""

import json
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.mastery.record_tool import MasteryRecordTool
from deeptutor.learning.models import (
    InteractionStatus,
    LearningEvidence,
    LearningProgress,
    MasteryInteraction,
    PendingQuestion,
)
from deeptutor.learning.storage import LearningStore


@pytest.fixture
def store(tmp_path):
    store = LearningStore(root=tmp_path)
    store.save(LearningProgress(book_id="path"))
    return store


def add_quiz(
    store,
    ident,
    *,
    kp="kp",
    answer="我的原始答案",
    status=InteractionStatus.GRADED,
    result=None,
    path="path",
    timestamp=1,
):
    def mutate(tx):
        tx.put_interaction(
            MasteryInteraction(
                interaction_id=ident,
                path_id=path,
                question=PendingQuestion(
                    question_id=ident,
                    knowledge_point_id=kp,
                    prompt="原题？",
                    expected_answer="SECRET",
                ),
                user_answer=answer,
                status=status,
                result=result
                if result is not None
                else {"is_correct": False, "feedback": "原始反馈"},
                session_id="earlier-session",
                turn_id="earlier-turn",
                created_at=timestamp,
            )
        )
        tx.touch()

    store.mutate(path, mutate)


def test_filter_before_pagination_and_stable_order(store):
    add_quiz(store, "old", kp="target")
    for i in range(25):
        add_quiz(store, f"new-{i:02}", timestamp=2)
    assert [
        r["record_id"]
        for r in store.list_assessment_records("path", knowledge_point_id="target", limit=1)
    ] == ["interaction:old"]
    first = store.list_assessment_records("path", limit=10)
    second = store.list_assessment_records("path", limit=10, offset=10)
    assert len({r["record_id"] for r in first + second}) == 20


def test_only_completed_records_and_no_duplicate_quiz_evidence(store):
    add_quiz(store, "done")
    add_quiz(store, "void", result={"is_correct": True, "voided": True})
    add_quiz(store, "ungraded", result={"is_correct": None, "result": "ungraded"})
    add_quiz(store, "pending", status=InteractionStatus.AWAITING_INPUT)
    progress = store.load("path")
    progress.learning_evidence = [
        LearningEvidence(question_id="done", knowledge_point_id="kp", assessment_type="quiz"),
        LearningEvidence(
            knowledge_point_id="kp",
            assessment_type="qualitative",
            learner_answer="解释原文",
            feedback="评估原文",
        ),
    ]
    store.save(progress)
    rows = store.list_assessment_records("path")
    assert len(rows) == 2
    assert {r["kind"] for r in rows} == {"quiz", "qualitative"}


@pytest.mark.asyncio
async def test_tool_recalls_old_session_and_preserves_state(store, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: SimpleNamespace(store=store))
    add_quiz(store, "done")
    before = store.load("path").model_dump()
    result = await MasteryRecordTool().execute(_mastery_path_id="path", _session_id="new-session")
    assert result.success
    record = json.loads(result.content)["records"][0]
    assert record["learner_answer"] == "我的原始答案"
    assert record["feedback"] == "原始反馈"
    assert record["session_id"] == "earlier-session"
    assert "SECRET" not in result.content
    assert store.load("path").model_dump() == before


@pytest.mark.asyncio
async def test_long_original_can_be_read_in_chunks(store, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: SimpleNamespace(store=store))
    original = "中文\\公式\n" * 2500
    add_quiz(store, "long", answer=original)
    tool = MasteryRecordTool()
    listed = json.loads((await tool.execute(_mastery_path_id="path")).content)
    assert "learner_answer" in listed["records"][0]["truncated_fields"]
    collected, offset = "", 0
    while offset is not None:
        response = await tool.execute(
            _mastery_path_id="path",
            record_id="interaction:long",
            field="learner_answer",
            text_offset=offset,
            expected_revision=listed["path_revision"],
        )
        page = json.loads(response.content)
        collected += page["text"]
        assert len(page["text"]) <= 6000
        offset = page["next_text_offset"]
    assert collected == original


@pytest.mark.asyncio
async def test_path_and_workspace_scope_and_invalid_inputs(store, tmp_path, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: SimpleNamespace(store=store))
    tool = MasteryRecordTool()
    add_quiz(store, "private")
    assert not (await tool.execute(path_id="path")).success
    assert not (
        await tool.execute(
            _mastery_path_id="other", record_id="interaction:private", expected_revision=0
        )
    ).success
    assert store.load("other") is None
    for kwargs in (
        {"limit": 0},
        {"limit": 21},
        {"offset": -1},
        {"limit": True},
        {"text_offset": "0"},
    ):
        assert not (await tool.execute(_mastery_path_id="path", **kwargs)).success
    other = LearningStore(root=tmp_path / "other-user-workspace")
    other.save(LearningProgress(book_id="path"))
    monkeypatch.setattr(tools, "_new_service", lambda: SimpleNamespace(store=other))
    assert not (
        await tool.execute(
            _mastery_path_id="path",
            record_id="interaction:private",
            expected_revision=other.load("path").version,
        )
    ).success


def test_tool_is_registered():
    from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES, MASTERY_TOOL_TYPES

    assert "mastery_record" in MASTERY_TOOL_NAMES
    assert MasteryRecordTool in MASTERY_TOOL_TYPES
    schema = MasteryRecordTool().get_definition().to_openai_schema()
    assert "path_id" not in schema["function"]["parameters"]["properties"]
    from deeptutor.modules.catalog import manifests
    from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPEC_BY_NAME

    assert isinstance(BUILTIN_TOOL_SPEC_BY_NAME["mastery_record"].create(), MasteryRecordTool)
    assert (
        "mastery_record"
        in manifests()["mastery"]["capabilities"]["mastery_path"]["manifest"]["tools_used"]
    )


def test_runtime_overwrites_model_supplied_path():
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
    from deeptutor.core.context import UnifiedContext

    context = UnifiedContext(
        session_id="new-session", metadata={"mastery_mode": True, "mastery_path_id": "allowed"}
    )
    bound = MasteryLoopCapability().augment_kwargs(
        "mastery_record", {"_mastery_path_id": "other"}, context
    )
    assert bound["_mastery_path_id"] == "allowed"
    assert "mastery_record" in MasteryLoopCapability.owned_tools


@pytest.mark.asyncio
async def test_revision_guards_pagination_and_field_reads(store, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: SimpleNamespace(store=store))
    for i in range(3):
        add_quiz(store, f"q{i}")
    tool = MasteryRecordTool()
    first = json.loads((await tool.execute(_mastery_path_id="path", limit=2)).content)
    assert first["next_offset"] == 2
    second = json.loads(
        (
            await tool.execute(
                _mastery_path_id="path", limit=2, offset=2, expected_revision=first["path_revision"]
            )
        ).content
    )
    assert second["next_offset"] is None
    assert len(second["records"]) == 1
    add_quiz(store, "new")
    for kwargs in ({"offset": 2}, {"record_id": first["records"][0]["record_id"]}):
        result = await tool.execute(
            _mastery_path_id="path", expected_revision=first["path_revision"], **kwargs
        )
        assert not result.success
        assert "changed" in result.content


@pytest.mark.asyncio
async def test_qualitative_originals_missing_fields_and_empty_path(store, monkeypatch):
    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: SimpleNamespace(store=store))
    tool = MasteryRecordTool()
    empty = json.loads((await tool.execute(_mastery_path_id="path")).content)
    assert empty["records"] == [] and empty["next_offset"] is None
    progress = store.load("path")
    progress.learning_evidence = [
        LearningEvidence(
            knowledge_point_id="kp",
            assessment_type="qualitative",
            learner_answer="解释原文",
            feedback="反馈原文",
            result="partial",
            session_id="old",
        )
    ]
    store.save(progress)
    result = json.loads((await tool.execute(_mastery_path_id="path")).content)
    row = result["records"][0]
    assert row["prompt"] is None and row["options"] is None
    assert (row["learner_answer"], row["feedback"], row["result"]) == (
        "解释原文",
        "反馈原文",
        "partial",
    )


def test_group_parent_does_not_duplicate_completed_leaves(store):
    questions = [
        PendingQuestion(
            question_id=f"leaf{i}",
            knowledge_point_id="kp",
            prompt=f"Question {i}",
            expected_answer="secret",
        )
        for i in range(2)
    ]
    parent = PendingQuestion(
        question_id="group", knowledge_point_id="kp", question_type="group", questions=questions
    )

    def write(tx):
        tx.put_interaction(
            MasteryInteraction(
                interaction_id="group",
                path_id="path",
                question=parent,
                status=InteractionStatus.GRADED,
                result={"is_correct": True},
            )
        )
        tx.touch()

    store.mutate("path", write)
    for question in questions:
        add_quiz(store, question.question_id)
    rows = store.list_assessment_records("path")
    assert {r["record_id"] for r in rows} == {"interaction:leaf0", "interaction:leaf1"}
