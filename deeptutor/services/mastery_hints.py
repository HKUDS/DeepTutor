"""Ask-hints — the line the study composer shows before the learner types.

The placeholder used to be ``Ask your tutor about "<waypoint>"…``, which is the
third time that waypoint's name appears on the screen and proposes nothing. A
learner who is stuck is stuck on *what to ask*, and a template cannot help with
that because it does not know what was just said.

So the line is written, per waypoint, by the task model: one question the
learner could ask right now, in their own voice, that the tutor's last message
did not already answer.

It is a question, never an answer
---------------------------------
The single hard rule. This runs on a mastery path, where the whole product
premise is that the learner produces the understanding. A hint that leaks the
answer ("Because the router picks the tool from the intent…") removes the work
the path exists to make them do. The system prompt says so, and
:func:`_sanitize` drops anything that does not end in a question mark.

Never blocks anything
---------------------
The composer is fully usable while this is in flight — the static placeholder
stands until a hint arrives, and a failure just means it keeps standing. So the
call is made synchronously under a short timeout rather than through a
stale-while-revalidate cache: nothing on screen is waiting for it, and a hint
that arrives two seconds late is still the first thing the learner reads.

What is cached is the *result*, keyed on the conversation's own position
(:func:`_cache_key`) — the path, the waypoint, and how far the transcript has
got. Remounting the study screen, toggling the outline or switching tabs all
land on the same key and cost nothing; sending a message moves it, which is
exactly when a new question is worth writing.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import time
from typing import Any

from deeptutor.services.prompt.language import is_chinese as _is_zh
from deeptutor.services.singleflight_cache import AsyncSingleFlightTTLCache

logger = logging.getLogger(__name__)

# A placeholder is read in the half-second before typing, so it has to be
# scannable at a glance. These are the same per-language bounds the starter
# suggestions use, for the same reason: a character is not a unit of meaning.
_MAX_HINT_CHARS = {"zh": 44, "en": 110}
# Bounded because it sits on a request path. The composer shows its static
# placeholder until this returns, so an overrun costs a nicety, not a screen.
_LLM_TIMEOUT = 12.0
# How much of the transcript reaches the prompt. The last exchange is what a
# follow-up question has to avoid repeating; anything older is already
# summarized by where the waypoint sits.
_HISTORY_TURNS = 4
_MAX_MESSAGE_CHARS = 700
# Entries are tiny and keyed on transcript position, so a session generates a
# handful over its life. The cap is a leak guard, not a tuning knob.
_CACHE_LIMIT = 256
_CACHE_TTL_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class AskHint:
    """One question the learner could ask, and what it was written for."""

    hint: str
    knowledge_point_id: str
    generated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "hint": self.hint,
            "knowledge_point_id": self.knowledge_point_id,
            "generated_at": self.generated_at,
        }


_hint_cache = AsyncSingleFlightTTLCache[str, AskHint](
    limit=_CACHE_LIMIT,
    ttl_seconds=_CACHE_TTL_SECONDS,
    value_timestamp=lambda value: value.generated_at,
)
_cache = _hint_cache.values
_inflight = _hint_cache.inflight


def _cache_key(path_id: str, kp_id: str, anchor: str) -> str:
    return f"{path_id}\0{kp_id}\0{anchor}"


# ── Material ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class _Material:
    """What the model is told: where the learner is, and what was just said."""

    path_name: str
    goal: str
    module_name: str
    waypoint: str
    waypoint_type: str
    status: str
    transcript: list[tuple[str, str]]
    anchor: str

    def __bool__(self) -> bool:
        return bool(self.waypoint)


def _load_position(path_id: str) -> tuple[str, str, str, str, str, str, str]:
    """``(path_name, goal, module, waypoint, kp_type, status, kp_id)``.

    Reads the same policy the tutor and the outline read, so the hint is about
    the waypoint the screen says the learner is on rather than a second guess
    at it.
    """
    from deeptutor.learning import policy as learning_policy
    from deeptutor.learning.storage import LearningStore

    store = LearningStore()
    progress = store.load(path_id)
    if progress is None:
        return ("", "", "", "", "", "", "")
    step = learning_policy.next_objective(progress)
    kp, _module_id, module_name = learning_policy.find_knowledge_point(
        progress, step.knowledge_point_id
    )
    # The goal lives on the topic, not on the progress aggregate. Description
    # first: it is the sentence a learner wrote about what they are after,
    # whereas ``goal`` is often just the topic's own name typed twice.
    topic = store.get_topic(path_id, progress=progress)
    goal = ""
    if topic is not None:
        goal = str(topic.metadata.description or topic.metadata.goal or "")
    return (
        learning_policy.path_display_name(progress),
        goal,
        module_name,
        step.knowledge_point_name or (kp.name if kp else ""),
        step.knowledge_point_type,
        step.status or "",
        step.knowledge_point_id,
    )


async def _load_transcript(session_id: str) -> tuple[list[tuple[str, str]], str]:
    """The tail of the conversation, plus an anchor for where it has got to.

    The anchor is what the cache keys on. It is derived from the transcript
    itself rather than from a timestamp so that reopening a finished session
    reuses its hint instead of writing a new one every visit.
    """
    if not session_id:
        return ([], "")
    try:
        from deeptutor.services.session import get_session_store

        session = await get_session_store().get_session_with_messages(session_id)
    except Exception:
        logger.debug("ask-hint: session %s unreadable", session_id, exc_info=True)
        return ([], "")
    if not session:
        return ([], "")
    messages = [
        message
        for message in (session.get("messages") or [])
        if isinstance(message, dict) and str(message.get("role")) in {"user", "assistant"}
    ]
    tail: list[tuple[str, str]] = []
    for message in messages[-_HISTORY_TURNS:]:
        content = " ".join(str(message.get("content") or "").split())
        if content:
            tail.append((str(message.get("role")), content[:_MAX_MESSAGE_CHARS]))
    return (tail, f"{len(messages)}")


async def _collect(path_id: str, session_id: str) -> _Material:
    position = await asyncio.to_thread(_load_position, path_id)
    path_name, goal, module_name, waypoint, kp_type, status, kp_id = position
    transcript, anchor = await _load_transcript(session_id)
    return _Material(
        path_name=path_name,
        goal=goal,
        module_name=module_name,
        waypoint=waypoint,
        waypoint_type=kp_type,
        status=status,
        transcript=transcript,
        anchor=f"{kp_id}:{anchor}",
    )


# ── Generation ───────────────────────────────────────────────────────────


_SYSTEM_EN = """You write ONE question a learner could ask their tutor right now.

