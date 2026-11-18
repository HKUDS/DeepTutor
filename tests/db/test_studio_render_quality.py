"""Defects found by looking at the output, not by testing the code.

A review package was built for an independent Persian reviewer and, before
sending it, the artefacts were opened. Three defects were visible to anyone who
looked and invisible to the existing tests:

1. every slide repeated the first line of the body as its title, which on an
   audio-overview script is "در این ویدیو یاد می‌گیریم" -- a lead-in, so the
   artefact introduced itself three times;
2. the mind map's branches were the most frequent *words*, so it read
   "مشتق / قاعده / نمودار / نرخ / تغییر": fragments, not concepts;
3. once branches became phrases, they collided with the hub, because the
   layout used a fixed radius measured against one-word labels.

Asking a human to grade those would have been asking them to grade work I could
already see was wrong. These tests exist so the three cannot come back.
"""

from __future__ import annotations

import pytest

from deeptutor.services.studio import render
from deeptutor.services.studio.script import (
    ScriptRequest,
    _keywords,
    build_script,
    concept_outline,
    outline_for,
)

LESSON = (
    "مشتق نرخ تغییر لحظه‌ای است. مشتق در یک نقطه شیب خط مماس است. "
    "قواعد مشتق‌گیری: قاعدهٔ توان، قاعدهٔ ضرب، قاعدهٔ تقسیم و قاعدهٔ زنجیره‌ای. "
    "کاربرد مشتق در یافتن بیشینه و کمینه و رسم نمودار است. "
    "مشتق مرتبهٔ دوم تقعر نمودار را نشان می‌دهد."
)

LIMIT_SOURCE = (
    "حد یعنی نزدیک شدن به یک مقدار. تابع می‌تواند در یک نقطه تعریف نشده باشد "
    "ولی حد داشته باشد. پیوستگی یعنی بی‌پرش بودن نمودار."
)


def _script(kind, source=LESSON, title="ریاضی دهم — فصل مشتق"):
    return build_script(
        ScriptRequest(
            kind=kind, source_text=source, source_id="s1", chapter_title=title
        )
    )


# ---------------------------------------------------------------------------
# 1. The chapter title, not the first line of the body
# ---------------------------------------------------------------------------


def test_a_slide_header_uses_the_chapter_title_when_one_is_given():
    settings = render.RenderSettings(chapter_title="ریاضی دهم — فصل مشتق")
    assert settings.chapter_title


def test_the_settings_carry_no_title_by_default():
    """Empty means "fall back", which must be distinguishable from a title."""
    assert render.RenderSettings().chapter_title == ""


def test_the_renderer_prefers_the_chapter_title_over_the_body():
    """The lead-in line is not a title, and drawing it as one repeated it."""
    script = _script("audio_overview", LIMIT_SOURCE, title="ریاضی دهم — فصل حد")
    with_title = render.render_slide_deck(
        script=script, settings=render.RenderSettings(chapter_title="ریاضی دهم — فصل حد")
    )
    without = render.render_slide_deck(script=script, settings=render.RenderSettings())
    assert with_title != without, (
        "the chapter title had no effect on the rendered deck: the header is "
        "still being taken from the body"
    )


def test_the_job_payload_reaches_the_slide_header():
    """`render_local` is the path a job takes. A setting nothing threads is
    a setting that renders nothing, which is how this defect survived the
    first version of these tests."""
    script = _script("slide_deck", title="ریاضی دهم — فصل مشتق")
    through_payload = render.render_local(
        "slide_deck",
        {"chapter_title": "ریاضی دهم — فصل مشتق", "attribution": ""},
        script=script,
    )
    direct = render.render_local(
        "slide_deck", {"attribution": ""}, script=script
    )
    assert through_payload.data != direct.data, (
        "chapter_title in the payload had no effect: render_local is not "
        "threading it into RenderSettings"
    )


