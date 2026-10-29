"""Conversations held at a line of a note page.

A thread is an ordinary chat session (the transcript, regenerate and ask-user
cards stay the chat runtime's) that the page owns: it is opened on a block,
listed with the page and folded back onto that block when it is closed. The
page keeps the anchor; the session keeps the conversation. Stored beside the
manifest, like the review queue, so anchoring a thread never bumps the page's
revision under an open editor.
"""

from __future__ import annotations

import time

from deeptutor.co_writer.storage import _atomic_write_json, _read_json
from deeptutor.notes.blocks import LEAF_BLOCK_TYPES, blocks_to_markdown, walk_blocks

MAX_THREADS = 500
QUOTE_LIMIT = 600
CARD_CONTENT_LIMIT = 6000


def _path(storage, doc_id):
    return storage.doc_root(doc_id) / "threads.json"


def list_threads(storage, doc_id) -> list[dict]:
    rows = _read_json(_path(storage, doc_id))
    return rows if isinstance(rows, list) else []


def adopt_legacy_threads(storage, doc_id, session_ids: list[str]) -> None:
    """Give a page's conversations from before threads a line: its first block.

    Runs once per page (the file's existence marks it done), so a thread the
    learner later deletes is not adopted again.
    """
    with storage.locked():
        if _path(storage, doc_id).exists():
            return
        doc = storage.load_document(doc_id)
        first = next(iter((doc.blocks if doc else None) or []), None)
        now = time.time()
        rows = (
            [
                {
                    "session_id": sid,
                    "block_id": first["id"],
                    "quote": "",
                    "origin": "ask",
                    "created_at": now,
                }
                for sid in dict.fromkeys(session_ids)
            ]
            if first
            else []
        )
        _atomic_write_json(_path(storage, doc_id), rows)


def find_thread(storage, doc_id, session_id) -> dict | None:
    return next((t for t in list_threads(storage, doc_id) if t["session_id"] == session_id), None)


def anchor_thread(storage, doc_id, *, session_id, block_id, quote="", origin="ask") -> dict:
    """Record (or move) the line a conversation belongs to."""
    with storage.locked():
        if storage.load_document(doc_id) is None:
            raise ValueError("Page not found")
        threads = list_threads(storage, doc_id)
        existing = next((t for t in threads if t["session_id"] == session_id), None)
        if existing is None:
            existing = {"session_id": session_id, "created_at": time.time()}
            threads.append(existing)
        existing.update(
            block_id=block_id,
            quote=(quote or existing.get("quote") or "")[:QUOTE_LIMIT],
            origin=origin if origin in {"ask", "generate"} else "ask",
        )
        _atomic_write_json(_path(storage, doc_id), threads[-MAX_THREADS:])
        return existing


def remove_thread(storage, doc_id, session_id) -> bool:
    with storage.locked():
        threads = list_threads(storage, doc_id)
        kept = [t for t in threads if t["session_id"] != session_id]
        if len(kept) == len(threads):
            return False
        _atomic_write_json(_path(storage, doc_id), kept)
        return True


def prune_threads(storage, doc_id, live_session_ids: set[str]) -> None:
    """Forget threads whose conversation was deleted elsewhere."""
    with storage.locked():
        threads = list_threads(storage, doc_id)
        kept = [t for t in threads if t["session_id"] in live_session_ids]
        if len(kept) != len(threads):
            _atomic_write_json(_path(storage, doc_id), kept)


def block_text(block: dict, limit: int = 400) -> str:
    """The visible text of one block, for telling the model which line this is."""
    parts: list[str] = []
    content = block.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or (item.get("props") or {}).get("title") or ""))
    props = block.get("props") or {}
    if not parts and block.get("type") == "learning":
        parts.append(f"[{props.get('kind') or 'learning'} block] {props.get('prompt') or ''}")
    text = " ".join("".join(parts).split())
    return text[:limit]


def card_content(block: dict) -> str:
    """What a card (a learning block, a figure, a table) holds, as Markdown.

    Its own text is only a kind and a prompt; the model needs the events, the
    questions or the cells to talk about it.
    """
    if block.get("type") not in LEAF_BLOCK_TYPES | {"table", "codeBlock"}:
        return ""
    try:
        text = blocks_to_markdown([{**block, "children": []}]).strip()
    except (ValueError, TypeError, AttributeError):
        return ""
    if len(text) > CARD_CONTENT_LIMIT:
        text = text[:CARD_CONTENT_LIMIT] + "\n…"
    return text


def thread_anchor_context(storage, doc_id: str, session_id: str, *, zh: bool) -> str:
    """Which line of the page this conversation is held at, or ""."""
    if not doc_id or not session_id:
        return ""
    thread = find_thread(storage, doc_id, session_id)
    if thread is None:
        return ""
    doc = storage.load_document(doc_id)
    block = next(
        (
            b
            for b in walk_blocks((doc.blocks if doc else None) or [])
            if b["id"] == thread["block_id"]
        ),
        None,
    )
    quote = str(thread.get("quote") or "").strip()
    content = card_content(block) if block is not None else ""
    if zh:
        lines = [
            f"这段对话是在页面的块 {thread['block_id']} 处发起的"
            + ("（该块已被删除）。" if block is None else f"：「{block_text(block)}」。")
        ]
        if quote:
            lines.append(f"用户当时选中的文字：「{quote}」。")
        lines.append(
            "用户说「这里」「这段」「这句」时指的就是它；插入、改写、生成的内容默认放在这个块附近，"
            "其余部分保持不动。"
        )
        if content:
            lines.append(f"这个块的内容如下：\n{content}")
    else:
        lines = [
            f"This conversation was opened at block {thread['block_id']} of the page"
            + (
                " (that block has since been deleted)."
                if block is None
                else f': "{block_text(block)}".'
            )
        ]
        if quote:
            lines.append(f'The learner had selected: "{quote}".')
        lines.append(
            '"Here", "this part" and "this sentence" mean that block. Place inserted, '
            "rewritten or generated material next to it and leave the rest of the page alone."
        )
        if content:
            lines.append(f"The block holds:\n{content}")
    return " ".join(lines)