You are given where they are on a mastery path and the tail of their conversation. Write the question they would ask next if they knew what to ask.

Hard rule: you write the QUESTION, never the answer. No explanation, no hint at the answer, no "because". If your line teaches the point, it is wrong — the learner is supposed to work that out with the tutor.

Rules:
- Reply with the question alone. No quotes, no prefix, no markdown, no trailing commentary.
- First person, as the learner would type it. Under 14 words.
- End with a question mark.
- It must be about the current waypoint, and it must not ask something the tutor's last message already answered.
- Prefer the question that opens the point up: a distinction, a why, a boundary case, a "what happens if". Avoid yes/no questions and avoid asking for a definition the conversation already gave.

Good: "Why does the router need the intent and not just the query?"
Good: "What breaks if I skip the reflection step?"
Bad: "Can you explain routing?"            <- asks for a lecture, names no edge
Bad: "Routing picks the tool by intent — right?"  <- states the answer"""

_SYSTEM_ZH = """你要写出学习者此刻**可以问导师的一个问题**。

给你的是他在精通路径上的位置，以及这段对话的结尾。写出他如果知道该问什么、接下来会问的那个问题。

硬规则：你写的是**问题**，绝不是答案。不要解释、不要暗示答案、不要出现"因为"。如果你这行字把知识点讲出来了，那就是错的——那部分应该由学习者和导师一起做出来。

规则：
- 只回复那个问题本身。不要引号、不要前缀、不要 markdown、不要任何补充说明。
- 第一人称，像学习者自己打出来的。不超过 25 个字。
- 以问号结尾。
- 必须是关于当前这个知识点的，且不能问导师上一条消息已经回答过的东西。
- 优先选那种能把问题打开的：一个区别、一个为什么、一个边界情况、一个"如果……会怎样"。避免是非题，也避免去问对话里已经给过的定义。

