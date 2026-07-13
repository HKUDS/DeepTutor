r"""Protocol-label parsing for streaming LLM responses.

The agentic engine drives LLM calls with a ``\`\`LABEL\`\`+content`` protocol:
prompts require one allowed label, double-backtick-wrapped, on the first line
of every reply, then the rest of the content. The parser detects that label
up front, tolerates a few provider/model formatting slips, and routes the
post-label stream accordingly.

Label sets are caller-supplied: chat uses ``(FINISH, TOOL, THINK)``, a solve
step uses ``(THINK, TOOL, FINISH, REPLAN)``, plan uses ``(PLAN,)``, etc.
"""

from __future__ import annotations

import re

LABEL_UNKNOWN = "UNKNOWN"
LABEL_PROBE_MAX_CHARS = 64

_INVISIBLE_PREFIX_CHARS = "﻿​‌‍"
_LABEL_SEPARATOR_CHARS = "\n\r \t:：-–—"


def strip_label_probe_prefix(buffer: str) -> str:
    """Trim leading whitespace and zero-width chars before label probing."""
    stripped = str(buffer or "")
    previous = None
    while stripped != previous:
        previous = stripped
        stripped = stripped.lstrip().lstrip(_INVISIBLE_PREFIX_CHARS)
    return stripped


def classify_label(
    buffer: str,
    *,
    allowed_labels: tuple[str, ...],
    final: bool = False,
) -> tuple[str, str] | None:
    r"""Inspect a content buffer for a leading ``\`\`LABEL\`\``` prefix.

    Returns ``(label, after_text)`` once an allowed label is detected after any
    leading whitespace — caller routes ``after_text`` and all subsequent chunks
    accordingly.

    Returns ``None`` while the buffer is too short or still a partial prefix
    match. The caller keeps buffering and tries again on the next chunk, and
    must fall back to :data:`LABEL_UNKNOWN` once the buffer exceeds
    :data:`LABEL_PROBE_MAX_CHARS` without a match.

    Accepts the wrapped form (``\`\`LABEL\`\``` preferred, with common
    one-/three-backtick variants tolerated) and a bare fallback (``LABEL``
    followed by a separator) — some models drop or alter the backticks on
    one-shot prompts and the bare form is unambiguous as long as the
    protocol labels are all-uppercase tokens. The wrapped form may be
    followed immediately by body text because Markdown inline-code styling
    visually separates the label even when the raw stream has no whitespace
    (for example ``\`\`FINISH\`\`你好``).

    ``final=True`` means the caller knows no more chunks are coming, so an
    exact bare label such as ``FINISH`` can be accepted even without a
    trailing separator.
    """
    stripped = strip_label_probe_prefix(buffer)
    for label in allowed_labels:
        wrapped = re.match(
            rf"^(?P<ticks>`+)\s*{re.escape(label)}\s*(?P=ticks)(?P<after>.*)$",
            stripped,
            flags=re.DOTALL,
        )
        if wrapped is not None:
            after = wrapped.group("after")
            if after and after[0] == "`":
                # Avoid accepting an over-closed / still-streaming wrapper
                # such as ``FINISH``` and leaking the extra backtick into
                # the routed body. A non-backtick tail is real body text,
                # even when the model forgot the separator after the label.
                continue
            # Eat the separating newline / spaces / punctuation after the
            # label so the body / reasoning text doesn't start with stray
            # blank lines or a locale-specific colon.
            return label, after.lstrip(_LABEL_SEPARATOR_CHARS)
        # Bare-label fallback: only when the label is followed by a clear
        # separator so we don't false-positive on a body that happens to
        # start with a token like ``FINISHED``. An empty tail (label
        # exactly matches buffer) is ambiguous while streaming — keep
        # buffering until the next chunk reveals a separator or a
        # continuation char. At stream end (``final=True``), accept it.
        if stripped.startswith(label):
            tail = stripped[len(label) :]
            if tail and tail[0] in _LABEL_SEPARATOR_CHARS:
                return label, tail.lstrip(_LABEL_SEPARATOR_CHARS)
            if final and not tail:
                return label, ""
    return None


def find_inline_labels(text: str, *, allowed_labels: tuple[str, ...]) -> list[str]:
    """Return labels that appear inside post-label body text.

    The protocol requires exactly one label per reply (on the first line).
    A second label found at the start of a later body line is a violation
    worth flagging. Mentions inside prose such as "next I should use
    ``TOOL``" are not action labels and must not trigger repair loops.
    """
    if not allowed_labels:
        return []
    pattern = "|".join(re.escape(label) for label in allowed_labels)
    raw = str(text or "")
    separators = re.escape(_LABEL_SEPARATOR_CHARS)
    wrapped = [
        match.group("label")
        for match in re.finditer(
            rf"(?m)^[^\S\r\n]*(?P<ticks>`+)\s*(?P<label>{pattern})\s*(?P=ticks)(?=$|[{separators}])",
            raw,
        )
    ]
    bare = re.findall(rf"(?m)^[^\S\r\n]*({pattern})(?=$|[{separators}])", raw)
    return [*wrapped, *bare]
