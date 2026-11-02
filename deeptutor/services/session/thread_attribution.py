"""Recover which message a pre-attribution Little Tutor thread came from.

``tutor_source_message_id`` is written when a side chat is opened, but threads
created before that field existed only kept the passage itself: either in
``preferences.tutor_selected_text`` (selection-scope threads), as a quote
attachment on a user message, or in the assistant row's ``model_turn.system``
prompt. The prompt is the strongest legacy signal for selection-scope threads:
it carries the containing message, its role and the exact selection. Current
quote-based threads carry the passage on the user message instead.

A passage that occurs in exactly one parent message is authoritative. One that
occurs in several is left alone rather than guessing, and a thread with no
passage at all is never attributed. The work is recorded per thread so the
scan runs once, not on every thread-list read. The write is conditional: a
concurrent turn/move/detach that lands between the snapshot and the write wins.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import re
import threading
from typing import Any, Sequence
import weakref

from .model_history import SOURCE_MESSAGE_METADATA_KEY
from .quote_attachments import read_quotes
from .selection_grounding import rendered_markdown_text

logger = logging.getLogger(__name__)

TUTOR_SOURCE_KEY = "tutor_source_message_id"
# Set once attribution has been attempted (successfully or not) so a thread is
# not re-scanned on every read. Clearing an anchor also sets it, which keeps a
# deliberate detach from being undone by a later backfill.
BACKFILL_ATTEMPTED_KEY = "tutor_source_backfill_attempted"
# One request may have to recover several threads; each needs the thread's
# transcript and (at most once) the parent's. Keep a single caller bounded.
MAX_BACKFILLED_THREADS = 50
# Shorter passages match too many messages to be evidence of a source.
MIN_QUOTE_CHARS = 8
_TRANSCRIPT_ROLES = frozenset({"user", "assistant"})
_OMITTED_MARKER = re.compile(r"\[(?:earlier|later) content omitted\]", re.IGNORECASE)
# The sidebar prompt is the one deterministic record older selection threads
# kept. Parse the two shapes the formatter emits, not arbitrary prose.
_EN_PROMPT = re.compile(
    r"\[Containing message\]\s*\n\s*Message role:\s*(?P<role>\w+)\s*\n"
    r"(?P<containing>.*?)\n\s*\[Learner's exact selection\]\s*\n"
    r"(?P<selection>.*?)(?=\n\s*Source session:|\Z)",
    re.DOTALL,
)
_ZH_PROMPT = re.compile(
    r"\[原消息上下文\]\s*\n\s*消息角色：\s*(?P<role>\w+)\s*\n"
    r"(?P<containing>.*?)\n\s*\[用户精确选中的内容\]\s*\n"
    r"(?P<selection>.*?)(?=\n\s*来源会话：|\Z)",
    re.DOTALL,
)

# Parent locks are per event loop and per store (account). A loop can outlive
# individual calls, so a WeakKeyDictionary keeps the registry from pinning
# closed loops; tests using several `asyncio.run` calls each get their own lock.
_LOCKS_GUARD = threading.Lock()
_PARENT_LOCKS: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[str, str], asyncio.Lock]
] = weakref.WeakKeyDictionary()


def _normalized(text: str) -> str:
    return " ".join(str(text or "").split())


def _store_key(store: Any) -> str:
    scope = getattr(store, "store_scope", None)
    scope_key = getattr(scope, "cache_key", "") if scope is not None else ""
    if scope_key:
        return f"pocketbase:{scope_key}"
    db_path = getattr(store, "db_path", None)
    if db_path is not None:
        return f"sqlite:{db_path}"
    return f"object:{id(store)}"


def _parent_lock(store: Any, parent_session_id: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (_store_key(store), str(parent_session_id))
    with _LOCKS_GUARD:
        per_loop = _PARENT_LOCKS.get(loop)
        if per_loop is None:
            per_loop = {}
            _PARENT_LOCKS[loop] = per_loop
        lock = per_loop.get(key)
        if lock is None:
            lock = asyncio.Lock()
            per_loop[key] = lock
    return lock


def _projected(content: str) -> str:
    try:
        return rendered_markdown_text(content)
    except Exception:
        # A message the Markdown projection cannot read simply does not
        # ground this passage; it must not take the whole scan down.
        logger.debug("tutor thread backfill: unreadable message", exc_info=True)
        return _normalized(content)


def _message_texts(messages: Sequence[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """Normalized raw text and rendered text, computed once per parent read."""
    cache: dict[str, tuple[str, str]] = {}
    for message in messages:
        message_id = message.get("id")
        if message_id is None:
            continue
        content = str(message.get("content") or "")
        cache[str(message_id)] = (_normalized(content), _projected(content))
    return cache


def _containing_matches(
    texts: tuple[str, str],
    containing: str,
    *,
    exact: bool,
) -> bool:
    normalized, projected = texts
    if exact:
        return containing == normalized or containing == projected
    return containing in normalized or containing in projected


def _matches(
    messages: Sequence[dict[str, Any]],
    needle: str,
    *,
    projections: dict[str, tuple[str, str]] | None = None,
    role: str | None = None,
    containing: str = "",
    exact_containing: bool = False,
) -> list[tuple[Any, str]]:
    if len(needle) < MIN_QUOTE_CHARS:
        return []
    texts_by_id = projections if projections is not None else _message_texts(messages)
    containing = _normalized(containing)
    matches: list[tuple[Any, str]] = []
    for message in messages:
        message_role = str(message.get("role") or "")
        if message_role not in _TRANSCRIPT_ROLES:
            continue
        if role is not None and message_role != role:
            continue
        message_id = message.get("id")
        if message_id is None:
            continue
        texts = texts_by_id.get(str(message_id))
        if texts is None:
            content = str(message.get("content") or "")
            texts = (_normalized(content), _projected(content))
        normalized, projected = texts
        if needle not in normalized and needle not in projected:
            continue
        if containing and not _containing_matches(texts, containing, exact=exact_containing):
            continue
        matches.append((message_id, message_role))
    return matches


def locate_quote_message(
    messages: list[dict[str, Any]],
    quote: str,
    *,
    projections: dict[str, tuple[str, str]] | None = None,
) -> int | str | None:
    """The one parent message containing ``quote``, or None when ambiguous."""
    needle = _normalized(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    matches = _matches(messages, needle, projections=projections)
    assistant_matches = [message_id for message_id, role in matches if role == "assistant"]
    if len(assistant_matches) == 1:
        return assistant_matches[0]
    if len(matches) == 1:
        return matches[0][0]
    return None


def locate_selected_message(
    messages: list[dict[str, Any]],
    selection: str,
    *,
    role: str | None = None,
    containing: str = "",
    projections: dict[str, tuple[str, str]] | None = None,
) -> int | str | None:
    """Locate a stored selection, optionally constrained by prompt evidence.

    ``containing`` comes from the sidebar prompt's ``[Containing message]``
    block. With it, and the recorded role, a selection that also occurs in the
    learner's own echoed words is no longer ambiguous.
    """
    needle = _normalized(selection)
    if len(needle) < MIN_QUOTE_CHARS:
        return None
    raw_containing = str(containing or "").strip()
    exact = bool(raw_containing) and not _OMITTED_MARKER.search(raw_containing)
    normalized_containing = _normalized(_OMITTED_MARKER.sub(" ", raw_containing))
    matches = _matches(
        messages,
        needle,
        projections=projections,
        role=role,
        containing=normalized_containing,
        exact_containing=exact,
    )
    if len(matches) == 1:
        return matches[0][0]
    if not role and not raw_containing:
        # No prompt evidence: preserve the historical assistant-first heuristic
        # for threads whose passage appears in both sides of the conversation.
        return locate_quote_message(messages, needle, projections=projections)
    return None


@dataclass(frozen=True)
class _PromptEvidence:
    selection: str
    containing: str
    role: str


@dataclass(frozen=True)
class _ThreadEvidence:
    selection: str
    prompt: _PromptEvidence | None
    quote: str
    quote_ambiguous: bool
    source_id: Any = None
    source_role: str = ""


def _parse_prompt_evidence(system: str) -> _PromptEvidence | None:
    for pattern in (_EN_PROMPT, _ZH_PROMPT):
        match = pattern.search(system)
        if match is None:
            continue
        role = str(match.group("role") or "").strip()
        selection = str(match.group("selection") or "").strip()
        if not selection or role not in _TRANSCRIPT_ROLES:
            continue
        return _PromptEvidence(
            selection=selection,
            containing=str(match.group("containing") or "").strip(),
            role=role,
        )
    return None


def _structured_source(messages: Sequence[dict[str, Any]]) -> tuple[Any, str] | None:
    for message in reversed(messages):
        if str(message.get("role") or "") != "assistant":
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        source = metadata.get(SOURCE_MESSAGE_METADATA_KEY)
        if not isinstance(source, dict):
            continue
        message_id = source.get("message_id")
        if message_id is None:
            continue
        role = str(source.get("role") or "").strip()
        return message_id, role if role in _TRANSCRIPT_ROLES else ""
    return None


def _first_prompt_evidence(messages: Sequence[dict[str, Any]]) -> _PromptEvidence | None:
    for message in messages:
        if str(message.get("role") or "") != "assistant":
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        model_turn = metadata.get("model_turn")
        if not isinstance(model_turn, dict):
            continue
        system = model_turn.get("system")
        if not isinstance(system, str) or not system.strip():
            continue
        evidence = _parse_prompt_evidence(system)
        if evidence is not None:
            return evidence
    return None


def _first_single_quote(messages: Sequence[dict[str, Any]]) -> tuple[str, bool]:
    """The earliest quoted passage in the thread, and whether it was ambiguous.

    A user message may carry several quote attachments; there is no way to tell
    which one opened the thread, so that message is treated as ambiguous rather
    than silently picking the first.
    """
    for message in messages:
        if str(message.get("role") or "") != "user":
            continue
        quotes = read_quotes(list(message.get("attachments") or []))
        if not quotes:
            continue
        if len(quotes) > 1:
            return "", True
        return quotes[0], False
    return "", False


async def _thread_evidence(store: Any, thread: dict[str, Any]) -> _ThreadEvidence | None:
    session_id = str(thread.get("session_id") or "").strip()
    if not session_id:
        return None
    messages = await store.get_messages(session_id)
    preferences = thread.get("preferences") or {}
    selection = str(preferences.get("tutor_selected_text") or "").strip()
    prompt = _first_prompt_evidence(messages)
    if prompt is not None and prompt.selection:
        selection = prompt.selection
    quote, quote_ambiguous = _first_single_quote(messages)
    structured = _structured_source(messages)
    source_id: Any = None
    source_role = ""
    if structured is not None:
        source_id, source_role = structured
    elif prompt is not None:
        source_role = prompt.role
    return _ThreadEvidence(
        selection=selection,
        prompt=prompt,
        quote=quote,
        quote_ambiguous=quote_ambiguous,
        source_id=source_id,
        source_role=source_role,
    )


async def parent_message_role(
    store: Any, parent_session_id: str, message_id: int | str | None
) -> str | None:
    """Role of ``message_id`` when it is a user/assistant message of the parent."""
    if message_id is None or not str(parent_session_id or "").strip():
        return None
    getter = getattr(store, "get_message_role", None)
    if getter is not None:
        role = await getter(parent_session_id, message_id)
        return role if role in _TRANSCRIPT_ROLES else None
    # Store doubles used by tests may not implement the narrow lookup.
    messages = await store.get_messages(parent_session_id)
    for message in messages:
        if str(message.get("id")) == str(message_id):
            role = str(message.get("role") or "")
            return role if role in _TRANSCRIPT_ROLES else None
    return None


def _validate_structured_source(
    messages: Sequence[dict[str, Any]], source_id: Any, source_role: str
) -> bool:
    for message in messages:
        if str(message.get("id")) != str(source_id):
            continue
        role = str(message.get("role") or "")
        if role not in _TRANSCRIPT_ROLES:
            return False
        return not source_role or role == source_role
    return False


def _locate_for_thread(
    parent_messages: list[dict[str, Any]],
    projections: dict[str, tuple[str, str]],
    evidence: _ThreadEvidence,
) -> Any:
    if evidence.source_id is not None:
        if _validate_structured_source(parent_messages, evidence.source_id, evidence.source_role):
            return evidence.source_id
    if evidence.prompt is not None:
        # The prompt is authoritative evidence; if it cannot identify one
        # message, do not fall back to the weaker assistant-first heuristic.
        return locate_selected_message(
            parent_messages,
            evidence.prompt.selection,
            role=evidence.prompt.role,
            containing=evidence.prompt.containing,
            projections=projections,
        )
    if evidence.selection:
        return locate_selected_message(
            parent_messages,
            evidence.selection,
            role=evidence.source_role or None,
            projections=projections,
        )
    if evidence.quote and not evidence.quote_ambiguous:
        return locate_quote_message(parent_messages, evidence.quote, projections=projections)
    return None


async def _claim_source(store: Any, thread_session_id: str, source_id: Any) -> bool:
    updates: dict[str, Any] = {BACKFILL_ATTEMPTED_KEY: True}
    if source_id is not None:
        updates[TUTOR_SOURCE_KEY] = source_id
    unset = (TUTOR_SOURCE_KEY, BACKFILL_ATTEMPTED_KEY)
    conditional = getattr(store, "update_session_preferences_if_unset", None)
    if conditional is not None:
        return bool(await conditional(thread_session_id, updates, unset=unset, touch=False))
    # Compatibility for test doubles: re-check immediately before the merge.
    session = await store.get_session(thread_session_id)
    if session is None:
        return False
    preferences = session.get("preferences") or {}
    if any(preferences.get(key) for key in unset):
        return False
    return bool(await store.update_session_preferences(thread_session_id, updates, touch=False))


def _is_pending(thread: dict[str, Any]) -> bool:
    preferences = thread.get("preferences") or {}
    return not preferences.get(TUTOR_SOURCE_KEY) and not preferences.get(BACKFILL_ATTEMPTED_KEY)


async def backfill_thread_sources(
    store: Any,
    parent_session_id: str,
    threads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attribute legacy threads in place; return the same rows.

    Serialized per parent (per account) so concurrent thread-list reads do not
    duplicate the scan. The conditional store write is what actually protects
    a live move or a detach that races this request.
    """
    pending = [thread for thread in threads if _is_pending(thread)]
    if not pending:
        return threads

    async with _parent_lock(store, parent_session_id):
        pending = [thread for thread in threads if _is_pending(thread)]
        if not pending:
            return threads
        parent_messages: list[dict[str, Any]] | None = None
        projections: dict[str, tuple[str, str]] = {}
        for thread in pending[:MAX_BACKFILLED_THREADS]:
            thread_session_id = str(thread.get("session_id") or "").strip()
            if not thread_session_id:
                continue
            try:
                # The snapshot may predate a turn that attached/moved or a
                # learner who detached; re-read before doing the expensive scan.
                fresh = await store.get_session(thread_session_id)
                if fresh is None:
                    continue
                fresh_preferences = fresh.get("preferences") or {}
                if any(
                    fresh_preferences.get(key)
                    for key in (
                        TUTOR_SOURCE_KEY,
                        BACKFILL_ATTEMPTED_KEY,
                    )
                ):
                    thread["preferences"] = dict(fresh_preferences)
                    continue
                evidence = await _thread_evidence(store, fresh)
                if evidence is None:
                    continue
                if parent_messages is None:
                    parent_messages = await store.get_messages(parent_session_id)
                    projections = _message_texts(parent_messages)
                message_id = _locate_for_thread(parent_messages, projections, evidence)
                claimed = await _claim_source(store, thread_session_id, message_id)
                if claimed:
                    updates: dict[str, Any] = {BACKFILL_ATTEMPTED_KEY: True}
                    if message_id is not None:
                        updates[TUTOR_SOURCE_KEY] = message_id
                    thread["preferences"] = {
                        **dict(fresh.get("preferences") or {}),
                        **updates,
                    }
                else:
                    latest = await store.get_session(thread_session_id)
                    if latest is not None:
                        thread["preferences"] = dict(latest.get("preferences") or {})
            except Exception:
                logger.warning(
                    "could not recover the source of tutor thread %s",
                    thread_session_id,
                    exc_info=True,
                )
                continue
    return threads


__all__ = [
    "BACKFILL_ATTEMPTED_KEY",
    "MAX_BACKFILLED_THREADS",
    "TUTOR_SOURCE_KEY",
    "backfill_thread_sources",
    "locate_quote_message",
    "locate_selected_message",
    "parent_message_role",
]
