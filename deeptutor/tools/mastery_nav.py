"""Navigating the learner's mastery topics from an ordinary chat.

A mastery topic and the conversations held on it are long-lived, named things
that outlive any one chat. Before this, reaching one meant the learner did the
addressing by hand — open the atlas, recognise the topic, open it, pick or
start a session — and only *then* could they say what they wanted. "Take me
back through lesson one of the stats course" is precisely the kind of fuzzy
reference a model is good at resolving, so these tools give it the atlas and
let it hand the learner a card that lands where they meant.

Four tools, deliberately split along what the learner is asking for:

* ``mastery_topics`` — what am I studying, and how far in am I?
* ``mastery_sessions`` — which conversations exist on one topic?
* ``mastery_open_session`` — go back into one of them.
* ``mastery_new_session`` — start a fresh one on that topic.

Two properties keep them safe to mount permanently, unlike the tutoring tools
in :mod:`deeptutor.capabilities.mastery.tools`:

**They never write.** No lease is taken, no question is registered, no mastery
level moves. A chat that browses the atlas cannot disturb a course being
taught in another conversation.

**They never navigate.** The last two produce a *hand-off* — a payload the
frontend renders as a card the learner clicks. The model proposes; the learner
decides, and arrives at the real study screen (with its map, outline and
progress) rather than being tutored in a window that cannot show any of it.

Every id a hand-off carries is validated against the store first: a card
naming a lesson or a conversation that does not exist would send the learner
to an empty screen, and the model has no way to tell without being told.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from deeptutor.core.tool_protocol import (
    BaseTool,
    ToolDefinition,
    ToolParameter,
    ToolPromptHints,
    ToolResult,
)
from deeptutor.learning import navigation
from deeptutor.tools.prompting import load_prompt_hints

#: Metadata key the frontend reads a hand-off card off (see
#: ``web/lib/mastery-handoff.ts``). One key for both hand-off tools so the
#: reader does not have to know which one produced the card.
HANDOFF_META_KEY = "mastery_handoff"

MASTERY_NAV_TOOL_NAMES: tuple[str, ...] = (
    "mastery_topics",
    "mastery_sessions",
    "mastery_open_session",
    "mastery_new_session",
)


def _result(payload: dict[str, Any], *, meta_key: str, success: bool = True) -> ToolResult:
    return ToolResult(
        content=json.dumps(payload, ensure_ascii=False),
        success=success,
        metadata={meta_key: payload},
    )


def _failure(message: str) -> ToolResult:
    return ToolResult(content=message, success=False)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


async def _topic_or_error(path_id: str) -> tuple[dict[str, Any] | None, ToolResult | None]:
    """Resolve a model-supplied topic id, or the error to return instead."""
    ref = _text(path_id)
    if not ref:
        return None, _failure("path_id is required; call mastery_topics for the ids.")
    topic = await asyncio.to_thread(navigation.find_topic, ref)
    if topic is None:
        return None, _failure(
            f"No mastery topic {ref!r} exists (or it has no knowledge map yet). "
            "Call mastery_topics for the topics you can send the learner to."
        )
    return topic, None


def _module_or_error(
    topic: dict[str, Any], module_ref: str
) -> tuple[dict[str, Any] | None, ToolResult | None]:
    """Resolve an optional lesson reference against the topic's outline."""
    ref = _text(module_ref)
    if not ref:
        return None, None
    module = navigation.resolve_module(topic, ref)
    if module is None:
        names = ", ".join(
            f"{item['order']}. {item['name']} ({item['module_id']})"
            for item in topic.get("modules") or []
        )
        return None, _failure(
            f"{topic['name']} has no lesson matching {ref!r}. Its lessons are: "
            f"{names or 'none yet'}. Leave `module` out to let the tutor pick "
            "up where the mastery gate says the learner is."
        )
    return module, None


def _handoff(
    *,
    kind: str,
    topic: dict[str, Any],
    module: dict[str, Any] | None,
    opening_message: str,
    reason: str,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "path_id": topic["path_id"],
        "path_name": topic["name"],
        "emoji": topic.get("emoji") or "",
        "session_id": str(session.get("session_id") or "") if session else "",
        "session_title": str(session.get("title") or "") if session else "",
        # Carried so the card can say what state the conversation is in
        # without a second round trip. "A question is waiting in there" is the
        # difference between resuming a thread and stranding one.
        "session_messages": int(session.get("message_count") or 0) if session else 0,
        "session_updated_at": float(session.get("updated_at") or 0) if session else 0,
        "session_awaiting": bool(session.get("has_pending_question")) if session else False,
        "session_running": bool(session.get("status") == "running" or session.get("active_turn_id"))
        if session
        else False,
        "module_id": module["module_id"] if module else "",
        "module_name": module["name"] if module else "",
        "opening_message": opening_message,
        "reason": reason,
        "due_reviews": topic.get("due_reviews", 0),
        "mastered": topic.get("mastered", 0),
        "objectives": topic.get("objectives", 0),
    }


