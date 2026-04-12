from __future__ import annotations

from deeptutor.agents.goal.models import GoalConfig, KnowledgeNode
from deeptutor.agents.goal.weight_model import WeightModel


def test_weight_model_applies_formula_and_foundation_bias() -> None:
    model = WeightModel()
    nodes = [
        KnowledgeNode.model_validate(
            {
                "node_id": "node_limit",
                "title": "极限",
                "tags": ["基础"],
                "signals": {
                    "doc_freq": 0.8,
                    "practice_freq": 0.4,
                    "heading_score": 0.6,
                    "weakness_score": 0.1,
                },
            }
        ),
        KnowledgeNode.model_validate(
            {
                "node_id": "node_chain_rule",
                "title": "链式法则",
                "tags": ["综合"],
                "signals": {
                    "doc_freq": 0.5,
                    "practice_freq": 0.3,
                    "heading_score": 0.2,
                    "weakness_score": 0.2,
                },
            }
        ),
    ]

    scored = model.score(
        nodes=nodes,
        edges=[],
        goal_config=GoalConfig(goal_level="foundation", daily_minutes=90, remaining_days=7),
    )

    # 0.35*0.8 + 0.25*0.4 + 0.20*0.6 + 0.20*0.1 + foundation_bias(0.15)
    # + short-horizon practice boost(0.08*0.4) + high-yield strategy boost(0.1*0.8)
    assert scored[0].node_id == "node_limit"
    assert scored[0].weight == 0.782


def test_weight_model_uses_feedback_weakness_override() -> None:
    model = WeightModel()
    node = KnowledgeNode.model_validate(
        {
            "node_id": "node_integral",
            "title": "积分",
            "signals": {
                "doc_freq": 0.2,
                "practice_freq": 0.2,
                "heading_score": 0.2,
                "weakness_score": 0.1,
            },
        }
    )

    scored = model.score(
        nodes=[node],
        edges=[],
        goal_config=GoalConfig(goal_level="competent", daily_minutes=90, remaining_days=7),
        feedback_summary={"weakness_score": {"node_integral": 0.9}},
    )

    # 0.35*0.2 + 0.25*0.2 + 0.20*0.2 + 0.20*0.9
    # + short-horizon practice boost(0.08*0.2) + high-yield strategy boost(0.1*0.2)
    assert scored[0].weight == 0.376
