"""confidence_before 采集（教研审计 80 行方案）。

出题卡片追加把握度第二题（id 以 ``_conf`` 结尾，选项 1-5），``mastery_grade``
接收可选 ``confidence_before`` 并透传到 ``LearningEvidence``。本文件验证：

1. 回传：学习者在把握度题上选的值原样写进证据行。
2. 漏传容忍：没答把握度时批改照常，证据行 ``confidence_before`` 为 None。
3. 越界忽略：1-5 之外的数值视为未提供（None），批改不受影响。

fail-open/fail-closed 方向不变：采集是旁路，绝不因把握度缺失或越界改变
判分结果；判分本身的 fail-closed（无期望答案判错）不在此文件改动。
"""

from __future__ import annotations

import pytest

from deeptutor.learning.evidence_store import EvidenceStore
from deeptutor.learning.models import LearningProgress
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import MasteryGradeTool, MasteryQuizTool


@pytest.fixture
def path_id(tmp_path, monkeypatch):
    """Point the LearningStore at a temp workspace and yield a stable path id."""
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    return "test_path"


def _store_init_factory(root):
    def _init(self, root_arg=None):  # mirrors LearningStore.__init__ signature
        from pathlib import Path

        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


def _make_progress() -> LearningProgress:
    from deeptutor.learning.models import KnowledgePoint, KnowledgeType, LearningModule

    return LearningProgress(
        book_id="book1",
        modules=[
            LearningModule(
                id="m1",
                name="M1",
                order=0,
                knowledge_points=[
                    KnowledgePoint(id="kp1", name="KP1", type=KnowledgeType.MEMORY, module_id="m1")
                ],
            )
        ],
    )


@pytest.fixture
def service(tmp_path):
    return LearningService(
        store=LearningStore(root=tmp_path / "learning"),
        evidence_store=EvidenceStore(db_path=tmp_path / "learning_evidence.db"),
    )


# ── service 层：grade_and_record 透传 ─────────────────────────────────────


class TestGradeAndRecordConfidenceBefore:
    def test_forwards_confidence_before_to_evidence(self, service):
        progress = _make_progress()
        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="42",
            expected_answer="42",
            user_id="u1",
            confidence_before=4,
        )
        assert result is True
        ev = service._evidence_store.query_evidence(user_id="u1")[0]
        assert ev.confidence_before == 4

    def test_missing_confidence_before_is_tolerated(self, service):
        progress = _make_progress()
        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="42",
            expected_answer="42",
            user_id="u1",
        )
        assert result is True
        ev = service._evidence_store.query_evidence(user_id="u1")[0]
        assert ev.confidence_before is None

    def test_service_passes_confidence_before_through(self, service):
        # 越界校验属于 tool 边界（_resolve_confidence_before）；service 层
        # 是透传，原样写入证据行（typed same-process boundary 信任调用方）。
        progress = _make_progress()
        result = service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="42",
            expected_answer="42",
            user_id="u1",
            confidence_before=7,
        )
        assert result is True
        ev = service._evidence_store.query_evidence(user_id="u1")[0]
        assert ev.confidence_before == 7

    def test_wrong_answer_still_records_confidence_before(self, service):
        progress = _make_progress()
        service.grade_and_record(
            progress,
            question_id="q1",
            knowledge_point_id="kp1",
            module_id="m1",
            user_answer="wrong",
            expected_answer="42",
            user_id="u1",
            confidence_before=2,
        )
        ev = service._evidence_store.query_evidence(user_id="u1")[0]
        assert ev.is_correct is False
        assert ev.confidence_before == 2


# ── tool 层：出题卡片双题 + mastery_grade 参数 ──────────────────────────────


async def _register_question(path_id):
    await _build_basic(path_id)
    # v1.6.5 契约：content 是导师话术文本，结构化 payload 在 metadata。
    return (
        await MasteryQuizTool().execute(
            _mastery_path_id=path_id,
            knowledge_point_id=_first_kp_id(path_id),
            question="2+2?",
            expected_answer="4",
            question_type="short",
        )
    ).metadata["mastery_quiz"]


