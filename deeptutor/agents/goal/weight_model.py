"""Weight scoring for Goal mode."""

from __future__ import annotations

from deeptutor.agents.goal.models import GoalConfig, GoalLevel, KnowledgeEdge, KnowledgeNode, PlanningStrategy


class WeightModel:
    """Score knowledge nodes using deterministic signals."""

    def score(
        self,
        nodes: list[KnowledgeNode],
        edges: list[KnowledgeEdge],
        goal_config: GoalConfig,
        feedback_summary: dict | None = None,
    ) -> list[KnowledgeNode]:
        weakness_signals = (feedback_summary or {}).get("weakness_score", {})
        for node in nodes:
            doc_freq = node.signals.get("doc_freq", 0.0)
            practice_freq = node.signals.get("practice_freq", 0.0)
            heading_score = node.signals.get("heading_score", 0.0)
            weakness_score = weakness_signals.get(node.node_id, node.signals.get("weakness_score", 0.0))

            weight = (
                0.35 * doc_freq
                + 0.25 * practice_freq
                + 0.20 * heading_score
                + 0.20 * weakness_score
            )
            if goal_config.goal_level == GoalLevel.FOUNDATION and "基础" in node.tags:
                weight += 0.15
            elif goal_config.goal_level == GoalLevel.ADVANCED and "基础" not in node.tags:
                weight += 0.10

            # High-yield tags and exam-style resources should be prioritized in time-constrained mode.
            if any(tag in node.tags for tag in ("高频", "真题", "重点")):
                weight += 0.12
            if goal_config.remaining_days <= 10:
                weight += 0.08 * practice_freq
            if goal_config.preferences.strategy == PlanningStrategy.HIGH_YIELD_FIRST:
                weight += 0.1 * max(doc_freq, practice_freq)
            elif goal_config.preferences.strategy == PlanningStrategy.DEPTH_FIRST and "基础" in node.tags:
                weight += 0.05

            node.weight = round(weight, 4)
        return sorted(nodes, key=lambda item: item.weight, reverse=True)
