"""Generate a solution sequence from a knowledge base and grade placements."""

from __future__ import annotations

from collections.abc import Callable
import secrets
from typing import Any

from deeptutor.learning.sequence.corpus import build_corpus, source_labels
from deeptutor.learning.sequence.grading import placement_accepted, sequence_complete
from deeptutor.learning.sequence.prompts import (
    explain_prompt,
    hint_prompt,
    system_prompt,
    tutor_prompt,
    user_prompt,
)
from deeptutor.learning.sequence.schema import (
    GOAL,
    SequenceError,
    evidence_key,
    parse_problem,
    public_problem,
)
from deeptutor.learning.sequence.store import SequenceStore

_SAFE_HINT = (
    "Look at what the source requires before the next move, and check which "
    "condition you have not used yet."
)


def _new_id(factory: Callable[[], str] | None = None) -> str:
    if factory is not None:
        return factory()
    return secrets.token_urlsafe(16)


def _step_id(factory: Callable[[], str] | None) -> str:
    if factory is not None:
        return factory()
    return "s_" + secrets.token_hex(4)


def response_language() -> str:
    try:
        from deeptutor.services.settings.interface_settings import get_ui_settings

        language = get_ui_settings().get("response_language") or "en"
    except Exception:
        language = "en"
    return str(language)


def _record_from_problem(
    problem,
    *,
    problem_id: str,
    kb_name: str,
    topic: str,
    corpus: str,
    sources: list[dict[str, str]],
    language: str,
    id_factory: Callable[[], str] | None,
    shuffle: Callable[[list], None] | None,
) -> dict[str, Any]:
    steps: list[dict[str, str]] = []
    correct_ids: list[str] = []
    for step in problem.correct_steps:
        step_id = _step_id(id_factory)
        correct_ids.append(step_id)
        steps.append(
            {
                "id": step_id,
                "explanation": step.explanation,
                "math": step.math,
                "role": "correct",
                "evidence": step.evidence,
            }
        )
    for step in problem.distractor_steps:
        steps.append(
            {
                "id": _step_id(id_factory),
                "explanation": step.explanation,
                "math": step.math,
                "role": "distractor",
                "evidence": "",
            }
        )
    if shuffle is None:
        secrets.SystemRandom().shuffle(steps)
    else:
        shuffle(steps)
    return {
        "id": problem_id,
        "kb_name": kb_name,
        "topic": topic,
        "language": language,
        "question": problem.question,
        "explanation": problem.explanation,
        "formulas": list(problem.formulas),
        "context": corpus,
        "sources": sources,
        "steps": steps,
        "correct_ids": correct_ids,
        "placed_ids": [],
        "solved": False,
    }


async def _complete_json(prompt: str, system: str) -> dict[str, Any]:
    from deeptutor.services.llm import complete
    from deeptutor.services.llm.structured_retry import json_with_reasoning_retry

    async def _run(reasoning_effort: str | None) -> str:
        return await complete(
            prompt=prompt,
            system_prompt=system,
            temperature=0.4,
            max_tokens=2_500,
            max_retries=0,
            response_format={"type": "json_object"},
            reasoning_effort=reasoning_effort,
        )

    return await json_with_reasoning_retry(_run, expected_key="question")


async def generate_problem(
    kb_name: str,
    topic: str,
    store: SequenceStore,
    *,
    language: str | None = None,
    search=None,
    complete_json=None,
    id_factory: Callable[[], str] | None = None,
    shuffle: Callable[[list], None] | None = None,
) -> dict[str, Any]:
    """Retrieve passages, write one problem, and return the public view."""
    kb_name = kb_name.strip()
    topic = " ".join(topic.split())
    if not kb_name:
        raise SequenceError(422, "Choose a knowledge base.")
    if not topic or len(topic) > 200:
        raise SequenceError(422, "Enter a topic of at most 200 characters.")

    if search is None:
        from deeptutor.tools.rag_tool import rag_search

        search = rag_search
    try:
        result = await search(topic, kb_name)
    except ValueError as exc:
        raise SequenceError(404, str(exc)) from exc
    if not isinstance(result, dict):
        raise SequenceError(422, "That knowledge base did not return any material.")
    if result.get("error_type") == "reasoning_as_retrieval_required":
        raise SequenceError(
            422,
            "This knowledge base is read through its own tools, not a passage search. "
            "Choose a different knowledge base for a solution sequence.",
        )
    if result.get("error_type") or result.get("needs_reindex"):
        message = result.get("answer") or result.get("content") or "Retrieval failed."
        raise SequenceError(422, str(message)[:300])

    corpus = build_corpus(result)
    if len(corpus) < 80:
        raise SequenceError(
            422,
            "That knowledge base did not return enough material for this topic.",
        )

    language = language or response_language()
    system = system_prompt(language)
    runner = complete_json or _complete_json
    rejection = ""
    problem = None
    for _attempt in range(2):
        data = await runner(user_prompt(topic, corpus, rejection=rejection), system)
        if not isinstance(data, dict):
            data = {}
        try:
            problem = parse_problem(data, corpus)
            break
        except SequenceError as exc:
            if exc.status != 422 or data.get("unsupported") is True:
                raise
            rejection = exc.message
            problem = None
    if problem is None:
        raise SequenceError(422, rejection or "The model could not write a grounded problem.")

    record = _record_from_problem(
        problem,
        problem_id=_new_id(id_factory),
        kb_name=kb_name,
        topic=topic,
        corpus=corpus,
        sources=source_labels(result),
        language=language,
        id_factory=id_factory,
        shuffle=shuffle,
    )
    record["progress_solved"] = store.progress(kb_name, topic)
    store.save(record)
    return public_problem(record)