#: What the model should do once a card exists. Repeated on both hand-offs
#: because the failure it prevents is the same: a model that follows a card
#: with "click here to continue" is describing a button the learner is already
#: looking at, and a model that keeps tutoring in this chat teaches the topic
#: in the one window that cannot show its map.
_HANDOFF_INSTRUCTION = (
    "The learner now sees a card for this destination and decides whether to "
    "take it. Say in one short sentence what they will find there and why it "
    "is worth it — do not restate the link, do not promise to open it "
    "yourself, and do not start tutoring the topic here: the mastery tutor "
    "picks up on the other side, with the learner's map and progress in view."
)


class _NavTool(BaseTool):
    """Shared prompt-hint loader, matching the other built-ins.

    The per-language hints under ``tools/prompting/hints`` are what the system
    prompt's tool list quotes, and they are where the "resolve, then hand off
    — never tutor here" rule is stated in the learner's language.
    """

    def get_prompt_hints(self, language: str = "en") -> ToolPromptHints:
        return load_prompt_hints(self.name, language=language)


class MasteryTopicsTool(_NavTool):
    """The learner's mastery topics, with lesson outlines."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_topics",
            description=(
                "List the learner's Mastery Path topics — each one's name, how "
                "many objectives are mastered vs still being learned, reviews "
                "due, how many study conversations it has, and its lesson "
                "(module) outline. Use it whenever the learner refers to "
                "something they are studying ('the stats course', 'lesson 1 of "
                "the ML path', 'what am I in the middle of?'), and before any "
                "mastery_sessions / mastery_open_session / mastery_new_session "
                "call, to resolve what they said into real ids."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description=(
                        "Optional filter matched against topic names, goals and "
                        "lesson names. Leave empty to list everything."
                    ),
                    required=False,
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        payload = await asyncio.to_thread(navigation.topic_cards, query=_text(kwargs.get("query")))
        if not payload["topics"]:
            hint = (
                "No mastery topic matches that. Call mastery_topics with no "
                "query to see everything the learner has."
                if payload.get("query")
                else "This learner has no mastery topics yet. One is built on "
                "the Mastery Path screen, or inside a mastery study session."
            )
            return _result({**payload, "instruction": hint}, meta_key="mastery_topics")
        payload["instruction"] = (
            "Resolve what the learner said against these before acting: "
            "`path_id` addresses a topic, and a lesson can be named to the "
            "hand-off tools by its module_id, its name, or its number. "
            "mastery_sessions lists the conversations on one topic."
        )
        return _result(payload, meta_key="mastery_topics")


class MasterySessionsTool(_NavTool):
    """The study conversations held on one mastery topic."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_sessions",
            description=(
                "List the study conversations that exist on one Mastery Path "
                "topic — title, how many messages, when it was last active, "
                "whether the tutor is mid-answer, whether a question is "
                "waiting to be answered there, and the last thing said. Use it "
                "when the learner wants to go back to a topic and you need to "
                "know whether to resume an existing conversation or start a "
                "new one. Archived conversations are not listed."
            ),
            parameters=[
                ToolParameter(
                    name="path_id",
                    type="string",
                    description="Topic id from mastery_topics (verbatim).",
                )
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        topic, error = await _topic_or_error(kwargs.get("path_id", ""))
        if error is not None or topic is None:
            return error or _failure("path_id is required.")
        rows = await navigation.topic_sessions(topic["path_id"])
        payload = {
            "path_id": topic["path_id"],
            "path_name": topic["name"],
            **navigation.navigable_session_rows(rows),
        }
        payload["instruction"] = (
            "Reopen one with mastery_open_session(path_id, session_id), or "
            "start a fresh one with mastery_new_session(path_id). Prefer "
            "reopening when the learner is continuing that thread — the "
            "tutor's memory of it lives in the conversation — and a new one "
            "when they are coming at the topic from a different angle. A "
            "conversation with `awaiting_answer` has a question still open in "
            "it, so it is the one to reopen rather than leave stranded."
            if payload["sessions"]
            else (
                "This topic has no conversations yet. Use "
                "mastery_new_session(path_id) to hand the learner the first one."
            )
        )
        return _result(payload, meta_key="mastery_sessions")


class MasteryOpenSessionTool(_NavTool):
    """Offer the learner a way back into one existing study conversation."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_open_session",
            description=(
                "Hand the learner a card that reopens one existing study "
                "conversation on a Mastery Path topic, with an opening message "
                "already written. Use it when they want to continue something "
                "they were doing. Call mastery_sessions first for the "
                "session_id. This does not navigate anywhere by itself — the "
                "learner clicks the card — and it changes no progress."
            ),
            parameters=[
                ToolParameter(
                    name="path_id",
                    type="string",
                    description="Topic id from mastery_topics (verbatim).",
                ),
                ToolParameter(
                    name="session_id",
                    type="string",
                    description="Conversation id from mastery_sessions (verbatim).",
                ),
                ToolParameter(
                    name="opening_message",
                    type="string",
                    description=(
                        "The first message the learner will send on arrival, "
                        "written in their voice and language — e.g. 'Take me "
                        "back through lesson 1 and quiz me on it'. Name the "
                        "lesson here when they asked for one; the tutor reads "
                        "this before deciding what to teach. The learner can "
                        "edit it on the card before going."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="module",
                    type="string",
                    description=(
                        "Optional lesson to focus on — module_id, lesson name, "
                        "or its number. Shown on the card, and validated "
                        "against the topic's outline, so name it whenever the "
                        "learner did rather than only implying it in the "
                        "opening message."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description=(
                        "One short line, in the learner's language, on why this "
                        "is worth doing now. Shown as the card's headline."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        topic, error = await _topic_or_error(kwargs.get("path_id", ""))
        if error is not None or topic is None:
            return error or _failure("path_id is required.")
        session_id = _text(kwargs.get("session_id"))
        if not session_id:
            return _failure(
                "session_id is required; call mastery_sessions for this "
                "topic's conversations, or mastery_new_session to start one."
            )
        module, module_error = _module_or_error(topic, kwargs.get("module", ""))
        if module_error is not None:
            return module_error

        rows = await navigation.topic_sessions(topic["path_id"])
        session = next((row for row in rows if row["session_id"] == session_id), None)
        if session is None:
            # A conversation from another topic (or an invented id) would open
            # a screen whose tutor knows nothing about what was promised here.
            return _failure(
                f"{topic['name']} has no conversation {session_id!r}. Call "
                "mastery_sessions for its conversations, or "
                "mastery_new_session to start a fresh one."
            )

        payload = _handoff(
            kind="open",
            topic=topic,
            module=module,
            opening_message=_text(kwargs.get("opening_message")),
            reason=_text(kwargs.get("reason")),
            session=session,
        )
        payload["instruction"] = _HANDOFF_INSTRUCTION
        return _result(payload, meta_key=HANDOFF_META_KEY)


class MasteryNewSessionTool(_NavTool):
    """Offer the learner a fresh study conversation on a topic."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mastery_new_session",
            description=(
                "Hand the learner a card that starts a NEW study conversation "
                "on a Mastery Path topic, with an opening message already "
                "written. Use it when they want to work on a topic and no "
                "existing conversation fits — a new angle, a review of one "
                "lesson, or a topic with no conversations yet. The topic keeps "
                "all of its progress; only the conversation is new. This does "
                "not navigate anywhere by itself — the learner clicks the card."
            ),
            parameters=[
                ToolParameter(
                    name="path_id",
                    type="string",
                    description="Topic id from mastery_topics (verbatim).",
                ),
                ToolParameter(
                    name="opening_message",
                    type="string",
                    description=(
                        "The first message the learner will send on arrival, "
                        "written in their voice and language — e.g. 'Review "
                        "lesson 1 with me and check what I still remember'. "
                        "Name the lesson here when they asked for one; the "
                        "tutor reads this before deciding what to teach. The "
                        "learner can edit it on the card before going."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="module",
                    type="string",
                    description=(
                        "Optional lesson to start from — module_id, lesson "
                        "name, or its number. Shown on the card, and validated "
                        "against the topic's outline, so name it whenever the "
                        "learner did rather than only implying it in the "
                        "opening message."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description=(
                        "One short line, in the learner's language, on why this "
                        "is worth doing now. Shown as the card's headline."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        topic, error = await _topic_or_error(kwargs.get("path_id", ""))
        if error is not None or topic is None:
            return error or _failure("path_id is required.")
        module, module_error = _module_or_error(topic, kwargs.get("module", ""))
        if module_error is not None:
            return module_error

        payload = _handoff(
            kind="new",
            topic=topic,
            module=module,
            opening_message=_text(kwargs.get("opening_message")),
            reason=_text(kwargs.get("reason")),
        )
        payload["instruction"] = _HANDOFF_INSTRUCTION
        return _result(payload, meta_key=HANDOFF_META_KEY)


MASTERY_NAV_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    MasteryTopicsTool,
    MasterySessionsTool,
    MasteryOpenSessionTool,
    MasteryNewSessionTool,
)

__all__ = [
    "HANDOFF_META_KEY",
    "MASTERY_NAV_TOOL_NAMES",
    "MASTERY_NAV_TOOL_TYPES",
    "MasteryNewSessionTool",
    "MasteryOpenSessionTool",
    "MasterySessionsTool",
    "MasteryTopicsTool",
]
