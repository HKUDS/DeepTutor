"""Route materialisation keeps product identity separate from display order."""

import json
import logging
from unittest.mock import AsyncMock

import pytest

from deeptutor.learning.models import TopicSource, TopicSourceKind
from deeptutor.learning.topic_generation import (
    TopicGenerationError,
    generate_topic_draft,
    materialize_modules,
)


def _module(module_id: str, *points: tuple[str, str]) -> dict:
    return {
        "id": module_id,
        "name": f"Region {module_id}",
        "knowledge_points": [
            {"id": point_id, "name": name, "type": "concept", "module_id": module_id}
            for point_id, name in points
        ],
    }


def test_edit_reorder_preserves_existing_module_and_objective_ids() -> None:
    raw = [
        _module("topic_m1", ("topic_m1_kp0", "Third objective")),
        _module(
            "topic_m0",
            ("topic_m0_kp1", "Second objective"),
            ("topic_m0_kp0", "First objective"),
        ),
    ]

    modules = materialize_modules(
        "topic",
        raw,
        strict=True,
        existing_module_ids={"topic_m0", "topic_m1"},
        existing_objective_ids={"topic_m0_kp0", "topic_m0_kp1", "topic_m1_kp0"},
    )

    assert [module.id for module in modules] == ["topic_m1", "topic_m0"]
    assert [point.id for point in modules[1].knowledge_points] == [
        "topic_m0_kp1",
        "topic_m0_kp0",
    ]
    assert [module.order for module in modules] == [0, 1]


def test_new_objective_never_reuses_an_existing_or_deleted_position_id() -> None:
    raw = [
        _module(
            "topic_m0",
            ("draft-new", "Brand new objective"),
            ("topic_m0_kp0", "Existing objective"),
        )
    ]

    modules = materialize_modules(
        "topic",
        raw,
        strict=True,
        existing_module_ids={"topic_m0"},
        existing_objective_ids={"topic_m0_kp0", "topic_m0_kp1"},
    )

    ids = [point.id for point in modules[0].knowledge_points]
    assert ids[1] == "topic_m0_kp0"
    assert ids[0] not in {"topic_m0_kp0", "topic_m0_kp1"}
    assert ids[0].startswith("topic_m0_kp_")


@pytest.mark.parametrize(
    "raw, message",
    [
        ([{"id": "m", "name": "", "knowledge_points": []}], "region 1 needs a name"),
        ([{"id": "m", "name": "Region", "knowledge_points": []}], "at least one waypoint"),
        (
            [
                {
                    "id": "m",
                    "name": "Region",
                    "knowledge_points": [{"id": "kp", "name": "", "type": "concept"}],
                }
            ],
            "waypoint 1 needs a name",
        ),
    ],
)
def test_strict_route_rejects_content_that_would_be_silently_dropped(
    raw: list[dict], message: str
) -> None:
    with pytest.raises(TopicGenerationError, match=message):
        materialize_modules("topic", raw, strict=True)


@pytest.mark.asyncio
async def test_selected_knowledge_base_is_retrieved_into_generation_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rag_search = AsyncMock(
        return_value={
            "provider": "test-rag",
            "sources": [
                {
                    "title": "Mechanics notes",
                    "content": "Hamiltonian flow preserves symplectic structure.",
                }
            ],
        }
    )
    complete = AsyncMock(
        return_value=json.dumps(
            {
                "description": "Mechanics route",
                "modules": [
                    {
                        "name": "Foundations",
                        "knowledge_points": [{"name": "Hamiltonian flow", "type": "concept"}],
                    }
                ],
            }
        )
    )
    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", rag_search)
    monkeypatch.setattr("deeptutor.learning.topic_generation.complete", complete)

    result = await generate_topic_draft(
        name="Classical mechanics",
        goal="Understand conserved geometric structure",
        sources=[
            TopicSource(
                id="kb-source",
                kind=TopicSourceKind.KNOWLEDGE_BASE,
                source_id="mechanics-kb",
                label="Mechanics KB",
            )
        ],
        language="en",
    )

    rag_search.assert_awaited_once()
    assert rag_search.await_args.args[:2] == (
        "Classical mechanics\nUnderstand conserved geometric structure",
        "mechanics-kb",
    )
    assert "Hamiltonian flow preserves" in complete.await_args.kwargs["prompt"]
    assert result["sources"][0]["available"] is True
    assert result["sources"][0]["metadata"]["grounded_for_route"] is True


@pytest.mark.asyncio
async def test_unavailable_knowledge_base_does_not_abort_other_sources(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "deeptutor.tools.rag_tool.rag_search",
        AsyncMock(side_effect=RuntimeError("index offline")),
    )
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(
            return_value=json.dumps(
                {
                    "description": "Fallback route",
                    "modules": [
                        {
                            "name": "Goal region",
                            "knowledge_points": [{"name": "Core objective", "type": "concept"}],
                        }
                    ],
                }
            )
        ),
    )

    with caplog.at_level(logging.ERROR, logger="deeptutor.learning.topic_generation"):
        result = await generate_topic_draft(
            name="Fallback",
            goal="Keep generating from the goal",
            sources=[
                TopicSource(
                    id="goal",
                    kind=TopicSourceKind.GOAL,
                    label="Goal",
                    excerpt="Keep generating from the goal",
                ),
                TopicSource(
                    id="offline",
                    kind=TopicSourceKind.KNOWLEDGE_BASE,
                    source_id="offline-kb",
                    label="Offline KB",
                ),
            ],
            language="en",
        )

    assert result["modules"]
    assert result["sources"][0]["available"] is True
    assert result["sources"][1]["available"] is False
    assert result["sources"][1]["metadata"]["unavailable_during_generation"] is True
    assert "Knowledge-base grounding failed" in caplog.text


@pytest.mark.asyncio
async def test_malformed_model_modules_are_reported_in_forgiving_draft(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(
            return_value=json.dumps(
                {
                    "description": "Partially usable route",
                    "modules": [
                        "not-an-object",
                        {"name": "", "knowledge_points": []},
                        {"name": "No list", "knowledge_points": "invalid"},
                        {
                            "name": "Usable region",
                            "knowledge_points": [
                                "not-an-object",
                                {"name": "Valid objective", "type": "concept"},
                            ],
                        },
                    ],
                }
            )
        ),
    )

    with caplog.at_level(logging.WARNING, logger="deeptutor.learning.topic_generation"):
        result = await generate_topic_draft(
            name="Mixed model output",
            goal="Keep the valid portion",
            sources=[],
            language="en",
        )

    assert len(result["modules"]) == 1
    assert result["discarded_module_count"] == 3
    assert result["discarded_modules"] == [
        {"index": 1, "reason": "module is not an object"},
        {"index": 2, "reason": "module name is missing"},
        {"index": 3, "reason": "knowledge_points is not a list"},
    ]
    assert "Discarded 3 generated route module(s)" in caplog.text
