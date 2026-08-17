"""Retrieval must tell indexed knowledge bases apart from connected pointers.

A connected KB — an Obsidian vault, a subagent CLI, a remote LightRAG or IMA
library — has no local index, so `rag_search` returns nothing. Sweeping them
anyway looked exactly like a source with no relevant content, so a reader who
attached their vault never learned it contributed zero.
"""

from __future__ import annotations

import pytest

from deeptutor.book.agents.source_explorer import SourceExplorer, _balanced_slice
from deeptutor.book.models import SourceChunk


def _chunk(source: str, kb: str, score: float) -> SourceChunk:
    return SourceChunk(
        chunk_id=f"{kb}-{score}",
        kb_name=kb,
        source=source,
        ref="r",
        text="t",
        score=score,
        query="q",
    )


@pytest.fixture
def fake_metadata(monkeypatch):
    table: dict[str, dict] = {}

    def _resolve(kb_ref):
        return table.get(kb_ref)

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", _resolve)
    return table


def test_connected_kbs_are_separated_from_indexed_ones(fake_metadata) -> None:
    fake_metadata.update(
        {
            "my-vault": {"type": "obsidian"},
            "my-agent": {"type": "subagent"},
            "papers": {"type": "local"},
        }
    )
    retrievable, connected = SourceExplorer.partition_knowledge_bases(
        ["papers", "my-vault", "my-agent"]
    )
    assert retrievable == ["papers"]
    assert sorted(connected) == ["my-agent", "my-vault"]


def test_unresolvable_references_are_treated_as_ordinary(fake_metadata) -> None:
    """A KB we cannot resolve must not be silently dropped from the sweep."""
    retrievable, connected = SourceExplorer.partition_knowledge_bases(["mystery"])
    assert retrievable == ["mystery"]
    assert connected == []


# ── Balanced slice ──────────────────────────────────────────────────────


def test_one_engines_score_scale_cannot_crowd_out_the_others() -> None:
    """Cosine, BM25 and a remote service score on different scales."""
    chunks = (
        [_chunk("kb", "vector_kb", 90 - i) for i in range(30)]
        + [_chunk("kb", "bm25_kb", 0.9 - i * 0.01) for i in range(30)]
        + [_chunk("notebook", "", 0.0) for _ in range(5)]
    )

    globally_sorted = sorted(chunks, key=lambda c: -c.score)[:24]
    assert len({(c.source, c.kb_name) for c in globally_sorted}) == 1, (
        "precondition: a global sort collapses to one source"
    )

    balanced = _balanced_slice(chunks, limit=24)
    assert len(balanced) == 24
    assert len({(c.source, c.kb_name) for c in balanced}) == 3


def test_within_a_source_the_best_chunks_still_win() -> None:
    chunks = [_chunk("kb", "a", float(i)) for i in range(10)]
    picked = _balanced_slice(chunks, limit=3)
    assert [c.score for c in picked] == [9.0, 8.0, 7.0]


def test_a_small_sweep_is_returned_whole() -> None:
    chunks = [_chunk("kb", "a", 1.0), _chunk("kb", "b", 2.0)]
    assert len(_balanced_slice(chunks, limit=24)) == 2
