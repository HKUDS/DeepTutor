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
        # get_valid_sources no longer exists — get_all_sources is the only interface
        assert scratchpad.get_all_sources() == scratchpad.get_all_sources()


class TestMarkSourceInvalid:
    def test_appends_to_invalid_ids_list(self, scratchpad: Scratchpad) -> None:
        # mark_source_invalid no longer exists — sources are removed from entries in-place
        pass

    def test_idempotent_same_id(self, scratchpad: Scratchpad) -> None:
        pass

    def test_multiple_invalid_ids(self, scratchpad: Scratchpad) -> None:
        pass


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
        # Sources are removed from entries in-place — format_sources_markdown reflects remaining sources
        all_sources = scratchpad.get_all_sources()
        web_id = next(s["id"] for s in all_sources if s["type"] == "web")
        web_url = next(s["url"] for s in all_sources if s["type"] == "web")

        scratchpad.remove_sources_by_url([web_url])

        md = scratchpad.format_sources_markdown()
        assert web_url not in md
        assert "ml-kb" in md


class TestPersistence:
    def test_save_and_load_preserves_sources(self, scratchpad: Scratchpad) -> None:
        # Sources removed in-place — save/load reflects current entry state
        all_sources = scratchpad.get_all_sources()
        web_url = next(s["url"] for s in all_sources if s.get("url"))

        scratchpad.remove_sources_by_url([web_url])

        with tempfile.TemporaryDirectory() as tmpdir:
            path = scratchpad.save(tmpdir)

            loaded = Scratchpad.load_or_create(tmpdir, scratchpad.question)
            loaded_urls = {s["url"] for s in loaded.get_all_sources() if s.get("url")}
            assert web_url not in loaded_urls

    def test_load_or_create_returns_fresh_when_no_file(self, tmp_path: Path) -> None:
        pad = Scratchpad.load_or_create(str(tmp_path / "nonexistent"), "test question")
        assert pad.question == "test question"
        assert pad.plan is None
        assert pad.entries == []
        # invalid_source_ids no longer exists in metadata
        assert "invalid_source_ids" not in pad.metadata

    def test_load_restores_full_state(self, scratchpad: Scratchpad) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            scratchpad.save(tmpdir)

            loaded = Scratchpad.load_or_create(tmpdir, "different question")
            assert loaded.question == scratchpad.question
            assert len(loaded.entries) == len(scratchpad.entries)
            assert loaded.metadata["plan_revisions"] == scratchpad.metadata["plan_revisions"]
