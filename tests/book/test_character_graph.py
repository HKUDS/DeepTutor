"""Tests for character relationship graph extraction and rendering."""

from __future__ import annotations

import unittest

from deeptutor.book.character_graph import (
    _hash_text,
    render_character_graph_mermaid,
)
from deeptutor.book.models import (
    CharacterEdge,
    CharacterGraph,
    CharacterNode,
)


class TestMermaidRendering(unittest.TestCase):
    """Verify Mermaid graph LR output from CharacterGraph data."""

    def test_empty_graph(self):
        graph = CharacterGraph()
        result = render_character_graph_mermaid(graph)
        self.assertIn("graph LR", result)
        self.assertIn("No characters found", result)

    def test_simple_graph(self):
        graph = CharacterGraph(
            nodes=[
                CharacterNode(id="alice", name="Alice"),
                CharacterNode(id="bob", name="Bob"),
            ],
            edges=[
                CharacterEdge(source="alice", target="bob", relation="friend"),
            ],
        )
        result = render_character_graph_mermaid(graph)
        self.assertIn("graph LR", result)
        self.assertIn("Alice", result)
        self.assertIn("Bob", result)
        self.assertIn("friend", result)
        self.assertIn("-->", result)

    def test_label_escaping(self):
        """Double quotes in names should be replaced with single quotes."""
        graph = CharacterGraph(
            nodes=[CharacterNode(id="a", name='John "The Boss"')],
        )
        result = render_character_graph_mermaid(graph)
        # The rendered label should use single quotes, not doubles
        self.assertIn("'The Boss'", result)

    def test_label_truncation(self):
        """Very long names should be truncated with ellipsis."""
        long_name = "A" * 100
        graph = CharacterGraph(
            nodes=[CharacterNode(id="a", name=long_name)],
        )
        result = render_character_graph_mermaid(graph)
        self.assertIn("...", result)

    def test_edge_with_missing_nodes_skipped(self):
        """Edges referencing non-existent nodes should be silently dropped."""
        graph = CharacterGraph(
            nodes=[CharacterNode(id="a", name="Alice")],
            edges=[
                CharacterEdge(source="a", target="ghost", relation="rival"),
            ],
        )
        result = render_character_graph_mermaid(graph)
        self.assertNotIn("ghost", result)
        self.assertIn("Alice", result)

    def test_relation_label_on_edge(self):
        graph = CharacterGraph(
            nodes=[
                CharacterNode(id="a", name="Alice"),
                CharacterNode(id="b", name="Bob"),
            ],
            edges=[
                CharacterEdge(source="a", target="b", relation="parent_of"),
            ],
        )
        result = render_character_graph_mermaid(graph)
        self.assertIn("parent_of", result)

    def test_multiple_edges(self):
        graph = CharacterGraph(
            nodes=[
                CharacterNode(id="a", name="Alice"),
                CharacterNode(id="b", name="Bob"),
                CharacterNode(id="c", name="Carol"),
            ],
            edges=[
                CharacterEdge(source="a", target="b", relation="friend"),
                CharacterEdge(source="b", target="c", relation="sibling"),
                CharacterEdge(source="a", target="c", relation="mentor"),
            ],
        )
        result = render_character_graph_mermaid(graph)
        self.assertEqual(result.count("-->"), 3)

    def test_safe_ids(self):
        """Non-ASCII IDs should be converted to safe Mermaid identifiers."""
        graph = CharacterGraph(
            nodes=[
                CharacterNode(id="孙悟空", name="Sun Wukong"),
                CharacterNode(id="唐僧", name="Tang Seng"),
            ],
            edges=[
                CharacterEdge(
                    source="孙悟空", target="唐僧", relation="disciple_of"
                ),
            ],
        )
        result = render_character_graph_mermaid(graph)
        self.assertIn("Sun Wukong", result)
        self.assertIn("Tang Seng", result)


class TestHashText(unittest.TestCase):
    def test_hash_stability(self):
        text = "Hello, World!"
        h1 = _hash_text(text)
        h2 = _hash_text(text)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_hash_differences(self):
        self.assertNotEqual(_hash_text("text A"), _hash_text("text B"))

    def test_empty_text(self):
        h = _hash_text("")
        self.assertEqual(len(h), 16)


class TestCharacterGraphModel(unittest.TestCase):
    def test_node_by_id(self):
        graph = CharacterGraph(
            nodes=[CharacterNode(id="alice", name="Alice")],
        )
        self.assertIsNotNone(graph.node_by_id("alice"))
        self.assertEqual(graph.node_by_id("alice").name, "Alice")
        self.assertIsNone(graph.node_by_id("ghost"))

    def test_model_dump_roundtrip(self):
        graph = CharacterGraph(
            book_id="bk1",
            chapter_id="ch1",
            scope="current",
            nodes=[
                CharacterNode(
                    id="a", name="Alice", aliases=["Al"], description="hero"
                ),
            ],
            edges=[
                CharacterEdge(source="a", target="a", relation="self"),
            ],
        )
        data = graph.model_dump(mode="json")
        restored = CharacterGraph.model_validate(data)
        self.assertEqual(restored.book_id, "bk1")
        self.assertEqual(len(restored.nodes), 1)
        self.assertEqual(restored.nodes[0].name, "Alice")
        self.assertEqual(restored.nodes[0].aliases, ["Al"])

    def test_default_scope(self):
        graph = CharacterGraph()
        self.assertEqual(graph.scope, "current")

    def test_edge_confidence_default(self):
        edge = CharacterEdge(source="a", target="b", relation="friend")
        self.assertEqual(edge.confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
