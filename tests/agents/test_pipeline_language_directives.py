from __future__ import annotations

from deeptutor.agents.question.pipeline import QuestionPipeline
from deeptutor.agents.research.pipeline import ResearchPipeline
from deeptutor.agents.solve.pipeline import SolvePipeline


def test_solve_pipeline_preserves_german_language_alias() -> None:
    assert SolvePipeline(language="Deutsch").language == "de"


def test_question_pipeline_preserves_german_language_alias() -> None:
    assert QuestionPipeline(language="de-DE").language == "de"


def test_research_pipeline_preserves_german_language_alias() -> None:
    assert ResearchPipeline(language="German").language == "de"