好："路由为什么需要意图，而不是只看查询本身？"
好："如果跳过反思那一步，会在哪里出问题？"
差："能讲讲路由吗？"              <- 要的是一段讲解，没点到任何边界
差："路由是按意图选工具，对吧？"  <- 把答案说出来了"""


def _render(material: _Material, zh: bool) -> str:
    lines: list[str] = []
    if zh:
        lines.append(f"# 学习主题\n{material.path_name}")
        if material.goal:
            lines.append(f"# 学习目标\n{material.goal}")
        where = f"# 当前知识点\n{material.waypoint}"
        if material.module_name:
            where += f"（所属模块：{material.module_name}）"
        if material.waypoint_type:
            where += f"\n类型：{material.waypoint_type}"
        if material.status:
            where += f"\n掌握状态：{material.status}"
        lines.append(where)
    else:
        lines.append(f"# Topic\n{material.path_name}")
        if material.goal:
            lines.append(f"# Goal\n{material.goal}")
        where = f"# Current waypoint\n{material.waypoint}"
        if material.module_name:
            where += f" (module: {material.module_name})"
        if material.waypoint_type:
            where += f"\nType: {material.waypoint_type}"
        if material.status:
            where += f"\nStatus: {material.status}"
        lines.append(where)

    if material.transcript:
        speaker = {"user": "学习者" if zh else "Learner", "assistant": "导师" if zh else "Tutor"}
        body = "\n".join(
            f"[{speaker.get(role, role)}] {text}" for role, text in material.transcript
        )
        lines.append(("# 对话结尾\n" if zh else "# End of the conversation\n") + body)
    else:
        lines.append(
            "# 对话结尾\n（还没开始，这是他要问的第一个问题。）"
            if zh
            else "# End of the conversation\n(Nothing yet — this is their opening question.)"
        )

    lines.append("\n请写出那一个问题。" if zh else "\nWrite that one question.")
    return "\n\n".join(lines)


def _sanitize(raw: str, language: str) -> str:
    """One clean question, or nothing.

    The question mark is a real check, not tidying: it is the cheapest reliable
    signal that the model wrote a question rather than the answer it was told
    not to write.
    """
    text = " ".join(str(raw or "").split())
    # Models reach for a fence or a leading bullet even when told not to.
    for fence in ("```", "「", "」", '"', "'", "“", "”", "‘", "’"):
        text = text.replace(fence, "")
    text = text.lstrip("-•*# ").strip()
    if not text:
        return ""
    # A model that ignored "the question alone" usually answers first and asks
    # last; keep the final sentence rather than discarding a usable question.
    if "\n" in text:
        text = text.split("\n")[-1].strip()
    if not text.endswith(("?", "？")):
        return ""
    limit = _MAX_HINT_CHARS["zh"] if _is_zh(language) else _MAX_HINT_CHARS["en"]
    if len(text) > limit:
        return ""
    return text


async def _generate(path_id: str, session_id: str, key_hint: str) -> AskHint:
    material = await _collect(path_id, session_id)
    empty = AskHint(hint="", knowledge_point_id=key_hint, generated_at=time.time())
    if not material:
        return empty

    from deeptutor.services.settings.interface_settings import get_response_language

    try:
        language = get_response_language(default="en")
    except Exception:
        logger.debug("ask-hint: response language unreadable", exc_info=True)
        language = "en"
    zh = _is_zh(language)

    try:
        from deeptutor.services.llm import complete
        from deeptutor.services.model_selection.tasks import task_llm_scope

        # Same call class as titles and starter lines — short, frequent, and
        # nobody asked for it — so it runs on the task model when one is set.
        with task_llm_scope():
            raw = await asyncio.wait_for(
                complete(
                    prompt=_render(material, zh),
                    system_prompt=_SYSTEM_ZH if zh else _SYSTEM_EN,
                    temperature=0.7,
                    max_tokens=120,
                    max_retries=0,
                ),
                timeout=_LLM_TIMEOUT,
            )
    except asyncio.TimeoutError:
        logger.debug("ask-hint LLM call timed out")
        return empty
    except Exception:
        logger.debug("ask-hint LLM call failed", exc_info=True)
        return empty

    return AskHint(
        hint=_sanitize(raw, language),
        knowledge_point_id=material.anchor.split(":", 1)[0],
        generated_at=time.time(),
    )


# ── Public API ───────────────────────────────────────────────────────────


async def get_ask_hint(path_id: str, session_id: str = "") -> dict[str, Any]:
    """The question to offer under the composer. ``hint`` is "" when there is none.

    An empty hint is a real answer, not an error: the composer keeps its static
    placeholder, which is what it showed before this existed.
    """
    material = await _collect(path_id, session_id)
    if not material:
        return AskHint(hint="", knowledge_point_id="", generated_at=time.time()).to_dict()

    key = _cache_key(path_id, material.anchor, session_id)
    try:
        value = await _hint_cache.get_or_create(
            key,
            lambda: _generate(path_id, session_id, material.anchor),
            cache_when=lambda item: bool(item.hint),
        )
    except Exception:
        logger.debug("ask-hint generation failed", exc_info=True)
        return AskHint(hint="", knowledge_point_id="", generated_at=time.time()).to_dict()
    return value.to_dict()


__all__ = ["AskHint", "get_ask_hint"]
