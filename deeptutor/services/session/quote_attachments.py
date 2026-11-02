"""Quoted passages attached to a chat message.

The composer's "add to composer" action sends a passage the learner selected
as an ordinary attachment of ``type == "quote"`` (UTF-8 Markdown in
``base64``). It is text the learner is pointing at, not a document they
uploaded: the turn reads it straight back and puts it in front of the
question, instead of sending it through document extraction.
"""

from __future__ import annotations

import base64
import binascii

QUOTE_ATTACHMENT_TYPE = "quote"
# Same bound as the browser's; a longer selection is clipped, never refused.
QUOTE_MAX_CHARS = 12_000


def is_quote(record: dict) -> bool:
    return str(record.get("type") or "") == QUOTE_ATTACHMENT_TYPE


def read_quotes(records: list[dict]) -> list[str]:
    """Decode every quote record in place and return their texts in order.

    Each record keeps its bytes for the attachment store and gains
    ``extracted_text`` — what the transcript shows once ``base64`` is pruned.
    """
    quotes: list[str] = []
    for record in records:
        if not is_quote(record):
            continue
        text = str(record.get("extracted_text") or "")
        if not text:
            try:
                text = base64.b64decode(record.get("base64") or "", validate=False).decode(
                    "utf-8", errors="replace"
                )
            except (binascii.Error, ValueError):
                text = ""
        text = text.strip()[:QUOTE_MAX_CHARS]
        record["extracted_text"] = text
        record["extracted_chars"] = len(text)
        if text:
            quotes.append(text)
    return quotes


def quote_block(quotes: list[str]) -> str:
    """The passages as the model reads them, ahead of the learner's words."""
    if not quotes:
        return ""
    blocks = ["\n".join(f"> {line}" if line else ">" for line in q.splitlines()) for q in quotes]
    return (
        "[Quoted Passages — selected by the learner; the message below is about them]\n"
        + "\n\n".join(blocks)
    )


def with_quotes(user_message: str, quotes: list[str]) -> str:
    block = quote_block(quotes)
    return f"{block}\n\n{user_message}" if block else user_message


__all__ = ["QUOTE_ATTACHMENT_TYPE", "is_quote", "quote_block", "read_quotes", "with_quotes"]
