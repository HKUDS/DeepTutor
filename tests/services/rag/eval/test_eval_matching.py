"""Tests for gold-passage matching."""

from __future__ import annotations

import pytest

from deeptutor.services.rag.eval import (
    MatchPolicy,
    MatchResult,
    RelevanceMatcher,
    normalize_text,
    source_text,
)
from deeptutor.services.rag.eval.matching import tokenize

GOLD = "Transformers stack self-attention layers to model long-range dependencies in sequences."
GOLD_TOKENS = "alpha beta gamma delta epsilon zeta eta theta"


def test_a_chunk_holding_the_gold_verbatim_matches() -> None:
    chunk = f"Introduction. {GOLD} The section then moves on."
    result = RelevanceMatcher([GOLD]).match(chunk)

    assert result
    assert result.indices == (0,)
    assert result.ratio == 1.0


def test_case_and_whitespace_differences_do_not_break_containment() -> None:
    chunk = (
        "TRANSFORMERS   STACK SELF-ATTENTION LAYERS TO MODEL LONG-RANGE DEPENDENCIES IN SEQUENCES."
    )
    assert RelevanceMatcher([GOLD]).match(chunk).indices == (0,)


def test_a_truncated_citation_inside_a_longer_gold_still_matches() -> None:
    """LlamaIndex and GraphRAG cap ``content`` at 200 characters."""
    truncated = GOLD[:60]
    assert len(tokenize(truncated)) >= 4

    result = RelevanceMatcher([GOLD]).match(truncated)

    assert result.indices == (0,)
    assert result.ratio == 1.0


def test_an_unrelated_chunk_does_not_match() -> None:
    result = RelevanceMatcher([GOLD]).match("Boiling pasta needs salted water and fresh tomatoes.")

    assert not result
    assert result.indices == ()
    assert result.ratio == 0.0


def test_partial_token_overlap_above_the_ratio_matches() -> None:
    chunk = "alpha beta gamma delta zeta eta theta iota"
    result = RelevanceMatcher([GOLD_TOKENS]).match(chunk)

    assert result.indices == (0,)
    assert result.ratio == pytest.approx(0.875)


def test_a_short_overlap_below_the_token_floor_is_rejected() -> None:
    """``alpha beta gamma iota`` covers 3 of 4 own tokens but only 3 shared ones."""
    matcher = RelevanceMatcher([GOLD_TOKENS])

    assert not matcher.match("alpha beta gamma iota")


def test_the_token_floor_can_be_lowered_for_a_smaller_corpus() -> None:
    matcher = RelevanceMatcher([GOLD_TOKENS], MatchPolicy(min_ratio=0.5, min_tokens=3))

    assert matcher.match("gamma delta epsilon").indices == (0,)


def test_the_ratio_floor_can_reject_a_loose_overlap() -> None:
    """Half of a four-token chunk overlapping is below a stricter ratio."""
    strict = RelevanceMatcher([GOLD_TOKENS], MatchPolicy(min_ratio=0.9, min_tokens=2))

    assert not strict.match("alpha beta iota kappa")


def test_each_gold_passage_is_matched_independently() -> None:
    matcher = RelevanceMatcher([GOLD, GOLD_TOKENS])

    result = matcher.match("alpha beta gamma delta zeta eta theta iota")

    assert result.indices == (1,)
    assert matcher.gold_count == 2


def test_one_chunk_can_cover_two_gold_passages() -> None:
    matcher = RelevanceMatcher(["alpha beta gamma", "delta epsilon zeta"])

    assert matcher.match("alpha beta gamma delta epsilon zeta").indices == (0, 1)


def test_cjk_text_is_compared_character_by_character() -> None:
    gold = "注意力机制让模型对每个词加权"
    matcher = RelevanceMatcher([gold])

    assert len(tokenize("注意力机制")) == 5
    assert matcher.match(f"{gold}，这是核心思想。").indices == (0,)


def test_blank_input_never_matches() -> None:
    matcher = RelevanceMatcher([GOLD])

    assert not matcher.match("")
    assert not matcher.match("   ")


def test_a_matcher_without_usable_gold_never_matches() -> None:
    matcher = RelevanceMatcher(["", "   "])

    assert matcher.gold_count == 0
    assert not matcher.match(GOLD)


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize_text("  Mixed\nCASE   text ") == "mixed case text"


def test_match_policy_rejects_impossible_thresholds() -> None:
    with pytest.raises(ValueError):
        MatchPolicy(min_ratio=0.0)
    with pytest.raises(ValueError):
        MatchPolicy(min_ratio=1.5)
    with pytest.raises(ValueError):
        MatchPolicy(min_tokens=0)


def test_match_result_truthiness_follows_the_matched_indices() -> None:
    assert MatchResult((0,), 1.0)
    assert not MatchResult()


def test_source_text_reads_the_engines_citation_shape() -> None:
    assert source_text({"content": "excerpt"}) == "excerpt"
    assert source_text({"content": "   ", "text": "fallback"}) == "fallback"
    assert source_text({"content": "", "snippet": "snippet wins"}) == "snippet wins"
    assert source_text({"summary": "community report"}) == "community report"
    assert source_text({}) == ""
    assert source_text("not a mapping") == ""
    assert source_text(None) == ""
