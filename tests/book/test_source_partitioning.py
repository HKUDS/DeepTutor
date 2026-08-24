"""Retrieval must tell searchable knowledge bases apart from unreachable ones.

An Obsidian vault (no index) and a subagent CLI (not a document collection)
return nothing from `rag_search`. Sweeping them anyway looked exactly like a
source with no relevant content, so a reader who attached their vault never
learned it contributed zero — they are named instead.

The other pointer kinds ARE searchable and must be swept: a `linked` folder
mounts an index built elsewhere, and `lightrag_server` / `ima` offload retrieval
over HTTP. Excluding every "connected" KB silently dropped those sources.
"""

from __future__ import annotations

from types import SimpleNamespace

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


def test_unreachable_kbs_are_separated_from_searchable_ones(fake_metadata) -> None:
    fake_metadata.update(
        {
            "my-vault": {"type": "obsidian"},
            "my-agent": {"type": "subagent"},
            "papers": {"type": "local"},
        }
    )
    retrievable, unreachable = SourceExplorer.partition_knowledge_bases(
        ["papers", "my-vault", "my-agent"]
    )
    assert retrievable == ["papers"]
    assert sorted(unreachable) == ["my-agent", "my-vault"]


def test_http_backed_and_linked_pointers_are_still_swept(fake_metadata) -> None:
    """These have an index or a retrieval API — dropping them cost every book."""
    fake_metadata.update(
        {
            "ima-lib": {"type": "ima", "knowledge_base_id": "kb-1"},
            "lightrag": {"type": "lightrag_server", "server_url": "https://x.invalid"},
            "linked": {"type": "linked", "external_path": "/tmp/elsewhere"},
        }
    )
    retrievable, unreachable = SourceExplorer.partition_knowledge_bases(
        ["ima-lib", "lightrag", "linked"]
    )
    assert sorted(retrievable) == ["ima-lib", "lightrag", "linked"]
    assert unreachable == []


def test_unresolvable_references_are_treated_as_ordinary(fake_metadata) -> None:
    """A KB we cannot resolve must not be silently dropped from the sweep."""
    retrievable, unreachable = SourceExplorer.partition_knowledge_bases(["mystery"])
    assert retrievable == ["mystery"]
    assert unreachable == []


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


@pytest.mark.asyncio
async def test_pageindex_is_read_by_source_explorer_agent_not_rag(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb",
        lambda name, **_kwargs: SimpleNamespace(base_dir="/kb", name=name),
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.provider_binding.resolve_bound_provider",
        lambda _base, _name: "pageindex-oss",
    )

    async def read(**_kwargs):
        return SimpleNamespace(
            text="Evidence from pages 3 and 7.",
            sources=[{"type": "pageindex", "page": 3}],
            tool_context=SimpleNamespace(provider="pageindex-oss"),
        )

    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.pageindex.reasoning.read_pageindex_with_agent",
        read,
    )

    async def no_rag(**_kwargs):
        pytest.fail("PageIndex SourceExplorer called rag_search")

    monkeypatch.setattr("deeptutor.tools.rag_tool.rag_search", no_rag)
    explorer = SourceExplorer(language="en")
    chunks = await explorer._retrieve_kb_chunks(["revenue"], ["reports"])

    assert len(chunks) == 1
    assert chunks[0].kb_name == "reports"
    assert chunks[0].text == "Evidence from pages 3 and 7."
    assert chunks[0].metadata["sources"][0]["page"] == 3
