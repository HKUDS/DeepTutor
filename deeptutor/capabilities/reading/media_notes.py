"""Render the embedded-image note that ``read_material`` appends to its result.

Kept beside :mod:`deeptutor.capabilities.reading.tools` rather than inside it
because the note grew its own formatting rules (per-caption truncation, a line
budget) and ``tools.py`` sits against its size ceiling. Nothing here imports the
tool classes, so the extraction is cycle-free.

A row in ``media.json`` is ``{"name", "locator", "mime", "bytes"}`` and may
carry an optional ``"caption"`` written at ingestion by a vision model. The
caption is the only way a text model learns what an embedded figure shows when
the image itself is not attached to the turn — a non-current page, a unit read
from another tab, or any turn without the viewport seed.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# One caption is a short English sentence; anything longer is runaway output, so
# it is clipped before it reaches the model's context.
CAPTION_CHAR_LIMIT = 300
# The note is supporting evidence, not the answer: a media-heavy material must
# not crowd out the text the model was actually asked to read.
MAX_NOTE_LINES = 20


def _flatten(text: str) -> str:
    """Collapse whitespace so a caption cannot forge extra list lines."""
    return " ".join((text or "").split())


def _render_image(name: str, caption: str) -> str:
    """One list entry: the file name, plus its caption when there is one."""
    if not caption:
        return name
    clipped = _flatten(caption)
    if len(clipped) > CAPTION_CHAR_LIMIT:
        clipped = clipped[: CAPTION_CHAR_LIMIT - 1] + "…"
    return f"{name} — {clipped}"


def render_media_note(store: Any, material_id: str, unit: str, locators: Sequence[int]) -> str:
    """List the embedded images that live in the units just read.

    The reader pane displays these images next to their unit, and the turn
    already carries the ones on the user's current page — so when the user
    asks about a figure, the model knows it exists, where it sits, and that
    the image parts attached to the message are those figures. Rows carrying a
    caption also hand the text model what the figure shows.
    """
    try:
        rows = store.media_items(material_id)
    except Exception:
        return ""
    wanted = set(locators)
    by_locator: dict[int, list[tuple[str, str]]] = {}
    for row in rows:
        try:
            locator = int(row.get("locator") or 0)
        except (TypeError, ValueError):
            continue
        name = str(row.get("name") or "")
        if locator in wanted and name:
            caption = str(row.get("caption") or "").strip()
            by_locator.setdefault(locator, []).append((name, caption))
    if not by_locator:
        return ""
    entries = sorted(by_locator.items())
    shown, omitted = entries[:MAX_NOTE_LINES], entries[MAX_NOTE_LINES:]
    lines = [
        f"- {unit} {locator}: "
        + ", ".join(_render_image(name, caption) for name, caption in images)
        for locator, images in shown
    ]
    if omitted:
        # Name the count so the model treats the list as incomplete rather than
        # assuming the units hold exactly these figures.
        dropped = sum(len(images) for _, images in omitted)
        lines.append(f"({dropped} more images omitted)")
    return (
        "\n\nEmbedded images in the units above (shown in the reader pane; "
        "image parts attached to this conversation's messages are these "
        "figures):\n" + "\n".join(lines)
    )


__all__ = [
    "CAPTION_CHAR_LIMIT",
    "MAX_NOTE_LINES",
    "render_media_note",
]
