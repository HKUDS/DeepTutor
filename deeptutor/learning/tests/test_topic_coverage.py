"""Tests for a generated route accounting for every selected document.

The failure these cover is specific: a knowledge base holding twenty PDFs was
grounded by four retrieved passages and capped at eight regions, so the route
covered whatever the retrieval happened to match and silently ignored the
rest — with nothing on screen saying so. The fixes are that the model is given
the *inventory*, that the region cap follows the material, that a single
document can be selected on its own, and that what the route left out is
reported back.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from deeptutor.knowledge.manifest import KbDocument, KbManifest
from deeptutor.learning.models import TopicSource, TopicSourceKind
from deeptutor.learning.topic_generation import (
    DEFAULT_MODULE_LIMIT,
    MAX_MODULE_LIMIT,
    TopicGenerationError,
    generate_topic_draft,
    materialize_modules,
    module_limit_for,
)


def _kb_source(documents: list[str] | None = None) -> TopicSource:
    return TopicSource(
        id="kb-source",
        kind=TopicSourceKind.KNOWLEDGE_BASE,
        source_id="course-kb",
        label="Course KB",
        metadata={"documents": documents} if documents is not None else {},
    )


def _draft_response(modules: list[dict]) -> str:
    return json.dumps({"description": "A route", "modules": modules})


def _region(name: str, materials: list[str] | None = None) -> dict:
    region: dict = {
        "name": name,
        "knowledge_points": [{"name": f"{name} objective", "type": "concept"}],
    }
    if materials is not None:
        region["materials"] = materials
    return region


# ── how many regions the material justifies ──────────────────────────────────


def test_a_goal_only_topic_keeps_the_default_region_cap() -> None:
    assert module_limit_for([]) == DEFAULT_MODULE_LIMIT


def test_a_library_of_fourteen_documents_earns_fourteen_regions() -> None:
    assert module_limit_for([_kb_source([f"lecture{i:02d}.pdf" for i in range(14)])]) == 14


def test_the_region_cap_still_has_a_ceiling() -> None:
    documents = [f"paper{i:03d}.pdf" for i in range(200)]
    assert module_limit_for([_kb_source(documents)]) == MAX_MODULE_LIMIT


def test_the_same_document_in_two_sources_is_counted_once() -> None:
    shared = ["intro.pdf", "intro.pdf"]
    assert module_limit_for([_kb_source(shared)]) == DEFAULT_MODULE_LIMIT


# ── the cap no longer truncates in silence ───────────────────────────────────


def test_a_strict_route_over_the_cap_is_rejected_rather_than_trimmed() -> None:
    # Saving used to return success having dropped every region past the
    # eighth — the one thing `strict` exists to prevent.
    raw = [_region(f"Region {index}") for index in range(9)]

    with pytest.raises(TopicGenerationError, match="at most 8 regions"):
        materialize_modules("topic", raw, strict=True)


def test_a_strict_route_fits_when_the_material_raises_the_cap() -> None:
    raw = [_region(f"Region {index}") for index in range(12)]

    modules = materialize_modules("topic", raw, strict=True, module_limit=14)

    assert len(modules) == 12


def test_a_strict_region_over_the_waypoint_cap_is_rejected() -> None:
    raw = [
        {
            "name": "Crowded",
            "knowledge_points": [
                {"name": f"Objective {index}", "type": "concept"} for index in range(8)
            ],
        }
    ]

    with pytest.raises(TopicGenerationError, match="at most 7 waypoints"):
        materialize_modules("topic", raw, strict=True)


def test_a_forgiving_draft_still_reports_what_the_cap_dropped() -> None:
    raw = [_region(f"Region {index}") for index in range(10)]
    discarded: list[dict] = []

    modules = materialize_modules("topic", raw, discarded_modules=discarded, module_limit=8)

    assert len(modules) == 8
    assert [item["reason"] for item in discarded] == ["module limit exceeded"] * 2


# ── the model sees the inventory, not only passages ──────────────────────────


@pytest.mark.asyncio
async def test_the_libraries_file_list_reaches_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = KbManifest(
        name="course-kb",
        total=11,
        matched=11,
        documents=tuple(KbDocument(name=f"week{i:02d}.pdf", size=1000) for i in range(11)),
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest",
        lambda *args, **kwargs: manifest,
    )
    monkeypatch.setattr(
        "deeptutor.tools.rag_tool.rag_search",
        AsyncMock(
            return_value={"provider": "p", "sources": [{"title": "t", "content": "c" * 600}]}
        ),
    )
    complete = AsyncMock(
        return_value=_draft_response(
            [_region("Weeks 1-3", ["week00.pdf", "week01.pdf", "week02.pdf"])]
        )
    )
    monkeypatch.setattr("deeptutor.learning.topic_generation.complete", complete)

    result = await generate_topic_draft(
        name="Course",
        goal="Pass it",
        sources=[_kb_source()],
        language="en",
    )

    prompt = complete.await_args.kwargs["prompt"]
    # Retrieval cannot answer "what is in this library?", so the names travel
    # separately — this is what stops a route from covering two files of ten.
    assert "week07.pdf" in prompt
    assert result["module_limit"] == 11
    assert result["sources"][0]["metadata"]["documents"][0] == "week00.pdf"


@pytest.mark.asyncio
async def test_a_library_with_no_enumerable_documents_still_generates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A connected external resource has no listable document set; grounding by
    # retrieval alone is the correct outcome, not an error.
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest",
        lambda *args, **kwargs: KbManifest(name="remote", unavailable="missing"),
    )
    monkeypatch.setattr(
        "deeptutor.tools.rag_tool.rag_search",
        AsyncMock(
            return_value={"provider": "p", "sources": [{"title": "t", "content": "c" * 600}]}
        ),
    )
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value=_draft_response([_region("Only region")])),
    )

    result = await generate_topic_draft(
        name="Course", goal="Pass it", sources=[_kb_source()], language="en"
    )

    assert result["sources"][0]["available"] is True
    assert "documents" not in result["sources"][0]["metadata"]
    assert result["module_limit"] == DEFAULT_MODULE_LIMIT


# ── one document, selected on its own ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_single_selected_file_is_read_rather_than_retrieved(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lesson = tmp_path / "lecture03.md"
    lesson.write_text("# Hypothesis testing\nType I and Type II error.", encoding="utf-8")
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_document_path",
        lambda kb, rel: lesson,
    )
    rag_search = AsyncMock()
    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", rag_search)
    complete = AsyncMock(
        return_value=_draft_response([_region("Hypothesis testing", ["lecture03.md"])])
    )
    monkeypatch.setattr("deeptutor.learning.topic_generation.complete", complete)

    result = await generate_topic_draft(
        name="Lesson 3",
        goal="Understand hypothesis testing",
        sources=[
            TopicSource(
                id="file-source",
                kind=TopicSourceKind.FILE,
                source_id="lecture03.md",
                label="lecture03.md",
                metadata={"kb_name": "course-kb", "path": "lecture03.md"},
            )
        ],
        language="en",
    )

    # Similarity search across the whole library cannot express "this one
    # lesson", so a picked file is read directly.
    rag_search.assert_not_awaited()
    assert "Type I and Type II error" in complete.await_args.kwargs["prompt"]
    assert result["sources"][0]["available"] is True
    assert result["sources"][0]["metadata"]["documents"] == ["lecture03.md"]
    assert result["coverage"]["missing"] == []


@pytest.mark.asyncio
async def test_a_file_outside_its_knowledge_base_is_marked_unavailable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_document_path",
        lambda kb, rel: None,
    )
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value=_draft_response([_region("Goal only")])),
    )

    result = await generate_topic_draft(
        name="Topic",
        goal="Learn",
        sources=[
            TopicSource(
                id="file-source",
                kind=TopicSourceKind.FILE,
                source_id="../../etc/passwd",
                label="passwd",
                metadata={"kb_name": "course-kb", "path": "../../etc/passwd"},
            )
        ],
        language="en",
    )

    assert result["sources"][0]["available"] is False
    assert result["sources"][0]["metadata"]["unavailable_during_generation"] is True


# ── what the route left out ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_uncovered_documents_are_reported_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest",
        lambda *args, **kwargs: KbManifest(
            name="course-kb",
            total=3,
            matched=3,
            documents=(
                KbDocument(name="a.pdf", size=1),
                KbDocument(name="slides/b.pdf", size=1),
                KbDocument(name="c.pdf", size=1),
            ),
        ),
    )
    monkeypatch.setattr(
        "deeptutor.tools.rag_tool.rag_search",
        AsyncMock(
            return_value={"provider": "p", "sources": [{"title": "t", "content": "c" * 600}]}
        ),
    )
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        # "b.pdf" for a document listed as "slides/b.pdf" is a match, not a miss.
        AsyncMock(return_value=_draft_response([_region("Start", ["a.pdf", "b.pdf"])])),
    )

    result = await generate_topic_draft(
        name="Course", goal="Pass it", sources=[_kb_source()], language="en"
    )

    coverage = result["coverage"]
    assert coverage["documents"] == 3
    assert coverage["covered"] == 2
    assert [item["document"] for item in coverage["missing"]] == ["c.pdf"]
    assert coverage["reported"] is True


@pytest.mark.asyncio
async def test_a_model_that_names_nothing_reports_no_coverage_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest",
        lambda *args, **kwargs: KbManifest(
            name="course-kb",
            total=2,
            matched=2,
            documents=(KbDocument(name="a.pdf", size=1), KbDocument(name="b.pdf", size=1)),
        ),
    )
    monkeypatch.setattr(
        "deeptutor.tools.rag_tool.rag_search",
        AsyncMock(
            return_value={"provider": "p", "sources": [{"title": "t", "content": "c" * 600}]}
        ),
    )
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value=_draft_response([_region("Start")])),
    )

    result = await generate_topic_draft(
        name="Course", goal="Pass it", sources=[_kb_source()], language="en"
    )

    # Reporting both documents as missed would send the learner regenerating a
    # route that may well already cover them.
    assert result["coverage"]["reported"] is False
    assert result["coverage"]["missing"] == []


@pytest.mark.asyncio
async def test_a_regeneration_tells_the_model_what_was_missed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "deeptutor.learning.topic_generation.complete",
        AsyncMock(return_value=_draft_response([_region("Region", ["c.pdf"])])),
    )
    complete = AsyncMock(return_value=_draft_response([_region("Region", ["c.pdf"])]))
    monkeypatch.setattr("deeptutor.learning.topic_generation.complete", complete)

    await generate_topic_draft(
        name="Course",
        goal="Pass it",
        sources=[],
        language="en",
        must_cover=["c.pdf"],
    )

    prompt = complete.await_args.kwargs["prompt"]
    assert "left these documents out" in prompt
    assert "- c.pdf" in prompt
