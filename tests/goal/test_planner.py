from __future__ import annotations

from deeptutor.agents.goal.models import GoalConfig, KnowledgeEdge, KnowledgeNode
from deeptutor.agents.goal.planner import Planner


def test_planner_respects_prerequisite_order() -> None:
    planner = Planner()
    nodes = [
        KnowledgeNode.model_validate(
            {
                "node_id": "node_limit",
                "title": "极限",
                "estimated_minutes": 30,
                "weight": 0.6,
            }
        ),
        KnowledgeNode.model_validate(
            {
                "node_id": "node_derivative",
                "title": "导数",
                "estimated_minutes": 30,
                "weight": 0.9,
                "prerequisites": ["node_limit"],
            }
        ),
    ]
    edges = [
        KnowledgeEdge.model_validate(
            {
                "from": "node_limit",
                "to": "node_derivative",
                "edge_type": "prerequisite",
            }
        )
    ]

    tasks = planner.plan(
        nodes,
        edges,
        GoalConfig(goal_level="foundation", daily_minutes=60, remaining_days=2, kb_name="calc"),
    )

    learn_tasks = [task for task in tasks if task.kind.value == "learn"]
    assert learn_tasks[0].node_id == "node_limit"
    assert learn_tasks[1].node_id == "node_derivative"


def test_planner_backfills_days_when_nodes_are_sparse() -> None:
    planner = Planner()
    nodes = [
        KnowledgeNode.model_validate(
            {
                "node_id": "node_limit",
                "title": "极限",
                "estimated_minutes": 30,
                "weight": 0.8,
            }
        ),
        KnowledgeNode.model_validate(
            {
                "node_id": "node_derivative",
                "title": "导数",
                "estimated_minutes": 35,
                "weight": 0.7,
            }
        ),
    ]

    tasks = planner.plan(
        nodes,
        [],
        GoalConfig(goal_level="foundation", daily_minutes=90, remaining_days=5, kb_name="calc"),
    )

    covered_days = {task.day_index for task in tasks}
    assert covered_days == {1, 2, 3, 4, 5}
    assert any(task.kind.value == "review" for task in tasks)
