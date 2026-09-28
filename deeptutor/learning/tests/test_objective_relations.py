"""Objective relations are structural metadata and must stay internally valid."""

from __future__ import annotations

from random import Random

import pytest

from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    TopicMetadata,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.learning.objective_relations import (
    ObjectiveRelationError,
    RelationRefs,
    normalize_refs,
    resolve_relation_refs,
    validate_objective_relations,
)
from deeptutor.learning.service import LearningService
from deeptutor.learning.storage import LearningStore


def _kp(kp_id: str, *, prerequisites: list[str] | None = None) -> KnowledgePoint:
    return KnowledgePoint(
        id=kp_id,
        name=f"Objective {kp_id}",
        type=KnowledgeType.CONCEPT,
        module_id="m0",
        prerequisite_ids=prerequisites or [],
    )


def _module(*points: KnowledgePoint) -> LearningModule:
    return LearningModule(id="m0", name="Foundations", order=0, knowledge_points=list(points))


def _source(source_id: str = "source_notes", kind: TopicSourceKind = TopicSourceKind.NOTEBOOK):
    return TopicSource(id=source_id, kind=kind, label=source_id)


def test_legacy_objectives_default_to_empty_relations():
    point = KnowledgePoint.model_validate(
        {"id": "kp1", "name": "Legacy", "type": "concept", "module_id": "m0"}
    )

    assert point.prerequisite_ids == []
    assert point.topic_source_ids == []


def test_validation_deduplicates_and_preserves_first_reference_order():
    point = _kp("kp1", prerequisites=["kp0", "", "kp0", "kp2"])
    point.topic_source_ids = ["source_notes", "source_book", "source_notes"]

    validate_objective_relations(
        [_module(_kp("kp0"), point, _kp("kp2", prerequisites=["kp0"]))],
        [_source("source_notes"), _source("source_book", TopicSourceKind.BOOK)],
    )

    assert point.prerequisite_ids == ["kp0", "kp2"]
    assert point.topic_source_ids == ["source_notes", "source_book"]


@pytest.mark.parametrize(
    "prerequisites, match",
    [
        (["missing"], "unknown prerequisite"),
        (["kp1"], "own prerequisite"),
        (["kp2"], "Prerequisite cycle"),
    ],
)
def test_validation_rejects_invalid_prerequisite_edges(prerequisites: list[str], match: str):
    first = _kp("kp1", prerequisites=prerequisites)
    second = _kp("kp2", prerequisites=["kp1"])

    with pytest.raises(ObjectiveRelationError, match=match):
        validate_objective_relations([_module(first, second)], [])


@pytest.mark.parametrize(
    "sources, match",
    [
        ([], "unknown or goal topic source"),
        ([_source("goal", TopicSourceKind.GOAL)], "unknown or goal topic source"),
    ],
)
def test_validation_rejects_sources_outside_the_topic(sources: list[TopicSource], match: str):
    point = _kp("kp1")
    point.topic_source_ids = ["goal" if not sources else "source_notes"]

    with pytest.raises(ObjectiveRelationError, match=match):
        validate_objective_relations([_module(point)], sources)


def test_random_dags_remain_valid_until_an_invalid_edge_is_injected():
    rng = Random(1290)
    for _ in range(12):
        point_ids = [f"kp{index}" for index in range(rng.randint(2, 16))]
        points = [
            _kp(
                point_id,
                prerequisites=[earlier for earlier in point_ids[:index] if rng.random() < 0.25],
            )
            for index, point_id in enumerate(point_ids)
        ]
        modules = [_module(*points)]
        validate_objective_relations(modules, [])
        assert all(
            point.prerequisite_ids == normalize_refs(point.prerequisite_ids, label="prerequisite")
            for point in points
        )

        damaged = _kp(point_ids[-1], prerequisites=[point_ids[-1]])
        with pytest.raises(ObjectiveRelationError, match="own prerequisite"):
            validate_objective_relations([_module(damaged)], [])


