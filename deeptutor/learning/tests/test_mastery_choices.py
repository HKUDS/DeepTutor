"""Unit tests for the choice-question data contract
(:mod:`deeptutor.capabilities.mastery.choices`).

These exercise the pure option-handling rules in isolation — parsing, body
validation, answer normalisation, and legacy recovery — independent of the
tool/engine wiring that :mod:`test_mastery_tools` drives end to end."""

from __future__ import annotations

import pytest

from deeptutor.capabilities.mastery.choices import (
    format_options,
    has_option_bodies,
    parse_options,
    recover_options_from_turn,
    resolve_answer,
)

# ── parse_options ────────────────────────────────────────────────────────────


def test_parse_options_reads_labelled_bodies():
    assert parse_options(["A: first", "B) second", "C、third"]) == {
        "A": "first",
        "B": "second",
        "C": "third",
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
