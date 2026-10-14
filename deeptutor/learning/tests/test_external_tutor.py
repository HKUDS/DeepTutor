"""Network and in-process tutors must produce the same durable learning state."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
import httpx

from deeptutor.api.routers.mastery_path import router
from deeptutor.api.routers.mastery_tutor import native_tools
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    LearningProgress,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


class ExternalTutorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = LearningStore(root / "learning")
        self.sessions = SQLiteSessionStore(root / "chat.sqlite3")
        self.patches = [
            patch("deeptutor.learning.storage.LearningStore", return_value=self.store),
            patch("deeptutor.api.routers.mastery_path.LearningStore", return_value=self.store),
            patch("deeptutor.services.session.get_session_store", return_value=self.sessions),
            patch("deeptutor.services.session.get_sqlite_session_store", return_value=self.sessions),
        ]
        for item in self.patches:
            item.start()
        for path_id in ("native", "network"):
            progress = LearningProgress(book_id=path_id, name="Chemistry")
            points = [KnowledgePoint(id="quantity", name="物质的量", type=KnowledgeType.PROCEDURE, module_id="m"), KnowledgePoint(id="concept", name="离子反应", type=KnowledgeType.CONCEPT, module_id="m")]
            progress.modules = [LearningModule(id="m", name="化学", order=0, knowledge_points=points)]
            progress.knowledge_types = {kp.id: kp.type for kp in points}
            self.store.save(progress)
        await self.sessions.create_session(title="Chemistry", session_id="native_session")
        app = FastAPI()
        app.include_router(router, prefix="/api/mastery-paths")
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.counter = 0

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def call(self, tool, arguments=None, **extra):
        self.counter += 1
        body = {"client_id": "test", "session_id": "chemistry", "turn_id": str(self.counter), "request_id": f"request-{self.counter:016d}", "tool": tool, "arguments": arguments or {}, **extra}
        response = await self.client.post("/api/mastery-paths/topics/network/tutor", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json(), body

    async def native(self, tool, arguments):
        result = await native_tools()[tool].execute(**arguments, _mastery_path_id="native", _session_id="native_session", _turn_id=f"native_{self.counter}")
        self.assertTrue(result.success, result.content)
        return result

    def assert_parity(self):
        left, right = self.store.load("native"), self.store.load("network")
        self.assertEqual(left.mastery_levels, right.mastery_levels)
        self.assertEqual(left.qualitative_mastery, right.qualitative_mastery)
        self.assertEqual([a.is_correct for a in left.quiz_attempts], [a.is_correct for a in right.quiz_attempts])
        self.assertEqual([(e.knowledge_point_id, e.result, e.quality) for e in left.learning_evidence], [(e.knowledge_point_id, e.result, e.quality) for e in right.learning_evidence])
        for kp in left.repetition_states:
            a, b = left.repetition_states[kp], right.repetition_states[kp]
            self.assertEqual(a.lapse_count, b.lapse_count)
            self.assertAlmostEqual(a.stability, b.stability, places=3)
            self.assertAlmostEqual(a.next_review_at, b.next_review_at, delta=3)
        self.assertEqual(len(left.error_records), len(right.error_records))
        self.assertEqual(left.learner_mastery_overrides, right.learner_mastery_overrides)

    async def test_catalog_uses_native_schemas(self):
        response = await self.client.get("/api/mastery-paths/tutor-tools")
        self.assertEqual(response.status_code, 200)
        expected = [t.get_definition().to_openai_schema()["function"] for t in native_tools().values()]
        self.assertEqual(response.json()["tools"], expected)

    async def test_quantitative_and_qualitative_parity_and_retry(self):
        def answer_for(metadata, is_correct):
            options = metadata["mastery_quiz"]["pending_question"]["options"]
            correct_label = next(option["label"] for option in options if option["body"] == "0.5 mol")
            if is_correct:
                return correct_label
            return next(option["label"] for option in options if option["label"] != correct_label)

        for is_correct in (True, True, True, False):
            args = {"knowledge_point_id": "quantity", "question": "22 g CO2 是多少 mol？", "question_type": "choice", "options": ["A: 0.5 mol", "B: 22 mol"], "expected_answer": "A"}
            network, quiz_body = await self.call("mastery_quiz", args)
            self.assertTrue(network["success"], network)
            native = await self.native("mastery_quiz", args)
            native_qid = native.metadata["mastery_quiz"]["question_id"]
            qid = network["metadata"]["mastery_quiz"]["question_id"]
            result, body = await self.call("mastery_grade", {"question_id": qid, "answer": answer_for(network["metadata"], is_correct)})
            self.assertTrue(result["success"], result)
            await self.native("mastery_grade", {"question_id": native_qid, "answer": answer_for(native.metadata, is_correct)})
            before = self.store.load("network").model_dump()
            replay = await self.client.post("/api/mastery-paths/topics/network/tutor", json=body)
            self.assertTrue(replay.json()["replayed"])
            self.assertEqual(before, self.store.load("network").model_dump())
            self.assert_parity()
        for passed in (True, False):
            args = {"knowledge_point_id": "concept", "passed": passed, "feedback": "学生解释了反应中离子的变化。"}
            result, body = await self.call("mastery_assess", args)
            self.assertTrue(result["success"], result)
            await self.native("mastery_assess", args)
            self.assert_parity()
        bank = await self.sessions.list_notebook_entries()
        self.assertGreaterEqual(len(bank["items"]), 2)

    async def test_transcript_is_verbatim_and_ui_reads_evidence(self):
        user = "呃，可能是……哦不对，离子才发生变化。\n  保留空格  "
        tutor = "解释：请区分实际参加反应的离子。"
        result, body = await self.call("mastery_assess", {"knowledge_point_id": "concept", "passed": False, "feedback": "需要进一步解释"}, turn_id="turn-1", user_message=user)
        saved, record = await self.call("record_turn", turn_id="turn-1", user_message=user, assistant_message=tutor)
        await self.client.post("/api/mastery-paths/topics/network/tutor", json=record)
        session = await self.sessions.get_session_with_messages(result["session_id"])
        self.assertEqual([m["content"] for m in session["messages"]], [user, tutor])
        self.assertTrue(session["messages"][1]["events"])
        self.assertEqual(session["preferences"]["mastery_path_id"], "network")
        response = await self.client.get("/api/mastery-paths/progress/network/objectives/concept")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["objective"]["evidence_count"], 1)
        self.assertEqual(response.json()["objective"]["status"], "learning")

    async def test_conflicts_and_private_arguments(self):
        result, body = await self.call("mastery_status")
        changed = {**body, "user_message": "changed"}
        response = await self.client.post("/api/mastery-paths/topics/network/tutor", json=changed)
        self.assertEqual(response.status_code, 409)
        response = await self.client.post("/api/mastery-paths/topics/network/tutor", json={**body, "request_id": "invalid-arguments-1", "arguments": {"_mastery_path_id": "native"}})
        self.assertEqual(response.status_code, 422)
        self.store.acquire_path_lease("network", "another-session", "another-turn", bind_session=False)
        response = await self.client.post("/api/mastery-paths/topics/network/tutor", json={**body, "request_id": "busy-request-000001"})
        self.assertEqual(response.status_code, 409)
        self.store.release_leases_for_turn("another-turn")

    async def test_interrupted_receipt_recovers_without_new_attempt_or_question(self):
        args = {"knowledge_point_id": "quantity", "question": "22 g CO2 是多少 mol？", "question_type": "choice", "options": ["A: 0.5 mol", "B: 22 mol"], "expected_answer": "A"}
        quiz, quiz_body = await self.call("mastery_quiz", args)
        # Model a process interruption after the native commit but before its
        # network receipt. The learner later answers the saved question.
        with self.store._connect() as conn:
            conn.execute("UPDATE mastery_tutor_requests SET response_json = NULL")
            conn.commit()
        grade, grade_body = await self.call("mastery_grade", {"answer": "A"})
        self.assertTrue(grade["success"], grade)
        replay = await self.client.post("/api/mastery-paths/topics/network/tutor", json=quiz_body)
        self.assertEqual(replay.json()["metadata"]["mastery_quiz"]["question_id"], quiz["metadata"]["mastery_quiz"]["question_id"])
        self.assertEqual(len(self.store.list_interactions("network")), 1)
        with self.store._connect() as conn:
            conn.execute("UPDATE mastery_tutor_requests SET response_json = NULL")
            conn.commit()
        replay = await self.client.post("/api/mastery-paths/topics/network/tutor", json=grade_body)
        self.assertTrue(replay.json()["success"], replay.text)
        self.assertEqual(len(self.store.load("network").quiz_attempts), 1)

    async def test_mode_and_path_binding_use_native_session_preferences(self):
        await self.call("mastery_mode", {"mode": "outline"})
        refusal, _ = await self.call("mastery_assess", {"knowledge_point_id": "concept", "passed": True})
        self.assertFalse(refusal["success"])
        await self.call("mastery_mode", {"mode": "study"})
        result, _ = await self.call("mastery_assess", {"knowledge_point_id": "concept", "passed": True})
        self.assertTrue(result["success"])
        switched, _ = await self.call("mastery_switch", {"path_id": "native"})
        self.assertTrue(switched["success"], switched)
        self.assertEqual(switched["path_id"], "native")
        session = await self.sessions.get_session(switched["session_id"])
        self.assertEqual(session["preferences"]["mastery_path_id"], "native")
        self.assertEqual(self.store.path_id_for_session(switched["session_id"]), "native")
        self.assertIsNone(self.store.get_path_lease("network"))
        self.assertIsNone(self.store.get_path_lease("native"))


if __name__ == "__main__":
    unittest.main()
