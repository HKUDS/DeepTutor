"""Tests for reading entity graph validation and rendering."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.reading.entity_graph import (
    normalise_entity_graph,
    render_entity_graph_mermaid,
)
from deeptutor.reading.store import ReadingStore
from deeptutor.services import reading_entity_graph
from deeptutor.services.reading_entity_graph import build_entity_graph


def test_graph_edges_require_verbatim_evidence() -> None:
    payload = {
        "nodes": [
            {"id": "alice", "name": "Alice", "aliases": ["Ally"], "confidence": 0.9},
            {"id": "bob", "name": "Bob", "confidence": 0.8},
            {"id": "ghost", "name": "Ghost", "confidence": 0.2},
        ],
        "edges": [
            {
                "source": "alice",
                "target": "bob",
                "relation": "partners",
                "evidence": "Alice told Bob they were partners",
                "confidence": 0.9,
            },
            {
                "source": "alice",
                "target": "bob",
                "relation": "rivals",
                "evidence": "This sentence is not in the chapter.",
                "confidence": 0.9,
            },
            {
                "source": "alice",
                "target": "ghost",
                "relation": "haunted",
                "evidence": "Alice told Bob they were partners",
                "confidence": 0.9,
            },
        ],
    }
    evidence_units = [(1, "Later, Alice told Bob they were partners.\n")]

    graph = normalise_entity_graph(payload, evidence_units)

    assert [node.name for node in graph.nodes] == ["Alice", "Bob"]
    assert graph.nodes[0].aliases == ("Ally",)
    assert len(graph.edges) == 1
    assert graph.edges[0].source == "entity_1"
    assert graph.edges[0].target == "entity_2"
    assert graph.edges[0].evidence_locators == (1,)


def test_graph_mermaid_output_is_deterministic_and_label_safe() -> None:
    payload = {
        "nodes": [
            {"id": "a <bad>", "name": 'Alice "The Architect"', "confidence": 1},
            {"id": "b", "name": "Bob", "confidence": 1},
        ],
        "edges": [
            {
                "source": "a <bad>",
                "target": "b",
                "relation": "partners",
                "evidence": "Alice and Bob are partners.",
                "confidence": 1,
            }
        ],
    }
    evidence_units = [(2, "Alice and Bob are partners.")]

    graph = normalise_entity_graph(payload, evidence_units)
    rendered = render_entity_graph_mermaid(graph)

    assert rendered.startswith("graph LR\n")
    assert "Alice 'The Architect'" in rendered
    assert "<" not in rendered and ">" not in rendered or " --> " in rendered
    assert 'entity_1 -- "partners" --> entity_2' in rendered
    assert render_entity_graph_mermaid(graph) == rendered


def test_empty_graph_renders_an_explicit_empty_state() -> None:
    assert 'empty["No entities found"]' in render_entity_graph_mermaid(
        normalise_entity_graph({"nodes": [], "edges": []}, [])
    )


@pytest.mark.asyncio
async def test_blank_unit_text_returns_empty_graph_without_calling_the_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    source = tmp_path / "blank.txt"
    source.write_text("temporary readable text", encoding="utf-8")
    manifest = store.ingest(source)
    (store.root / manifest.material_id / "units" / "0001.txt").write_text(" \n", encoding="utf-8")

    async def unexpected_llm_call(context, rows):
        raise AssertionError("blank unit text must not call the LLM")

    monkeypatch.setattr(reading_entity_graph, "_extract", unexpected_llm_call)
    result = await build_entity_graph(store, manifest.material_id, locator=1, scope="current")

    assert result.graph.nodes == ()
    assert result.graph.edges == ()
    assert 'empty["No entities found"]' in result.mermaid


@pytest.mark.asyncio
async def test_through_current_scope_preserves_the_current_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    source = tmp_path / "long-history.txt"
    source.write_text("temporary readable text", encoding="utf-8")
    manifest = store.ingest(source)

    material_dir = store.root / manifest.material_id
    manifest_path = material_dir / "manifest.json"
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["unit_count"] = 2
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    current_text = "Alice and Bob are partners."
    (material_dir / "units" / "0001.txt").write_text(
        "x" * (reading_entity_graph._MAX_PRIOR_CHARS + 1),
        encoding="utf-8",
    )
    (material_dir / "units" / "0002.txt").write_text(current_text, encoding="utf-8")

    captured_rows: list[tuple[int, str]] = []

    async def capture_rows(context, rows):
        captured_rows.extend(rows)
        return normalise_entity_graph({"nodes": [], "edges": []}, rows)

    monkeypatch.setattr(reading_entity_graph, "_extract", capture_rows)
    reading_entity_graph._CACHE.clear()

    result = await build_entity_graph(
        store,
        manifest.material_id,
        locator=2,
        scope="through_current",
    )

    assert result.included_locators == (1, 2)
    assert result.truncated is True
    assert len(captured_rows[0][1]) == reading_entity_graph._MAX_PRIOR_CHARS
    assert captured_rows[1] == (2, current_text)
