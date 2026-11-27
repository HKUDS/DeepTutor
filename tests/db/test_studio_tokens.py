"""The cost column needs a number that is measured, not guessed.

Gate 8 asks for cost to be documented. The first attempt documented
`len(text) // 4` -- the English rule of thumb -- and it undercounts Persian by
2.9x, because Persian is written without short vowels and cl100k has almost no
merges for it. These tests exist so that mistake cannot come back silently.
"""

from __future__ import annotations

import pytest

from deeptutor.services.studio import tokens as T


def test_empty_text_costs_nothing():
    assert T.count("").tokens == 0
    assert T.count("   \n ").tokens == 0


def test_count_is_monotonic_in_length():
    """More text must never cost fewer tokens."""
    base = "مشتق نرخ تغییر لحظه‌ای است. "
    previous = 0
    for n in range(1, 12):
        current = T.count(base * n).tokens
        assert current >= previous
        previous = current


def test_persian_costs_far_more_than_the_english_heuristic():
    """The regression that motivated this module."""
    text = (
        "مشتق نرخ تغییر لحظه‌ای است. در فیزیک، مشتق مکان نسبت به زمان همان "
        "سرعت است. شتاب نیز مشتق سرعت نسبت به زمان است."
    )
    counted = T.count(text).tokens
    heuristic = T.count_chars_baseline(text)
    assert counted > heuristic * 2, (
        f"counted {counted} vs heuristic {heuristic}: the estimator has "
        f"reverted to an English-shaped model"
    )


def test_persian_is_mostly_one_token_per_character():
    """The measured shape: ~0.87 tokens/char, not ~0.25."""
    text = "انتگرال مساحت زیر نمودار است و معکوس مشتق است."
    ratio = T.count(text).tokens / len(text)
    assert 0.6 < ratio < 1.2, f"tokens/char = {ratio:.2f}, expected ~0.87"


def test_english_is_cheaper_per_character_than_persian():
    """The asymmetry is the whole reason for two models."""
    persian = "مشتق نرخ تغییر لحظه‌ای است"
    english = "The derivative is the instantaneous rate of change"
    p_ratio = T.count(persian).tokens / len(persian)
    e_ratio = T.count(english).tokens / len(english)
    assert p_ratio > e_ratio * 2


def test_the_old_heuristic_is_still_available_for_comparison():
    """Kept on purpose: the cost report compares measured against assumed."""
    assert T.count_chars_baseline("abcd") == 1
    assert T.count_chars_baseline("") == 0


# ---------------------------------------------------------------------------
# Honesty about the number
# ---------------------------------------------------------------------------


def test_every_count_states_how_it_was_obtained():
    result = T.count("متن")
    assert result.method
    assert result.uncertainty is not None


def test_the_estimator_is_honest_about_being_an_estimate():
    """If the real tokenizer is absent, uncertainty must not be zero."""
    if T.counter() is not None:
        pytest.skip("real tokenizer is available; nothing to be uncertain about")
    assert T.count("متن آزمایشی").uncertainty > 0


def test_a_real_tokenizer_reports_zero_uncertainty_when_present():
    if T.counter() is None:
        pytest.skip("tokenizer data not cached offline")
    assert T.count("متن آزمایشی").uncertainty == 0.0
    assert T.count("متن").method.startswith("tiktoken:")


def test_the_result_serialises_for_the_cost_ledger():
    record = T.count("متن").as_dict()
    assert set(record) == {"tokens", "method", "uncertainty"}


def test_counting_does_not_raise_on_awkward_input():
    for value in ("", "\n\n\n", "🙂", "۱۲۳", "a" * 5000, "م" * 5000):
        assert T.count(value).tokens >= 0


def test_the_fitted_constant_is_documented_with_its_measurement():
    """A constant without its provenance is a magic number."""
    doc = T.__doc__ or ""
    assert "cl100k" in doc
    assert "0.87" in doc or "2.9" in doc


# ---------------------------------------------------------------------------
# Calibration against committed reference counts
# ---------------------------------------------------------------------------
#
# `tests/data/cl100k_reference.json` holds real cl100k counts for twenty
# sentences, produced offline from the published BPE file. Committing the
# *counts* rather than the 1.6 MB of merges keeps the repository small while
# still letting CI check that the estimator has not drifted. Re-generate with
# `scripts/measure_tokens.py`.


def _reference():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "data" / "cl100k_reference.json"
    if not path.exists():
        pytest.fail(
            f"{path} is missing: the calibration cannot be checked without it, "
            "and a calibration test that skips is not evidence. Regenerate with "
            "`python scripts/measure_tokens.py --bpe <cl100k_base.tiktoken>`"
        )
    return json.loads(path.read_text())


def test_the_estimator_agrees_with_real_tokenizer_counts():
    """The claim in the module docstring, checked rather than asserted."""
    reference = _reference()
    total_real = 0
    total_estimate = 0
    for row in reference["sentences"]:
        total_real += row["cl100k"]
        total_estimate += T.count(row["text"]).tokens
    error = abs(total_estimate - total_real) / total_real
    assert error < 0.05, (
        f"estimator is {error:.1%} off real cl100k counts "
        f"({total_estimate} vs {total_real}) on {len(reference['sentences'])} "
        f"sentences; the constants or the model have drifted"
    )


def test_the_estimator_beats_the_old_heuristic_on_the_same_text():
    reference = _reference()
    rows = reference["sentences"]
    real = sum(r["cl100k"] for r in rows)
    estimate = sum(T.count(r["text"]).tokens for r in rows)
    baseline = sum(T.count_chars_baseline(r["text"]) for r in rows)
    assert abs(estimate - real) < abs(baseline - real) / 3, (
        f"estimator {estimate}, heuristic {baseline}, reality {real}"
    )


def test_the_reference_file_records_how_it_was_produced():
    reference = _reference()
    assert reference["reference"] == "cl100k_base"
    assert reference["how_obtained"]
    assert "network" in reference["why_committed"] or "offline" in reference["why_committed"]


def test_every_reference_row_is_reproducible_from_its_text():
    for row in _reference()["sentences"]:
        assert row["cl100k"] >= 1
        assert row["chars"] == len(row["text"])
