"""The automatic snapshot is small; full state remains explicitly inspectable."""

import json

import pytest

from deeptutor.capabilities.mastery.loop import MasteryLoopCapability
from deeptutor.capabilities.mastery.tools import MasteryStatusTool
from deeptutor.core.context import UnifiedContext
from deeptutor.learning.models import KnowledgePoint, LearningModule, LearningProgress
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore


@pytest.mark.asyncio
async def test_runtime_brief_retains_live_objective_prerequisites_and_discovery(
    tmp_path, monkeypatch
):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    service.save(
        LearningProgress(
            book_id="path",
            modules=[
                LearningModule(
                    id=f"m{i}",
                    name=f"Module {i}",
                    order=i,
                    objective=f"Understand module {i}",
                    knowledge_points=[
                        KnowledgePoint(
                            id=f"p{i}-{j}",
                            name=f"Objective {i}-{j}",
                            module_id=f"m{i}",
                            type="concept",
                            prerequisite_ids=["p1-0"] if (i, j) == (0, 0) else [],
                            topic_source_ids=["selected-source"],
                        )
                        for j in range(8)
                    ],
                )
                for i in range(10)
            ],
        )
    )
    monkeypatch.setattr("deeptutor.capabilities.mastery.tools._new_service", lambda: service)
    before = store.load("path").model_dump()
    full = await MasteryStatusTool().execute(_mastery_path_id="path")
    context = UnifiedContext(
        metadata={"mastery_mode": True, "mastery_path_id": "path", "mastery_session_mode": "study"}
    )
    block = await MasteryLoopCapability().pre_loop(context, None)
    brief = json.loads(block.content[block.content.index("{") :])
    assert brief["state_scope"] == "working_brief"
    assert brief["next"] == json.loads(full.content)["next"]
    assert brief["path_revision"] == before["version"]
    points = {p["id"]: p for m in brief["map"]["modules"] for p in m["knowledge_points"]}
    assert set(points) == {"p0-0", "p1-0"}
    assert points["p0-0"]["topic_source_ids"] == ["selected-source"]
    assert brief["map"]["counts"]["total"] == 80
    assert "mastery_status" in brief["inspection_instruction"]
    assert len(block.content) < len(full.content) * 0.3
    assert store.load("path").model_dump() == before
    # Outline work needs the entire map, including objective IDs for edits.
    context.metadata["mastery_session_mode"] = "outline"
    outline = await MasteryLoopCapability().pre_loop(context, None)
    assert "p9-7" in outline.content


@pytest.mark.asyncio
async def test_native_pending_question_and_profile_remain_exact(tmp_path, monkeypatch):
    from deeptutor.learning.models import LearnerProfile, PendingQuestion

    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    service.save(
        LearningProgress(
            book_id="path",
            modules=[
                LearningModule(
                    id="m",
                    name="Module",
                    order=0,
                    knowledge_points=[
                        KnowledgePoint(id=p, name=p, module_id="m", type="memory")
                        for p in ("one", "two")
                    ],
                )
            ],
            pending_question=PendingQuestion(
                question_id="pending",
                knowledge_point_id="two",
                module_id="m",
                prompt="Which relationship applies?",
                expected_answer="private key",
            ),
            learner_profile=LearnerProfile(
                preferences="Use connected explanations", time_budget="Two weeks"
            ),
        )
    )
    monkeypatch.setattr("deeptutor.capabilities.mastery.tools._new_service", lambda: service)
    context = UnifiedContext(metadata={"mastery_mode": True, "mastery_path_id": "path"})
    block = await MasteryLoopCapability().pre_loop(context, None)
    brief = json.loads(block.content[block.content.index("{") :])
    full = json.loads((await MasteryStatusTool().execute(_mastery_path_id="path")).content)
    assert brief["next"]["pending_question"] == full["next"]["pending_question"]
    assert brief["learner_profile"] == full["learner_profile"]
    assert "private key" not in block.content
    assert {p["id"] for m in brief["map"]["modules"] for p in m["knowledge_points"]} == {"two"}
