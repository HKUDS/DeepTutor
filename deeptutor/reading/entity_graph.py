"""Validation and rendering for reading entity relationship graphs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Sequence
import unicodedata

from deeptutor.reading.models import (
    EntityGraph,
    EntityGraphEdge,
    EntityGraphNode,
    ReadingError,
)

MAX_NODES = 30
MAX_EDGES = 120
MIN_EDGE_CONFIDENCE = 0.35
_MIN_NODE_CONFIDENCE = 0.30


class EntityGraphExtractionError(ReadingError):
    """The model did not return a usable relationship graph."""


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _confidence(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, number))


def _key(value: str) -> str:
    normal = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normal).strip()


def _match_key(value: str) -> str:
    return _key(value)


@dataclass(slots=True)
class _CanonicalEntity:
    key: str
    name: str
    aliases: set[str]
    description: str
    confidence: float


def normalise_entity_graph(
    payload: Any,
    evidence_units: Sequence[tuple[int, str]],
    *,
    max_nodes: int = MAX_NODES,
    max_edges: int = MAX_EDGES,
) -> EntityGraph:
    """Validate an extracted graph and discard relationships without evidence.

    Entity IDs are regenerated from sorted display names. That keeps Mermaid
    identifiers safe and deterministic even when a local model returns Chinese,
    punctuation-bearing, or colliding IDs.
    """
    if not isinstance(payload, dict):
        raise EntityGraphExtractionError("the model response was not a JSON object")

    entities: dict[str, _CanonicalEntity] = {}
    entities_by_reference: dict[str, str] = {}

    def entity_for(raw: dict[str, Any]) -> _CanonicalEntity | None:
        name = _clean(raw.get("name"), 80)
        if not name:
            return None
        confidence = _confidence(raw.get("confidence"), 0.70)
        if confidence < _MIN_NODE_CONFIDENCE:
            return None

        key = _key(name)
        existing = entities.get(key)
        if existing is None:
            existing = _CanonicalEntity(
                key=key,
                name=name,
                aliases=set(),
                description=_clean(raw.get("description"), 240),
                confidence=confidence,
            )
            entities[key] = existing
        else:
            existing.confidence = max(existing.confidence, confidence)
            if not existing.description:
                existing.description = _clean(raw.get("description"), 240)

        raw_id = _clean(raw.get("id"), 80)
        if raw_id:
            entities_by_reference[_key(raw_id)] = existing.key
        for alias in raw.get("aliases") or []:
            cleaned = _clean(alias, 80)
            if cleaned and cleaned.casefold() != existing.name.casefold():
                existing.aliases.add(cleaned)
        entities_by_reference[_key(name)] = existing.key
        return existing

    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, list):
        raise EntityGraphExtractionError("the model response has no nodes array")
    for raw in raw_nodes:
        if len(entities) >= max_nodes:
            break
        if isinstance(raw, dict):
            entity_for(raw)

    normalized_units = tuple((locator, text, _match_key(text)) for locator, text in evidence_units)

    def find_evidence(evidence: str) -> tuple[int, ...]:
        needle = _match_key(evidence)
        return tuple(
            locator for locator, _, haystack in normalized_units if needle and needle in haystack
        )

    raw_edges = payload.get("edges")
    if not isinstance(raw_edges, list):
        raise EntityGraphExtractionError("the model response has no edges array")

    edges_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for raw in raw_edges:
        if len(edges_by_key) >= max_edges:
            break
        if not isinstance(raw, dict):
            continue
        source_ref = _clean(raw.get("source"), 80)
        target_ref = _clean(raw.get("target"), 80)
        source_key = entities_by_reference.get(_key(source_ref), _key(source_ref))
        target_key = entities_by_reference.get(_key(target_ref), _key(target_ref))
        source = entities.get(source_key)
        target = entities.get(target_key)
        if source is None or target is None or source.key == target.key:
            continue

        relation = _clean(raw.get("relation"), 60) or "related"
        confidence = _confidence(raw.get("confidence"), 0.60)
        evidence = _clean(raw.get("evidence"), 240)
        locators = find_evidence(evidence)
        if confidence < MIN_EDGE_CONFIDENCE or not evidence or not locators:
            continue

        edge_key = (
            min(source.key, target.key),
            max(source.key, target.key),
            _key(relation),
        )
        previous = edges_by_key.get(edge_key)
        candidate = {
            "source": source.key,
            "target": target.key,
            "relation": relation,
            "evidence": evidence,
            "locators": locators,
            "confidence": confidence,
        }
        if previous is None or confidence > float(previous["confidence"]):
            edges_by_key[edge_key] = candidate

    ordered_keys = sorted(entities)
    public_ids = {key: f"entity_{index}" for index, key in enumerate(ordered_keys, 1)}
    nodes = tuple(
        EntityGraphNode(
            id=public_ids[key],
            name=entities[key].name,
            aliases=tuple(sorted(entities[key].aliases, key=str.casefold))[:8],
            description=entities[key].description,
            confidence=round(entities[key].confidence, 3),
        )
        for key in ordered_keys
    )
    referenced = {edge[row] for edge in edges_by_key.values() for row in ("source", "target")}
    edges = tuple(
        EntityGraphEdge(
            source=public_ids[edge["source"]],
            target=public_ids[edge["target"]],
            relation=edge["relation"],
            evidence=edge["evidence"],
            evidence_locators=edge["locators"],
            confidence=round(float(edge["confidence"]), 3),
        )
        for edge in edges_by_key.values()
        if edge["source"] in referenced and edge["target"] in referenced
    )
    return EntityGraph(nodes=nodes, edges=edges)


def _mermaid_label(value: str, limit: int) -> str:
    cleaned = _clean(value, limit)
    cleaned = cleaned.replace("\\", "\\\\").replace('"', "'")
    cleaned = re.sub(r"[<>]", "", cleaned)
    return cleaned or "?"


def render_entity_graph_mermaid(graph: EntityGraph) -> str:
    """Render a graph deterministically with strict, quoted Mermaid labels."""
    if not graph.nodes:
        return 'graph LR\n  empty["No entities found"]'

    lines = ["graph LR"]
    for node in graph.nodes:
        lines.append(f'  {node.id}["{_mermaid_label(node.name, 48)}"]')
    for edge in graph.edges:
        relation = _mermaid_label(edge.relation, 28)
        lines.append(f'  {edge.source} -- "{relation}" --> {edge.target}')
    return "\n".join(lines)


__all__ = [
    "EntityGraphExtractionError",
    "MAX_EDGES",
    "MAX_NODES",
    "MIN_EDGE_CONFIDENCE",
    "normalise_entity_graph",
    "render_entity_graph_mermaid",
]
