"""Tests for Scratchpad source management and invalid source filtering."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from deeptutor.agents.solve.memory.scratchpad import (
    Entry,
    Plan,
    PlanStep,
    Scratchpad,
    Source,
)


@pytest.fixture
def scratchpad() -> Scratchpad:
    """Fresh scratchpad with a simple plan and entries for testing."""
    pad = Scratchpad(question="What is machine learning?")
    pad.plan = Plan(
        analysis="Test plan",
        steps=[
            PlanStep(id="S1", goal="Define machine learning", status="completed"),
            PlanStep(id="S2", goal="List types of ML", status="completed"),
        ],
    )
    # Entry with a valid web source
    pad.entries.append(
        Entry(
            step_id="S1",
            round=1,
            thought="I need to search for a definition",
            action="web_search",
            action_input="machine learning definition",
            observation="ML is a subset of AI...",
            self_note="ML is defined as a subset of AI",
            sources=[
                Source(type="web", url="https://example.com/ml-definition", chunk_id=None),
            ],
        )
    )
    # Entry with a RAG source
    pad.entries.append(
        Entry(
            step_id="S2",
            round=1,
            thought="Now list types",
            action="rag",
            action_input="types of machine learning",
            observation="Supervised, unsupervised, reinforcement...",
            self_note="Three main types of ML",
            sources=[
                Source(type="rag", file="ml-kb", chunk_id="types of ml"),
            ],
        )
    )
    return pad


class TestGetAllSources:
    def test_returns_deduplicated_sources(self, scratchpad: Scratchpad) -> None:
        sources = scratchpad.get_all_sources()
        assert len(sources) == 2
        ids = {s["id"] for s in sources}
        assert "web-1" in ids
        assert "rag-1" in ids

    def test_same_source_not_duplicated(self, scratchpad: Scratchpad) -> None:
        scratchpad.entries.append(
            Entry(
                step_id="S2",
                round=2,
                thought="More details",
                action="rag",
                action_input="types of ml",
                observation="Also semi-supervised...",
                self_note="Semi-supervised also exists",
                sources=[
                    Source(type="rag", file="ml-kb", chunk_id="types of ml"),
                ],
            )
        )
        sources = scratchpad.get_all_sources()
        # Same (type, file, url, chunk_id) key should still only produce one source
        assert len(sources) == 2

    def test_sources_have_ids(self, scratchpad: Scratchpad) -> None:
        sources = scratchpad.get_all_sources()
        for s in sources:
            assert "id" in s
            assert s["id"].startswith(("web-", "rag-"))


class TestGetValidSources:
    def test_returns_all_sources_when_none_invalid(self, scratchpad: Scratchpad) -> None:
        assert scratchpad.get_valid_sources() == scratchpad.get_all_sources()

    def test_excludes_marked_invalid_sources(self, scratchpad: Scratchpad) -> None:
        all_sources = scratchpad.get_all_sources()
        web_source_id = next(s["id"] for s in all_sources if s["type"] == "web")

        scratchpad.mark_source_invalid(web_source_id)

        valid = scratchpad.get_valid_sources()
        valid_ids = {s["id"] for s in valid}
        assert web_source_id not in valid_ids
        assert "rag-1" in valid_ids

    def test_exclude_only_invalidates_specified_id(self, scratchpad: Scratchpad) -> None:
        all_sources = scratchpad.get_all_sources()
        web_id = next(s["id"] for s in all_sources if s["type"] == "web")
        rag_id = next(s["id"] for s in all_sources if s["type"] == "rag")

        scratchpad.mark_source_invalid(web_id)

        valid = scratchpad.get_valid_sources()
        valid_ids = {s["id"] for s in valid}
        assert web_id not in valid_ids
        assert rag_id in valid_ids


class TestMarkSourceInvalid:
    def test_appends_to_invalid_ids_list(self, scratchpad: Scratchpad) -> None:
        all_sources = scratchpad.get_all_sources()
        web_id = next(s["id"] for s in all_sources if s["type"] == "web")

        scratchpad.mark_source_invalid(web_id)

        assert web_id in scratchpad.metadata["invalid_source_ids"]

    def test_idempotent_same_id(self, scratchpad: Scratchpad) -> None:
        all_sources = scratchpad.get_all_sources()
        web_id = next(s["id"] for s in all_sources if s["type"] == "web")

        scratchpad.mark_source_invalid(web_id)
        scratchpad.mark_source_invalid(web_id)

        assert scratchpad.metadata["invalid_source_ids"].count(web_id) == 1

    def test_multiple_invalid_ids(self, scratchpad: Scratchpad) -> None:
        all_sources = scratchpad.get_all_sources()
        web_id = next(s["id"] for s in all_sources if s["type"] == "web")
        rag_id = next(s["id"] for s in all_sources if s["type"] == "rag")

        scratchpad.mark_source_invalid(web_id)
        scratchpad.mark_source_invalid(rag_id)

        assert set(scratchpad.metadata["invalid_source_ids"]) == {web_id, rag_id}


class TestFindSourceIdByUrl:
    def test_finds_source_id_by_url(self, scratchpad: Scratchpad) -> None:
        src_id = scratchpad.find_source_id_by_url("https://example.com/ml-definition")
        assert src_id == "web-1"

    def test_returns_none_for_unknown_url(self, scratchpad: Scratchpad) -> None:
        assert scratchpad.find_source_id_by_url("https://unknown.invalid/page") is None

    def test_returns_none_for_empty_url(self, scratchpad: Scratchpad) -> None:
        assert scratchpad.find_source_id_by_url("") is None


class TestFormatSourcesMarkdown:
    def test_includes_valid_sources(self, scratchpad: Scratchpad) -> None:
        md = scratchpad.format_sources_markdown()
        assert "https://example.com/ml-definition" in md
        assert "ml-kb" in md

    def test_excludes_invalid_sources(self, scratchpad: Scratchpad) -> None:
        all_sources = scratchpad.get_all_sources()
        web_id = next(s["id"] for s in all_sources if s["type"] == "web")
        scratchpad.mark_source_invalid(web_id)

        md = scratchpad.format_sources_markdown()
        assert "https://example.com/ml-definition" not in md
        assert "ml-kb" in md


class TestPersistence:
    def test_save_and_load_preserves_invalid_ids(self, scratchpad: Scratchpad) -> None:
        all_sources = scratchpad.get_all_sources()
        web_id = next(s["id"] for s in all_sources if s["type"] == "web")
        scratchpad.mark_source_invalid(web_id)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = scratchpad.save(tmpdir)

            loaded = Scratchpad.load_or_create(tmpdir, scratchpad.question)
            assert web_id in loaded.metadata["invalid_source_ids"]
            # Confirm invalid source is excluded
            valid = loaded.get_valid_sources()
            valid_ids = {s["id"] for s in valid}
            assert web_id not in valid_ids

    def test_load_or_create_returns_fresh_when_no_file(self, tmp_path: Path) -> None:
        pad = Scratchpad.load_or_create(str(tmp_path / "nonexistent"), "test question")
        assert pad.question == "test question"
        assert pad.plan is None
        assert pad.entries == []
        assert pad.metadata["invalid_source_ids"] == []

    def test_load_restores_full_state(self, scratchpad: Scratchpad) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scratchpad.save(tmpdir)

            loaded = Scratchpad.load_or_create(tmpdir, "different question")
            assert loaded.question == scratchpad.question
            assert len(loaded.entries) == len(scratchpad.entries)
            assert loaded.metadata["plan_revisions"] == scratchpad.metadata["plan_revisions"]
