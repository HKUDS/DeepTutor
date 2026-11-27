"""Hint descriptions retain assistance without failing after source inspection."""

from types import SimpleNamespace

import pytest

from deeptutor.capabilities.mastery.tools import MasteryQuizTool
from deeptutor.learning.models import LearningProgress
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.visual_practice import prepare_visual


@pytest.fixture
def visual_source(monkeypatch):
    calls = []

    def resolve(_name):
        calls.append("resolve")
        return SimpleNamespace(base_dir="synthetic", name="kb")

    def retrieve(*_args, **_kwargs):
        calls.append("retrieve")
        return SimpleNamespace(
            error="",
            images=[
                (
                    {
                        "asset_id": "synthetic-figure",
                        "source_path": "synthetic.pdf",
                        "source_document_id": "a" * 64,
                        "page_number": 1,
                        "text": "The target is alpha.",
                    },
                    b"synthetic-pixels",
                )
            ],
            sources=[
                {
                    "visual_asset_url": "/synthetic-image",
                    "url": "/synthetic-document",
                }
            ],
        )

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_for_rag", resolve)
    monkeypatch.setattr("deeptutor.services.rag.source_visuals.retrieve_visual", retrieve)
    return calls


def request(hints):
    return {
        "sources": [{"kb_name": "kb", "asset_id": "synthetic-figure"}],
        "reference_quote": "The target is alpha.",
        "key_status": "verified",
        "answer_cues": "none",
        "pixels_inspected": True,
        "hints_used": hints,
    }


@pytest.mark.parametrize(
    "hints,count",
    [
        (["A solution was previously visible"], 1),
        (["First hint", "Second hint"], 2),
        (3, 3),
        (0, 0),
        (None, 0),
    ],
)
def test_valid_hints_preserve_count_and_independent_credit(visual_source, tmp_path, hints, count):
    context, _ = prepare_visual(request(hints), expected_answer="alpha", options={})
    assert context["hints_used"] == count
    progress = LearningProgress(book_id="synthetic")
    LearningService(LearningStore(tmp_path))._apply_grade(
        progress,
        question_id="q",
        knowledge_point_id="kp",
        module_id="m",
        user_answer="alpha",
        expected_answer="alpha",
        question_type="short",
        visual_context=context,
    )
    assert progress.quiz_attempts[0].independent is (count == 0)
    assert progress.learning_evidence[0].hints_used == count
    assert progress.learning_evidence[0].quality == (0.6 if count else 1)


@pytest.mark.parametrize("invalid", [True, False, 1.5, -1, "", "1", [], [""], ["  "], [1], {}])
def test_invalid_hint_shapes_fail_before_source_io(visual_source, invalid):
    with pytest.raises(ValueError, match="hints_used"):
        prepare_visual(request(invalid), expected_answer="alpha", options={})
    assert visual_source == []


def test_single_and_group_visual_schema_type_hint_count_or_descriptions():
    definition = MasteryQuizTool().get_definition()
    props = definition.to_openai_schema()["function"]["parameters"]["properties"]
    single = props["visual"]["properties"]["hints_used"]
    grouped = props["questions"]["items"]["properties"]["visual"]["properties"]["hints_used"]
    assert grouped == single
    assert {branch["type"] for branch in single["anyOf"]} == {"integer", "array", "null"}
    assert next(branch for branch in single["anyOf"] if branch["type"] == "integer")["minimum"] == 0
    descriptions = next(branch for branch in single["anyOf"] if branch["type"] == "array")
    assert descriptions["minItems"] == 1 and descriptions["items"]["type"] == "string"
    assert all(p.sensitive for p in definition.parameters if p.name in {"visual", "questions"})


@pytest.mark.asyncio
async def test_invalid_second_leaf_hints_reject_group_before_building_first_leaf(monkeypatch):
    from unittest.mock import AsyncMock

    from deeptutor.capabilities.mastery import tools

    monkeypatch.setattr(tools, "_new_service", lambda: object())
    monkeypatch.setattr(tools, "_load_path", lambda *_: LearningProgress(book_id="synthetic"))
    builder = AsyncMock(side_effect=AssertionError("No source-bearing leaf should be built"))
    monkeypatch.setattr(MasteryQuizTool, "_build_question", builder)
    leaf = {
        "knowledge_point_id": "kp",
        "question": "Identify the target",
        "expected_answer": "alpha",
    }
    result = await MasteryQuizTool().execute(
        _mastery_path_id="synthetic",
        questions=[
            {**leaf, "visual": request(1)},
            {**leaf, "visual": request([""])},
        ],
    )
    assert not result.success and "hints_used" in result.content
    builder.assert_not_called()