async def _build_basic(path_id):
    from deeptutor.tools.mastery_tool import MasteryBuildTool

    await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        mode="replace",
        modules=[
            {
                "name": "Module 1",
                "knowledge_points": [{"name": "Truth tables", "type": "memory"}],
            }
        ],
    )


def _first_kp_id(path_id) -> str:
    progress = LearningStore().load(path_id)
    assert progress is not None
    return progress.modules[0].knowledge_points[0].id


def _wire_tool_service(monkeypatch, tmp_path) -> EvidenceStore:
    """Point the tools' ``_new_service`` at a temp evidence store so the
    tool-level tests can read the rows it writes."""
    import deeptutor.capabilities.mastery.tools as mastery_tools

    evidence_store = EvidenceStore(db_path=tmp_path / "tool_evidence.db")

    def factory():
        return LearningService(
            store=LearningStore(),
            evidence_store=evidence_store,
        )

    monkeypatch.setattr(mastery_tools, "_new_service", factory)
    return evidence_store


class TestQuizCardTwoQuestions:
    @pytest.mark.asyncio
    async def test_ask_user_payload_carries_confidence_second_question(self, path_id):
        registered = await _register_question(path_id)
        questions = registered["ask_user"]["questions"]
        assert len(questions) == 2
        main, confidence = questions
        assert main["id"] == registered["question_id"]
        assert main["prompt"] == "2+2?"
        assert confidence["id"] == registered["question_id"] + "_conf"
        assert confidence["prompt"] == "你有多大把握？(1=纯猜, 5=非常确定)"
        assert [o["label"] for o in confidence["options"]] == ["1", "2", "3", "4", "5"]
        assert confidence["multi_select"] is False
        assert confidence["allow_free_text"] is False

    @pytest.mark.asyncio
    async def test_grade_tool_exposes_confidence_before_parameter(self):
        definition = MasteryGradeTool().get_definition()
        params = {p.name: p for p in definition.parameters}
        assert "confidence_before" in params
        assert params["confidence_before"].type == "integer"
        assert params["confidence_before"].required is False


class TestGradeToolConfidenceRoundtrip:
    @pytest.mark.asyncio
    async def test_roundtrips_confidence_before_into_evidence(self, path_id, tmp_path, monkeypatch):
        evidence_store = _wire_tool_service(monkeypatch, tmp_path)
        registered = await _register_question(path_id)

        grade = (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=registered["question_id"],
                answer="4",
                confidence_before=4,
            )
        ).metadata["mastery_grade"]
        assert grade["is_correct"] is True
        ev = evidence_store.query_evidence()[0]
        assert ev.confidence_before == 4

    @pytest.mark.asyncio
    async def test_missing_confidence_before_tolerated(self, path_id, tmp_path, monkeypatch):
        evidence_store = _wire_tool_service(monkeypatch, tmp_path)
        registered = await _register_question(path_id)

        grade = (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=registered["question_id"],
                answer="4",
            )
        ).metadata["mastery_grade"]
        assert grade["is_correct"] is True
        ev = evidence_store.query_evidence()[0]
        assert ev.confidence_before is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", [99, 0, -3, "high", True, 2.5])
    async def test_out_of_range_ignored_without_failing_grade(
        self, path_id, tmp_path, monkeypatch, bad
    ):
        evidence_store = _wire_tool_service(monkeypatch, tmp_path)
        registered = await _register_question(path_id)

        grade = (
            await MasteryGradeTool().execute(
                _mastery_path_id=path_id,
                question_id=registered["question_id"],
                answer="4",
                confidence_before=bad,
            )
        ).metadata["mastery_grade"]
        assert grade["is_correct"] is True
        ev = evidence_store.query_evidence()[0]
        assert ev.confidence_before is None
