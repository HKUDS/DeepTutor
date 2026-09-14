"""Read, organise, and record the learner's question bank from the chat agent.

The question bank is the ``notebook_entries`` table behind
``/space/questions``: every quiz question the learner has answered, in
chat, in a quiz, or on a mastery path. It is a *different* store from
the notebooks that :mod:`deeptutor.tools.write_note` writes to — notes
are prose the learner keeps, bank entries are graded questions with a
correct answer. Before this tool existed the agent had no way to touch
the bank, so "file my wrong answers into my new question set" landed in
a notebook instead: the only writable surface it could see.

One tool, six actions, because the useful sequence is short and always
the same — look, then file:

* ``overview``  — counts + the existing category names (one call, no ids
  needed; the natural first step).
* ``list``      — entries under a filter, each prefixed with the id the
  other actions consume.
* ``organize``  — file entries into a category **by name**, creating it
  when it does not exist yet. Name-addressed on purpose: the learner
  says "my mistakes set", not "category 7", and a two-step
  create-then-file is one more place for the model to drop the ball.
* ``unfile``    — take entries back out of a category.
* ``bookmark``  — star / unstar entries for later review.
* ``record``    — write one wrong question the learner just owned up to
  in conversation (source ``partner_chat``). Partner turns are the main
  caller (#1244): the tutor coaches a photographed homework mistake and
  the question lands in the bank the family reviews, instead of dying
  in the chat transcript.

Every action is dependency-injected with ``store`` so tests never touch
a real database, and every failure returns ``ok=False`` with a sentence
the model can act on rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

ACTIONS = ("overview", "list", "organize", "unfile", "bookmark", "record")

FILTERS = ("all", "wrong", "bookmarked", "uncategorized")

# Ceilings. The bank can hold thousands of rows; a listing is a working
# set for one decision, not a dump. Both are echoed in the rendered text
# when they bite so the model knows it is seeing a slice.
DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100
MAX_ENTRY_IDS = 200
MAX_QUESTION_PREVIEW = 160
MAX_ANSWER_PREVIEW = 60
MAX_CATEGORY_NAME = 100


@dataclass(frozen=True)
class QuestionBankOutcome:
    """Result of one ``question_bank`` invocation."""

    ok: bool
    action: str = ""
    text: str = ""
    error: str = ""
    # Structured echo for the frontend; deliberately small.
    summary: dict[str, Any] = field(default_factory=dict)


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _coerce_ids(raw: Any) -> tuple[list[int], list[str]]:
    """Parse the model's ``entry_ids`` into ints, reporting what was junk.

    Models hand back ``[3, "4", "id-5"]`` often enough that silently
    dropping the bad ones would make a partial file look complete.
    """
    if raw is None:
        return [], []
    if isinstance(raw, (int, str)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return [], [str(raw)]
    ids: list[int] = []
    rejected: list[str] = []
    for item in raw:
        try:
            value = int(str(item).strip())
        except (TypeError, ValueError):
            rejected.append(str(item))
            continue
        if value <= 0:
            rejected.append(str(item))
            continue
        if value not in ids:
            ids.append(value)
    return ids[:MAX_ENTRY_IDS], rejected


def _render_entry(entry: dict[str, Any]) -> str:
    mark = "✓" if entry.get("is_correct") else "✗"
    star = " ★" if entry.get("bookmarked") else ""
    line = f"- [{entry.get('id')}] {mark}{star} {_truncate(entry.get('question', ''), MAX_QUESTION_PREVIEW)}"
    given = _truncate(entry.get("user_answer", ""), MAX_ANSWER_PREVIEW)
    expected = _truncate(entry.get("correct_answer", ""), MAX_ANSWER_PREVIEW)
    if given or expected:
        line += f"\n    answered: {given or '—'} | correct: {expected or '—'}"
    cats = [str(c.get("name", "")) for c in (entry.get("categories") or []) if c.get("name")]
    line += f"\n    filed in: {', '.join(cats)}" if cats else "\n    filed in: (nothing yet)"
    return line


def _render_categories(categories: list[dict[str, Any]]) -> str:
    if not categories:
        return "(no categories yet — `organize` creates one by name)"
    return ", ".join(f"{c.get('name')} ({c.get('entry_count', 0)})" for c in categories)


async def _resolve_store(store: Any) -> Any:
    if store is not None:
        return store
    target_paths = _partner_bank_paths()
    if target_paths is not None:
        from deeptutor.services.session import get_sqlite_session_store_for

        return get_sqlite_session_store_for(target_paths)
    from deeptutor.services.session import get_sqlite_session_store

    return get_sqlite_session_store()


def _partner_bank_paths() -> Any | None:
    """Path service of the bank a partner turn should read and record into.

    Partner turns execute inside the partner's synthetic user scope, where the
    default store would be the partner's own — a bank nobody can see in the
    web UI. The partner turn context exposes the scope the family actually
    browses (the admin's for IM/admin turns, the assigned learner's own for
    assigned ones); ``None`` outside partner turns, so product chat keeps
    resolving the current user's store.
    """
    try:
        from deeptutor.services.partners.interaction import get_partner_turn_context

        context = get_partner_turn_context()
    except Exception:
        return None
    if context is None:
        return None
    return context.shared_memory


async def _overview(store: Any) -> QuestionBankOutcome:
    stats = await store.question_bank_stats()
    categories = await store.list_categories()
    if not stats.get("total"):
        return QuestionBankOutcome(
            ok=True,
            action="overview",
            text="The question bank is empty — the learner has not answered any quiz questions yet.",
            summary={"stats": stats, "categories": []},
        )
    text = (
        f"Question bank: {stats['total']} questions "
        f"({stats['wrong']} answered wrong, {stats['bookmarked']} bookmarked, "
        f"{stats['uncategorized']} not filed in any category).\n"
        f"Categories: {_render_categories(categories)}\n\n"
        "Next: `list` the entries you want (filter='wrong' or 'uncategorized'), "
        "then `organize` them into a category by name."
    )
    return QuestionBankOutcome(
        ok=True,
        action="overview",
        text=text,
        summary={"stats": stats, "categories": categories},
    )


async def _list(
    store: Any,
    *,
    filter_mode: str,
    category: str,
    search: str,
    limit: int,
) -> QuestionBankOutcome:
    mode = (filter_mode or "all").strip().lower()
    if mode not in FILTERS:
        return QuestionBankOutcome(
            ok=False,
            action="list",
            error=f"Unknown filter {filter_mode!r}. Use one of: {', '.join(FILTERS)}.",
        )

    category_id: int | None = None
    wanted = (category or "").strip()
    if wanted:
        match = await store.find_category_by_name(wanted)
        if match is None:
            categories = await store.list_categories()
            return QuestionBankOutcome(
                ok=False,
                action="list",
                error=(
                    f"No category named {wanted!r}. Existing: {_render_categories(categories)}."
                ),
            )
        category_id = int(match["id"])

    capped = max(1, min(int(limit or DEFAULT_LIST_LIMIT), MAX_LIST_LIMIT))
    result = await store.list_notebook_entries(
        category_id=category_id,
        uncategorized=mode == "uncategorized",
        bookmarked=True if mode == "bookmarked" else None,
        is_correct=False if mode == "wrong" else None,
        search=search or "",
        limit=capped,
    )
    items = list(result.get("items") or [])
    total = int(result.get("total") or 0)
    if not items:
        return QuestionBankOutcome(
            ok=True,
            action="list",
            text="No question-bank entries match that filter.",
            summary={"count": 0, "total": 0, "filter": mode},
        )

    header = f"Question bank — {mode}"
    if wanted:
        header += f" in category '{wanted}'"
    if search:
        header += f" matching '{search}'"
    header += f" ({len(items)} of {total}):"
    lines = [header, ""]
    lines.extend(_render_entry(entry) for entry in items)
    if total > len(items):
        lines.append(f"\n... {total - len(items)} more; raise `limit` or narrow with `search`.")
    lines.append(
        "\nThe number in [brackets] is the entry id — pass those ids to "
        "`organize` to file them into a category."
    )
    return QuestionBankOutcome(
        ok=True,
        action="list",
        text="\n".join(lines),
        summary={
            "count": len(items),
            "total": total,
            "filter": mode,
            "entry_ids": [int(i["id"]) for i in items],
        },
    )


async def _resolve_or_create_category(store: Any, name: str) -> tuple[dict[str, Any], bool]:
    """Return ``(category, created)`` for a display name.

    Reuses an existing name case-insensitively so "Wrong Answers" and
    "wrong answers" cannot become two piles of the same thing.
    """
    existing = await store.find_category_by_name(name)
    if existing is not None:
        return existing, False
    created = await store.create_category(name)
    return created, True


async def _organize(
    store: Any, *, entry_ids: Any, category: str, link: bool
) -> QuestionBankOutcome:
    action = "organize" if link else "unfile"
    name = (category or "").strip()[:MAX_CATEGORY_NAME]
    if not name:
        return QuestionBankOutcome(
            ok=False,
            action=action,
            error="`category` is required — the name of the set to file these questions under.",
        )
    ids, rejected = _coerce_ids(entry_ids)
    if not ids:
        return QuestionBankOutcome(
            ok=False,
            action=action,
            error=(
                "`entry_ids` must contain at least one numeric entry id from a "
                "`list` call (the number in [brackets])."
            ),
        )

    if link:
        category_row, created = await _resolve_or_create_category(store, name)
    else:
        match = await store.find_category_by_name(name)
        if match is None:
            return QuestionBankOutcome(
                ok=False,
                action=action,
                error=f"No category named {name!r} to remove entries from.",
            )
        category_row, created = match, False

    changed = await store.link_entries_to_category(ids, int(category_row["id"]), link=link)
    verb = "filed into" if link else "removed from"
    parts = [f"{changed} of {len(ids)} question(s) {verb} '{category_row['name']}'."]
    if created:
        parts.append("The category did not exist and was created.")
    if changed < len(ids) and link:
        parts.append(
            f"{len(ids) - changed} skipped (already filed there, or no longer in the bank)."
        )
    if rejected:
        parts.append(f"Ignored non-numeric ids: {', '.join(rejected[:5])}.")
    parts.append("The learner sees this immediately under Learning Space → Question Bank.")
    return QuestionBankOutcome(
        ok=True,
        action=action,
        text=" ".join(parts),
        summary={
            "changed": changed,
            "requested": len(ids),
            "category": category_row["name"],
            "category_id": int(category_row["id"]),
            "created_category": created,
            "link": link,
        },
    )


async def _bookmark(store: Any, *, entry_ids: Any, bookmarked: bool) -> QuestionBankOutcome:
    ids, rejected = _coerce_ids(entry_ids)
    if not ids:
        return QuestionBankOutcome(
            ok=False,
            action="bookmark",
            error="`entry_ids` must contain at least one numeric entry id from a `list` call.",
        )
    updated = 0
    for entry_id in ids:
        try:
            if await store.update_notebook_entry(entry_id, {"bookmarked": bookmarked}):
                updated += 1
        except Exception:
            logger.warning("question_bank: bookmark failed for entry %s", entry_id, exc_info=True)
    verb = "bookmarked" if bookmarked else "un-bookmarked"
    text = f"{updated} of {len(ids)} question(s) {verb}."
    if rejected:
        text += f" Ignored non-numeric ids: {', '.join(rejected[:5])}."
    return QuestionBankOutcome(
        ok=updated > 0,
        action="bookmark",
        text=text,
        error="" if updated else "No matching entries were updated.",
        summary={"updated": updated, "requested": len(ids), "bookmarked": bookmarked},
    )


MAX_RECORD_QUESTION = 4000
MAX_RECORD_FIELD = 2000


def _record_question_id(question: str) -> str:
    """Stable content hash so re-recording the same mistake updates the row
    (the store dedups on ``session_id + turn_id + question_id``) instead of
    piling up duplicates each time the learner revisits it."""
    normalized = " ".join(question.split()).casefold()
    return "pq_" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def _partner_record_session() -> tuple[str, str]:
    """Stable ``(session_id, title)`` naming one partner pairing's mistakes.

    Deterministic per partner + partner-of pairing so every recorded mistake
    lands in the same notebook session the family can review as one list.
    """
    partner_id = ""
    actor_id = ""
    name = ""
    try:
        from deeptutor.services.partners.interaction import get_partner_turn_context

        context = get_partner_turn_context()
    except Exception:
        context = None
    if context is not None:
        partner_id = str(getattr(context, "partner_id", "") or "")
        actor_id = str(getattr(context, "actor_id", "") or "")
        name = str(getattr(context, "partner_name", "") or "").strip()
    session_id = f"partner-notebook:{partner_id or 'unknown'}:{actor_id or 'admin'}"
    if name:
        title = f"{name} (Partner)"
    elif partner_id:
        title = f"Partner {partner_id} notebook"
    else:
        title = "Partner notebook"
    return session_id, title


async def _record(
    store: Any,
    *,
    question: str,
    user_answer: str,
    correct_answer: str,
    explanation: str,
    question_type: str,
    is_correct: bool,
    category: str,
) -> QuestionBankOutcome:
    text = " ".join(str(question or "").split())
    if not text:
        return QuestionBankOutcome(
            ok=False,
            action="record",
            error="`question` is required — the problem as the learner wrote or photographed it.",
        )
    session_id, session_title = _partner_record_session()
    try:
        await store.ensure_notebook_session(session_id, session_title)
    except Exception:
        logger.warning("question_bank: could not ensure a notebook session", exc_info=True)
        return QuestionBankOutcome(
            ok=False,
            action="record",
            error="The question bank is not available in this conversation; nothing was recorded.",
        )
    item = {
        "question_id": _record_question_id(text),
        "question": text[:MAX_RECORD_QUESTION],
        "question_type": str(question_type or "").strip()[:100],
        "correct_answer": _truncate(correct_answer, MAX_RECORD_FIELD),
        "explanation": _truncate(explanation, MAX_RECORD_FIELD),
        "user_answer": _truncate(user_answer, MAX_RECORD_FIELD),
        "source": "partner_chat",
        "is_correct": bool(is_correct),
    }
    upserted = await store.upsert_notebook_entries(session_id, [item])
    if not upserted:
        return QuestionBankOutcome(
            ok=False,
            action="record",
            error="The bank rejected the entry; nothing was recorded.",
        )
    parts = [f"Recorded 1 wrong question into the bank ({session_title})."]
    summary: dict[str, Any] = {
        "session_id": session_id,
        "question_id": item["question_id"],
        "source": "partner_chat",
    }
    name = (category or "").strip()[:MAX_CATEGORY_NAME]
    if name:
        entry = await store.find_notebook_entry(session_id, item["question_id"])
        entry_id = int(entry["id"]) if entry and entry.get("id") is not None else None
        if entry_id is None:
            parts.append("Could not file it into a category (entry not found after recording).")
        else:
            category_row, created = await _resolve_or_create_category(store, name)
            await store.link_entries_to_category([entry_id], int(category_row["id"]), link=True)
            parts.append(f"Filed under '{category_row['name']}'.")
            if created:
                parts.append("The category did not exist and was created.")
            summary["category"] = category_row["name"]
    parts.append("The learner sees it immediately under Learning Space → Question Bank.")
    return QuestionBankOutcome(ok=True, action="record", text=" ".join(parts), summary=summary)


async def run_question_bank(
    *,
    action: str = "overview",
    filter_mode: str = "all",
    category: str = "",
    search: str = "",
    entry_ids: Any = None,
    bookmarked: bool = True,
    limit: int = DEFAULT_LIST_LIMIT,
    question: str = "",
    user_answer: str = "",
    correct_answer: str = "",
    explanation: str = "",
    question_type: str = "",
    is_correct: bool = False,
    store: Any = None,
) -> QuestionBankOutcome:
    """Run one question-bank action. Never raises — errors come back typed."""
    verb = (action or "overview").strip().lower()
    if verb not in ACTIONS:
        return QuestionBankOutcome(
            ok=False,
            action=verb,
            error=f"Unknown action {action!r}. Use one of: {', '.join(ACTIONS)}.",
        )
    try:
        resolved = await _resolve_store(store)
        if verb == "overview":
            return await _overview(resolved)
        if verb == "list":
            return await _list(
                resolved,
                filter_mode=filter_mode,
                category=category,
                search=search,
                limit=limit,
            )
        if verb in {"organize", "unfile"}:
            return await _organize(
                resolved,
                entry_ids=entry_ids,
                category=category,
                link=verb == "organize",
            )
        if verb == "record":
            return await _record(
                resolved,
                question=question,
                user_answer=user_answer,
                correct_answer=correct_answer,
                explanation=explanation,
                question_type=question_type,
                is_correct=is_correct,
                category=category,
            )
        return await _bookmark(resolved, entry_ids=entry_ids, bookmarked=bookmarked)
    except Exception as exc:
        logger.warning("question_bank action %s failed", verb, exc_info=True)
        return QuestionBankOutcome(ok=False, action=verb, error=f"Question bank error: {exc}")


__all__ = [
    "ACTIONS",
    "FILTERS",
    "QuestionBankOutcome",
    "run_question_bank",
]
