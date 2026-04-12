from __future__ import annotations

import json
from pathlib import Path

from deeptutor.agents.goal.models import GoalSession, Plan
from deeptutor.agents.goal.storage import GoalStorage


def _build_session() -> GoalSession:
    return GoalSession.model_validate(
        {
            "session_id": "goal_001",
            "kb_name": "calc",
            "goal_config": {
                "goal_level": "foundation",
                "daily_minutes": 90,
            },
            "artifacts": {
                "root_dir": "data/user/goal/goal_001",
            },
        }
    )


def _build_plan(version: int = 1) -> Plan:
    return Plan.model_validate(
        {
            "plan_id": "plan_001",
            "session_id": "goal_001",
            "kb_name": "calc",
            "plan_version": version,
            "days": [
                {
                    "day_index": 1,
                    "budget_minutes": 90,
                    "task_ids": ["task_001"],
                }
            ],
            "tasks": [
                {
                    "task_id": "task_001",
                    "day_index": 1,
                    "node_id": "node_limit",
                    "title": "Learn limit basics",
                    "kind": "learn",
                    "objective": "Understand the core definition",
                    "estimate_minutes": 45,
                }
            ],
            "artifacts": {
                "root_dir": "data/user/goal/goal_001",
            },
        }
    )


def test_storage_saves_and_loads_session(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path)
    session = _build_session()

    path = storage.save_session(session)
    loaded = storage.load_session(session.session_id)

    assert Path(path).exists()
    assert loaded.session_id == session.session_id


def test_storage_version_snapshots_existing_plan(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path)
    storage.save_plan(_build_plan(version=1))
    storage.save_plan(_build_plan(version=2))

    snapshot = tmp_path / "goal_001" / "plan.v1.json"
    current = tmp_path / "goal_001" / "plan.json"

    assert snapshot.exists()
    assert current.exists()
    assert json.loads(snapshot.read_text(encoding="utf-8"))["plan_version"] == 1


def test_storage_appends_events(tmp_path: Path) -> None:
    storage = GoalStorage(base_dir=tmp_path)
    storage.append_event("goal_001", {"type": "stage", "stage": "extract", "progress": 0.4})

    event_file = tmp_path / "goal_001" / "events.jsonl"
    lines = event_file.read_text(encoding="utf-8").strip().splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0])["stage"] == "extract"
