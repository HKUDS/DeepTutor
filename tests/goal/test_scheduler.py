from __future__ import annotations

from deeptutor.agents.goal.models import Feedback, Plan
from deeptutor.agents.goal.scheduler import Scheduler


def _build_plan() -> Plan:
    return Plan.model_validate(
        {
            "plan_id": "plan_001",
            "session_id": "goal_001",
            "kb_name": "calc",
            "plan_version": 1,
            "days": [
                {"day_index": 1, "budget_minutes": 90, "task_ids": ["task_day1_001"]},
                {"day_index": 2, "budget_minutes": 90, "task_ids": []},
            ],
            "tasks": [
                {
                    "task_id": "task_day1_001",
                    "day_index": 1,
                    "node_id": "node_limit",
                    "title": "学习极限",
                    "kind": "learn",
                    "objective": "掌握极限定义",
                    "estimate_minutes": 45,
                    "practice_spec": {
                        "difficulty": "easy",
                        "question_type": "short_answer",
                        "count": 3,
                    },
                }
            ],
            "artifacts": {"root_dir": "data/user/goal/goal_001"},
        }
    )


def test_scheduler_adds_review_and_moves_partial_task() -> None:
    scheduler = Scheduler()
    plan = _build_plan()
    feedback = Feedback.model_validate(
        {
            "feedback_id": "fb_001",
            "session_id": "goal_001",
            "task_id": "task_day1_001",
            "completion": "partial",
            "quiz": {"score": 2, "total": 5},
            "timestamp": "2026-04-09T20:00:00+08:00",
        }
    )

    new_plan, diff = scheduler.replan(plan, [feedback])

    assert new_plan.plan_version == 2
    assert "task_day1_001_review" in diff["added_tasks"]
    assert "task_day1_001_drill" in diff["added_tasks"]
    assert "task_day1_001" in diff["moved_tasks"]
    assert any(task.task_id == "task_day1_001_review" for task in new_plan.tasks)
    assert any(task.task_id == "task_day1_001_drill" for task in new_plan.tasks)
