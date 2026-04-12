"""Graph construction for Goal mode."""

from __future__ import annotations

from deeptutor.agents.goal.models import EdgeType, KnowledgeEdge, KnowledgeNode, KnowledgeNodeDraft
from deeptutor.agents.goal.utils import slugify


class GraphBuilder:
    """Convert drafts into a lightweight knowledge graph."""

    def build(
        self,
        drafts: list[KnowledgeNodeDraft],
    ) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
        nodes: list[KnowledgeNode] = []
        edges: list[KnowledgeEdge] = []

        for index, draft in enumerate(drafts):
            node_id = f"node_{slugify(draft.title)}"
            prerequisites = [f"node_{slugify(title)}" for title in draft.prerequisites]
            nodes.append(
                KnowledgeNode(
                    node_id=node_id,
                    title=draft.title,
                    aliases=draft.aliases,
                    node_type=draft.node_type,
                    tags=draft.tags,
                    prerequisites=prerequisites,
                    estimated_minutes=draft.estimated_minutes,
                    weight_evidence=draft.evidence,
                    signals={
                        "doc_freq": draft.doc_freq,
                        "practice_freq": draft.practice_freq,
                        "heading_score": draft.heading_score,
                        "weakness_score": draft.weakness_score,
                    },
                )
            )

            if index > 0:
                edges.append(
                    KnowledgeEdge(
                        **{
                            "from": nodes[index - 1].node_id,
                            "to": node_id,
                            "edge_type": EdgeType.RELATED,
                            "weight": 0.5,
                        }
                    )
                )

            for prerequisite in prerequisites:
                edges.append(
                    KnowledgeEdge(
                        **{
                            "from": prerequisite,
                            "to": node_id,
                            "edge_type": EdgeType.PREREQUISITE,
                            "weight": 1.0,
                        }
                    )
                )

        return nodes, edges
