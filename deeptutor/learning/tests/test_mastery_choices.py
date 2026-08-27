"""Unit tests for the choice-question data contract
(:mod:`deeptutor.capabilities.mastery.choices`).

These exercise the pure option-handling rules in isolation — parsing, body
validation, answer normalisation, and legacy recovery — independent of the
tool/engine wiring that :mod:`test_mastery_tools` drives end to end."""

from __future__ import annotations

import pytest

from deeptutor.capabilities.mastery.choices import (
    canonical_labels,
    format_options,
    has_option_bodies,
    is_readable_choice_answer,
    option_label_intent,
    parse_options,
    recover_options_from_turn,
    resolve_answer,
    resolve_choice_submission,
)

# ── parse_options ────────────────────────────────────────────────────────────


def test_parse_options_reads_labelled_bodies():
    assert parse_options(["A: first", "B) second", "C、third"]) == {
        "A": "first",
        "B": "second",
        "C": "third",
    }


def test_parse_options_reads_multiline_bodies():
    assert parse_options(["A: first\nanswer", "B: second answer"]) == {
        "A": "first\nanswer",
        "B": "second answer",
    }


def test_parse_options_keeps_bare_labels_for_legacy_data():
    assert parse_options(["A", "B", "C", "D"]) == {"A": "A", "B": "B", "C": "C", "D": "D"}


def test_parse_options_assigns_positional_labels_to_unprefixed_text():
    assert parse_options(["first answer", "second answer"]) == {
        "A": "first answer",
        "B": "second answer",
    }


def test_parse_options_skips_blank_entries():
    assert parse_options(["A: keep", "   ", ""]) == {"A": "keep"}


def test_parse_options_does_not_mistake_a_formula_for_a_label():
    """``"x - 1 = 0"`` matches the label pattern; it is still not labelled."""
    assert parse_options(["x - 1 = 0", "x - 2 = 0"]) == {
        "A": "x - 1 = 0",
        "B": "x - 2 = 0",
    }


def test_parse_options_reads_malformed_labels_positionally():
    """Repeated labels keep every body — registration rejects them separately."""
    assert parse_options(["A: first", "A: second"]) == {
        "A": "A: first",
        "B": "A: second",
    }


# ── option_label_intent ──────────────────────────────────────────────────────


def test_option_label_intent_reads_labels_that_start_at_a():
    assert option_label_intent(["A: first", "B: second"]) == ["A", "B"]
    assert option_label_intent(["A: first", "A: second", "B: third"]) == ["A", "A", "B"]


def test_option_label_intent_is_none_for_unlabelled_options():
    assert option_label_intent(["x - 1 = 0", "y - 2 = 0"]) is None
    assert option_label_intent(["first answer", "second answer"]) is None


def test_canonical_labels_is_the_well_formed_set():
    assert canonical_labels(3) == {"A", "B", "C"}


# ── has_option_bodies ────────────────────────────────────────────────────────


def test_has_option_bodies_true_for_real_text():
    assert has_option_bodies({"A": "first", "B": "second"}) is True


def test_has_option_bodies_false_for_bare_labels():
    assert has_option_bodies({"A": "A", "B": "B"}) is False


def test_has_option_bodies_false_when_fewer_than_two():
    assert has_option_bodies({"A": "only one"}) is False


# ── format_options ───────────────────────────────────────────────────────────


def test_format_options_round_trips_with_parse():
    options = {"A": "first", "B": "second"}
    assert parse_options(format_options(options)) == options


# ── resolve_answer ───────────────────────────────────────────────────────────


def test_resolve_answer_accepts_direct_label():
    assert resolve_answer("C", {"A": "x", "B": "y", "C": "z"}) == "C"


def test_resolve_answer_strips_label_prefix():
    assert resolve_answer("C: the answer", {"A": "x", "C": "the answer"}) == "C"


def test_resolve_answer_matches_full_body_exactly():
    assert (
        resolve_answer(
            "Step 6 — add the stop condition",
            {
                "A": "Step 2 — write the first tool",
                "C": "Step 6 — add the stop condition",
            },
        )
        == "C"
    )


