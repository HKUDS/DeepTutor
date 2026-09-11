"""General ask-hints — the line the home composer offers before the user types.

The mastery and reading composers each show a hint scoped to something fixed
in view — a waypoint, a page. The home chat has no such anchor: it can be
about anything, so there is nothing to write "a question about" the way the
other two do. What it *does* have is the conversation itself, and that is
enough to predict the one thing worth offering — the line the user is likely
to type next, given what the assistant just said.

That is deliberately not required to be a question. "继续" (keep going), "换
一种更简洁的说法" (say it more simply), a straight follow-up question — any of
these is a plausible next turn, and demanding a question mark the way the
mastery hint does would reject most of them. The one hard rule carried over is
voice: this writes what the *user* would type, never a description of it
("you could ask...") and never the assistant's own voice.

Nothing to predict from is a real state, not a failure
-------------------------------------------------------
A conversation with no messages yet has nothing for this to work from — that
opening-screen case is already served by :mod:`deeptutor.services.suggestions`
(the starter chips), which draws on the learner's broader history instead of
a transcript that does not exist yet. So this returns an empty hint, with no
LLM call, until there is at least one exchange to continue.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
import time
from typing import Any

from deeptutor.services.prompt.language import is_chinese as _is_zh
from deeptutor.services.singleflight_cache import AsyncSingleFlightTTLCache

logger = logging.getLogger(__name__)

_MAX_HINT_CHARS = {"zh": 44, "en": 110}
_LLM_TIMEOUT = 12.0
_HISTORY_TURNS = 4
_MAX_MESSAGE_CHARS = 700
_CACHE_LIMIT = 256
_CACHE_TTL_SECONDS = 30 * 60


@dataclass(frozen=True, slots=True)
class AskHint:
    """One predicted user line, and what it was written for."""

    hint: str
    session_id: str
    generated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "hint": self.hint,
            "session_id": self.session_id,
            "generated_at": self.generated_at,
        }


_hint_cache = AsyncSingleFlightTTLCache[str, AskHint](
    limit=_CACHE_LIMIT,
    ttl_seconds=_CACHE_TTL_SECONDS,
    value_timestamp=lambda value: value.generated_at,
)
# Compatibility views for test/setup code that clears service-local state.
_cache = _hint_cache.values
_inflight = _hint_cache.inflight


def _cache_key(session_id: str, transcript_length: int) -> str:
    return f"{session_id}\0{transcript_length}"


# -- Material -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Material:
    transcript: list[tuple[str, str]]
    transcript_length: int

    def __bool__(self) -> bool:
        # Nothing to continue without at least one real exchange.
        return bool(self.transcript)

    @property
    def last_user_message(self) -> str:
        for role, content in reversed(self.transcript):
            if role == "user":
                return content
        return ""


async def _collect(session_id: str) -> _Material:
    if not session_id:
        return _Material(transcript=[], transcript_length=0)
    try:
        from deeptutor.services.session import get_session_store

        session = await get_session_store().get_session_with_messages(session_id)
    except Exception:
        logger.debug("chat ask-hint: session %s unreadable", session_id, exc_info=True)
        return _Material(transcript=[], transcript_length=0)
    if not session:
        return _Material(transcript=[], transcript_length=0)

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
    return _Material(transcript=tail, transcript_length=len(messages))


# -- Generation ---------------------------------------------------------------


_SYSTEM_EN = """You predict ONE line the user is likely to type next into the chat box — this is the composer's placeholder text, read before they start typing.

You are given the tail of the conversation. Write the single most likely thing the user says next: a follow-up question, a reaction, a further request, a next step in the same task — whatever fits, and NOT necessarily a question.

Rules:
- Reply with that line alone. No quotes, no prefix, no markdown, no commentary.
- First person, exactly as the user would type it. Under 14 words.
- Write what the USER would say, never what the assistant would say back, and never a description of a question ("you could ask...") instead of the question itself.
- Ground it in what the assistant just said; do not introduce an unrelated subject.

Good (assistant just explained a retry policy): "What happens after the third retry fails?"
Good (assistant just drafted an email): "Make the tone more casual"
Good (assistant just listed three options): "Let's go with the second one"
Bad: "You could ask about the retry limit"  <- describes a line instead of being it
Bad: "That's a great explanation!"          <- not worth typing, continues nothing
Bad: "Here's a more casual version: ..."    <- the assistant's voice, not the user's"""

_SYSTEM_ZH = """你要预测用户接下来最可能在聊天框里打出的**一句话**——这是输入框的占位提示，会在他开始打字之前被读到。

给你的是这段对话的结尾。写出用户接下来最可能说的那一句：一个追问、一个反应、一个进一步的要求、同一件事的下一步——只要贴切就行，**不必是问题**。

规则：
- 只回复那一句话本身。不要引号、不要前缀、不要 markdown、不要任何补充说明。
- 第一人称，就像用户自己会打出来的样子。不超过 25 个字。
- 写的是**用户**会说的话，绝不是助手会回的话，也不能只是描述一个问题（比如"你可以问问重试上限"），而要把那句话本身写出来。
- 要接得上助手刚说的内容，不要引入一个不相关的话题。

