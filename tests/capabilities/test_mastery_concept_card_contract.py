"""Practice cards are allowed for qualitative objectives without opening their gate."""

import pytest

from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.capabilities.mastery.tools import MasteryQuizTool
from deeptutor.core.context import UnifiedContext
from deeptutor.learning.models import KnowledgeType
from deeptutor.learning.policy import is_mastered

pytest_plugins = ["tests.capabilities.test_mastery_question_groups"]


def test_quiz_schema_allows_practice_cards_for_all_objective_types():
    description = MasteryQuizTool().get_definition().description
    assert "all objective types" in description
    assert "qualitative gate" in description and "mastery_assess" in description
    assert "use mastery_assess instead" not in description


def test_group_finish_nudge_preserves_concept_practice_and_separate_gate():
    instruction = MasteryLoopCapability().finish_instruction(
        UnifiedContext(metadata={"mastery_mode": True}),
        "Answer these two practice questions; I will grade both answers.\n"
        "1. Which change increases the rate?\n2. Explain why it increases?",
    )
    assert "all objective types" in instruction
    assert "qualitative gate" in instruction and "mastery_assess" in instruction


@pytest.mark.asyncio
async def test_grouped_concept_and_design_practice_cannot_open_qualitative_gate(
    service, monkeypatch
):
    from deeptutor.capabilities.mastery import tools

    progress = service.store.load("p")
    objectives = progress.modules[0].knowledge_points
    objectives[0].type = KnowledgeType.CONCEPT
    objectives[1].type = KnowledgeType.DESIGN
    service.save(progress)
    monkeypatch.setattr(tools, "_new_service", lambda: service)

    async def sync(**kwargs):
        pass

    monkeypatch.setattr(tools, "_sync_mastery_attempt_to_question_bank", sync)
    for _ in range(3):
        posed = await tools.MasteryQuizTool().execute(
            _mastery_path_id="p",
            questions=[
                {
                    "knowledge_point_id": "kp1",
                    "question": "Name the concept.",
                    "expected_answer": "alpha",
                },
                {
                    "knowledge_point_id": "kp2",
                    "question": "Name the design.",
                    "expected_answer": "beta",
                },
            ],
        )
        assert posed.success
        active = service.store.get_active_interaction("p")
        assert len(active.question.questions) == 2
        graded = await tools.MasteryGradeTool().execute(
            _mastery_path_id="p",
            question_id=active.interaction_id,
            answers={leaf.question_id: leaf.expected_answer for leaf in active.question.questions},
        )
        assert graded.success
        assert all(
            item["is_correct"] for item in graded.metadata["mastery_grade"]["result"]["results"]
        )

    final = service.store.load("p")
    assert len(final.quiz_attempts) == 6
    assert not any(is_mastered(final, point) for point in final.modules[0].knowledge_points)
    assert all(event.assessment_type != "qualitative" for event in final.learning_evidence)
    assert "qualitative gate" in posed.content and "mastery_assess" in posed.content