def _require(store: SequenceStore, problem_id: str) -> dict[str, Any]:
    record = store.load(problem_id)
    if record is None:
        raise SequenceError(404, "That problem is no longer available.")
    return record


def _step(record: dict[str, Any], step_id: str) -> dict[str, str]:
    for step in record.get("steps") or []:
        if step.get("id") == step_id:
            return step
    raise SequenceError(404, "That step is not part of this problem.")


def place_step(store: SequenceStore, problem_id: str, step_id: str, index: int) -> dict[str, Any]:
    record = _require(store, problem_id)
    if record.get("solved"):
        raise SequenceError(409, "This solution is already complete.")
    step = _step(record, step_id)
    placed = list(record.get("placed_ids") or [])
    if step_id in placed:
        raise SequenceError(409, "That step is already in your solution.")
    if not isinstance(index, int) or isinstance(index, bool):
        raise SequenceError(422, "Say where the step should go.")
    correct_ids = list(record.get("correct_ids") or [])
    accepted = placement_accepted(correct_ids, placed, step["id"], index)
    if accepted:
        placed = placed[:index] + [step["id"]] + placed[index:]
        record["placed_ids"] = placed
        if sequence_complete(correct_ids, placed):
            record["solved"] = True
            record["progress_solved"] = store.mark_solved(
                record["kb_name"],
                record["topic"],
                record["id"],
                goal=GOAL,
            )
        else:
            record["progress_solved"] = store.progress(record["kb_name"], record["topic"])
        store.save(record)
    else:
        record["progress_solved"] = store.progress(record["kb_name"], record["topic"])
    view = public_problem(record)
    return {"accepted": accepted, "problem": view}


def remove_step(store: SequenceStore, problem_id: str, step_id: str) -> dict[str, Any]:
    record = _require(store, problem_id)
    if record.get("solved"):
        raise SequenceError(409, "This solution is already complete.")
    _step(record, step_id)
    correct_ids = list(record.get("correct_ids") or [])
    remaining = [item for item in record.get("placed_ids") or [] if item != step_id]
    kept: list[str] = []
    for item in remaining:
        if len(kept) < len(correct_ids) and correct_ids[len(kept)] == item:
            kept.append(item)
        else:
            break
    record["placed_ids"] = kept
    record["progress_solved"] = store.progress(record["kb_name"], record["topic"])
    store.save(record)
    return public_problem(record)


def _next_correct_math(record: dict[str, Any]) -> str:
    placed = list(record.get("placed_ids") or [])
    correct_ids = list(record.get("correct_ids") or [])
    if len(placed) >= len(correct_ids) or placed != correct_ids[: len(placed)]:
        return ""
    next_id = correct_ids[len(placed)]
    for step in record.get("steps") or []:
        if step.get("id") == next_id:
            return str(step.get("math") or "")
    return ""


def scrub_hint(hint: str, next_math: str) -> str:
    """Drop a hint that repeats the next expression."""
    text = " ".join(str(hint or "").split())
    secret = evidence_key(next_math)
    if secret and len(secret) > 8 and secret in evidence_key(text):
        return _SAFE_HINT
    if not text:
        return _SAFE_HINT
    return text[:600]


async def hint(store: SequenceStore, problem_id: str, *, complete_text=None) -> dict[str, str]:
    record = _require(store, problem_id)
    if record.get("solved"):
        raise SequenceError(409, "This solution is already complete.")
    placed_math = []
    by_id = {step["id"]: step for step in record.get("steps") or []}
    for step_id in record.get("placed_ids") or []:
        step = by_id.get(step_id)
        if step:
            placed_math.append(f"{step['explanation']} {step['math']}")
    prompt = hint_prompt(record["question"], placed_math, record.get("context") or "")
    if complete_text is None:
        from deeptutor.services.llm import complete as complete_text
    text = await complete_text(
        prompt=prompt,
        system_prompt=tutor_prompt(record.get("language")),
        temperature=0.3,
        max_tokens=400,
        max_retries=0,
    )
    return {"hint": scrub_hint(text, _next_correct_math(record))}


async def explain_step(
    store: SequenceStore,
    problem_id: str,
    step_id: str,
    *,
    complete_text=None,
) -> dict[str, str]:
    record = _require(store, problem_id)
    step = _step(record, step_id)
    placed = list(record.get("placed_ids") or [])
    correct_ids = list(record.get("correct_ids") or [])
    if step_id not in placed:
        raise SequenceError(409, "Place this step correctly before asking why.")
    index = placed.index(step_id)
    if index >= len(correct_ids) or correct_ids[index] != step_id:
        raise SequenceError(409, "Place this step correctly before asking why.")
    prompt = explain_prompt(
        record["question"],
        step["explanation"],
        step["math"],
        record.get("context") or "",
    )
    if complete_text is None:
        from deeptutor.services.llm import complete as complete_text
    text = await complete_text(
        prompt=prompt,
        system_prompt=tutor_prompt(record.get("language")),
        temperature=0.3,
        max_tokens=500,
        max_retries=0,
    )
    body = " ".join(str(text or "").split())
    if not body:
        body = step["explanation"]
    return {"explanation": body[:800]}