好（助手刚讲完重试策略）："第三次重试失败之后会怎样？"
好（助手刚起草了一封邮件）："语气改随意一点"
好（助手刚列出三个选项）："就选第二个吧"
差："你可以问问重试上限"          <- 描述了一句话，而不是把它写出来
差："讲得真好！"                  <- 不值得打出来，也没往下接
差："这是更随意一点的版本：……"    <- 这是助手的口吻，不是用户的"""


def _render(material: _Material, zh: bool) -> str:
    speaker = {"user": "用户" if zh else "User", "assistant": "助手" if zh else "Assistant"}
    body = "\n".join(f"[{speaker.get(role, role)}] {text}" for role, text in material.transcript)
    lines = [("# 对话结尾\n" if zh else "# End of the conversation\n") + body]
    lines.append("\n请写出用户接下来最可能说的那一句。" if zh else "\nWrite that single next line.")
    return "\n\n".join(lines)


_META_EN = re.compile(
    r"(?:\byou (?:can|could|should)\b|\btry (?:asking|saying)\b|\bconsider asking\b|"
    r"\bthe user (?:can|could|should)\b)",
    re.IGNORECASE,
)
_META_ZH = re.compile(r"你可以|你能试着|你应该|不妨问|建议问|可以这样问")
_ASSISTANT_VOICE_EN = re.compile(
    r"^(?:sure|certainly|of course|here(?:'|’)s|here is|as an ai|i(?:'|’)d be happy)\b",
    re.IGNORECASE,
)
_ASSISTANT_VOICE_ZH = re.compile(r"^(?:好的|当然|没问题|作为(?:一个)?(?:人工智能|AI))")


def _normal_form(value: str) -> str:
    return re.sub(r"[^\w㐀-鿿]+", "", value).casefold()


def _echoes_last_message(hint: str, last_user_message: str) -> bool:
    """True when *hint* is essentially the user's own last message read back."""
    if not last_user_message:
        return False
    hint_form = _normal_form(hint)
    message_form = _normal_form(last_user_message)
    return len(hint_form) >= 6 and (hint_form in message_form or message_form in hint_form)


def _sanitize(raw: str, language: str, last_user_message: str = "") -> str:
    """One compliant predicted line, or an empty string."""
    lines = [line.strip() for line in str(raw or "").splitlines() if line.strip()]
    if len(lines) != 1:
        return ""
    text = lines[0].strip()
    if text.startswith("```") or text.endswith("```"):
        return ""
    text = text.lstrip("-•*# ").strip()
    if len(text) >= 2 and (text[0], text[-1]) in {
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
        ("「", "」"),
    }:
        text = text[1:-1].strip()
    text = " ".join(text.split())
    if not text:
        return ""

    zh = _is_zh(language)
    limit = _MAX_HINT_CHARS["zh" if zh else "en"]
    if len(text) > limit:
        return ""
    if (_META_ZH if zh else _META_EN).search(text):
        return ""
    if (_ASSISTANT_VOICE_ZH if zh else _ASSISTANT_VOICE_EN).search(text):
        return ""
    if _echoes_last_message(text, last_user_message):
        return ""
    return text


def _response_language() -> str:
    from deeptutor.services.settings.interface_settings import get_response_language

    try:
        return get_response_language(default="en")
    except Exception:
        logger.debug("chat ask-hint: response language unreadable", exc_info=True)
        return "en"


async def _call_llm(material: _Material, language: str) -> str:
    from deeptutor.services.llm import complete
    from deeptutor.services.model_selection.tasks import task_llm_scope

    zh = _is_zh(language)
    # Same call class as titles and starter lines — short, frequent, and
    # nobody asked for it — so it runs on the task model when one is set.
    with task_llm_scope():
        return await asyncio.wait_for(
            complete(
                prompt=_render(material, zh),
                system_prompt=_SYSTEM_ZH if zh else _SYSTEM_EN,
                temperature=0.7,
                max_tokens=120,
                max_retries=0,
            ),
            timeout=_LLM_TIMEOUT,
        )


async def _generate(session_id: str, material: _Material) -> AskHint:
    empty = AskHint(hint="", session_id=session_id, generated_at=time.time())
    if not material:
        return empty

    language = _response_language()
    try:
        raw = await _call_llm(material, language)
    except asyncio.TimeoutError:
        logger.debug("chat ask-hint LLM call timed out")
        return empty
    except Exception:
        logger.debug("chat ask-hint LLM call failed", exc_info=True)
        return empty

    return AskHint(
        hint=_sanitize(raw, language, material.last_user_message),
        session_id=session_id,
        generated_at=time.time(),
    )


# -- Public API ---------------------------------------------------------------


async def get_ask_hint(session_id: str) -> dict[str, Any]:
    """The line to offer under the home composer, or "" when there is none.

    An empty hint is a real answer, not an error — a conversation with no
    messages yet, a timeout, a model that answered instead of predicting, all
    leave the composer's own static placeholder standing.
    """
    material = await _collect(session_id)
    if not material:
        return AskHint(hint="", session_id=session_id, generated_at=time.time()).to_dict()

    key = _cache_key(session_id, material.transcript_length)
    try:
        value = await _hint_cache.get_or_create(
            key,
            lambda: _generate(session_id, material),
            cache_when=lambda item: bool(item.hint),
        )
    except Exception:
        logger.debug("chat ask-hint generation failed", exc_info=True)
        return AskHint(hint="", session_id=session_id, generated_at=time.time()).to_dict()
    return value.to_dict()


__all__ = ["AskHint", "get_ask_hint"]
