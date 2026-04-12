from __future__ import annotations

from deeptutor.agents.goal.graph_builder import GraphBuilder
from deeptutor.agents.goal.models import KnowledgeNodeDraft, WeightEvidence


def test_graph_builder_builds_nodes_and_edges() -> None:
    builder = GraphBuilder()
    drafts = [
        KnowledgeNodeDraft(
            title="极限",
            evidence=[WeightEvidence(source="doc.md", snippet="极限基础")],
            tags=["基础"],
        ),
        KnowledgeNodeDraft(
            title="导数",
            prerequisites=["极限"],
            evidence=[WeightEvidence(source="doc.md", snippet="导数依赖极限")],
        ),
    ]

    nodes, edges = builder.build(drafts)

    assert len(nodes) == 2
    assert nodes[0].node_id == "node_极限"
    assert nodes[1].node_id == "node_导数"
    assert nodes[1].prerequisites == ["node_极限"]

    edge_pairs = {(edge.from_, edge.to, edge.edge_type.value) for edge in edges}
    assert ("node_极限", "node_导数", "related") in edge_pairs
    assert ("node_极限", "node_导数", "prerequisite") in edge_pairs
