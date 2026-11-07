"""
Question Generation System

Refactored dual-loop architecture:
- Idea loop: IdeaAgent <-> Evaluator
- Generation loop: Generator <-> Validator
- AgentCoordinator: End-to-end orchestration for topic and exam paths

Tools (moved to src/tools/question):
- parse_pdf_with_mineru
- extract_questions_from_paper
- mimic_exam_questions
"""

from .agents import Evaluator, Generator, IdeaAgent, Validator
from .coordinator import AgentCoordinator
from .models import QAPair, QuestionTemplate

__all__ = [
    "IdeaAgent",
    "Evaluator",
    "Generator",
    "Validator",
    "QuestionTemplate",
    "QAPair",
    "AgentCoordinator",
]
