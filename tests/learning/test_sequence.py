"""Solution sequences stay grounded, and the answer order stays on the server."""

from __future__ import annotations

import hashlib
import json

import pytest

from deeptutor.learning.sequence.corpus import build_corpus
from deeptutor.learning.sequence.grading import placement_accepted, sequence_complete
from deeptutor.learning.sequence.outline import modules_from_files
from deeptutor.learning.sequence.schema import SequenceError, parse_problem
from deeptutor.learning.sequence.service import (
    build_outline,
    check_answer,
    generate_problem,
    hint,
    place_step,
    read_outline,
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
    saved = json.loads(
        (tmp_path / "sessions" / f"{view['problem_id']}.json").read_text(encoding="utf-8")
    )
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
    saved = json.loads(
        (tmp_path / "sessions" / f"{view['problem_id']}.json").read_text(encoding="utf-8")
    )
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


def _forbidden_keys(value):
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(value)
        for item in value.values():
            found.update(_forbidden_keys(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_forbidden_keys(item))
    return found


def test_modules_from_files_groups_a_nested_pdf_and_a_root_md():
    paths = [
        "figures/plot.png",
        "calculus/chain_rule.pdf",
        "limits-and-continuity.md",
        ".draft/notes.txt",
    ]
    first = modules_from_files(paths)
    second = modules_from_files(list(reversed(paths)))
    assert first == second
    assert [item["category"] for item in first] == ["calculus", "Course"]
    assert [item["name"] for item in first] == ["chain rule", "limits and continuity"]
    assert [item["topic"] for item in first] == ["chain rule", "limits and continuity"]
    assert first[0]["id"] == "m_" + hashlib.sha256(b"calculus/chain_rule.pdf").hexdigest()[:12]
    assert first[1]["id"] == "m_" + hashlib.sha256(b"limits-and-continuity.md").hexdigest()[:12]
    many = [f"unit/lesson_{index:02d}.md" for index in range(40)]
    assert len(modules_from_files(many)) == 36


@pytest.mark.asyncio
async def test_build_outline_saves_the_file_outline(tmp_path):
    store = SequenceStore(tmp_path)
    paths = [
        "figures/plot.png",
        "calculus/chain_rule.pdf",
        "limits-and-continuity.md",
    ]

    def lister(kb_name: str) -> list[str]:
        assert kb_name == "calculus"
        return paths

    async def search(*_args, **_kwargs):
        raise AssertionError("a file outline must not search")

    first = await build_outline("calculus", store, list_documents=lister, search=search)
    second = await build_outline(" calculus ", store, list_documents=lister, search=search)
    assert second == first
    assert first["source"] == "files"
    assert first["knowledge_base"] == "calculus"
    assert [item["name"] for item in first["modules"]] == ["chain rule", "limits and continuity"]
    assert first["modules"][0]["solved"] == 0
    assert first["modules"][0]["goal"] == 5
    digest = hashlib.sha256(b"calculus").hexdigest()[:24]
    saved = json.loads((tmp_path / "outlines" / f"{digest}.json").read_text(encoding="utf-8"))
    assert saved["source"] == "files"
    assert "correct_ids" not in _forbidden_keys(saved)
    again = read_outline(store, "calculus")
    assert again["modules"][0]["id"] == first["modules"][0]["id"]
    assert "solved" in again["modules"][0]


@pytest.mark.asyncio
async def test_retrieval_outline_assigns_ids_and_rejects_a_bad_quote(tmp_path):
    store = SequenceStore(tmp_path)
    calls = {"n": 0}

    async def search(query, _kb_name):
        assert query == "course modules, chapters, and topics"
        return _search_result()

    async def complete_json(_prompt, _system):
        calls["n"] += 1
        return {
            "modules": [
                {
                    "id": "from-the-model",
                    "category": "Derivatives",
                    "name": "Chain rule",
                    "topic": "chain rule",
                    "evidence": "The chain rule says",
                },
                {
                    "category": "Derivatives",
                    "name": "Outer function",
                    "topic": "outer function",
                    "evidence": "identifying the outer and inner functions",
                },
                {
                    "category": "Derivatives",
                    "name": "Inner derivative",
                    "topic": "inner derivative",
                    "evidence": "times g prime of x",
                },
            ]
        }

    outline = await build_outline(
        "calculus",
        store,
        list_documents=lambda _kb: [],
        language="en",
        search=search,
        complete_json=complete_json,
    )
    assert calls["n"] == 1
    assert outline["source"] == "retrieval"
    assert len(outline["modules"]) == 3
    assert all(item["id"].startswith("m_") and len(item["id"]) == 10 for item in outline["modules"])
    assert "from-the-model" not in {item["id"] for item in outline["modules"]}
    assert "evidence" not in _forbidden_keys(outline)
    assert outline["modules"][0]["goal"] == 5

    async def rejected(_prompt, _system):
        return {
            "modules": [
                {
                    "category": "Derivatives",
                    "name": "Chain rule",
                    "topic": "chain rule",
                    "evidence": "this quote was never retrieved",
                },
                {
                    "category": "Derivatives",
                    "name": "Outer function",
                    "topic": "outer function",
                    "evidence": "The chain rule says",
                },
                {
                    "category": "Derivatives",
                    "name": "Inner derivative",
                    "topic": "inner derivative",
                    "evidence": "times g prime of x",
                },
            ]
        }

    with pytest.raises(SequenceError, match="not supported") as exc:
        await build_outline(
            "other-course",
            store,
            list_documents=lambda _kb: [],
            language="en",
            search=search,
            complete_json=rejected,
        )
    assert exc.value.status == 422
    assert store.load_outline("other-course") is None


def test_missing_outline_says_the_knowledge_base_has_not_been_read(tmp_path):
    with pytest.raises(SequenceError, match="has not been read yet") as exc:
        read_outline(SequenceStore(tmp_path), "calculus")
    assert exc.value.status == 404


@pytest.mark.asyncio
async def test_check_marks_a_leading_distractor_without_saving(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    wrong = next(step["id"] for step in saved["steps"] if step["role"] == "distractor")
    result = check_answer(store, view["problem_id"], [wrong])
    assert result["solved"] is False
    assert result["marks"] == ["incorrect"]
    assert result["problem"]["placed_ids"] == []
    assert result["problem"]["explanation"] is None
    assert "correct_ids" not in _forbidden_keys(result)
    assert "role" not in _forbidden_keys(result["problem"])
    assert "evidence" not in _forbidden_keys(result["problem"])
    assert store.load(view["problem_id"])["placed_ids"] == []
    assert store.load(view["problem_id"])["solved"] is False


@pytest.mark.asyncio
async def test_check_exact_order_solves_and_returns_the_explanation(tmp_path):
    store, view = await _generate(tmp_path)
    correct_ids = list(store.load(view["problem_id"])["correct_ids"])
    result = check_answer(store, view["problem_id"], correct_ids)
    assert result["solved"] is True
    assert result["marks"] == ["correct"] * len(correct_ids)
    assert result["problem"]["explanation"]
    assert result["problem"]["progress"]["solved"] == 1
    assert result["problem"]["placed_ids"] == correct_ids
    assert "correct_ids" not in _forbidden_keys(result)
    assert "role" not in _forbidden_keys(result["problem"])
    assert "evidence" not in _forbidden_keys(result["problem"])
    saved = store.load(view["problem_id"])
    assert saved["solved"] is True
    assert saved["placed_ids"] == correct_ids
    with pytest.raises(SequenceError, match="already complete") as exc:
        check_answer(store, view["problem_id"], correct_ids)
    assert exc.value.status == 409


@pytest.mark.asyncio
async def test_check_rejects_an_unknown_or_repeated_step(tmp_path):
    store, view = await _generate(tmp_path)
    first = store.load(view["problem_id"])["correct_ids"][0]
    with pytest.raises(SequenceError, match="not part") as unknown:
        check_answer(store, view["problem_id"], ["missing-step"])
    assert unknown.value.status == 422
    with pytest.raises(SequenceError, match="only once") as repeated:
        check_answer(store, view["problem_id"], [first, first])
    assert repeated.value.status == 422
    assert store.load(view["problem_id"])["placed_ids"] == []


@pytest.mark.asyncio
async def test_hint_uses_assembled_ids_and_scrubs_only_the_next_step(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    correct_ids = saved["correct_ids"]
    by_id = {step["id"]: step for step in saved["steps"]}
    seen = {}

    async def leak_later(**kwargs):
        seen["prompt"] = kwargs["prompt"]
        return "The later move is $2x\\cos(x^2)$."

    later = await hint(store, view["problem_id"], [correct_ids[0]], complete_text=leak_later)
    assert "2x" in later["hint"]
    assert by_id[correct_ids[0]]["math"] in seen["prompt"]
    assert by_id[correct_ids[1]]["math"] not in seen["prompt"]
    assert store.load(view["problem_id"])["placed_ids"] == []

    async def leak_next(**_kwargs):
        return "Try $\\cos(x^2)$ next."

    scrubbed = await hint(store, view["problem_id"], [correct_ids[0]], complete_text=leak_next)
    assert "cos" not in scrubbed["hint"].casefold()


@pytest.mark.asyncio
async def test_progress_counts_a_topic_once_per_problem(tmp_path):
    store, first = await _generate(tmp_path)
    saved = json.loads(
        (tmp_path / "sessions" / f"{first['problem_id']}.json").read_text(encoding="utf-8")
    )
    for index, step_id in enumerate(saved["correct_ids"]):
        place_step(store, first["problem_id"], step_id, index)
    _store, second = await _generate(tmp_path)
    assert second["progress"]["solved"] == 1
