from __future__ import annotations

import pytest

from deeptutor.agents.goal.models import GoalConfig, GoalLevel, GoalSession, Plan


def test_goal_config_requires_positive_daily_minutes() -> None:
    with pytest.raises(ValueError):
        GoalConfig(goal_level=GoalLevel.FOUNDATION, daily_minutes=0)


def test_goal_config_json_schema_exposes_required_fields() -> None:
    schema = GoalConfig.model_json_schema()
    assert "goal_level" in schema["required"]
    assert "daily_minutes" in schema["required"]


def test_plan_requires_days_and_tasks() -> None:
    with pytest.raises(ValueError):
        Plan.model_validate(
            {
                "plan_id": "plan_001",
                "session_id": "goal_001",
                "kb_name": "calc",
                "plan_version": 1,
                "days": None,
                "tasks": [],
                "artifacts": {
                    "root_dir": "data/user/goal/goal_001",
                },
            }
        )


def test_goal_session_round_trip_dump_validate() -> None:
    session = GoalSession.model_validate(
        {
            "session_id": "goal_001",
            "kb_name": "calc",
            "goal_config": {
                "goal_level": "foundation",
                "daily_minutes": 60,
            },
            "artifacts": {
                "root_dir": "data/user/goal/goal_001",
            },
        }
    )

    dumped = session.model_dump(mode="json")
    restored = GoalSession.model_validate(dumped)

    assert restored.session_id == "goal_001"
    assert restored.goal_config.daily_minutes == 60
