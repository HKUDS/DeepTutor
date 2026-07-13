"""Tool-result truncation and on-demand expansion buffer for the CLI.

Tool outputs in agent loops (RAG hits, web search dumps, file reads, code
execution stdout) can run to hundreds of lines. Streaming the full body into
the terminal drowns the reasoning around it and forces the user to scroll
past noise on every turn. We instead show a short head and stash the full
body so the REPL can re-print it on request — mirroring the
``… +N lines (ctrl+o to expand)`` UX users already know from other CLI
agents.

This module is pure logic so it can be unit-tested without a live REPL:

* :func:`truncate_for_display` decides what to show now.
* :class:`ToolResultBuffer` remembers the full bodies so the
  ``/show`` REPL command (and any future Ctrl+O keybinding) can expand
  them later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Defaults tuned for "agent reasoning is the signal, tool dumps are the
# noise". Ten lines is enough to recognise the result; long single lines
# (a giant JSON blob, a binary blob) get a hard character cap so the head
# never blows past one screen.
DEFAULT_HEAD_LINES = 10
DEFAULT_LINE_HARD_CAP = 240
# Cap how many recent tool results we hold onto so a long REPL session
# doesn't keep every tool dump in memory forever. The /show command only
# needs the recent ones; older results stay in the session DB if anyone
# wants the full archive.
DEFAULT_RING_CAPACITY = 32


def truncate_for_display(
    body: str,
    *,
    head_lines: int = DEFAULT_HEAD_LINES,
    line_hard_cap: int = DEFAULT_LINE_HARD_CAP,
) -> tuple[str, int]:
    """Return ``(visible_text, hidden_line_count)`` for an inline preview.

    ``hidden_line_count == 0`` means the full body fits within the budget
    and the caller should not append an expansion hint. The returned
    ``visible_text`` already has overlong single lines clipped with an
    ellipsis so the head can't blow past one screen on JSON-style output.
    """

    if head_lines <= 0:
        return "", _line_count(body)

    lines = body.split("\n")
    if len(lines) <= head_lines:
        head_slice = lines
        hidden = 0
    else:
        head_slice = lines[:head_lines]
        hidden = len(lines) - head_lines

    clipped = [_clip_long_line(line, line_hard_cap) for line in head_slice]
    return "\n".join(clipped), hidden


def _line_count(body: str) -> int:
    if not body:
        return 0
    return body.count("\n") + 1


def _clip_long_line(line: str, line_hard_cap: int) -> str:
    if line_hard_cap <= 0 or len(line) <= line_hard_cap:
        return line
    # Keep most of the line, append a marker so the reader knows the line
    # itself was clipped (independent of the line-count hidden marker).
    return line[: line_hard_cap - 1] + "…"


@dataclass(slots=True)
class ToolResultEntry:
    """One captured tool result that can later be expanded by ``/show``."""

    index: int  # 1-based, monotonically increasing per REPL session
    label: str  # tool name as reported by the stream
    body: str  # untruncated text


@dataclass(slots=True)
class ToolResultBuffer:
    """Bounded ring of recent tool results.

    The buffer is intentionally tiny — its only purpose is to back the
    ``/show`` REPL command, not to be a transcript store.
    """

    capacity: int = DEFAULT_RING_CAPACITY
    head_lines: int = DEFAULT_HEAD_LINES
    line_hard_cap: int = DEFAULT_LINE_HARD_CAP
    _entries: list[ToolResultEntry] = field(default_factory=list)
    _next_index: int = 1

    def remember(self, label: str, body: str) -> ToolResultEntry:
        entry = ToolResultEntry(index=self._next_index, label=label or "tool", body=body)
        self._next_index += 1
        self._entries.append(entry)
        if len(self._entries) > self.capacity:
            # Drop oldest; preserve indices so ``/show 7`` keeps meaning
            # "the seventh tool result of this session" even after older
            # entries fall out of the ring.
            del self._entries[: len(self._entries) - self.capacity]
        return entry

    def truncate(self, body: str) -> tuple[str, int]:
        """Front-door to :func:`truncate_for_display` using this buffer's policy."""

        return truncate_for_display(
            body,
            head_lines=self.head_lines,
            line_hard_cap=self.line_hard_cap,
        )

    def last(self) -> ToolResultEntry | None:
        return self._entries[-1] if self._entries else None

    def get(self, selector: str | int | None) -> ToolResultEntry | None:
        """Resolve ``/show`` arguments: ``None``/``"last"`` → most recent;
        a positive integer → entry with that 1-based index;
        any other string → most recent entry whose label matches.
        """

        if selector is None or selector == "" or selector == "last":
            return self.last()
        if isinstance(selector, int):
            return self._by_index(selector)
        text = str(selector).strip()
        if text.isdigit():
            return self._by_index(int(text))
        for entry in reversed(self._entries):
            if entry.label == text:
                return entry
        return None

    def entries(self) -> list[ToolResultEntry]:
        """Snapshot of current contents (newest last). For inspection/tests."""

        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._next_index = 1

    def _by_index(self, idx: int) -> ToolResultEntry | None:
        for entry in self._entries:
            if entry.index == idx:
                return entry
        return None


__all__ = [
    "DEFAULT_HEAD_LINES",
    "DEFAULT_LINE_HARD_CAP",
    "DEFAULT_RING_CAPACITY",
    "ToolResultBuffer",
    "ToolResultEntry",
    "truncate_for_display",
]
