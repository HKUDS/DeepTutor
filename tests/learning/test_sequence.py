"""Solution sequences stay grounded, and the answer order stays on the server."""

from __future__ import annotations

import hashlib
import json
import threading

import pytest

from deeptutor.learning.sequence.corpus import build_corpus
from deeptutor.learning.sequence.grading import placement_accepted, sequence_complete
from deeptutor.learning.sequence.outline import modules_from_files
from deeptutor.learning.sequence.schema import SequenceError, parse_problem
from deeptutor.learning.sequence.service import (
    build_outline,
    check_answer,
    explain_step,
    generate_problem,
    hint,
    place_step,
    read_outline,
    remove_step,
    scrub_explanation,
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


def test_explanation_that_copies_an_unplaced_expression_is_replaced():
    leaked = "Then the derivative finishes at $2x\\cos(x^2)$."
    stored = "Identify the outer function and the inner function."
    assert scrub_explanation(leaked, stored, ["$2x\\cos(x^2)$"]) == stored
    echoed = "This rewrites the step as $f(u)=\\sin u$ before continuing."
    assert scrub_explanation(echoed, stored, ["$2x\\cos(x^2)$"]) == echoed
    assert scrub_explanation("", stored, []) == stored


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
    assert [item["category"] for item in first] == ["calculus", ""]
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


@pytest.mark.asyncio
async def test_explain_needs_a_correctly_placed_step(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    distractor = next(step["id"] for step in saved["steps"] if step["role"] == "distractor")

    async def complete_text(**_kwargs):
        return "The outer function is differentiated first."

    with pytest.raises(SequenceError, match="before asking why") as unplaced:
        await explain_step(
            store, view["problem_id"], saved["correct_ids"][0], complete_text=complete_text
        )
    assert unplaced.value.status == 409
    with pytest.raises(SequenceError, match="before asking why") as rejected:
        await explain_step(store, view["problem_id"], distractor, complete_text=complete_text)
    assert rejected.value.status == 409
    with pytest.raises(SequenceError, match="not part") as unknown:
        await explain_step(store, view["problem_id"], "missing-step", complete_text=complete_text)
    assert unknown.value.status == 404


@pytest.mark.asyncio
async def test_explain_answers_for_a_step_the_learner_placed(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    first = saved["correct_ids"][0]
    place_step(store, view["problem_id"], first, 0)

    async def complete_text(**_kwargs):
        return "The outer function is differentiated first."

    result = await explain_step(store, view["problem_id"], first, complete_text=complete_text)
    assert result["explanation"] == "The outer function is differentiated first."
    assert "correct_ids" not in _forbidden_keys(result)
    assert "role" not in _forbidden_keys(result)
    assert "evidence" not in _forbidden_keys(result)


@pytest.mark.asyncio
async def test_explain_keeps_the_eight_hundred_character_bound(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    first = saved["correct_ids"][0]
    place_step(store, view["problem_id"], first, 0)

    async def complete_text(**_kwargs):
        return "word " * 200

    result = await explain_step(store, view["problem_id"], first, complete_text=complete_text)
    assert len(result["explanation"]) == 800


@pytest.mark.asyncio
async def test_explain_falls_back_to_the_stored_explanation(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    by_id = {step["id"]: step for step in saved["steps"]}
    first = saved["correct_ids"][0]
    place_step(store, view["problem_id"], first, 0)

    async def complete_text(**_kwargs):
        return ""

    result = await explain_step(store, view["problem_id"], first, complete_text=complete_text)
    assert result["explanation"] == by_id[first]["explanation"]


@pytest.mark.asyncio
async def test_explain_that_leaks_an_unplaced_step_is_replaced(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    by_id = {step["id"]: step for step in saved["steps"]}
    correct_ids = saved["correct_ids"]
    place_step(store, view["problem_id"], correct_ids[0], 0)

    async def leaky(**_kwargs):
        return f"From here the solution reaches {by_id[correct_ids[2]]['math']}."

    result = await explain_step(store, view["problem_id"], correct_ids[0], complete_text=leaky)
    assert result["explanation"] == by_id[correct_ids[0]]["explanation"]
    assert "2x" not in result["explanation"]

    async def echoes_placed(**_kwargs):
        return f"This rewrites the step as {by_id[correct_ids[0]]['math']} before continuing."

    kept = await explain_step(
        store, view["problem_id"], correct_ids[0], complete_text=echoes_placed
    )
    assert kept["explanation"] == "This rewrites the step as $f(u)=\\sin u$ before continuing."


def test_mutate_holds_the_root_lock_across_the_callback(tmp_path):
    store = SequenceStore(tmp_path)
    store.save({"id": "problem-000000000001", "placed_ids": []})
    inside = threading.Event()
    release = threading.Event()
    order: list[str] = []
    results = {}

    def slow(record):
        order.append("first")
        inside.set()
        assert release.wait(5)
        record["placed_ids"] = ["s_one"]
        return "first-done"

    def quick(record):
        order.append("second")
        return "second-done"

    def run_slow():
        results["first"] = store.mutate("problem-000000000001", slow)

    def run_quick():
        results["second"] = store.mutate("problem-000000000001", quick)

    holder = threading.Thread(target=run_slow)
    holder.start()
    try:
        assert inside.wait(5)
        competitor = threading.Thread(target=run_quick)
        competitor.start()
        competitor.join(timeout=0.3)
        # Still blocked: the lock covers the whole load-modify-save cycle.
        assert competitor.is_alive()
        release.set()
        holder.join(timeout=5)
        competitor.join(timeout=5)
        assert not holder.is_alive() and not competitor.is_alive()
    finally:
        release.set()
        holder.join(timeout=5)
    assert order == ["first", "second"]
    assert results == {"first": "first-done", "second": "second-done"}
    assert store.load("problem-000000000001")["placed_ids"] == ["s_one"]


def test_mutate_callback_exception_leaves_the_session_untouched(tmp_path):
    store = SequenceStore(tmp_path)
    store.save({"id": "problem-000000000001", "placed_ids": [], "solved": False})

    def reject(record):
        record["placed_ids"] = ["s_bogus"]
        raise SequenceError(409, "This solution is already complete.")

    with pytest.raises(SequenceError, match="already complete"):
        store.mutate("problem-000000000001", reject)
    assert store.load("problem-000000000001")["placed_ids"] == []
    # The exception released the lock: a later write still goes through.
    store.save({"id": "problem-000000000001", "placed_ids": ["s_one"], "solved": False})
    assert store.load("problem-000000000001")["placed_ids"] == ["s_one"]


def test_mutate_returns_none_for_a_missing_session(tmp_path):
    store = SequenceStore(tmp_path)
    calls = []

    def never(record):
        calls.append(record)

    assert store.mutate("problem-000000000002", never) is None
    assert calls == []


def test_store_rejects_ids_that_are_not_url_safe(tmp_path):
    store = SequenceStore(tmp_path)
    with pytest.raises(ValueError, match="Invalid problem id"):
        store.save({"id": "../evil"})
    with pytest.raises(ValueError, match="Invalid problem id"):
        store.mutate("../evil", lambda record: record)
    assert store.load("../evil") is None
    assert store.load("tooshort") is None
    assert store.load("id with spaces-00000") is None


def test_place_with_a_malformed_problem_id_is_a_404(tmp_path):
    store = SequenceStore(tmp_path)
    with pytest.raises(SequenceError, match="no longer available") as exc:
        place_step(store, "../evil", "s_one", 0)
    assert exc.value.status == 404


@pytest.mark.asyncio
async def test_two_placements_through_mutate_are_both_saved(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    first, second = saved["correct_ids"][:2]
    assert place_step(store, view["problem_id"], first, 0)["accepted"] is True
    assert place_step(store, view["problem_id"], second, 1)["accepted"] is True
    assert store.load(view["problem_id"])["placed_ids"] == [first, second]


@pytest.mark.asyncio
async def test_remove_after_solve_is_a_conflict(tmp_path):
    store, view = await _generate(tmp_path)
    saved = store.load(view["problem_id"])
    for index, step_id in enumerate(saved["correct_ids"]):
        place_step(store, view["problem_id"], step_id, index)
    with pytest.raises(SequenceError, match="already complete") as exc:
        remove_step(store, view["problem_id"], saved["correct_ids"][0])
    assert exc.value.status == 409
    assert store.load(view["problem_id"])["solved"] is True


@pytest.mark.asyncio
async def test_check_rejects_more_than_twelve_steps(tmp_path):
    store, view = await _generate(tmp_path)
    with pytest.raises(SequenceError, match="at most 12") as exc:
        check_answer(store, view["problem_id"], [f"step-{index}" for index in range(13)])
    assert exc.value.status == 422
    assert store.load(view["problem_id"])["placed_ids"] == []
    assert store.load(view["problem_id"])["solved"] is False


def test_load_treats_a_corrupt_session_as_missing(tmp_path):
    store = SequenceStore(tmp_path)
    sessions = tmp_path / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "corrupt-session-000001.json").write_text("{not json", encoding="utf-8")
    assert store.load("corrupt-session-000001") is None
    with pytest.raises(SequenceError, match="no longer available") as exc:
        place_step(store, "corrupt-session-000001", "s_one", 0)
    assert exc.value.status == 404