def test_resolve_answer_matches_unique_substring():
    assert (
        resolve_answer(
            "Step 6",
            {
                "A": "Step 2 — write the first tool",
                "C": "Step 6 — add the stop condition",
            },
        )
        == "C"
    )


def test_resolve_answer_blank_when_ambiguous():
    assert resolve_answer("Step", {"A": "Step 2", "B": "Step 6"}) == ""


def test_resolve_answer_blank_when_empty():
    assert resolve_answer("", {"A": "x", "B": "y"}) == ""


def test_resolve_choice_submission_accepts_label_or_exact_body_only():
    options = {"A": "Step 2", "B": "Step 6"}
    assert resolve_choice_submission("B", options) == "B"
    assert resolve_choice_submission("Step 6", options) == "B"
    assert resolve_choice_submission("Step", options) == ""


def test_resolve_choice_submission_reads_a_typed_answer():
    """A learner who types instead of tapping the card still picks an option."""
    options = {"A": "3x² - 3x = 2x + 8", "B": "3x² - x - 8 = 0", "C": "3x² - 5x - 8 = 0"}
    assert resolve_choice_submission("选C", options) == "C"
    assert resolve_choice_submission("答案是 C", options) == "C"
    assert resolve_choice_submission("C。", options) == "C"
    # Spacing differences between the card and the stored body are not a
    # different answer.
    assert resolve_choice_submission("3x²-5x-8=0", options) == "C"


def test_resolve_choice_submission_refuses_an_ambiguous_answer():
    options = {"A": "Step 2", "B": "Step 6"}
    assert resolve_choice_submission("A or B", options) == ""
    assert resolve_choice_submission("", options) == ""


def test_readable_choice_answer_requires_selection_intent_not_a_label_mention():
    options = {"A": "first", "B": "second", "C": "third"}
    assert is_readable_choice_answer("B", options)
    assert is_readable_choice_answer("选B", options)
    assert is_readable_choice_answer("答案是 C", options)
    assert is_readable_choice_answer("I think it's A", options)
    assert is_readable_choice_answer("second", options)
    assert not is_readable_choice_answer("为什么 B 不对？", options)
    assert not is_readable_choice_answer("Can you explain B", options)
    assert not is_readable_choice_answer("B or C", options)


# ── recover_options_from_turn ────────────────────────────────────────────────


class _FakeStore:
    def __init__(self, events):
        self._events = events

    async def get_turn_events(self, turn_id, after_seq=0):
        return self._events


def _ask_user_event(prompt, options):
    return {
        "type": "tool_call",
        "metadata": {
            "tool_name": "ask_user",
            "args": {"questions": [{"prompt": prompt, "options": options}]},
        },
    }


@pytest.mark.asyncio
async def test_recover_options_from_turn_pulls_bodies_from_ask_user():
    store = _FakeStore(
        [
            _ask_user_event(
                "Where is the stop condition added?",
                [
                    {"label": "A", "description": "Step 2"},
                    {"label": "B", "description": "Step 4"},
                    {"label": "C", "description": "Step 6"},
                ],
            )
        ]
    )
    recovered = await recover_options_from_turn(
        store, "turn_1", "Where is the stop condition added?"
    )
    assert recovered == {"A": "Step 2", "B": "Step 4", "C": "Step 6"}


@pytest.mark.asyncio
async def test_recover_options_from_turn_ignores_non_matching_prompt():
    store = _FakeStore(
        [
            _ask_user_event(
                "An unrelated question",
                [{"label": "A", "description": "x"}, {"label": "B", "description": "y"}],
            )
        ]
    )
    assert await recover_options_from_turn(store, "turn_1", "Different prompt") == {}


@pytest.mark.asyncio
async def test_recover_options_from_turn_handles_missing_capability_and_errors():
    assert await recover_options_from_turn(object(), "turn_1", "q") == {}

    class _Raising:
        async def get_turn_events(self, turn_id, after_seq=0):
            raise RuntimeError("boom")

    assert await recover_options_from_turn(_Raising(), "turn_1", "q") == {}
    assert await recover_options_from_turn(_FakeStore([]), "", "q") == {}
