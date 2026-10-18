"""Generate a solution sequence from a knowledge base and grade placements."""

from __future__ import annotations

from collections.abc import Callable
import secrets
from typing import Any

from deeptutor.learning.sequence.corpus import build_corpus, source_labels
from deeptutor.learning.sequence.grading import placement_accepted, sequence_complete
from deeptutor.learning.sequence.outline import (
    grounded_modules,
    list_kb_documents,
    modules_from_files,
)
from deeptutor.learning.sequence.prompts import (
    explain_prompt,
    hint_prompt,
    outline_system_prompt,
    outline_user_prompt,
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
_OUTLINE_QUERY = "course modules, chapters, and topics"
_MAX_ATTEMPT = 12


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


async def _complete_outline(prompt: str, system: str) -> dict[str, Any]:
    from deeptutor.services.llm import complete
    from deeptutor.services.llm.structured_retry import json_with_reasoning_retry

    async def _run(reasoning_effort: str | None) -> str:
        return await complete(
            prompt=prompt,
            system_prompt=system,
            temperature=0.2,
            max_tokens=3_000,
            max_retries=0,
            response_format={"type": "json_object"},
            reasoning_effort=reasoning_effort,
        )

    return await json_with_reasoning_retry(_run, expected_key="modules")


async def _search_material(kb_name: str, query: str, search) -> tuple[str, dict[str, Any]]:
    """Run the same retrieval generate_problem uses, and require a usable corpus."""
    if search is None:
        from deeptutor.tools.rag_tool import rag_search

        search = rag_search
    try:
        result = await search(query, kb_name)
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
    return corpus, result


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

    corpus, result = await _search_material(kb_name, topic, search)

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


def _outline_view(
    store: SequenceStore,
    kb_name: str,
    source: str,
    modules: list[dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    for module in modules:
        topic = module.get("topic") if isinstance(module.get("topic"), str) else ""
        name = module.get("name") if isinstance(module.get("name"), str) else ""
        category = module.get("category") if isinstance(module.get("category"), str) else ""
        module_id = module.get("id") if isinstance(module.get("id"), str) else ""
        rows.append(
            {
                "id": module_id,
                "category": category,
                "name": name or topic,
                "topic": topic,
                "solved": store.progress(kb_name, topic),
                "goal": GOAL,
            }
        )
    return {"knowledge_base": kb_name, "source": source, "modules": rows}


async def _modules_from_retrieval(
    kb_name: str,
    *,
    language: str,
    search,
    complete_json,
) -> list[dict[str, str]]:
    corpus, _result = await _search_material(kb_name, _OUTLINE_QUERY, search)
    runner = complete_json or _complete_outline
    rejection = ""
    rows = None
    for _attempt in range(2):
        data = await runner(
            outline_user_prompt(corpus, rejection=rejection), outline_system_prompt(language)
        )
        if not isinstance(data, dict):
            data = {}
        try:
            rows = grounded_modules(data, corpus)
            break
        except SequenceError as exc:
            if exc.status != 422:
                raise
            rejection = exc.message
            rows = None
    if rows is None:
        raise SequenceError(422, rejection or "The model could not write a course outline.")
    used: set[str] = set()
    modules: list[dict[str, str]] = []
    for row in rows:
        module_id = "m_" + secrets.token_hex(4)
        while module_id in used:
            module_id = "m_" + secrets.token_hex(4)
        used.add(module_id)
        modules.append(
            {
                "id": module_id,
                "category": row["category"],
                "name": row["name"],
                "topic": row["topic"],
            }
        )
    return modules


async def build_outline(
    kb_name: str,
    store: SequenceStore,
    *,
    list_documents: Callable[[str], list[str]] | None = None,
    language: str | None = None,
    search=None,
    complete_json=None,
) -> dict[str, Any]:
    """Rebuild the saved outline from raw files, or from grounded retrieval."""
    kb_name = kb_name.strip()
    if not kb_name or len(kb_name) > 200:
        raise SequenceError(422, "Choose a knowledge base.")
    lister = list_documents or list_kb_documents
    documents = lister(kb_name)
    paths = (
        [item for item in documents if isinstance(item, str)] if isinstance(documents, list) else []
    )
    modules: list[dict[str, Any]] = modules_from_files(paths)
    source = "files"
    if not modules:
        modules = await _modules_from_retrieval(
            kb_name,
            language=language or response_language(),
            search=search,
            complete_json=complete_json,
        )
        source = "retrieval"
    outline = _outline_view(store, kb_name, source, modules)
    store.save_outline(kb_name, outline)
    return outline


def read_outline(store: SequenceStore, kb_name: str) -> dict[str, Any]:
    """Return the saved outline with progress filled in, or 404."""
    kb_name = kb_name.strip()
    if not kb_name or len(kb_name) > 200:
        raise SequenceError(422, "Choose a knowledge base.")
    saved = store.load_outline(kb_name)
    if not isinstance(saved, dict) or not isinstance(saved.get("modules"), list):
        raise SequenceError(404, "This knowledge base has not been read yet.")
    source = saved.get("source")
    if source not in {"files", "retrieval"}:
        source = "files"
    modules = [item for item in saved["modules"] if isinstance(item, dict)]
    return _outline_view(store, kb_name, source, modules)


def _require(store: SequenceStore, problem_id: str) -> dict[str, Any]:
    record = store.load(problem_id)
    if record is None:
        raise SequenceError(404, "That problem is no longer available.")
    return record


def _mutate(store: SequenceStore, problem_id: str, fn: Callable[[dict[str, Any]], Any]) -> Any:
    """Run one read-modify-write cycle under the store lock.

    A missing or malformed problem id is the same 404 a plain read gives, and
    a ``SequenceError`` raised inside ``fn`` reaches the learner with the
    session file left exactly as it was.
    """
    try:
        result = store.mutate(problem_id, fn)
    except ValueError as exc:
        raise SequenceError(404, "That problem is no longer available.") from exc
    if result is None:
        raise SequenceError(404, "That problem is no longer available.")
    return result


def _step(record: dict[str, Any], step_id: str) -> dict[str, str]:
    for step in record.get("steps") or []:
        if step.get("id") == step_id:
            return step
    raise SequenceError(404, "That step is not part of this problem.")


def place_step(store: SequenceStore, problem_id: str, step_id: str, index: int) -> dict[str, Any]:
    def apply(record: dict[str, Any]) -> dict[str, Any]:
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
        else:
            record["progress_solved"] = store.progress(record["kb_name"], record["topic"])
        return {"accepted": accepted, "problem": public_problem(record)}

    return _mutate(store, problem_id, apply)


def remove_step(store: SequenceStore, problem_id: str, step_id: str) -> dict[str, Any]:
    def apply(record: dict[str, Any]) -> dict[str, Any]:
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
        return public_problem(record)

    return _mutate(store, problem_id, apply)


def check_answer(store: SequenceStore, problem_id: str, step_ids: list[str]) -> dict[str, Any]:
    """Grade one attempt. A miss is not stored, and the key is not returned."""

    def apply(record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(step_ids, list) or len(step_ids) > _MAX_ATTEMPT:
            raise SequenceError(422, "Submit at most 12 steps.")
        known = {step.get("id") for step in record.get("steps") or []}
        if any(not isinstance(step_id, str) or step_id not in known for step_id in step_ids):
            raise SequenceError(422, "That step is not part of this problem.")
        if len(set(step_ids)) != len(step_ids):
            raise SequenceError(422, "Each step can appear only once.")
        if record.get("solved"):
            raise SequenceError(409, "This solution is already complete.")
        correct_ids = list(record.get("correct_ids") or [])
        marks = [
            "correct" if index < len(correct_ids) and correct_ids[index] == step_id else "incorrect"
            for index, step_id in enumerate(step_ids)
        ]
        solved = bool(correct_ids) and step_ids == correct_ids
        if solved:
            record["placed_ids"] = list(step_ids)
            record["solved"] = True
            record["progress_solved"] = store.mark_solved(
                record["kb_name"],
                record["topic"],
                record["id"],
                goal=GOAL,
            )
        return {"solved": solved, "marks": marks, "problem": public_problem(record)}

    return _mutate(store, problem_id, apply)


def _next_correct_math(record: dict[str, Any]) -> str:
    placed = list(record.get("placed_ids") or [])
    correct_ids = list(record.get("correct_ids") or [])
    if len(placed) >= len(correct_ids) or placed != correct_ids[: len(placed)]:
        return ""
    return _math_for(record, correct_ids[len(placed)])


def _math_for(record: dict[str, Any], step_id: str) -> str:
    for step in record.get("steps") or []:
        if step.get("id") == step_id:
            return str(step.get("math") or "")
    return ""


def _math_after_prefix(record: dict[str, Any], step_ids: list[str]) -> str:
    """Math of the next correct step after the longest correct prefix, else ""."""
    correct_ids = list(record.get("correct_ids") or [])
    prefix = 0
    for step_id in step_ids:
        if prefix < len(correct_ids) and correct_ids[prefix] == step_id:
            prefix += 1
            continue
        break
    if prefix >= len(correct_ids):
        return ""
    return _math_for(record, correct_ids[prefix])


def _known_ids(record: dict[str, Any], step_ids: list[str]) -> list[str]:
    known = {step.get("id") for step in record.get("steps") or []}
    return [step_id for step_id in step_ids if isinstance(step_id, str) and step_id in known]


def scrub_hint(hint: str, next_math: str) -> str:
    """Drop a hint that repeats the next expression."""
    text = " ".join(str(hint or "").split())
    secret = evidence_key(next_math)
    if secret and len(secret) > 8 and secret in evidence_key(text):
        return _SAFE_HINT
    if not text:
        return _SAFE_HINT
    return text[:600]


def scrub_explanation(text: str, stored: str, unplaced_math: list[str]) -> str:
    """Drop an explanation that repeats the math of a step not yet placed.

    Same normalized-containment check ``scrub_hint`` uses: a leak falls back
    to the stored explanation for the step being explained, which the learner
    has already earned by placing it.
    """
    body = " ".join(str(text or "").split())
    normalized = evidence_key(body)
    for math in unplaced_math:
        secret = evidence_key(str(math or ""))
        if secret and len(secret) > 8 and secret in normalized:
            body = ""
            break
    if not body:
        body = " ".join(str(stored or "").split())
    return body[:800]


async def hint(
    store: SequenceStore,
    problem_id: str,
    step_ids: list[str] | None = None,
    *,
    complete_text=None,
) -> dict[str, str]:
    record = _require(store, problem_id)
    if record.get("solved"):
        raise SequenceError(409, "This solution is already complete.")
    if step_ids is None:
        assembled = [item for item in record.get("placed_ids") or [] if isinstance(item, str)]
        secret = _next_correct_math(record)
    else:
        if not isinstance(step_ids, list) or len(step_ids) > _MAX_ATTEMPT:
            raise SequenceError(422, "Submit at most 12 steps.")
        assembled = _known_ids(record, step_ids)
        secret = _math_after_prefix(record, assembled)
    by_id = {step["id"]: step for step in record.get("steps") or []}
    placed_math = []
    for step_id in assembled:
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
    return {"hint": scrub_hint(text, secret)}


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
    unplaced_math = [
        _math_for(record, correct_id) for correct_id in correct_ids if correct_id not in placed
    ]
    return {"explanation": scrub_explanation(text, step["explanation"], unplaced_math)}
