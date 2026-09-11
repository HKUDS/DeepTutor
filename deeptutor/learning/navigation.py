"""Reading the mastery atlas from outside a tutoring turn.

A mastery topic outlives every conversation held on it, so "what am I
studying, and where did I leave it?" is a question that has to be answerable
from anywhere — an ordinary chat included. This module is the read-only half
of that: it walks the store for the atlas (topics, their module outlines, the
conversations held on each) and returns plain dictionaries.

It is deliberately separate from :mod:`deeptutor.capabilities.mastery.tools`.
Those tools *teach* — they take the path lease, register questions and move a
gate, and only mount when a tutoring turn is live. Nothing here touches a
lease, a question or a mastery level; the same walk therefore serves the REST
atlas (:mod:`deeptutor.api.routers.mastery_path`) and the navigation tools
chat mounts permanently, without either one importing the tutor.

Payload sizes are capped here rather than at each call site: a learner with a
semester of topics would otherwise hand the model a few thousand tokens of
outline it did not ask for. Every cap reports what it clipped, so a truncated
answer is never mistaken for a complete one.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from deeptutor.learning import policy
from deeptutor.learning.storage import LearningStore

#: Topics returned by one atlas read, newest activity first.
TOPIC_LIMIT = 20
#: Module outline rows per topic. Enough to recognise "the first lesson".
MODULE_LIMIT = 14
#: Conversations returned for one topic, most recently active first.
SESSION_LIMIT = 20
#: How much of a conversation's last message rides along as a reminder.
LAST_MESSAGE_CHARS = 160


def learner_has_topics() -> bool:
    """Whether this learner has any mastery topic worth navigating to.

    The mount gate for chat's navigation tools, so it runs on every ordinary
    chat turn. Probing the database file before opening a store keeps that
    gate from creating one for a learner who has never used a mastery path,
    and it fails closed: a tool with nothing to list is worse than a tool the
    learner does not see.
    """
    try:
        if not LearningStore.default_db_path().exists():
            return False
        return LearningStore().has_active_topics()
    except Exception:
        return False


def _clip(rows: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    """Return ``rows`` capped at ``limit`` plus how many were dropped."""
    if len(rows) <= limit:
        return rows, 0
    return rows[:limit], len(rows) - limit


def _module_outline(summary: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """The module list without its objectives.

    ``map_summary`` nests every objective under its module because the tutor
    needs them to pick what to teach. A navigator only needs the lesson's
    name, its position and how much of it is cleared — the objectives are two
    orders of magnitude more text for a question ("take me back to lesson 1")
    that is answered by the name alone.
    """
    rows = [
        {
            "module_id": module["id"],
            "name": module["name"],
            "order": module["order"],
            "mastered": module["mastered"],
            "objectives": module["total"],
        }
        for module in summary.get("modules", [])
    ]
    return _clip(rows, MODULE_LIMIT)


def topic_cards(*, query: str = "", store: LearningStore | None = None) -> dict[str, Any]:
    """Every active topic the learner owns, with its module outline.

    ``query`` is matched against the topic's name, its goal and its module
    names, so "the stats course" and "the one with the Bayes lesson" both
    land. Matching happens here rather than in the model's head because the
    full atlas is what would otherwise have to travel to it.

    Only topics carrying topic metadata are listed: an ad-hoc path created
    inside a chat (keyed by session id, no name, no map) is a scratchpad, not
    somewhere to send a learner back to.
    """
    store = store or LearningStore()
    snapshots = store.list_topic_snapshots(status="active")
    needle = " ".join(str(query or "").split()).casefold()

    cards: list[dict[str, Any]] = []
    for progress, topic, session_count, active_interaction in snapshots:
        summary = policy.map_summary(progress)
        counts = summary["counts"]
        if counts["total"] <= 0:
            # Built as a topic but never given a map: there is nothing to
            # study there yet, so offering it as a destination misleads.
            continue
        modules, modules_clipped = _module_outline(summary)
        haystack = " ".join(
            [
                summary["name"],
                topic.metadata.goal,
                *(module["name"] for module in modules),
            ]
        ).casefold()
        if needle and needle not in haystack:
            continue
        cards.append(
            {
                "path_id": progress.book_id,
                "name": summary["name"],
                "emoji": topic.metadata.emoji,
                "goal": topic.metadata.goal,
                "objectives": counts["total"],
                "mastered": counts["mastered"],
                "learning": counts["learning"],
                "not_started": counts["new"],
                "due_reviews": summary["due_reviews"],
                "complete": summary["complete"],
                "sessions": session_count,
                "open_question": active_interaction is not None,
                "updated_at": progress.updated_at,
                "modules": modules,
                **({"modules_omitted": modules_clipped} if modules_clipped else {}),
            }
        )

    cards, clipped = _clip(cards, TOPIC_LIMIT)
    return {
        "topics": cards,
        "total_topics": len(cards) + clipped,
        **({"topics_omitted": clipped} if clipped else {}),
        **({"query": query} if query else {}),
    }


def find_topic(path_id: str, *, store: LearningStore | None = None) -> dict[str, Any] | None:
    """One topic's card, or ``None`` when nothing is stored under *path_id*.

    Used to validate a model-supplied id before it becomes a hand-off the
    learner can click: a card pointing at a path that does not exist would
    open an empty screen, and the model has no way to tell the difference
    without asking.
    """
    store = store or LearningStore()
    try:
        progress = store.load(path_id) if store.exists(path_id) else None
    except ValueError:
        # An id that cannot even be a path id (separators, traversal).
        return None
    if progress is None:
        return None
    summary = policy.map_summary(progress)
    if summary["counts"]["total"] <= 0:
        return None
    topic = store.get_topic(path_id, progress=progress)
    modules, modules_clipped = _module_outline(summary)
    return {
        "path_id": progress.book_id,
        "name": summary["name"],
        "emoji": topic.metadata.emoji if topic is not None else "",
        "goal": topic.metadata.goal if topic is not None else "",
        "objectives": summary["counts"]["total"],
        "mastered": summary["counts"]["mastered"],
        "due_reviews": summary["due_reviews"],
        "complete": summary["complete"],
        "modules": modules,
        **({"modules_omitted": modules_clipped} if modules_clipped else {}),
    }


#: Chinese numerals a learner counts lessons with. Only 1-10: past that they
#: say the digits, and a bare "十一" is rare enough that a miss (which asks
#: the model again) beats guessing.
_CN_NUMERALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _position_in(ref: str) -> int | None:
    """The lesson number inside a phrase, or ``None``.

    "lesson 1", "第一课", "Module 2", "2" — the model relays the learner's own
    phrasing, which is rarely a bare integer. Any digit run in the phrase
    wins; failing that, a single Chinese numeral does.
    """
    digits = re.search(r"\d+", ref)
    if digits:
        return int(digits.group())
    found = [_CN_NUMERALS[char] for char in ref if char in _CN_NUMERALS]
    return found[0] if len(found) == 1 else None


def resolve_module(topic: dict[str, Any], module_ref: str) -> dict[str, Any] | None:
    """Match a module by id, by name, or by the position named in a phrase.

    A learner says "lesson 1", "第一课" or "the regression chapter"; a model
    relays whichever of those it holds. Accepting all of them here keeps that
    translation out of the tools and out of the prompt. Returning ``None`` on
    a miss is the point of the function: it is what stops a hand-off card from
    advertising a lesson the topic does not have.

    Name matching runs before position, so a topic whose lesson is literally
    called "Chapter 2" is not silently swapped for the second one.
    """
    ref = " ".join(str(module_ref or "").split())
    if not ref:
        return None
    modules = topic.get("modules") or []
    folded = ref.casefold()
    for module in modules:
        if str(module["module_id"]).casefold() == folded:
            return module
    for module in modules:
        if str(module["name"]).casefold() == folded:
            return module
    for module in modules:
        name = str(module["name"]).casefold()
        if folded in name or (len(folded) > 3 and name in folded):
            return module
    position = _position_in(ref)
    if position is not None:
        for module in modules:
            if int(module["order"]) == position:
                return module
        if 1 <= position <= len(modules):
            return modules[position - 1]
    return None


async def topic_sessions(
    path_id: str, *, store: LearningStore | None = None
) -> list[dict[str, Any]]:
    """The conversations held on one topic, most recently active first.

    Two stores answer this together: the mastery store knows which sessions
    are bound to the path (and which one holds its open question), the session
    store knows what each conversation is called and when it last moved.
    Neither is authoritative alone, which is why this lives here instead of in
    either one.

    ``store`` lets a caller hand in the mastery store it already resolved,
    rather than this walk constructing a second one against the default
    workspace root.
    """
    learning_store = store or LearningStore()
    session_ids = await asyncio.to_thread(learning_store.list_session_ids, path_id)
    if not session_ids:
        return []
    active_interaction = await asyncio.to_thread(
        learning_store.get_active_interaction,
        path_id,
    )
    pending_session_id = active_interaction.session_id if active_interaction else ""

    from deeptutor.services.session import get_session_store

    summaries = await get_session_store().get_session_summaries(session_ids)
    rows: list[dict[str, Any]] = []
    for session in summaries:
        session_id = str(session.get("session_id") or session.get("id") or "")
        preferences = session.get("preferences") or {}
        last_message = str(session.get("last_message") or "").strip()
        rows.append(
            {
                "session_id": session_id,
                "title": session.get("title") or "",
                "created_at": session.get("created_at") or 0,
                "updated_at": session.get("updated_at") or 0,
                "status": session.get("status") or "idle",
                "active_turn_id": session.get("active_turn_id") or "",
                "message_count": int(session.get("message_count") or 0),
                "last_message": last_message[:240],
                "pinned": bool(preferences.get("pinned")),
                "archived": bool(preferences.get("archived")),
                "has_pending_question": bool(
                    pending_session_id and pending_session_id == session_id
                ),
            }
        )
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    return rows


def navigable_session_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Trim the REST session shape down to what a navigator needs.

    The atlas screen renders pins, archive state and creation dates; a model
    choosing which conversation to reopen needs the title, how alive it is,
    and a reminder of what was last said there. Archived conversations are
    dropped rather than listed and explained — the learner archived them to
    stop being offered them.
    """
    live = [row for row in rows if not row["archived"]]
    capped, clipped = _clip(live, SESSION_LIMIT)
    return {
        "sessions": [
            {
                "session_id": row["session_id"],
                "title": row["title"],
                "messages": row["message_count"],
                "updated_at": row["updated_at"],
                "running": bool(row["status"] == "running" or row["active_turn_id"]),
                "awaiting_answer": row["has_pending_question"],
                "last_message": row["last_message"][:LAST_MESSAGE_CHARS],
            }
            for row in capped
        ],
        "total_sessions": len(live),
        **({"sessions_omitted": clipped} if clipped else {}),
    }


__all__ = [
    "LAST_MESSAGE_CHARS",
    "MODULE_LIMIT",
    "SESSION_LIMIT",
    "TOPIC_LIMIT",
    "find_topic",
    "learner_has_topics",
    "navigable_session_rows",
    "resolve_module",
    "topic_cards",
    "topic_sessions",
]
