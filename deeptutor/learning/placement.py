"""Open the conversation that belongs to one mastery phase.

Outline planning is one session for the whole path. Study and review each
have one session per knowledge point. Callers that used to reopen whichever
conversation moved last go through :func:`resolve_placed_session` instead.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from deeptutor.capabilities.mastery.mode import MODES, OUTLINE, admission_error
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.topic_generation import _MAX_OBJECTIVES_PER_MODULE

logger = logging.getLogger(__name__)

#: A lecture is written from a whole sitting, not the last exchange. The
#: budget has to fit a lesson's teaching plus the learner's questions, or the
#: writer silently loses the early knowledge points it is asked to build on.
_BUBBLE_CHAR_BUDGET = 24_000
#: A lecture is a document, not a chat reply. The chat default truncates one
#: at roughly a page, which is shorter than the thing being written.
_LECTURE_MAX_TOKENS = 4_000


def _point_name(progress: Any, knowledge_point_id: str) -> str:
    for module in getattr(progress, "modules", []) or []:
        for point in module.knowledge_points:
            if point.id == knowledge_point_id:
                return str(point.name or "").strip()
    return ""


def _module_id_for_point(progress: Any, knowledge_point_id: str) -> str:
    for module in getattr(progress, "modules", []) or []:
        if any(point.id == knowledge_point_id for point in module.knowledge_points):
            return str(module.id)
    return ""


def _module_name(modules: list[dict[str, Any]], module_id: str) -> str:
    for module in modules:
        if str(module.get("id") or "") == module_id:
            return str(module.get("name") or "").strip()
    return ""


def _find_point(progress: Any, knowledge_point_id: str) -> tuple[Any, Any]:
    """The module and point this lecture belongs to, or ``(None, None)``."""
    for module in getattr(progress, "modules", []) or []:
        for point in module.knowledge_points:
            if point.id == knowledge_point_id:
                return module, point
    return None, None


#: How much of an earlier lecture to repeat as context. Enough for the writer
#: to name a connection, not enough for it to copy the whole page.
_CONTEXT_LECTURE_CHARS = 700


def _lecture_context(
    store: LearningStore,
    path_id: str,
    progress: Any,
    knowledge_point_id: str,
) -> str:
    """What this lecture may connect back to: its module and what came before.

    A lecture written from one conversation in isolation reads like the point
    appeared out of nowhere. The outline already knows the module's purpose and
    which points are prerequisites, and earlier points may already have a
    lecture — so the writer gets that material instead of inventing links.
    """
    module, point = _find_point(progress, knowledge_point_id)
    if module is None or point is None:
        return ""

    lines: list[str] = [f"Module: {module.name}"]
    if str(getattr(module, "objective", "") or "").strip():
        lines.append(f"Module objective: {str(module.objective).strip()}")

    siblings = [
        candidate.name
        for candidate in module.knowledge_points
        if candidate.id != knowledge_point_id and str(candidate.name or "").strip()
    ]
    if siblings:
        lines.append("Other knowledge points in this module: " + ", ".join(siblings))

    prerequisites = _prerequisites(progress, knowledge_point_id)
    if prerequisites:
        lines.append(
            "Prerequisites the learner studied first: "
            + ", ".join(prerequisite.name for prerequisite in prerequisites)
        )
        for prerequisite in prerequisites:
            lecture = store.get_lecture(path_id, prerequisite.id) or {}
            body = str(lecture.get("body") or "").strip()
            if body:
                excerpt = body[:_CONTEXT_LECTURE_CHARS].strip()
                lines.append(
                    f"Already learned in 「{prerequisite.name}」:\n{excerpt}"
                )
    return "\n".join(lines)


#: How many graded check questions the lecture may reuse. More than this turns
#: the page into an exam paper, which is not what it is for.
_CHECK_QUESTION_LIMIT = 12


async def _check_question_items(
    path_id: str,
    knowledge_point_id: str,
    *,
    limit: int = _CHECK_QUESTION_LIMIT,
) -> list[dict[str, Any]]:
    """The graded check questions for this point, as question-bank rows.

    The question bank stores a question only after it has been graded, so an
    answer key still pending in the current turn can never leak into a draft
    the learner is about to answer. These are the questions the conversation
    actually asked; keeping them — and their answers — is what makes the
    lecture a self-test instead of a summary.
    """
    from deeptutor.services.session import get_session_store

    store = get_session_store()
    lister = getattr(store, "list_notebook_entries", None)
    if not callable(lister):
        return []
    try:
        listing = await lister(
            mastery_path_id=path_id,
            knowledge_point_id=knowledge_point_id,
            assessment_type="quiz",
            limit=limit,
            sort="oldest",
        )
    except Exception:
        logger.warning(
            "Could not read check questions for path %s point %s",
            path_id,
            knowledge_point_id,
            exc_info=True,
        )
        return []
    items = listing.get("items") if isinstance(listing, dict) else None
    return [
        item
        for item in items or []
        if isinstance(item, dict)
        and str(item.get("question") or "").strip()
        and str(item.get("correct_answer") or "").strip()
    ]


def _format_check_questions(items: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for item in items:
        question = str(item.get("question") or "").strip()
        answer = str(item.get("correct_answer") or "").strip()
        block = [f"Question: {question}"]
        options = item.get("options") or {}
        if isinstance(options, dict) and options:
            block.append(
                "Options: "
                + "; ".join(f"{key}. {options[key]}" for key in sorted(options))
            )
        block.append(f"Reference answer: {answer}")
        explanation = str(item.get("explanation") or "").strip()
        if explanation:
            block.append(f"Why: {explanation[:600]}")
        blocks.append("\n".join(block))
    return "\n\n".join(blocks)


async def _check_questions(
    path_id: str,
    knowledge_point_id: str,
    *,
    limit: int = _CHECK_QUESTION_LIMIT,
) -> str:
    return _format_check_questions(
        await _check_question_items(path_id, knowledge_point_id, limit=limit)
    )


async def resolve_placed_session(
    path_id: str,
    mode: str,
    knowledge_point_id: str = "",
    *,
    store: LearningStore | None = None,
) -> dict[str, Any]:
    """Return the session for this phase, creating an empty one when needed."""
    from deeptutor.services.session import get_session_store

    placed_mode = str(mode or "").strip().lower()
    if placed_mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(MODES)}")
    point_id = "" if placed_mode == OUTLINE else str(knowledge_point_id or "").strip()
    if placed_mode != OUTLINE and not point_id:
        raise ValueError("A study or review conversation needs a knowledge point.")

    learning = store or LearningStore()
    progress = learning.load(path_id)
    has_outline = progress is not None and any(module.knowledge_points for module in progress.modules)
    refusal = admission_error(placed_mode, has_outline=has_outline)
    if refusal:
        raise ValueError(refusal)
    if placed_mode != OUTLINE and progress is not None and not _point_name(progress, point_id):
        raise ValueError("That knowledge point is not on this outline.")

    existing = learning.find_placed_session(path_id, placed_mode, point_id)
    if existing:
        return {"session_id": existing, "created": False, "mode": placed_mode, "knowledge_point_id": point_id}

    title = "Outline"
    if placed_mode != OUTLINE and progress is not None:
        title = _point_name(progress, point_id) or placed_mode
    session_store = get_session_store()
    created = await session_store.create_session(title=title[:100])
    session_id = str(created.get("session_id") or created.get("id") or "")
    if not session_id:
        raise RuntimeError("The conversation could not be opened.")
    await session_store.update_session_preferences(
        session_id,
        {
            "workspace_mode": "mastery_path",
            "capability": "mastery_path",
            "mastery_path_id": path_id,
            "mastery_session_mode": placed_mode,
            "mastery_knowledge_point_id": point_id,
        },
    )
    try:
        learning.bind_session(path_id, session_id, mode=placed_mode, knowledge_point_id=point_id)
    except Exception:
        winner = learning.find_placed_session(path_id, placed_mode, point_id)
        if winner and winner != session_id:
            return {
                "session_id": winner,
                "created": False,
                "mode": placed_mode,
                "knowledge_point_id": point_id,
            }
        raise
    return {"session_id": session_id, "created": True, "mode": placed_mode, "knowledge_point_id": point_id}


async def _bubbles(session_id: str) -> list[dict[str, Any]]:
    from deeptutor.services.session import get_session_store

    session_store = get_session_store()
    reader = getattr(session_store, "list_bubble_texts", None)
    if callable(reader):
        rows = await reader(session_id)
    else:
        rows = await session_store.get_messages(session_id)
    bubbles: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"} or not content:
            continue
        try:
            message_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            message_id = 0
        bubbles.append({"id": message_id, "role": role, "content": content})
    return bubbles


def lecture_status(store: LearningStore, path_id: str, knowledge_point_id: str, bubbles: list[dict[str, Any]]) -> dict[str, Any]:
    """What review should render, and what the learner still has to decide.

    Three states, and the UI must not collapse them. ``confirmed`` is a
    lecture somebody committed; ``draft_only`` is the rolling summary of a
    study conversation nobody has confirmed yet — shown, but marked, so it is
    never mistaken for settled content; ``none`` means this point has nothing
    to read. A confirmed lecture can still be ``stale`` against study, and
    that is reported separately because it is a much weaker signal than
    "unconfirmed" and deserves a chip rather than a warning.
    """
    saved = store.get_lecture(path_id, knowledge_point_id) or {
        "body": "",
        "covered_message_id": 0,
        "revision": 0,
        "confirmed_at": 0,
        "source": "",
        "updated_at": 0,
    }
    draft = store.get_lecture_draft(path_id, knowledge_point_id)
    latest = max((int(row["id"]) for row in bubbles), default=0)
    covered = int(saved["covered_message_id"] or 0)
    body = str(saved["body"] or "")
    draft_body = str((draft or {}).get("body") or "")
    if body:
        status = "confirmed"
    elif draft_body:
        status = "draft_only"
    else:
        status = "none"
    return {
        # What review renders. A draft-only point renders its draft rather
        # than an empty page, and ``status`` is what tells the reader which
        # one they are looking at.
        "body": body or draft_body,
        "confirmed_body": body,
        "status": status,
        "revision": int(saved["revision"] or 0),
        "source": str(saved["source"] or ""),
        "confirmed_at": float(saved["confirmed_at"] or 0),
        "covered_message_id": covered,
        "latest_message_id": latest,
        "has_study": bool(bubbles),
        "stale": bool(body) and latest > covered,
        "draft": {
            "session_id": str(draft["session_id"]),
            "body": draft_body,
            "diff": list(draft.get("diff") or []),
            "base_revision": int(draft["base_revision"] or 0),
            "covered_message_id": int(draft["covered_message_id"] or 0),
            "origin": str(draft["origin"] or ""),
            "updated_at": float(draft["updated_at"] or 0),
        }
        if draft and draft_body
        else None,
        # Study moved on while a confirmed lecture sits in review. Weaker than
        # a draft: the reader has settled content, it is just behind.
        "stale_from_study": bool(body) and draft is not None,
    }


async def study_bubbles(path_id: str, knowledge_point_id: str, *, store: LearningStore | None = None) -> list[dict[str, Any]]:
    learning = store or LearningStore()
    session_id = learning.find_placed_session(path_id, "study", knowledge_point_id)
    if not session_id:
        return []
    return await _bubbles(session_id)


def _transcript(bubbles: list[dict[str, Any]]) -> str:
    # Both speakers are kept on purpose: the tutor carries the material, and the
    # learner's questions show which points actually needed explaining, which is
    # what makes the lecture answer the right thing.
    lines: list[str] = []
    used = 0
    for row in bubbles:
        speaker = "Learner" if row["role"] == "user" else "Tutor"
        piece = f"{speaker}: {row['content'].strip()}"
        if used and used + len(piece) > _BUBBLE_CHAR_BUDGET:
            break
        lines.append(piece)
        used += len(piece)
    return "\n\n".join(lines)


# --------------------------------------------------------------------------
# Section-level diffs
#
# A lecture is one markdown document, but the learner edits it a section at a
# time and reads it a section at a time. Diffing whole bodies produces "the
# entire document changed" for a one-line edit, which is useless to review.
# Splitting on headings gives blocks a stable name, so a revision card can say
# *which* part of the lecture it is about to change.
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
#: A lecture section is identified by its heading text, not its position:
#: inserting a section must not renumber every section below it.
_PREAMBLE = "（引言）"


def split_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown into ``(heading, text)`` blocks, preamble first."""
    text = str(body or "")
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [(_PREAMBLE, text)] if text.strip() else []
    sections: list[tuple[str, str]] = []
    if text[: matches[0].start()].strip():
        sections.append((_PREAMBLE, text[: matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        sections.append((heading, text[match.start() : end]))
    return sections


def lecture_diff(before: str, after: str) -> list[dict[str, Any]]:
    """Section-level changes between two lecture bodies.

    ``op`` is ``added`` / ``removed`` / ``replaced`` and ``heading`` names the
    block, so the card can render the change against a title the learner
    recognises even after a rewrite has moved the section.
    """
    old = dict(split_sections(before))
    new = dict(split_sections(after))
    changes: list[dict[str, Any]] = []
    for heading, text in new.items():
        if heading not in old:
            changes.append({"op": "added", "heading": heading, "before": "", "after": text})
        elif old[heading].strip() != text.strip():
            changes.append(
                {"op": "replaced", "heading": heading, "before": old[heading], "after": text}
            )
    for heading, text in old.items():
        if heading not in new:
            changes.append({"op": "removed", "heading": heading, "before": text, "after": ""})
    return changes


# --------------------------------------------------------------------------
# Coverage: what the conversation covered that the lecture does not.
#
# "Did the lecture miss anything?" is not a question a reader can answer,
# because the reader has not seen the conversation. So the miss is computed as
# a diff against a ledger the runtime already has: the learner's questions and
# the graded check questions. The result is a list of candidates to review —
# not an error — and it is the same list the reviewer and the UI see.
# --------------------------------------------------------------------------

#: Words that carry no topic signal, so overlap on them proves nothing.
_LATIN_STOPWORDS = frozenset(
    {
        "the", "and", "for", "that", "with", "this", "from", "what", "why",
        "how", "does", "did", "are", "was", "were", "you", "your", "into",
        "about", "when", "which", "then", "than", "not", "but", "can",
        "could", "would", "should", "have", "has", "had", "its", "it's",
        "they", "them", "there", "here", "will", "just", "like", "more",
    }
)
#: Chinese characters so common that a bigram made only of them is noise.
_CJK_STOP_CHARS = frozenset(
    "的是了和与在也就都而及或有个这那我你他她它吗呢吧啊什么怎么为对不了把被让给还再从到向"
)


def _clip(text: str, limit: int = 200) -> str:
    body = str(text or "").strip()
    return body if len(body) <= limit else body[:limit].rstrip() + "…"


def _meaningful_terms(text: str) -> set[str]:
    """Distinctive terms in ``text`` for an overlap test.

    Latin words of three or more letters, plus character bigrams for Chinese
    (a single character is far too common to prove anything). No tokenizer
    dependency: the test is deliberately cheap because it only ever produces
    candidates for review.
    """
    raw = str(text or "")
    terms: set[str] = set()
    for word in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", raw.lower()):
        if word not in _LATIN_STOPWORDS:
            terms.add(word)
    for run in re.findall(r"[\u4e00-\u9fff]+", raw):
        if len(run) == 1:
            terms.add(run)
            continue
        for index in range(len(run) - 1):
            bigram = run[index : index + 2]
            if not all(char in _CJK_STOP_CHARS for char in bigram):
                terms.add(bigram)
    return terms


def _prerequisites(progress: Any, knowledge_point_id: str) -> list[Any]:
    module, point = _find_point(progress, knowledge_point_id)
    if module is None or point is None:
        return []
    by_id = {
        candidate.id: candidate
        for each_module in getattr(progress, "modules", []) or []
        for candidate in each_module.knowledge_points
    }
    return [
        by_id[prerequisite_id]
        for prerequisite_id in getattr(point, "prerequisite_ids", []) or []
        if prerequisite_id in by_id
    ]


def lecture_coverage(
    store: LearningStore,
    path_id: str,
    knowledge_point_id: str,
    bubbles: list[dict[str, Any]],
    body: str,
    *,
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Candidate gaps between the study conversation and the lecture body.

    A gap is a learner question, a graded check question, or a prerequisite
    that shares no distinctive term with the lecture. The list is intentionally
    conservative: it flags what it cannot find, and a human (the learner) or the
    reviewer decides whether the absence actually matters. ``count`` is what a
    reader pane can show as "可能漏了 N 项".
    """
    covered = _meaningful_terms(body)
    missing: list[dict[str, str]] = []
    for row in bubbles:
        if str(row.get("role") or "") != "user":
            continue
        text = str(row.get("content") or "").strip()
        terms = _meaningful_terms(text)
        if terms and not (terms & covered):
            missing.append({"kind": "question", "text": _clip(text)})
    for item in checks or []:
        answer = str(item.get("correct_answer") or "").strip()
        terms = _meaningful_terms(answer)
        if terms and not (terms & covered):
            question = str(item.get("question") or "").strip()
            missing.append({"kind": "check", "text": _clip(question or answer)})
    progress = store.load(path_id)
    if progress is not None:
        for prerequisite in _prerequisites(progress, knowledge_point_id):
            terms = _meaningful_terms(getattr(prerequisite, "name", ""))
            if terms and not (terms & covered):
                missing.append({"kind": "prerequisite", "text": str(prerequisite.name)})
    return {"missing": missing, "count": len(missing)}


async def lecture_coverage_report(
    path_id: str,
    knowledge_point_id: str,
    *,
    store: LearningStore | None = None,
) -> dict[str, Any]:
    """What a reader pane can show: is the lecture behind, and what is it missing.

    Two different questions, two different signals: ``stale`` is about *time*
    (study moved past the lecture's watermark) and ``missing`` is about
    *content* (a question or answer the lecture body does not carry). A lecture
    can be current and still incomplete.
    """
    learning = store or LearningStore()
    bubbles = await study_bubbles(path_id, knowledge_point_id, store=learning)
    status = lecture_status(learning, path_id, knowledge_point_id, bubbles)
    checks = await _check_question_items(path_id, knowledge_point_id)
    report = lecture_coverage(
        learning, path_id, knowledge_point_id, bubbles, status["body"], checks=checks
    )
    return {
        **report,
        "status": status["status"],
        "revision": status["revision"],
        "covered_message_id": status["covered_message_id"],
        "latest_message_id": status["latest_message_id"],
        "stale": status["stale"],
    }


_LECTURE_ROLL_SYSTEM = """You are writing one knowledge point's lecture (讲义) for a learner on a mastery path.

This is the page they come back to: to understand the idea again, and to recall
it before a test or a discussion. It is not a chat reply and not a stack of
bullet points. Write to teach — 深入浅出: begin with something concrete, build up
to the precise idea, say why it exists, and show where it stops being true. A
reader who finishes a section should be able to explain it in their own words.

There is no required template. A lecture that works answers these questions, in
whatever order the material makes natural:
- What is it, in one or two sentences they could say out loud?
- What problem or question makes it necessary, and what would break without it?
- How does it work — the mechanism, the steps, or the derivation?
- What is a concrete example? Prefer the tutor's own analogy or example from
  the conversation; those are what make the point stick.
- How does it connect to what the learner already knows? The path context gives
  you the module's objective, the sibling points, and the prerequisites, and
  sometimes an excerpt of an earlier lecture. Name the connection, then build
  the new idea on top of it. If the learner compared this to something in the
  conversation, use their comparison.
- Where do people get it wrong? Call out the mistakes and confusions the
  learner actually hit, say what the mistake looks like, and how to tell it
  apart from the correct idea.
- What was actually checked? The conversation may contain graded check
  questions with reference answers. Keep the real ones: give the question, its
  options if it had any, and its reference answer, with the explanation where
  that adds something. Prefer these over questions you invent. If there were
  none, close with two to four recall questions that test understanding rather
  than wording, each with a one-line answer.
- What is the one thing worth remembering? Give it as a single sentence or a
  small structure before the self-test.

Follow the learner's thread, not the clock:
- The exchange is a path, not a dump. The learner asked something, it was
  clarified, then they probed further. Organize the lecture around the
  questions the learner actually asked, and let each part answer the question
  that produced it. Their first confusion is the reader's first question too.
- A later question that sharpens an earlier idea is a refinement, not a new
  topic. Rewrite that idea's section so the clarification is woven in, instead
  of appending it at the end as one more bullet.
- Keep the learner's own words for what they were trying to understand. If they
  called it X and the answer gave X a precise name, the lecture says both.
- Keep the extensions the learner asked for. A follow-up question may have
  reached another knowledge point; put that material in a clearly named section
  (e.g. "延伸" / "Going further") rather than dropping it. The point's name is a
  starting place, not a fence.
- Each round of questions should make the lecture clearer and more precise,
  not longer. Fold answers into the sections they deepen; never just stack new
  paragraphs on top of the old ones.

How to write it:
- Write in the language of the transcript.
- Keep it scannable: headings, short paragraphs, a list for steps, a table only
  when several things are compared, bold for the one thing in a section that
  must be remembered.
- Use short sentences and concrete words. Define a term the first time it
  appears. Explain the why, not just the what.
- Be generous enough that a reader who was not in the conversation can follow
  the idea, but cut anything that only restates a heading.

Never include:
- The conversation itself ("earlier", "I showed you", "last round"), except a
  connection the learner will recognise ("you compared it to X").
- Feedback on an answer the learner gave, scores, or the mechanics of quizzing
  and grading — but the questions themselves and their reference answers do
  belong in the self-test.
- Instructions for the learner's next step.
- A replay of the question-and-answer exchange. The learner's questions are
  evidence of what confused them, not text to reproduce.
- Material the transcript did not discuss. No invented facts or examples, and
  no filling in the obvious next chapter.

Rules that matter more than fluency:
- Keep every heading that already exists, in its existing order and wording.
  The learner may have renamed or rewritten a section; that wording is theirs
  now and you must not restyle it.
- Merge new material into the section it belongs to. Add a new section only
  when the new material genuinely starts a new topic.
- Do not rewrite a section the new material does not touch.
- Output the document itself. No preamble, no code fence, no commentary."""


#: One review round, modelled on the Draft → Critique → Revise loop in
#: ``deeptutor/book/agents/spine_synthesizer.py``. The writer is not the best
#: judge of whether it followed the learner's thread; a separate reader is.
#: Bounded to a single pass so a lecture turn can never become a spiral, and
#: run after DONE, so it costs latency the composer does not wait on.
_LECTURE_CRITIQUE_ROUNDS = 1

_LECTURE_CRITIQUE_SYSTEM = """You review a lecture draft before a learner reads it. You are not rewriting it; you decide whether it does its job, using only the material provided.

Return JSON:
{"verdict": "ok" | "revise",
 "missing": ["<a learner question or taught point the lecture leaves out>"],
 "issues": [{"section": "<heading, or whole>", "problem": "...", "fix": "..."}]}

Judge, in order:
1. Does the lecture follow the learner's own thread — the questions they asked, in the order their understanding moved?
2. Does it answer those questions and fold each clarification into the right section, rather than appending it at the end?
3. Are the checked questions and their reference answers present and faithful to the material given?
4. Is it 深入浅出: concrete first, then the precise idea, why it exists, an example, and where it stops being true?
5. Does it connect to the prior knowledge points named in the path context?
6. Does it contain material the conversation and context do not support?
7. Does it read like a lecture, not a transcript, a bullet dump, or a revision sheet?

Return "ok" when a learner who read the lecture would not need to ask their questions again. Return "revise" only for issues that change what the learner understands; wording preferences are not issues. Keep the issue list short and specific, and name the section each one affects.
"""


def _strip_code_fence(text: str) -> str:
    """Drop a wrapping code fence the model may have echoed.

    Untouched, the fence becomes part of the draft's own text, so every later
    merge inherits it.
    """
    body = str(text or "").strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n", "", body)
        body = re.sub(r"\n?```$", "", body).strip()
    return body


async def _review_lecture(
    *,
    point_name: str,
    context_block: str,
    check_block: str,
    transcript: str,
    draft: str,
) -> str:
    """One critique pass; returns a revised body, or ``draft`` unchanged.

    Empty or unparseable critique is treated as "ok": a review step that fails
    must never cost the learner the draft that already exists.
    """
    from deeptutor.services.llm.factory import complete
    from deeptutor.utils.json_parser import parse_json_response

    raw = await complete(
        (
            f"Knowledge point: {point_name}\n\n"
            f"{context_block}{check_block}"
            f"--- LEARNER'S CONVERSATION ---\n{transcript}\n--- END ---\n\n"
            f"--- LECTURE DRAFT ---\n{draft}\n--- END DRAFT ---"
        ),
        system_prompt=_LECTURE_CRITIQUE_SYSTEM,
        max_tokens=1_200,
    )
    payload = parse_json_response(raw, logger_instance=logger, fallback={})
    if not isinstance(payload, dict):
        return draft
    issues = [issue for issue in (payload.get("issues") or []) if isinstance(issue, dict)]
    missing = [
        str(item).strip()
        for item in (payload.get("missing") or [])
        if str(item).strip()
    ]
    if str(payload.get("verdict") or "").lower() != "revise" or not (issues or missing):
        return draft

    rendered = "\n".join(
        [
            *(
                "- [{section}] {problem} → {fix}".format(
                    section=str(issue.get("section") or "whole").strip() or "whole",
                    problem=str(issue.get("problem") or "").strip(),
                    fix=str(issue.get("fix") or "").strip(),
                )
                for issue in issues
                if str(issue.get("problem") or "").strip()
            ),
            *(
                f"- [whole] missing from the lecture: {entry}"
                for entry in missing
            ),
        ]
    )
    if not rendered:
        return draft
    revised = await complete(
        (
            f"Knowledge point: {point_name}\n\n"
            f"{context_block}{check_block}"
            "A reviewer read the lecture draft below. Rewrite it so every issue "
            "is resolved. Keep everything the review does not name, keep every "
            "existing heading's wording, and keep the reference answers. Output "
            "the full document.\n\n"
            f"--- REVIEW ---\n{rendered}\n--- END REVIEW ---\n\n"
            f"--- CURRENT LECTURE ---\n{draft}\n--- END LECTURE ---"
        ),
        system_prompt=_LECTURE_ROLL_SYSTEM,
        max_tokens=_LECTURE_MAX_TOKENS,
    )
    revised_text = _strip_code_fence(revised)
    if not revised_text:
        logger.warning(
            "Lecture review for %s produced no text; keeping the draft", point_name
        )
        return draft
    return revised_text


async def write_lecture_draft(
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
    store: LearningStore | None = None,
    request_id: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Roll this point's lecture draft forward from its study conversation.

    Deliberately not "rewrite the lecture". A full rewrite from the whole
    transcript is non-idempotent — the same conversation produces different
    prose each time — and it silently discards anything the learner edited by
    hand. So the existing draft is an *input*: only bubbles past its watermark
    are summarised, and they are merged into the sections already there.
    """
    from deeptutor.services.llm.factory import complete

    learning = store or LearningStore()
    progress = learning.load(path_id)
    point_name = _point_name(progress, knowledge_point_id) if progress is not None else ""
    if not point_name:
        raise ValueError("That knowledge point is not on this outline.")
    bubbles = await study_bubbles(path_id, knowledge_point_id, store=learning)
    if not bubbles:
        raise ValueError("This knowledge point has no study conversation to summarize.")

    study_session = session_id or learning.find_placed_session(path_id, "study", knowledge_point_id)
    existing = learning.get_lecture_draft(path_id, knowledge_point_id, session_id=study_session)
    if existing and request_id and existing["request_id"] == request_id and not force:
        return lecture_status(learning, path_id, knowledge_point_id, bubbles)

    covered_before = int((existing or {}).get("covered_message_id") or 0)
    # Fresh material is the whole exchange past the watermark, learner included:
    # which points the learner asked about is exactly what the lecture has to
    # answer. Only a window with no teaching at all has nothing to write.
    fresh = [row for row in bubbles if int(row["id"]) > covered_before]
    if force:
        # A forced re-roll means "write it again from the whole sitting", not
        # "write it again from only what was asked".
        fresh = list(bubbles)
    if not any(row["role"] != "user" for row in fresh):
        # Questions with no answers since the last roll teach nothing, and
        # writing a lecture out of them would put the learner's own words in the
        # document as if they were the lesson.
        return lecture_status(learning, path_id, knowledge_point_id, bubbles)

    previous_body = str((existing or {}).get("body") or "")
    confirmed = learning.get_lecture(path_id, knowledge_point_id) or {}
    base_body = previous_body or str(confirmed.get("body") or "")
    base_revision = int(
        (existing or {}).get("base_revision") or confirmed.get("revision") or 0
    )
    context = _lecture_context(learning, path_id, progress, knowledge_point_id)
    context_block = (
        f"--- PATH CONTEXT ---\n{context}\n--- END PATH CONTEXT ---\n\n" if context else ""
    )
    check_items = await _check_question_items(path_id, knowledge_point_id)
    checks = _format_check_questions(check_items)
    check_block = (
        "--- CHECK QUESTIONS ALREADY ASKED (with reference answers) ---\n"
        f"{checks}\n--- END ---\n\n"
        if checks
        else ""
    )

    if previous_body:
        # The lecture is the older of the two, so a question the learner asked
        # after it was rolled is the most likely thing to be missing. Hand that
        # ledger to the writer rather than hoping it re-reads every bubble.
        coverage = lecture_coverage(
            learning,
            path_id,
            knowledge_point_id,
            bubbles,
            previous_body,
            checks=check_items,
        )
        missing_block = ""
        if coverage["count"]:
            missing_lines = "\n".join(
                f"- [{item['kind']}] {item['text']}" for item in coverage["missing"]
            )
            missing_block = (
                "--- NOT YET FOUND IN THE LECTURE (candidates, not orders) ---\n"
                f"{missing_lines}\n--- END ---\n\n"
            )
        instruction = (
            f"Knowledge point: {point_name}\n\n"
            f"{context_block}{check_block}{missing_block}"
            "Here is the lecture as it stands. The new conversation continues "
            "the learner's own thread of questions and refinements. Read it for "
            "how their understanding moved: fold each clarification into the "
            "section that idea belongs to and rewrite that section so it answers "
            "the question the learner was actually asking. Cover the candidates "
            "above when the conversation supports them. Do not append the "
            "answers at the end, and do not rewrite sections the exchange did "
            "not touch. Keep every existing heading's wording. Keep the "
            "reference answers of every check question that has been asked. "
            "Write the lecture, not a transcript of the exchange.\n\n"
            f"--- CURRENT LECTURE ---\n{previous_body}\n--- END LECTURE ---\n\n"
            f"--- NEW CONVERSATION ---\n{_transcript(fresh)}\n--- END ---"
        )
    else:
        instruction = (
            f"Knowledge point (use this verbatim as the first heading): {point_name}\n\n"
            f"{context_block}{check_block}"
            "Write this point's lecture from the study conversation below. The "
            "conversation has the tutor's teaching and the learner's questions: "
            "follow the learner's own line of thought — each question they asked, "
            "and what answering it added — and build on the knowledge points the "
            "learner already met. Keep the reference answers of every check "
            "question that has been asked. Write the lecture, not a transcript "
            "of the exchange.\n\n"
            f"{_transcript(fresh)}"
        )

    body = await complete(
        instruction,
        system_prompt=_LECTURE_ROLL_SYSTEM,
        max_tokens=_LECTURE_MAX_TOKENS,
    )
    text = _strip_code_fence(body)
    if not text:
        raise RuntimeError("The lecture could not be written.")
    # Review the first draft and an explicit re-roll. An incremental merge is
    # already anchored to the learner's edits, and reviewing every roll would
    # spend two more model calls to protect text nobody has touched.
    if _LECTURE_CRITIQUE_ROUNDS and (not previous_body or force):
        try:
            text = await _review_lecture(
                point_name=point_name,
                context_block=context_block,
                check_block=check_block,
                transcript=_transcript(fresh),
                draft=text,
            )
        except Exception:
            logger.warning(
                "Lecture review failed for path %s point %s; keeping the draft",
                path_id,
                knowledge_point_id,
                exc_info=True,
            )

    covered = max(int(row["id"]) for row in bubbles)
    learning.save_lecture_draft(
        path_id,
        knowledge_point_id,
        session_id=study_session,
        body=text,
        base_revision=base_revision,
        covered_message_id=covered,
        diff=lecture_diff(base_body, text),
        request_id=request_id,
        origin="study_roll",
    )
    return lecture_status(learning, path_id, knowledge_point_id, bubbles)


async def revise_lecture_draft(
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str,
    instruction: str,
    store: LearningStore | None = None,
    quoted_text: str = "",
    section_heading: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    """Propose a lecture revision from a learner's own words.

    Never writes the confirmed lecture. This is the counterpart of
    ``mastery_revise(action=preview)`` for outline content: the model produces
    a candidate, the learner applies it from a card under the reply. Writing
    straight through meant a long markdown document got rewritten wholesale
    and the learner only noticed afterwards that a paragraph they had written
    themselves was gone.
    """
    from deeptutor.services.llm.factory import complete

    learning = store or LearningStore()
    progress = learning.load(path_id)
    point_name = _point_name(progress, knowledge_point_id) if progress is not None else ""
    if not point_name:
        raise ValueError("That knowledge point is not on this outline.")

    confirmed = learning.get_lecture(path_id, knowledge_point_id) or {}
    current = str(confirmed.get("body") or "")
    origin = "chat_revision"
    if not current:
        # No confirmed lecture yet: revise the study draft if there is one, so
        # a learner in review is never told "there is nothing to edit" for a
        # lecture they can plainly see on screen.
        draft = learning.get_lecture_draft(path_id, knowledge_point_id)
        current = str((draft or {}).get("body") or "")
        origin = "chat_revision_of_draft"
    if not current:
        raise ValueError("This knowledge point has no lecture to revise yet.")

    target = f"\nTarget section: {section_heading}\n" if section_heading else ""
    quote = f'\nText to change (verbatim): "{quoted_text}"\n' if quoted_text else ""
    context = (
        _lecture_context(learning, path_id, progress, knowledge_point_id)
        if progress is not None
        else ""
    )
    context_block = (
        f"--- PATH CONTEXT ---\n{context}\n--- END PATH CONTEXT ---\n" if context else ""
    )
    body = await complete(
        (
            f"Knowledge point: {point_name}\n"
            f"{context_block}{target}{quote}\n"
            f"The learner asks: {instruction}\n\n"
            "Apply exactly what was asked and nothing else. Keep every other "
            "section's wording byte-for-byte. Output the full document.\n\n"
            f"--- CURRENT LECTURE ---\n{current}\n--- END LECTURE ---"
        ),
        system_prompt=_LECTURE_ROLL_SYSTEM,
        max_tokens=_LECTURE_MAX_TOKENS,
    )
    text = _strip_code_fence(body)
    if not text:
        raise RuntimeError("The lecture could not be revised.")
    changes = lecture_diff(current, text)
    if not changes:
        raise ValueError("That request did not change the lecture. Say so instead of saving.")

    draft = learning.save_lecture_draft(
        path_id,
        knowledge_point_id,
        session_id=session_id,
        body=text,
        base_revision=int(confirmed.get("revision") or 0),
        covered_message_id=int(confirmed.get("covered_message_id") or 0),
        diff=changes,
        request_id=request_id,
        origin=origin,
    )
    return {
        "preview_id": int(draft["updated_at"] * 1000),
        "session_id": draft["session_id"],
        "base_revision": draft["base_revision"],
        "changes": changes,
        "body": text,
        "origin": origin,
    }


def commit_lecture_draft(
    store: LearningStore,
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
    source: str = "learner_confirmed",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Promote a draft to the confirmed lecture review will show.

    Conflict, not overwrite: a reviewer's stale tab must not replace a lecture
    that study rolled up in the meantime. ``expected_revision`` is checked
    against the confirmed lecture, and the draft's own ``base_revision`` is
    checked against it too — the second catches the case a client cannot see
    (its own draft was written against a lecture that has since moved).
    """
    draft = store.get_lecture_draft(path_id, knowledge_point_id, session_id=session_id)
    if draft is None:
        raise ValueError("There is no lecture draft to confirm. Write it first.")
    body = str(draft["body"] or "").strip()
    if not body:
        raise ValueError("That lecture draft is empty.")

    current = store.get_lecture(path_id, knowledge_point_id) or {}
    current_revision = int(current.get("revision") or 0)
    if expected_revision is not None and current_revision != int(expected_revision):
        raise ValueError(
            "This lecture changed while you were reading it. Reload before confirming."
        )
    base = int(draft["base_revision"] or 0)
    if base and current_revision and base != current_revision:
        raise ValueError(
            "This draft was written against an older lecture. Reload and revise again."
        )

    revision = store.save_lecture(
        path_id,
        knowledge_point_id,
        body,
        int(draft["covered_message_id"] or 0),
        source=source,
        # Optimistic, not blind: the reads above are only a friendly error
        # message. The write itself has to prove the revision it inspected is
        # still current, or two cards confirmed a second apart both "succeed"
        # and one of the two bodies silently loses.
        expected_revision=current_revision,
    )
    store.delete_lecture_draft(path_id, knowledge_point_id, session_id=draft["session_id"])
    return {
        "status": "confirmed",
        "knowledge_point_id": knowledge_point_id,
        "revision": revision,
        "source": source,
        "body": body,
    }


def abandon_lecture_draft(
    store: LearningStore,
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Throw away an unapplied revision without touching the lecture."""
    removed = store.delete_lecture_draft(path_id, knowledge_point_id, session_id=session_id)
    return {"status": "abandoned" if removed else "nothing_to_abandon"}


def revert_lecture_confirmation(
    store: LearningStore,
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Undo an implicit confirmation, putting its text back as a draft.

    Confirming on the learner's behalf when they walk away from a point is
    what keeps review from being empty. It is still a decision made for them,
    so it has to be reversible — and reversing it must not lose the text, so
    the draft is written *before* the confirmed row is dropped. If there is no
    conversation left to hold a draft, the confirmation is not undone at all:
    an explicit "cannot undo" beats silently deleting the only copy.
    """
    saved = store.get_lecture(path_id, knowledge_point_id)
    if saved is None or str(saved.get("source") or "") != "implicit":
        raise ValueError("Only a lecture saved automatically can be undone.")
    body = str(saved.get("body") or "")
    study_session = session_id or store.find_placed_session(path_id, "study", knowledge_point_id)
    if not study_session:
        raise ValueError(
            "This point has no study conversation left to hold the lecture, "
            "so undoing would delete the only copy."
        )
    store.save_lecture_draft(
        path_id,
        knowledge_point_id,
        session_id=study_session,
        body=body,
        base_revision=0,
        covered_message_id=int(saved.get("covered_message_id") or 0),
        diff=[],
        origin="study_roll",
    )
    store.delete_lecture(path_id, knowledge_point_id)
    return {"status": "reverted", "knowledge_point_id": knowledge_point_id}


def auto_confirm_lecture(
    path_id: str, knowledge_point_id: str, *, store: LearningStore | None = None
) -> bool:
    """Confirm whatever study rolled up, when the learner leaves the point.

    This is the answer to "what if they never press the button": they still
    walk forward, and a lecture nobody confirmed is worth less than a correct
    one marked as saved automatically. Returns whether anything was saved.
    """
    learning = store or LearningStore()
    draft = learning.get_lecture_draft(path_id, knowledge_point_id)
    if draft is None or not str(draft["body"] or "").strip():
        return False
    try:
        commit_lecture_draft(learning, path_id, knowledge_point_id, source="implicit")
    except ValueError:
        return False
    except RuntimeError:
        # A lost race with another writer (the learner's own button, or a
        # review tab) is not a failure worth surfacing: whoever won saved a
        # lecture from the same conversation.
        return False
    return True



def _new_point_names(current_ids: set[str], modules: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for module in modules:
        for point in module.get("knowledge_points") or []:
            if str(point.get("id") or "") not in current_ids:
                names.append(str(point.get("name") or "").strip())
    return [name for name in names if name]


def relocate_new_points(
    modules: list[dict[str, Any]],
    current_ids: set[str],
    target_module_id: str,
) -> list[dict[str, Any]]:
    """Move points the preview added into the module the learner confirmed."""
    moved: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    for module in modules:
        kept = []
        for point in list(module.get("knowledge_points") or []):
            if str(point.get("id") or "") in current_ids:
                kept.append(point)
            else:
                moved.append(dict(point))
        placed.append({**module, "knowledge_points": kept})
    if not moved:
        return modules
    target = next((module for module in placed if str(module.get("id") or "") == target_module_id), None)
    if target is None:
        raise ValueError("Choose a module on this outline.")
    if len(target["knowledge_points"]) + len(moved) > _MAX_OBJECTIVES_PER_MODULE:
        raise ValueError(
            f"A module may hold at most {_MAX_OBJECTIVES_PER_MODULE} knowledge points."
        )
    target["knowledge_points"] = [*target["knowledge_points"], *moved]
    return placed


async def commit_outline_addition(
    path_id: str,
    *,
    preview_id: int,
    session_id: str,
    module_id: str,
    store: LearningStore | None = None,
) -> dict[str, Any]:
    """Save a study/review preview into the outline and note it on the outline session."""
    from deeptutor.learning.models import LearningModule
    from deeptutor.learning.service import LearningService
    from deeptutor.services.session import get_session_store

    learning = store or LearningStore()
    progress = learning.load(path_id)
    if progress is None:
        raise ValueError("Mastery topic not found")
    current_ids = {point.id for module in progress.modules for point in module.knowledge_points}
    with learning._connect() as conn:
        row = conn.execute(
            """SELECT payload_json FROM mastery_events
               WHERE id = ? AND path_id = ? AND session_id = ?
               AND event_type = 'path.modules_previewed'""",
            (int(preview_id), path_id, session_id),
        ).fetchone()
    if row is None:
        raise ValueError("Preview is unavailable in this path/session. Create a fresh preview.")
    import json

    payload = json.loads(row["payload_json"])
    modules = relocate_new_points(list(payload.get("modules") or []), current_ids, module_id)
    service = LearningService(learning)
    preview, _proposed = service.preview_module_revision(
        path_id,
        [LearningModule.model_validate(module) for module in modules],
        expected_revision=progress.version,
        session_id=session_id,
    )
    _progress, receipt = service.commit_module_revision(
        path_id,
        int(preview["preview_id"]),
        session_id=session_id,
        learner_confirmed=True,
    )
    names = _new_point_names(current_ids, modules)
    module_label = _module_name(modules, module_id) or module_id
    note = (
        f"Added {', '.join(names)} to module {module_label}."
        if names
        else f"Updated module {module_label}."
    )
    outline = await resolve_placed_session(path_id, OUTLINE, store=learning)
    await get_session_store().add_message(
        str(outline["session_id"]),
        "assistant",
        note,
        capability="mastery_path",
        metadata={"outline_addition": True, "preview_id": int(preview["preview_id"])},
    )
    return {"status": "committed", "note": note, **receipt}
