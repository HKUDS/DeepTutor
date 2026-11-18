"""Local renderers: real artefacts, no provider, no network.

Why these exist next to the provider adapters
----------------------------------------------
Phase 8 shipped with a mock renderer and proved the accounting with it. That is
honest for the *money* and useless for the *output*: nobody had ever seen a
pixel or heard a syllable the pipeline produced. These renderers close that gap
with the tools already on the machine -- PIL for images, the stdlib ``wave``
module for audio -- so the pipeline can be exercised end to end without an API
key and without pretending a mock is a provider.

What they are not
-----------------
Not a substitute for a real video provider. ``video_lesson`` here produces a
**storyboard**: a sequence of real frames with the real narration text burned in,
returned as a PNG contact sheet. It is genuinely useful for checking that the
script and the scene split are right, and it is *not* a video. Saying so in the
kind's own output is the difference between a fallback and a lie.

Persian needs shaping
---------------------
PIL has no raqm in most installs, so Arabic-script text drawn directly comes out
with disconnected letters in the wrong order. ``arabic_reshaper`` + ``bidi``
produce the presentation-form, right-to-left string that FreeType can draw. When
those two packages are absent, the renderer **refuses** rather than emitting
garbled Persian -- a broken lesson with correct billing is the worst outcome of
the three.

Audio is a tone envelope, not speech
------------------------------------
Without a TTS engine the only honest audio is a placeholder that lasts as long
as the narration would at reading speed. It is marked as such in the artefact's
metadata and in its filename. It exists so duration, storage and settlement can
be measured against something real; it is never presented to a student as a
lesson.
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import math
import struct
from typing import Any, Mapping

#: Where the DejaVu family lives on this image. A font that cannot draw Persian
#: is not a font that should be silently substituted, so the search is explicit
#: and a miss is an error.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
)

#: Persian is written right to left; PIL needs the string already reordered.
_PERSIAN_RANGE = ("\u0600", "\u06ff")


class RenderError(RuntimeError):
    """A local render could not be produced honestly."""


@dataclass(frozen=True)
class RenderSettings:
    width: int = 1280
    height: int = 720
    background: str = "#ffffff"
    foreground: str = "#111111"
    accent: str = "#2563eb"
    font_size: int = 40
    #: The attribution line the licence obliges us to carry. Rendered on the
    #: artefact itself, not only in the database: an obligation stored in a row
    #: the reader never sees has not been met, and the file is what gets shared.
    attribution: str = ""
    #: The chapter this artefact belongs to, drawn as the slide header.
    #: Separate from the body on purpose: the previous code used the first line
    #: of the body as the title, which on an audio-overview script is
    #: "در این ویدیو یاد می‌گیریم" -- a lead-in, not a title -- so every frame
    #: repeated it and the artefact introduced itself five times.
    chapter_title: str = ""


def _font_path() -> str:
    import os

    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise RenderError(
        "no usable font found; refusing to render rather than emit a blank image"
    )


def shape(text: str) -> str:
    """Presentation-form, visual-order string for PIL.

    Raises when the shaping packages are missing. Emitting unshaped Persian
    produces disconnected letters that look like corruption, and a copy of a
    broken lesson outlives the bug that made it.
    """
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError as exc:  # pragma: no cover - depends on the image
        raise RenderError(
            "arabic-reshaper and python-bidi are required to render Persian; "
            "without them the text would be disconnected and reversed"
        ) from exc

    # A string can mix Persian and a Latin technical term; reshaping the whole
    # string is still correct because the shaper leaves Latin alone and bidi
    # puts the runs in order.
    return get_display(arabic_reshaper.reshape(str(text or "")))


def _wrap(text: str, font: Any, draw: Any, max_width: int) -> list[str]:
    """Greedy wrap in visual order.

    Wrapping happens *after* shaping, so the width measured is the width that
    will actually be drawn. Wrapping the logical string and shaping each line
    afterwards would break words at the wrong end for RTL text.
    """
    words = str(text or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_attribution(draw: Any, settings: "RenderSettings", *, y: int | None = None) -> None:
    """Stamp the licence obligation onto the image.

    The attribution is split on " — " and each part is drawn on its own line:
    the Persian source title shaped and right-aligned, the Latin licence name
    and URL left-aligned without shaping. Drawing them as one string was the
    first attempt and it came out mangled -- a long URL inside an RTL run gets
    reordered by bidi and clipped at the margin, which produces something that
    looks like a corrupted file rather than a credit.

    Never truncated silently: if the parts do not fit in two lines the font
    shrinks, because an attribution cut off at the edge is not the attribution
    the licence asked for.
    """
    if not settings.attribution:
        return
    from PIL import ImageFont

    margin = int(settings.width * 0.03)
    parts = [part.strip() for part in settings.attribution.split("—") if part.strip()]
    persian = [p for p in parts if any("\u0600" <= ch <= "\u06ff" for ch in p)]
    latin = [p for p in parts if p not in persian]

    # Persian credit first (it sits at the bottom-right of the block), then the
    # licence terms in Latin. Two lines is the budget.
    lines: list[tuple[str, bool]] = []
    if persian:
        lines.append((" — ".join(persian), True))
    if latin:
        lines.append((" — ".join(latin), False))

    size = max(10, int(settings.font_size * 0.45))
    font = ImageFont.truetype(_font_path(), size)
    max_width = settings.width - 2 * margin
    # Shrink until every line fits, down to a floor where it is still legible.
    while size > 9 and any(
        draw.textlength(shape(text) if is_rtl else text, font=font) > max_width
        for text, is_rtl in lines
    ):
        size -= 1
        font = ImageFont.truetype(_font_path(), size)

    base = y if y is not None else settings.height - int(settings.height * 0.035)
    line_height = int(size * 1.5)
    for offset, (text, is_rtl) in enumerate(reversed(lines)):
        rendered = shape(text) if is_rtl else text
        draw.text(
            (settings.width - margin, base - offset * line_height),
            rendered,
            font=font,
            fill="#6b7280",
            anchor="rd",
        )


def render_slide(
    *,
    title: str,
    body: str,
    settings: RenderSettings,
    index: int = 1,
    total: int = 1,
) -> bytes:
    """One 16:9 slide as PNG bytes, Persian shaped and right-aligned."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (settings.width, settings.height), settings.background)
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(_font_path(), int(settings.font_size * 1.4))
    body_font = ImageFont.truetype(_font_path(), settings.font_size)
    small_font = ImageFont.truetype(_font_path(), int(settings.font_size * 0.7))

    margin = int(settings.width * 0.07)

    # A colour band rather than a border: it gives the eye somewhere to start
    # and it is the one element that needs no shaping, so it cannot be wrong.
    draw.rectangle(
        [(0, 0), (settings.width, int(settings.height * 0.055))], fill=settings.accent
    )

    if title:
        shaped_title = shape(title)
        draw.text(
            (settings.width - margin, int(settings.height * 0.16)),
            shaped_title,
            font=title_font,
            fill=settings.accent,
            anchor="ra",
        )

    if body:
        y = int(settings.height * 0.36)
        line_height = int(settings.font_size * 2.0)
        for line in _wrap(shape(body), body_font, draw, settings.width - 2 * margin):
            draw.text(
                (settings.width - margin, y),
                line,
                font=body_font,
                fill=settings.foreground,
                anchor="ra",
            )
            y += line_height
            if y > settings.height - margin:
                break

    if total > 1:
        # The counter is a Latin numeral on purpose: mixing Persian digits into
        # a shaped string inside a small label is a formatting bug waiting to
        # happen, and the slide number is a navigational aid, not content.
        draw.text(
            (margin, settings.height - margin),
            f"{index}/{total}",
            font=small_font,
            fill=settings.accent,
            anchor="ld",
        )

    _draw_attribution(draw, settings, y=settings.height - margin)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_slide_deck(*, script: Any, settings: RenderSettings | None = None) -> bytes:
    """A real multi-page deck, tiled into one contact-sheet PNG.

    One file rather than N is a compromise: the storage and download paths take
    a single artefact per job, and a zip would need a different content type
    and a preview that browsers cannot show inline. The contact sheet preserves
    what matters for review -- whether each slide reads correctly -- while
    staying one addressable asset.
    """
    from PIL import Image

    settings = settings or RenderSettings()
    sections = [s for s in (getattr(script, "outline", None) or []) if str(s).strip()]
    if not sections:
        sections = [str(getattr(script, "text", "") or "").strip() or "—"]

    title = settings.chapter_title.strip()
    if not title:
        lines = str(getattr(script, "text", "") or "").splitlines()
        if lines:
            title = lines[0]

    frames = [
        render_slide(
            title=title,
            body=section,
            settings=settings,
            index=index,
            total=len(sections),
        )
        for index, section in enumerate(sections, start=1)
    ]

    images = [Image.open(io.BytesIO(payload)) for payload in frames]
    columns = 2 if len(images) > 1 else 1
    rows = math.ceil(len(images) / columns)
    gap = 12
    canvas = Image.new(
        "RGB",
        (
            columns * settings.width + (columns + 1) * gap,
            rows * settings.height + (rows + 1) * gap,
        ),
        "#e5e7eb",
    )
    for position, image in enumerate(images):
        row, column = divmod(position, columns)
        canvas.paste(
            image,
            (
                gap + column * (settings.width + gap),
                gap + row * (settings.height + gap),
            ),
        )

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_mind_map(*, script: Any, settings: RenderSettings | None = None) -> bytes:
    """A radial mind map drawn from the outline.

    Drawn, not generated: the branches are the keywords the script layer
    extracted, so a wrong map is traceable to a wrong outline rather than to a
    model's mood. Edges are computed from the centre, which keeps the layout
    stable as branches are added.
    """
    from PIL import Image, ImageDraw, ImageFont

    settings = settings or RenderSettings()
    branches = [str(b) for b in (getattr(script, "outline", None) or []) if str(b).strip()]
    if not branches:
        raise RenderError("a mind map needs at least one branch")

    image = Image.new("RGB", (settings.width, settings.height), settings.background)
    draw = ImageDraw.Draw(image)
    node_font = ImageFont.truetype(_font_path(), int(settings.font_size * 0.85))
    centre_font = ImageFont.truetype(_font_path(), int(settings.font_size * 1.2))

    cx, cy = settings.width // 2, settings.height // 2
    # The centre is the topic. It must come from the first *branch*, not from
    # the raw script: the script starts with the chapter heading, so splitting
    # that string gave "فصل ۳ مشتق" -- a heading, wrapped across two lines and
    # clipped by the ellipse. The first branch is what the map is about.
    # The hub is the topic; the first branch is the *best* candidate for it, so
    # it is consumed rather than repeated. Drawing it twice (once as the hub,
    # once as a branch) looks like a data bug to a reader even when the layout
    # is intentional.
    centre_raw = branches[0] if branches else "موضوع"
    centre_text = shape(centre_raw)
    branches = branches[1:] if len(branches) > 1 else branches

    palette = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0891b2"]

    # Lay out by measured size, not by a fixed radius. A branch label is a
    # phrase now, not a single word, so a fixed radius threw two labels through
    # the hub: the boxes were wider than the gap the angle gave them. Each node
    # is sized first, then placed on a ring big enough to hold the widest one.
    count = len(branches)
    # The hub is sized first: the ring radius has to clear it, and the previous
    # order (ring, then hub) is why two labels sat on top of the topic text.
    hub_width, hub_height = 190, 74
    hub_box = draw.textbbox((0, 0), centre_text, font=centre_font)
    hub_width = max(hub_width, (hub_box[2] - hub_box[0]) + 56)
    max_hub = int(settings.width * 0.62)
    if hub_width > max_hub:
        scale = max_hub / hub_width
        centre_font = ImageFont.truetype(
            _font_path(), max(14, int(settings.font_size * 1.2 * scale))
        )
        hub_box = draw.textbbox((0, 0), centre_text, font=centre_font)
        hub_width = min(max_hub, (hub_box[2] - hub_box[0]) + 56)
    hub_height = max(hub_height, (hub_box[3] - hub_box[1]) + 40)

    labels: list[tuple[str, int, int, int]] = []
    for branch in branches:
        text = shape(branch)
        box = draw.textbbox((0, 0), text, font=node_font)
        width, height = box[2] - box[0], box[3] - box[1]
        labels.append((text, width, height, 14))

    padding = 14
    widest = max((w + 2 * padding for _, w, _, _ in labels), default=0)
    tallest = max((h + 2 * padding for _, _, h, _ in labels), default=0)
    hub_half = hub_width // 2 + 8

    # Horizontal room each node needs is half its width plus half the hub, so
    # the ring radius must clear that for the worst case at its angle.
    min_radius = max(widest, tallest * 2, hub_half * 2) + padding
    max_radius = int(min(settings.width, settings.height) * 0.42)
    radius = max(min_radius, min(int(min(settings.width, settings.height) * 0.33), max_radius))
    # Vertical squash keeps the ellipse inside a 16:9 canvas, but the vertical
    # radius must still clear the tallest box.
    vertical = min(int(radius * 0.72), (settings.height // 2) - tallest - padding)
    vertical = max(vertical, tallest + padding)

    for index, (branch, (label, width, height, padding)) in enumerate(zip(branches, labels)):
        angle = (2 * math.pi * index / count) - (math.pi / 2)
        x = cx + int(radius * math.cos(angle))
        y = cy + int(vertical * math.sin(angle))
        # Keep the box inside the canvas even when the ring is wide.
        x = max(width // 2 + padding, min(x, settings.width - width // 2 - padding))
        # The bottom margin holds the attribution; a node drawn into it collides
        # with the credit line, which is both ugly and a licence problem.
        bottom_limit = settings.height - height // 2 - padding - int(settings.height * 0.13)
        y = max(height // 2 + padding, min(y, bottom_limit))
        colour = palette[index % len(palette)]
        draw.line([(cx, cy), (x, y)], fill=colour, width=3)

        draw.rounded_rectangle(
            [
                (x - width // 2 - padding, y - height // 2 - padding),
                (x + width // 2 + padding, y + height // 2 + padding),
            ],
            radius=12,
            fill="#ffffff",
            outline=colour,
            width=3,
        )
        draw.text((x, y), label, font=node_font, fill=colour, anchor="mm")

    # Size the hub to the label rather than the label to a guessed hub. A fixed
    # ellipse clipped any centre word longer than a few characters, and the
    # clipping was silent -- the image looked deliberate but the topic was
    # unreadable.
    draw.ellipse(
        [(cx - hub_width // 2, cy - hub_height // 2),
         (cx + hub_width // 2, cy + hub_height // 2)],
        fill="#111827",
        outline=settings.accent,
        width=4,
    )
    draw.text((cx, cy), centre_text, font=centre_font, fill="#ffffff", anchor="mm")
    _draw_attribution(draw, settings)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_infographic(*, script: Any, settings: RenderSettings | None = None) -> bytes:
    """Stacked information blocks, one per outline line."""
    from PIL import Image, ImageDraw, ImageFont

    settings = settings or RenderSettings()
    blocks = [str(b) for b in (getattr(script, "outline", None) or []) if str(b).strip()]
    if not blocks:
        raise RenderError("an infographic needs at least one block")

    image = Image.new("RGB", (settings.width, settings.height), settings.background)
    draw = ImageDraw.Draw(image)
    heading_font = ImageFont.truetype(_font_path(), int(settings.font_size * 1.2))
    body_font = ImageFont.truetype(_font_path(), int(settings.font_size * 0.8))

    margin = int(settings.width * 0.06)
    heading = str(getattr(script, "text", "") or "").splitlines()[:1]
    if heading:
        draw.text(
            (settings.width - margin, margin),
            shape(heading[0]),
            font=heading_font,
            fill=settings.accent,
            anchor="ra",
        )

    available = settings.height - 3 * margin
    block_height = max(60, available // max(1, len(blocks)) - 12)
    palette = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#dc2626", "#0891b2"]
    y = 2 * margin
    for index, block in enumerate(blocks):
        colour = palette[index % len(palette)]
        draw.rounded_rectangle(
            [(margin, y), (settings.width - margin, y + block_height)],
            radius=14,
            fill="#f8fafc",
            outline=colour,
            width=3,
        )
        draw.rectangle(
            [(settings.width - margin - 8, y + 10), (settings.width - margin - 4, y + block_height - 10)],
            fill=colour,
        )
        label = shape(block)
        lines = _wrap(label, body_font, draw, settings.width - 2 * margin - 60)
        text_y = y + block_height // 2 - (len(lines) - 1) * settings.font_size * 0.6
        for line in lines[:3]:
            draw.text(
                (settings.width - margin - 24, text_y),
                line,
                font=body_font,
                fill=settings.foreground,
                anchor="ra",
            )
            text_y += int(settings.font_size * 1.4)
        y += block_height + 12

    _draw_attribution(draw, settings)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_silence(*, seconds: float, sample_rate: int = 22050) -> bytes:
    """A real WAV of the requested length, with a gentle amplitude envelope.

    Not speech. It is a real file with a real duration so that storage, download
    and settlement are exercised against actual bytes, and it is deliberately
    not silent silence -- a flat zero file is easy to mistake for a corrupt one.
    """
    seconds = max(0.2, min(float(seconds or 0), 120.0))
    frames = int(sample_rate * seconds)
    payload = bytearray()
    for index in range(frames):
        # 220 Hz at very low amplitude with a slow tremolo: audibly a placeholder
        # tone, never mistakable for a narration track.
        envelope = 0.5 - 0.5 * math.cos(2 * math.pi * min(1.0, index / max(1, frames)))
        sample = int(1500 * envelope * math.sin(2 * math.pi * 220 * index / sample_rate))
        payload += struct.pack("<h", sample)

    buffer = io.BytesIO()
    import wave

    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(bytes(payload))
    return buffer.getvalue()


@dataclass(frozen=True)
class Rendered:
    """A local render's bytes plus what it honestly is."""

    data: bytes
    mime_type: str
    extension: str
    note: str = ""


def render_local(
    kind: str,
    payload: Mapping[str, Any],
    *,
    script: Any,
    settings: RenderSettings | None = None,
) -> Rendered:
    """Dispatch to the local renderer for a kind.

    ``audio_overview`` and ``video_lesson`` are explicitly placeholder-shaped:
    there is no TTS engine and no video encoder on this machine, and inventing
    one out of sine waves would be worse than naming the limitation.
    """
    # The attribution comes from the job payload, resolved once at submit time,
    # so every kind produced under the same licence carries the same credit.
    settings = settings or RenderSettings(
        attribution=str(payload.get("attribution") or ""),
        chapter_title=str(payload.get("chapter_title") or ""),
    )

    if kind == "slide_deck":
        return Rendered(
            render_slide_deck(script=script, settings=settings), "image/png", ".png", "local renderer"
        )
    if kind == "mind_map":
        return Rendered(
            render_mind_map(script=script, settings=settings), "image/png", ".png", "local renderer"
        )
    if kind == "infographic":
        return Rendered(
            render_infographic(script=script, settings=settings),
            "image/png",
            ".png",
            "local renderer",
        )
    if kind == "audio_overview":
        from deeptutor.services.studio.script import estimate_duration

        seconds = estimate_duration(kind, str(getattr(script, "text", "") or "")) or 5.0
        return Rendered(
            render_silence(seconds=seconds),
            "audio/wav",
            ".wav",
            "placeholder tone: no TTS engine on this host",
        )
    if kind == "video_lesson":
        return Rendered(
            render_slide_deck(script=script, settings=settings),
            "image/png",
            ".png",
            "storyboard only: no video encoder on this host",
        )
    raise RenderError(f"no local renderer for {kind!r}")


__all__ = [
    "RenderError",
    "RenderSettings",
    "Rendered",
    "render_infographic",
    "render_local",
    "render_mind_map",
    "render_silence",
    "render_slide",
    "render_slide_deck",
    "shape",
]
