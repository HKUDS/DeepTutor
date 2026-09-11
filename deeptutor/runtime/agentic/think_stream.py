"""Split a provider's inline ``<think>`` blocks out of a content stream.

Reasoning models differ in *where* they put their reasoning. Some report it on
a dedicated channel (``delta.reasoning_content``), and some — Qwen's thinking
models, DeepSeek-R1 through several proxies, a number of local builds — simply
write it into the content channel wrapped in ``<think>`` tags.

That second group has to be split at streaming time, in one place, because
every consumer downstream is wrong otherwise: the live bubble shows the
model's private deliberation, the persisted message keeps it, and the loop's
finish detection reads it as an answer. Splitting here routes it to the trace
instead, where a reader can open it deliberately.

The raw text — tags included — still goes back into the LLM conversation
untouched, because that is the transcript the model expects to see.

This lives in the runtime layer rather than beside the chat loop so the other
executors (labeled steps, the exploration pre-pass, the notebook and CoWriter
agents) can route reasoning the same way instead of discarding it.
"""

from __future__ import annotations

import re

__all__ = [
    "THINK_CLOSE_RE",
    "THINK_OPEN_RE",
    "InlineThinkFilter",
    "split_inline_think",
]

THINK_OPEN_RE = re.compile(r"<\s*think(?:ing)?\b[^>]*>", re.IGNORECASE)
THINK_CLOSE_RE = re.compile(r"<\s*/\s*think(?:ing)?\s*>", re.IGNORECASE)
# Longest partial tag worth waiting a chunk for (e.g. "</thinking" + slack).
_TAG_HOLDBACK_CHARS = 24


class InlineThinkFilter:
    """Incremental ``<think>``/``<thinking>`` splitter for streamed content."""

    def __init__(self) -> None:
        self._buffer = ""
        self._in_think = False

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        """Consume *chunk*; return ``(kind, text)`` segments, kind in
        ``{"content", "thinking"}``. May hold back a partial trailing tag
        until the next chunk (``flush`` releases it at stream end)."""
        self._buffer += chunk
        segments: list[tuple[str, str]] = []
        while True:
            pattern = THINK_CLOSE_RE if self._in_think else THINK_OPEN_RE
            match = pattern.search(self._buffer)
            if match is None:
                break
            if match.start() > 0:
                segments.append((self._kind(), self._buffer[: match.start()]))
            self._buffer = self._buffer[match.end() :]
            self._in_think = not self._in_think
        emit_upto = len(self._buffer)
        tag_start = self._buffer.rfind("<")
        if (
            tag_start != -1
            and len(self._buffer) - tag_start <= _TAG_HOLDBACK_CHARS
            and ">" not in self._buffer[tag_start:]
        ):
            emit_upto = tag_start
        if emit_upto > 0:
            segments.append((self._kind(), self._buffer[:emit_upto]))
            self._buffer = self._buffer[emit_upto:]
        return segments

    def flush(self) -> list[tuple[str, str]]:
        """Release whatever is still buffered (stream ended)."""
        if not self._buffer:
            return []
        segments = [(self._kind(), self._buffer)]
        self._buffer = ""
        return segments

    def _kind(self) -> str:
        return "thinking" if self._in_think else "content"


def split_inline_think(text: str) -> list[tuple[str, str]]:
    """Split a complete (non-streamed) string into content/thinking segments.

    For executors that collect a whole response before reporting it: the same
    routing rule as the streaming filter, applied once.
    """
    inline = InlineThinkFilter()
    return [*inline.feed(text), *inline.flush()]
