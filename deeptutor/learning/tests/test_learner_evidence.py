"""Only durable learner replies can advance a mastery gate."""

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from deeptutor.learning.models import (
    KnowledgePoint,
    LearningModule,
    PendingQuestion,
    TopicSource,
)
from deeptutor.learning.service import LearningService, MasteryInteractionError
from deeptutor.learning.storage import LearningStore


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = LearningService(LearningStore(Path(self.tmp.name)))
        self.path = "evidence-test"
        progress = self.service.get_or_create(self.path)
        self.service.init_modules(
            progress,
            [
                LearningModule(
                    id="module",
                    name="Statistics",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(
                            id="calc", name="Compute mean", type="procedure", module_id="module"
                        ),
                        KnowledgePoint(
                            id="why", name="Explain sampling", type="concept", module_id="module"
                        ),
                        KnowledgePoint(
                            id="other", name="Explain inference", type="concept", module_id="module"
                        ),
                    ],
                )
            ],
        )
        self.service.save(progress)

    def question(self, objective="calc", question_type="short_answer", options=None):
        self.service.register_question(
            self.path,
            PendingQuestion(
                question_id="question",
                knowledge_point_id=objective,
                module_id="module",
                prompt="Explain sampling" if objective == "why" else "Mean of 2 and 4?",
                question_type=question_type,
                expected_answer="3",
                options=options or [],
            ),
            session_id="learner-session",
            turn_id="question-turn",
        )

    def answer(self, answer):
        self.service.mark_question_awaiting(self.path)
        self.service.record_question_answer(self.path, answer, session_id="learner-session")

    def test_model_cannot_grade_its_own_answer(self):
        self.question()
        with self.assertRaisesRegex(MasteryInteractionError, "No learner answer"):
            self.service.grade_interaction(self.path, answer="3")
        self.assertEqual(self.service.store.load(self.path).quiz_attempts, [])

    def test_empty_reply_cannot_earn_credit(self):
        self.question()
        self.answer(" ")
        with self.assertRaises(MasteryInteractionError):
            self.service.grade_interaction(self.path, answer="3")

    def test_short_answers_use_numeric_equality_not_text_similarity(self):
        from deeptutor.learning.grading import grade_answer

        self.assertTrue(grade_answer("3.0", "3", "short_answer"))
        self.assertFalse(grade_answer("0.05", "0.5", "short"))
        self.assertFalse(grade_answer("dependent", "independent", "short"))

    def test_recorded_answer_wins_and_grading_is_idempotent(self):
        self.question()
        self.answer("3")
        progress, interaction, replayed = self.service.grade_interaction(
            self.path, answer="invented", question_id="question"
        )
        self.assertFalse(replayed)
        self.assertTrue(interaction.result["is_correct"])
        self.assertEqual(progress.quiz_attempts[0].user_answer, "3")
        progress, _, replayed = self.service.grade_interaction(
            self.path, answer="invented", question_id="question"
        )
        self.assertTrue(replayed)
        self.assertEqual(len(progress.quiz_attempts), 1)

    def test_model_cannot_replace_unreadable_choice(self):
        self.question(question_type="choice", options=["A: 3", "B: 4"])
        self.answer("Please explain this first")
        with self.assertRaisesRegex(MasteryInteractionError, "readable choice"):
            self.service.grade_interaction(self.path, answer="A")

    def test_concept_pass_requires_an_answer_for_that_objective(self):
        with self.assertRaises(MasteryInteractionError):
            self.service.record_qualitative_for_path(
                self.path, "why", passed=True, evidence="Already knows it"
            )
        self.question("why")
        self.answer("Every possible sample of the same size has equal probability.")
        with self.assertRaises(MasteryInteractionError):
            self.service.record_qualitative_for_path(
                self.path, "other", passed=True, evidence="Transferred knowledge"
            )
        with self.assertRaises(MasteryInteractionError):
            self.service.record_qualitative_for_path(self.path, "why", passed=True)
        self.assertFalse(self.service.store.load(self.path).qualitative_mastery)

    def test_concept_assessment_preserves_answer_and_closes_question(self):
        self.question("why")
        self.answer("Every possible sample of the same size has equal probability.")
        progress = self.service.record_qualitative_for_path(
            self.path, "why", passed=True, evidence="Correct equal-probability criterion."
        )
        self.assertTrue(progress.qualitative_mastery["why"])
        self.assertIn("Every possible sample", progress.feynman_explanations["why"])
        self.assertIsNone(progress.pending_question)
        self.assertIsNone(self.service.store.get_active_interaction(self.path))

    def test_failed_retrieval_cannot_be_grounding(self):
        from deeptutor.learning.topic_generation import ground_topic_sources

        source = TopicSource(
            id="source", kind="knowledge_base", source_id="stat-151", label="Statistics"
        )
        with patch(
            "deeptutor.tools.rag_tool.rag_search",
            new=AsyncMock(
                return_value={
                    "needs_reindex": True,
                    "answer": "This knowledge base has no index for the active embedding model.",
                }
            ),
        ):
            result = asyncio.run(
                ground_topic_sources(name="Statistics", goal="Learn", sources=[source])
            )
        self.assertFalse(result[0].available)
        self.assertFalse(result[0].metadata.get("grounded_for_route"))

    def test_concept_answer_is_left_for_rubric_assessment(self):
        self.question("why")
        self.answer("Every possible sample has the same probability")
        with self.assertRaisesRegex(MasteryInteractionError, "requires mastery_assess"):
            self.service.grade_interaction(self.path, answer="3")
        self.assertEqual(self.service.store.load(self.path).quiz_attempts, [])
        self.assertIsNotNone(self.service.store.get_active_interaction(self.path))
