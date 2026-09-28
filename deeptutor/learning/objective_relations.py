"""Validation and request-reference handling for mastery objective relations.

Relations are structural metadata in this slice. They do not gate learning or
retrieval yet, but every writer must leave them internally consistent.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from deeptutor.learning.models import KnowledgePoint, LearningModule, TopicSource, TopicSourceKind


class ObjectiveRelationError(ValueError):
    """Raised when a mutation would leave an invalid objective graph."""


@dataclass(frozen=True)
class RelationRefs:
    """Request-local references carried alongside provisional objective ids."""

    client_ref: str = ""
    prerequisite_refs: list[str] = field(default_factory=list)
    topic_source_refs: list[str] = field(default_factory=list)


def normalize_refs(values: Iterable[Any] | None, *, label: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        ref = str(value or "").strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs


def source_ref_map(
    sources: Iterable[TopicSource], aliases: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Map request-local source aliases and durable source ids to durable ids."""

    resolved: dict[str, str] = {}
    for source in sources:
        if source.kind == TopicSourceKind.GOAL:
            continue
        if source.id in resolved:
            raise ObjectiveRelationError(f"Duplicate topic source id {source.id!r}")
        resolved[source.id] = source.id
    for alias, source_id in (aliases or {}).items():
        alias = str(alias or "").strip()
        if not alias:
            continue
        if source_id not in resolved:
            raise ObjectiveRelationError(
                f"Source alias {alias!r} names unknown source {source_id!r}"
            )
        if alias in resolved and resolved[alias] != source_id:
            raise ObjectiveRelationError(f"Source reference {alias!r} is ambiguous")
        resolved[alias] = source_id
    return resolved


def _knowledge_points(modules: Iterable[LearningModule]) -> Iterable[KnowledgePoint]:
    for module in modules:
        yield from module.knowledge_points


def validate_objective_relations(
    modules: Iterable[LearningModule], sources: Iterable[TopicSource]
) -> None:
    points = list(_knowledge_points(modules))
    point_ids = {point.id for point in points}
    if len(point_ids) != len(points):
        raise ObjectiveRelationError("Knowledge point ids must be unique within a mastery path")

    source_ids = {source.id for source in sources if source.kind != TopicSourceKind.GOAL}
    names = {point.id: point.name for point in points}

    graph: dict[str, list[str]] = {}
    for point in points:
        prerequisites = normalize_refs(point.prerequisite_ids, label="prerequisite")
        point.prerequisite_ids = prerequisites
        graph[point.id] = prerequisites
        topic_sources = normalize_refs(point.topic_source_ids, label="topic source")
        point.topic_source_ids = topic_sources
        unknown_sources = [ref for ref in topic_sources if ref not in source_ids]
        if unknown_sources:
            raise ObjectiveRelationError(
                f"Objective {names[point.id]!r} references unknown or goal topic source "
                f"{unknown_sources[0]!r}"
            )

    for point_id, prerequisites in graph.items():
        for prerequisite in prerequisites:
            if prerequisite == point_id:
                raise ObjectiveRelationError(
                    f"Objective {names[point_id]!r} cannot be its own prerequisite"
                )
            if prerequisite not in graph:
                raise ObjectiveRelationError(
                    f"Objective {names[point_id]!r} has unknown prerequisite {prerequisite!r}"
                )

    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(point_id: str) -> None:
        if point_id in visited:
            return
        if point_id in visiting:
            cycle_start = path.index(point_id)
            cycle = path[cycle_start:] + [point_id]
            raise ObjectiveRelationError("Prerequisite cycle: " + " -> ".join(cycle))
        visiting.add(point_id)
        path.append(point_id)
        for prerequisite in graph[point_id]:
            visit(prerequisite)
        path.pop()
        visiting.remove(point_id)
        visited.add(point_id)

    for point_id in graph:
        visit(point_id)


def resolve_relation_refs(
    modules: list[LearningModule],
    relation_refs: Mapping[str, RelationRefs],
    *,
    prerequisite_aliases: Mapping[str, str],
    source_aliases: Mapping[str, str],
    sources: Iterable[TopicSource],
) -> None:
    """Resolve request-local refs into durable ids on the final module tree."""

    source_ids = source_ref_map(sources, source_aliases)
    for module in modules:
        for point in module.knowledge_points:
            refs = relation_refs.get(point.id)
            if refs is None:
                continue
            prerequisites: list[str] = []
            seen_prerequisites: set[str] = set()
            for ref in normalize_refs(refs.prerequisite_refs, label="prerequisite"):
                if ref not in prerequisite_aliases:
                    raise ObjectiveRelationError(
                        f"Objective {point.name!r} has unknown prerequisite ref {ref!r}"
                    )
                resolved = prerequisite_aliases[ref]
                if resolved not in seen_prerequisites:
                    seen_prerequisites.add(resolved)
                    prerequisites.append(resolved)
            point.prerequisite_ids = prerequisites

            topic_sources: list[str] = []
            seen_sources: set[str] = set()
            for ref in normalize_refs(refs.topic_source_refs, label="topic source"):
                if ref not in source_ids:
                    raise ObjectiveRelationError(
                        f"Objective {point.name!r} has unknown topic source ref {ref!r}"
                    )
                resolved = source_ids[ref]
                if resolved not in seen_sources:
                    seen_sources.add(resolved)
                    topic_sources.append(resolved)
            point.topic_source_ids = topic_sources


__all__ = [
    "ObjectiveRelationError",
    "RelationRefs",
    "normalize_refs",
    "resolve_relation_refs",
    "source_ref_map",
    "validate_objective_relations",
]
