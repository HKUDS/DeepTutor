"""Solution sequences stay grounded, and the answer order stays on the server."""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.sequence.corpus import build_corpus
from deeptutor.learning.sequence.grading import placement_accepted, sequence_complete
from deeptutor.learning.sequence.schema import SequenceError, parse_problem
from deeptutor.learning.sequence.service import (
    generate_problem,
    hint,
    place_step,
    remove_step,
    scrub_hint,
)
from deeptutor.learning.sequence.store import SequenceStore

CORPUS = (
    "The chain rule says the derivative of f of g of x is f prime of g of x "
    "times g prime of x. Apply it only after identifying the outer and inner functions."
)


def _ids():
    counter = {"n": 0}

    def factory() -> str:
        counter["n"] += 1
        return f"id{counter['n']:016d}"

    return factory


def _payload() -> dict:
    return {
        "question": "Differentiate $y = \\sin(x^2)$ using the chain rule.",
        "explanation": "The outer function is sine and the inner function is x squared.",
        "formulas": ["$(f\\circ g)'(x)$"],
        "correct_steps": [
            {
                "explanation": "Identify the outer function and the inner function.",
                "math": "$f(u)=\\sin u$",
                "evidence": "identifying the outer and inner functions",
            },
            {
                "explanation": "Differentiate the outer function and keep the inner one.",
                "math": "$\\cos(x^2)$",
                "evidence": "derivative of f of g of x is f prime of g of x",
            },
            {
                "explanation": "Multiply by the derivative of the inner function.",
                "math": "$2x\\cos(x^2)$",
                "evidence": "times g prime of x",
            },
        ],
        "distractor_steps": [
            {
                "explanation": "Differentiate the inner function and stop there.",
                "math": "$2x$",
                "evidence": "",
            },
            {
                "explanation": "Multiply by the inner function instead of its derivative.",
                "math": "$x^2\\cos(x^2)$",
                "evidence": "",
            },
            {
                "explanation": "Add the derivatives instead of multiplying them.",
                "math": "$\\cos(x^2)+2x$",
                "evidence": "",
            },
        ],
    }


def _search_result(**extra):
    result = {
        "provider": "llamaindex",
        "answer": CORPUS,
        "content": CORPUS,
        "sources": [{"title": "Calculus notes", "content": CORPUS}],
    }
    result.update(extra)
    return result


async def _generate(tmp_path, payload=None, search_result=None):
    store = SequenceStore(tmp_path)
    body = payload if payload is not None else _payload()

    async def search(_topic, _kb):
        return search_result if search_result is not None else _search_result()

    async def complete_json(_prompt, _system):
        return body

    view = await generate_problem(
        "calculus",
        "chain rule",
        store,
        language="en",
        search=search,
        complete_json=complete_json,
        id_factory=_ids(),
        shuffle=lambda _steps: None,
    )
    return store, view


def test_synthesis_engines_do_not_ground_on_the_written_answer():
    corpus = build_corpus(
        {
            "provider": "lightrag",
            "answer": "A invented theorem that is not in the source.",
            "sources": [{"content": CORPUS, "title": "Notes"}],
        }
    )
    assert "invented theorem" not in corpus
    assert "chain rule" in corpus


def test_other_engines_keep_the_full_passage_when_snippets_are_short():
    corpus = build_corpus(
        {
            "provider": "llamaindex",
            "answer": CORPUS,
            "sources": [{"content": "chain rule", "title": "Notes"}],
        }
    )
    assert "g prime of x" in corpus


def test_a_step_quote_must_come_from_the_source():
    payload = _payload()
    payload["correct_steps"][0]["evidence"] = "this quote was never retrieved"
    with pytest.raises(SequenceError, match="not supported"):
        parse_problem(payload, CORPUS)


def test_placement_requires_the_right_step_at_that_index():
    correct = ["a", "b", "c"]
    assert placement_accepted(correct, [], "a", 0)
    assert not placement_accepted(correct, [], "b", 0)
    assert placement_accepted(correct, ["a"], "b", 1)
    assert not placement_accepted(correct, ["a"], "c", 1)
    assert sequence_complete(correct, ["a", "b", "c"])
    assert not sequence_complete(correct, ["a", "b"])


def test_hint_that_copies_the_next_expression_is_replaced():
    leaked = "Try $2x\\cos(x^2)$ next."
    assert "cos" not in scrub_hint(leaked, "$2x\\cos(x^2)$").casefold()


@pytest.mark.asyncio
async def test_public_problem_hides_the_order_until_it_is_solved(tmp_path):
    store, view = await _generate(tmp_path)
    saved = json.loads((tmp_path / "sessions" / f"{view['problem_id']}.json").read_text(encoding="utf-8"))
    assert "correct_ids" not in view
    assert view["explanation"] is None
    assert {step["id"] for step in view["steps"]} == {step["id"] for step in saved["steps"]}
    assert all("role" not in step and "evidence" not in step for step in view["steps"])

    wrong = next(step["id"] for step in saved["steps"] if step["role"] == "distractor")
    rejected = place_step(store, view["problem_id"], wrong, 0)
    assert rejected["accepted"] is False
    assert rejected["problem"]["placed_ids"] == []

    for index, step_id in enumerate(saved["correct_ids"]):
        placed = place_step(store, view["problem_id"], step_id, index)
        assert placed["accepted"] is True
    assert placed["problem"]["solved"] is True
    assert placed["problem"]["explanation"]
    assert placed["problem"]["progress"]["solved"] == 1
    with pytest.raises(SequenceError, match="already complete"):
        place_step(store, view["problem_id"], saved["correct_ids"][0], 0)


@pytest.mark.asyncio
async def test_removing_an_earlier_step_drops_the_broken_tail(tmp_path):
    store, view = await _generate(tmp_path)
    saved = json.loads((tmp_path / "sessions" / f"{view['problem_id']}.json").read_text(encoding="utf-8"))
    first, second = saved["correct_ids"][:2]
    place_step(store, view["problem_id"], first, 0)
    place_step(store, view["problem_id"], second, 1)
    remaining = remove_step(store, view["problem_id"], first)
    assert remaining["placed_ids"] == []


@pytest.mark.asyncio
async def test_hint_uses_the_server_copy_and_not_the_next_step(tmp_path):
    store, view = await _generate(tmp_path)

    async def complete_text(**_kwargs):
        return "Next write $f(u)=\\sin u$."

    result = await hint(store, view["problem_id"], complete_text=complete_text)
    assert "sin" not in result["hint"].casefold()


@pytest.mark.asyncio
async def test_progress_counts_a_topic_once_per_problem(tmp_path):
    store, first = await _generate(tmp_path)
    saved = json.loads((tmp_path / "sessions" / f"{first['problem_id']}.json").read_text(encoding="utf-8"))
    for index, step_id in enumerate(saved["correct_ids"]):
        place_step(store, first["problem_id"], step_id, index)
    _store, second = await _generate(tmp_path)
    assert second["progress"]["solved"] == 1
