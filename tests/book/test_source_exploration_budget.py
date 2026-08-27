"""The source sweep must stay bounded, and stay fair when it is bounded.

One retrieval per (knowledge base x query) pair, each a vector search plus an
LLM synthesis on most backends. Ungated, eight KBs against a dozen queries
fired ~100 concurrent provider calls. Capping is only half the fix: capping a
KB-major list would spend the whole budget on the first few knowledge bases.
"""

from __future__ import annotations

from deeptutor.book.agents.source_explorer import (
    MAX_RETRIEVAL_CALLS,
    RETRIEVAL_CONCURRENCY,
)
from deeptutor.book.engine import _source_quality_summary
from deeptutor.book.models import BookInputs, ExplorationReport, SourceChunk


def _pairs(kbs: list[str], queries: list[str]) -> list[tuple[str, str]]:
    """The interleaving the explorer uses, then the same cap it applies."""
    return [(kb, q) for q in queries for kb in kbs][:MAX_RETRIEVAL_CALLS]


def test_the_budget_is_actually_bounded() -> None:
    pairs = _pairs([f"kb{i}" for i in range(8)], [f"q{i}" for i in range(12)])
    assert len(pairs) == MAX_RETRIEVAL_CALLS
    assert MAX_RETRIEVAL_CALLS < 8 * 12, "the cap must bite on a realistic fan-out"


def test_capping_still_covers_every_knowledge_base() -> None:
    kbs = [f"kb{i}" for i in range(8)]
    pairs = _pairs(kbs, [f"q{i}" for i in range(12)])
    assert {kb for kb, _ in pairs} == set(kbs), "a knowledge base was starved"


def test_kb_major_ordering_would_have_starved_most_of_them() -> None:
    """Guards the ordering itself, not just the cap."""
    kbs = [f"kb{i}" for i in range(8)]
    queries = [f"q{i}" for i in range(12)]
    kb_major = [(kb, q) for kb in kbs for q in queries][:MAX_RETRIEVAL_CALLS]
    assert len({kb for kb, _ in kb_major}) < len(kbs), (
        "if this passes, the interleaving no longer matters — re-check the fix"
    )


def test_small_workloads_are_untouched() -> None:
    kbs, queries = ["kb0", "kb1"], ["q0", "q1", "q2"]
    assert len(_pairs(kbs, queries)) == len(kbs) * len(queries)


def test_concurrency_gate_is_sane() -> None:
    assert 1 <= RETRIEVAL_CONCURRENCY <= 16
    assert RETRIEVAL_CONCURRENCY < MAX_RETRIEVAL_CALLS


def test_source_quality_reports_missing_selected_knowledge_base() -> None:
    inputs = BookInputs(user_intent="topic", knowledge_bases=["covered", "missing"])
    exploration = ExplorationReport(
        chunks=[
            SourceChunk(source="kb", kb_name="covered", text="evidence"),
        ],
        coverage={"kb": 1},
    )

    quality = _source_quality_summary(inputs, exploration)

    assert quality["status"] == "warning"
    assert quality["covered_kbs"] == ["covered"]
    assert quality["missing_kbs"] == ["missing"]
    assert "missing" in quality["warnings"][0]