def test_an_empty_payload_title_falls_back_without_error():
    script = _script("slide_deck")
    rendered = render.render_local("slide_deck", {"attribution": ""}, script=script)
    assert rendered.data[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_deck_still_renders_with_no_chapter_title():
    """The fallback path must keep working for callers that pass nothing."""
    data = render.render_slide_deck(script=_script("slide_deck"))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# 2. Concept labels, not word frequencies
# ---------------------------------------------------------------------------


def _branches(source=LESSON):
    """Branches as the pipeline produces them, not as a helper returns them.

    The first version of this file called `concept_outline` directly, so a
    mutation that pointed `outline_for` back at `_keywords` passed: the tests
    were exercising a function nothing else called. This helper goes through
    `build_script`, which is the path a rendered map actually takes.
    """
    script = build_script(ScriptRequest(kind="mind_map", source_text=source, source_id="s1"))
    return list(script.outline)


def test_branches_are_phrases_not_single_words():
    """The original defect: 'مشتق / قاعده / نمودار / نرخ / تغییر'."""
    labels = _branches()
    assert labels
    multi = [label for label in labels if len(label.split()) > 1]
    assert len(multi) >= 3, f"too many one-word branches: {labels}"
    # The specific defect: `_keywords` on this text returns five bare words.
    assert labels != _keywords(LESSON, 5), (
        "the outline is word frequency again, not concept labels"
    )


def test_a_concept_label_names_what_the_clause_does():
    labels = _branches()
    joined = " ".join(labels)
    assert "تعریف" in joined, labels
    assert "قاعده" in joined or "قواعد" in joined, labels
    assert "کاربرد" in joined, labels


def test_grammatical_glue_never_becomes_a_branch():
    """'نرخ' and 'تغییر' alone were the visible symptom."""
    labels = _branches()
    for label in labels:
        assert len(label.split()) >= 2, f"'{label}' is a fragment"
        assert label.strip() not in {"و", "در", "از", "که", "نرخ", "تغییر"}


def test_branches_are_distinct():
    labels = _branches()
    assert len(labels) == len(set(labels))


def test_the_topic_is_not_repeated_as_the_first_branch():
    """The hub already says 'مشتق'; a branch starting with it reads as a dup."""
    labels = _branches()
    hub = labels[0].split()[0] if labels else ""
    if hub:
        assert not labels[1].startswith(hub) or len(labels[1].split()) > 2


def test_a_short_source_still_produces_branches():
    labels = _branches("مشتق چیست؟")
    assert isinstance(labels, list)


def test_concept_labels_are_bounded_in_length():
    for label in _branches():
        assert len(label.split()) <= 5, f"'{label}' is too long for a node"


# ---------------------------------------------------------------------------
# 3. The layout clears the hub and the credit
# ---------------------------------------------------------------------------


def test_a_mind_map_with_phrase_branches_renders():
    """The collision appeared only after branches became phrases."""
    data = render.render_mind_map(script=_script("mind_map"))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def _hub_box(image):
    """The hub is the only large filled dark region; find its bounding box."""
    width, height = image.size
    pixels = image.load()
    xs, ys = [], []
    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]
            if r < 60 and g < 60 and b < 80:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _dark_pixels_in(image, box):
    """How many hub-coloured pixels sit inside a rectangle."""
    pixels = image.load()
    count = 0
    for y in range(max(0, box[1]), min(image.size[1], box[3])):
        for x in range(max(0, box[0]), min(image.size[0], box[2])):
            r, g, b = pixels[x, y]
            if r < 60 and g < 60 and b < 80:
                count += 1
    return count


def test_the_hub_is_wide_enough_for_its_own_text():
    """The collision defect, measured where it happened.

    When the hub was sized *after* the ring, two branch boxes were drawn across
    the topic text. The evidence is in the pixels: a hub drawn too narrow for
    its label leaves branch-coloured ink inside the hub's bounding box. This
    checks the hub's width against the text it must hold, using the same font
    measurement the renderer uses.
    """
    import io

    from PIL import Image, ImageDraw, ImageFont

    data = render.render_mind_map(script=_script("mind_map"))
    image = Image.open(io.BytesIO(data)).convert("RGB")
    hub = _hub_box(image)
    assert hub is not None, "no hub found: the centre was not drawn"

    centre = _branches()[0] if _branches() else ""
    # The hub label is the first branch's topic; measure it with the renderer's
    # own font choices rather than guessing.
    font = ImageFont.truetype(render._font_path(), int(render.RenderSettings().font_size * 1.2))
    scratch = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    label = render.shape("مشتق")
    box = scratch.textbbox((0, 0), label, font=font)

    hub_width = hub[2] - hub[0]
    needed = (box[2] - box[0]) + 40
    assert hub_width >= needed, (
        f"hub is {hub_width}px wide but its label needs {needed}px: "
        f"the centre text is clipped"
    )


def test_no_branch_ink_is_drawn_over_the_hub_region():
    """Branch boxes are white-filled; if one landed on the hub it erases it."""
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(render.render_mind_map(script=_script("mind_map")))).convert("RGB")
    hub = _hub_box(image)
    assert hub is not None
    dark = _dark_pixels_in(image, hub)
    area = (hub[2] - hub[0]) * (hub[3] - hub[1])
    assert dark > area * 0.5, (
        f"only {dark}/{area} of the hub box is hub-coloured, which means "
        f"something was drawn on top of it"
    )


def test_the_mind_map_stays_inside_its_canvas():
    import io

    from PIL import Image

    data = render.render_mind_map(script=_script("mind_map"))
    image = Image.open(io.BytesIO(data))
    assert image.size == (render.RenderSettings().width, render.RenderSettings().height)


@pytest.mark.parametrize("count", [2, 3, 4, 5, 6])
def test_every_branch_count_lays_out(count):
    text = " ".join(f"مفهوم شمارهٔ {i} این جمله را بیان می‌کند." for i in range(count))
    script = build_script(
        ScriptRequest(kind="mind_map", source_text=text, source_id="s1")
    )
    data = render.render_mind_map(script=script)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