def test_resolve_maps_client_refs_and_source_aliases_to_final_ids():
    first = _kp("draft_a")
    second = _kp("draft_b")
    refs = {
        "draft_b": RelationRefs(
            client_ref="second",
            prerequisite_refs=["draft_a", "draft_a"],
            topic_source_refs=["notes"],
        )
    }

    resolve_relation_refs(
        [_module(first, second)],
        refs,
        prerequisite_aliases={"draft_a": "final_a", "second": "final_b"},
        source_aliases={"notes": "source_notes"},
        sources=[_source()],
    )

    assert second.prerequisite_ids == ["final_a"]
    assert second.topic_source_ids == ["source_notes"]


def test_duplicate_client_refs_reject_topic_creation_without_persisting(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    modules = [_module(_kp("draft_a"), _kp("draft_b"))]

    with pytest.raises(ObjectiveRelationError, match="ambiguous"):
        service.create_topic(
            "topic",
            name="Relations",
            modules=modules,
            metadata=TopicMetadata(path_id="topic", goal="Learn relations"),
            sources=[],
            relation_refs={
                "draft_a": RelationRefs(client_ref="same"),
                "draft_b": RelationRefs(client_ref="same"),
            },
        )

    assert store.load("topic") is None


def test_append_resolves_refs_after_final_ids_are_assigned(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    metadata = TopicMetadata(path_id="topic", goal="Learn relations")
    source = _source()
    service.create_topic(
        "topic",
        name="Relations",
        modules=[_module(_kp("base"))],
        metadata=metadata,
        sources=[source],
    )
    incoming = LearningModule(
        id="draft_module",
        name="Next steps",
        order=1,
        knowledge_points=[_kp("draft_next")],
    )

    progress = service.replace_modules_for_path(
        "topic",
        [incoming],
        append=True,
        relation_refs={
            "draft_next": RelationRefs(
                client_ref="next",
                prerequisite_refs=["base"],
                topic_source_refs=["source_notes"],
            )
        },
    )

    appended = progress.modules[1].knowledge_points[0]
    assert appended.id == "topic_m1_kp0"
    assert appended.prerequisite_ids == ["base"]
    assert appended.topic_source_ids == ["source_notes"]


def test_replace_build_can_start_a_fresh_objective_identity(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    first = service.replace_modules_for_path("path", [_module(_kp("kp0"))])
    first.mastery_levels["kp0"] = 0.9
    store.save(first)

    replaced = service.replace_modules_for_path(
        "path",
        [_module(_kp("kp0"))],
        fresh_identity=True,
    )

    new_id = replaced.modules[0].knowledge_points[0].id
    assert new_id != "kp0"
    assert new_id not in replaced.mastery_levels


def test_fresh_replace_resolves_client_refs_without_reusing_old_ids(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    service.replace_modules_for_path("path", [_module(_kp("kp0"))])
    replacement = _module(
        _kp("kp0"),
        _kp("draft", prerequisites=["new-base"]),
    )

    replaced = service.replace_modules_for_path(
        "path",
        [replacement],
        fresh_identity=True,
        relation_refs={
            "kp0": RelationRefs(client_ref="new-base"),
            "draft": RelationRefs(prerequisite_refs=["new-base"]),
        },
    )

    base, dependent = replaced.modules[0].knowledge_points
    assert base.id != "kp0"
    assert dependent.prerequisite_ids == [base.id]


def test_invalid_append_rolls_back_modules_and_revision(tmp_path):
    store = LearningStore(root=tmp_path)
    service = LearningService(store)
    seeded = service.replace_modules_for_path("topic", [_module(_kp("base"))])
    incoming = LearningModule(
        id="draft",
        name="Invalid",
        order=1,
        knowledge_points=[_kp("draft")],
    )

    with pytest.raises(ObjectiveRelationError, match="unknown prerequisite ref"):
        service.replace_modules_for_path(
            "topic",
            [incoming],
            append=True,
            relation_refs={"draft": RelationRefs(prerequisite_refs=["missing"])},
        )

    unchanged = store.load("topic")
    assert unchanged is not None
    assert unchanged.version == seeded.version
    assert [module.id for module in unchanged.modules] == ["m0"]
