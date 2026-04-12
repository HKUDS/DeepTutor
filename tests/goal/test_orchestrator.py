from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.agents.goal.exercise_adapter import ExerciseAdapter
from deeptutor.agents.goal.extractor import KnowledgeExtractor
from deeptutor.agents.goal.graph_builder import GraphBuilder
from deeptutor.agents.goal.models import Feedback, GoalConfig
from deeptutor.agents.goal.orchestrator import GoalOrchestrator
from deeptutor.agents.goal.planner import Planner
from deeptutor.agents.goal.scheduler import Scheduler
from deeptutor.agents.goal.storage import GoalStorage
from deeptutor.agents.goal.weight_model import WeightModel


@pytest.mark.asyncio
async def test_orchestrator_runs_end_to_end_without_kb(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path / "goal")
    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")
    orchestrator = GoalOrchestrator(
        storage=storage,
        extractor=extractor,
        graph_builder=GraphBuilder(),
        weight_model=WeightModel(),
        planner=Planner(),
        scheduler=Scheduler(),
        exercise_adapter=ExerciseAdapter(),
    )

    session = await orchestrator.create_session(
        "placeholder_kb",
        GoalConfig(goal_level="foundation", daily_minutes=90, remaining_days=3),
    )
    plan = await orchestrator.run_plan(session.session_id)

    assert plan.plan_version == 1
    assert len(plan.tasks) >= 3
    assert len(plan.days) == 3

    feedback_result = await orchestrator.submit_feedback(
        session.session_id,
        Feedback.model_validate(
            {
                "feedback_id": "fb_task_001",
                "session_id": session.session_id,
                "task_id": plan.tasks[0].task_id,
                "completion": "partial",
                "quiz": {"score": 2, "total": 5},
                "timestamp": "2026-04-09T20:00:00+08:00",
            }
        ),
    )
    assert feedback_result["accepted"] is True

    replanned = await orchestrator.replan(session.session_id, "manual_feedback")
    assert replanned.plan_version == 2
    assert replanned.diff is not None
    assert replanned.diff.added_tasks

    practice = await orchestrator.generate_practice(session.session_id, replanned.tasks[0].task_id, count=2)
    assert practice["practice_set_path"].endswith(".json")


@pytest.mark.asyncio
async def test_get_day_plan_detail_returns_blocks_for_existing_day(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path / "goal")
    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")
    orchestrator = GoalOrchestrator(
        storage=storage,
        extractor=extractor,
        graph_builder=GraphBuilder(),
        weight_model=WeightModel(),
        planner=Planner(),
        scheduler=Scheduler(),
        exercise_adapter=ExerciseAdapter(),
    )

    session = await orchestrator.create_session(
        "placeholder_kb",
        GoalConfig(goal_level="foundation", daily_minutes=90, remaining_days=3),
    )
    plan = await orchestrator.run_plan(session.session_id)
    first_task = next(task for task in plan.tasks if task.day_index == 1)

    detail = orchestrator.get_day_plan_detail(session.session_id, 1)
    assert detail.day_index == 1
    assert detail.time_blocks
    assert first_task.task_id in detail.linked_task_ids
    assert detail.objective_summary


@pytest.mark.asyncio
async def test_get_day_plan_detail_returns_fallback_for_empty_day(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path / "goal")
    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")
    orchestrator = GoalOrchestrator(
        storage=storage,
        extractor=extractor,
        graph_builder=GraphBuilder(),
        weight_model=WeightModel(),
        planner=Planner(),
        scheduler=Scheduler(),
        exercise_adapter=ExerciseAdapter(),
    )

    session = await orchestrator.create_session(
        "placeholder_kb",
        GoalConfig(goal_level="foundation", daily_minutes=90, remaining_days=3),
    )
    await orchestrator.run_plan(session.session_id)

    detail = orchestrator.get_day_plan_detail(session.session_id, 4)
    assert detail.day_index == 4
    assert len(detail.time_blocks) == 1
    assert detail.time_blocks[0].title == "轻量复盘与预热"
    assert detail.linked_task_ids == []


@pytest.mark.asyncio
async def test_get_day_plan_detail_raises_for_invalid_day_index(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path / "goal")
    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")
    orchestrator = GoalOrchestrator(
        storage=storage,
        extractor=extractor,
        graph_builder=GraphBuilder(),
        weight_model=WeightModel(),
        planner=Planner(),
        scheduler=Scheduler(),
        exercise_adapter=ExerciseAdapter(),
    )
    session = await orchestrator.create_session(
        "placeholder_kb",
        GoalConfig(goal_level="foundation", daily_minutes=90, remaining_days=3),
    )
    await orchestrator.run_plan(session.session_id)

    with pytest.raises(ValueError, match="day_index must be > 0"):
        orchestrator.get_day_plan_detail(session.session_id, 0)


@pytest.mark.asyncio
async def test_submit_feedback_persists_task_status_to_plan(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path / "goal")
    extractor = KnowledgeExtractor(kb_base_dir=tmp_path / "knowledge_bases")
    orchestrator = GoalOrchestrator(
        storage=storage,
        extractor=extractor,
        graph_builder=GraphBuilder(),
        weight_model=WeightModel(),
        planner=Planner(),
        scheduler=Scheduler(),
        exercise_adapter=ExerciseAdapter(),
    )

    session = await orchestrator.create_session(
        "placeholder_kb",
        GoalConfig(goal_level="foundation", daily_minutes=90, remaining_days=3),
    )
    plan = await orchestrator.run_plan(session.session_id)
    target_task = plan.tasks[0]

    await orchestrator.submit_feedback(
        session.session_id,
        Feedback.model_validate(
            {
                "feedback_id": "fb_task_status_001",
                "session_id": session.session_id,
                "task_id": target_task.task_id,
                "completion": "done",
                "timestamp": "2026-04-10T20:00:00+08:00",
            }
        ),
    )

    persisted_plan = storage.load_plan(session.session_id)
    persisted_task = next(task for task in persisted_plan.tasks if task.task_id == target_task.task_id)
    assert persisted_task.status.value == "done"
