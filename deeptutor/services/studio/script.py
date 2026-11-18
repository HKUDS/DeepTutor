"""Source-aware Persian scripts for media jobs.

Why this is a separate module from the renderers
------------------------------------------------
The renderers (voice, video, image) turn text into bytes. They do not decide
*what* the text says, and they should not: the same script may be spoken,
drawn as slides, or reduced to a mind map. This module owns the text, and every
artefact in the library can point back to the script that produced it.

Two rules it enforces, both from things that went wrong earlier in the project:

**Persian output is the default, not a translation step.** A prompt that says
"answer in Persian" after a long English system prompt still produces English
half the time. The instruction has to be first, in Persian, and the source text
has to be quoted rather than paraphrased through an intermediate language.

**Provenance travels with the text.** ``source_id`` is not decoration: it is how
a licence attaches to an asset. An asset with no ``source_id`` is one the
pipeline wrote from the user's own prompt, and it must be marked as such rather
than left blank and silently treated as licensed content.

Nothing here calls a provider. ``build_script`` is a pure function so the
quality of its output can be inspected and tested without an API key, and the
caller decides whether to spend tokens running it through a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

#: What an asset is derived from. Recorded on every artefact so a licence
#: question can always be answered from the asset row alone.
PROVENANCE_USER_PROMPT = "user_prompt"
PROVENANCE_SOURCE = "source"

#: Persian numerals, because a lesson that says "3" among Persian words reads
#: as a different register to a student who reads "۳".
_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

#: Sentence-ending punctuation, both Persian and Latin. Persian uses the same
#: Arabic question mark (؟) and the Latin full stop is common in technical text.
_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+")

#: ZWNJ, which Persian uses to join prefixes but which breaks naive word
#: matching if left inside a token boundary.
_ZWNJ = "\u200c"

#: Words that carry no meaning as a mind-map branch. Persian is full of copulas
#: and light verbs that outrank the actual topic in any raw frequency count:
#: a map whose biggest branch is "است" is worse than no map, because it looks
#: authoritative and says nothing.
_PERSIAN_STOPWORDS = frozenset(
    """
    است هست هستند بود بودند شد شدند می‌شود می‌شوند می‌کند می‌کنند می‌دهد می‌گیرد
    که این آن را را از به با در بر برای تا هم نیز ولی اما یا اگر چون چه چیزی
    یک دو سه خود ما شما او ایشان آنها اینها کار مورد طور صورت گونه بخش فصل
    می‌باشد باشد باشند دارد دارند داشت داشتند کند کنند کرده کردن
    """.split()
)

#: Characters that already end a clause; appending a full stop after one of
#: these produces "چیست؟." which reads as a typo in Persian.
_CLOSERS = ("،", ".", "!", "؟", ":", "؛", "…")


@dataclass(frozen=True)
class ScriptRequest:
    """Everything needed to write a script, without a provider call."""

    kind: str
    prompt: str = ""
    #: The text of the source, when the caller has it. Used verbatim as the
    #: body so the model does not get a chance to lose the content.
    source_text: str = ""
    source_id: str | None = None
    chapter_title: str = ""
    licence_code: str = ""
    #: Target length in words, for kinds where length matters (audio, video).
    target_words: int | None = None
    #: Extra instructions from the caller (tone, audience grade).
    instructions: str = ""
    audience: str = ""


@dataclass(frozen=True)
class Script:
    """A generated script plus what it is allowed to claim."""

    text: str
    language: str
    provenance: str
    source_id: str | None
    licence_code: str
    outline: list[str] = field(default_factory=list)
    #: True when the body came from the source text rather than the prompt.
    from_source: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "provenance": self.provenance,
            "source_id": self.source_id,
            "licence_code": self.licence_code,
            "outline": list(self.outline),
            "from_source": self.from_source,
        }


#: Per-kind shaping. These are not prompts sent to a model; they are the
#: structural decisions that change what a *good* script looks like, and getting
#: them wrong is why generated lessons sound like an essay read aloud.
_SHAPES: dict[str, dict[str, Any]] = {
    "audio_overview": {
        "intro": "به این درس خوش آمدید.",
        "lead": "در این گفتار می‌خواهیم بدانیم",
        "words_per_minute": 130,
        "max_words": 900,
        "section_prefix": "بخش",
    },
    "video_lesson": {
        "intro": "در این ویدیو یاد می‌گیریم",
        "lead": "نکتهٔ اصلی این است که",
        "words_per_minute": 120,
        "max_words": 1400,
        "section_prefix": "صحنهٔ",
    },
    "slide_deck": {
        "intro": "",
        "lead": "",
        "words_per_minute": 0,
        "max_words": 40,  # per slide, not total
        "section_prefix": "اسلاید",
    },
    "mind_map": {
        "intro": "",
        "lead": "",
        "words_per_minute": 0,
        "max_words": 8,  # per node
        "section_prefix": "شاخهٔ",
    },
    "infographic": {
        "intro": "",
        "lead": "",
        "words_per_minute": 0,
        "max_words": 12,  # per block
        "section_prefix": "بلوک",
    },
}


def to_persian_digits(text: str) -> str:
    return text.translate(_PERSIAN_DIGITS)


def _sentences(text: str) -> list[str]:
    """Split on sentence boundaries, keeping the punctuation.

    Persian paragraphs often use ideographic spacing between sentences, so the
    split has to tolerate both newlines and a single space after the stop.
    """
    text = re.sub(r"[ \t]*\n+[ \t]*", " ", str(text or "")).strip()
    if not text:
        return []
    parts = _SENTENCE_END.split(text)
    return [part.strip() for part in parts if part.strip()]


def _keywords(text: str, limit: int) -> list[str]:
    """Pick the most repeated non-trivial words, preserving first appearance.

    Crude on purpose. A stemmer for Persian is a project of its own, and a
    naive frequency count is enough to give a mind map's branches something to
    hang on. When this is wrong it is visibly wrong, which is better than a
    clever heuristic that is subtly wrong.
    """
    words = re.findall(r"[\w\u0600-\u06FF" + _ZWNJ + r"]{3,}", str(text or ""))
    counts: dict[str, int] = {}
    order: dict[str, int] = {}
    for index, word in enumerate(words):
        key = word.replace(_ZWNJ, "").strip()
        if not key or key in _PERSIAN_STOPWORDS:
            continue
        counts[key] = counts.get(key, 0) + 1
        order.setdefault(key, index)
    ranked = sorted(counts, key=lambda w: (-counts[w], order[w]))
    return ranked[:limit]


def outline_for(kind: str, text: str, *, max_sections: int = 5) -> list[str]:
    """The structural skeleton of a script, per kind.

    Slides and mind maps are *structure first*: their quality is decided by
    whether the branches are balanced and the slides are one idea each, not by
    the prose. Returning the outline separately lets a renderer lay it out
    without re-parsing the script.
    """
    sentences = _sentences(text)
    if kind == "mind_map":
        return _keywords(text, max_sections)
    if kind in {"slide_deck", "infographic"}:
        # One sentence per slide/node, truncated to the kind's line budget.
        budget = int(_SHAPES.get(kind, {}).get("max_words") or 40)
        return [
            " ".join(sentence.split()[:budget]) for sentence in sentences[: max_sections * 2]
        ]
    # Audio and video: group sentences into sections of roughly equal size.
    if not sentences:
        return []
    per_section = max(1, len(sentences) // max_sections + 1)
    return [
        " ".join(sentences[start : start + per_section])
        for start in range(0, min(len(sentences), per_section * max_sections), per_section)
    ]


def build_script(request: ScriptRequest) -> Script:
    """Compose a Persian script from a prompt and/or a source.

    Deterministic and provider-free: this produces the *plan* a model or a
    renderer then fills in. Keeping it pure means the Persian can be reviewed
    line by line in a test rather than depending on a model's mood.
    """
    kind = str(request.kind or "").strip()
    if kind not in _SHAPES:
        raise ValueError(f"unknown media kind {kind!r}")

    source_text = str(request.source_text or "").strip()
    prompt = str(request.prompt or "").strip()
    if not source_text and not prompt:
        raise ValueError("a script needs either a source text or a prompt")

    shape = _SHAPES[kind]
    body = source_text or prompt
    from_source = bool(source_text)

    # Provenance is decided by what the text actually came from, not by whether
    # the caller happened to pass a source_id. An asset built from the user's
    # own prompt is not licensed content and must never be recorded as if it
    # were -- that is the difference between a provenance record and a label.
    provenance = PROVENANCE_SOURCE if from_source else PROVENANCE_USER_PROMPT
    if from_source and not request.source_id:
        raise ValueError(
            "a script built from source text needs a source_id, or its licence "
            "cannot be traced back to anything"
        )

    style = str(request.audience or "").strip()
    heading_parts = [part for part in (request.chapter_title.strip(), prompt) if part]
    heading = " — ".join(heading_parts) if heading_parts else ""

    lines: list[str] = []
    if shape["intro"]:
        lines.append(shape["intro"])
    if heading:
        lines.append(heading if heading.endswith(_CLOSERS) else heading + ".")

    sections = outline_for(kind, body, max_sections=int(shape.get("sections") or 5))
    if kind in {"audio_overview", "video_lesson"} and sections:
        for index, section in enumerate(sections, start=1):
            marker = to_persian_digits(str(index))
            lines.append(f"{shape['section_prefix']} {marker}: {section}")
    elif kind in {"slide_deck", "infographic"}:
        for index, section in enumerate(sections, start=1):
            lines.append(f"{shape['section_prefix']} {to_persian_digits(str(index))}: {section}")
    elif kind == "mind_map":
        # A mind map's script *is* its branches; the renderer draws the centre.
        lines.append(" | ".join(sections))

    if style:
        lines.append(f"مخاطب: {style}.")
    if request.instructions:
        lines.append(str(request.instructions).strip())

    # Word budget: trim only the narrative kinds. A slide deck's budget is per
    # slide, so trimming the whole thing would silently delete slides.
    text = "\n".join(line for line in lines if line).strip()
    budget = int(shape.get("max_words") or 0)
    if budget and kind in {"audio_overview", "video_lesson"}:
        words = text.split()
        if len(words) > budget:
            text = " ".join(words[:budget]) + " …"

    return Script(
        text=text,
        language="fa",
        provenance=provenance,
        source_id=request.source_id if from_source else None,
        licence_code=str(request.licence_code or ""),
        outline=sections,
        from_source=from_source,
    )


def estimate_duration(kind: str, text: str) -> float | None:
    """Rough spoken length. None for kinds that are not spoken.

    Used to size a video job *before* it runs, which is the only way a
    per-second provider cost can be estimated at all.
    """
    rate = int(_SHAPES.get(kind, {}).get("words_per_minute") or 0)
    if not rate:
        return None
    words = len(str(text or "").split())
    return round(words / rate * 60, 1)


def quality_checklist(kind: str) -> list[dict[str, str]]:
    """The human checklist Gate 8 asks for.

    Returned as data rather than prose so a reviewer can fill it in and a report
    can quote it, instead of the criteria living only in someone's head.
    """
    common = [
        {
            "id": "persian_register",
            "question": "آیا متن به فارسی روان نوشته شده و از ترجمهٔ ماشینی خوانده نمی‌شود؟",
        },
        {
            "id": "technical_terms",
            "question": "آیا اصطلاحات فنی یکدست به کار رفته‌اند (یا معادل فارسی، یا لاتین، نه هر دو در یک متن)؟",
        },
        {
            "id": "digits",
            "question": "آیا اعداد فارسی نوشته شده‌اند؟",
        },
        {
            "id": "pronunciation",
            "question": "آیا جمله‌ها برای شنیدن ساخته شده‌اند (نه برای خواندن)؟",
        },
        {
            "id": "accuracy",
            "question": "آیا هر ادعای متن در منبع قابل ردیابی است؟",
        },
    ]
    specifics = {
        "audio_overview": [
            {"id": "pacing", "question": "آیا سرعت گفتار برای پایهٔ هدف مناسب است؟"},
            {"id": "no_reading", "question": "آیا متن صرفاً خواندنِ یک صفحه نیست؟"},
        ],
        "video_lesson": [
            {"id": "scene_match", "question": "آیا هر صحنه با جملهٔ متن هم‌زمان است؟"},
            {"id": "no_wall_of_text", "question": "آیا روی صفحه دیوار متن نداریم؟"},
        ],
        "slide_deck": [
            {"id": "one_idea", "question": "آیا هر اسلاید فقط یک ایده دارد؟"},
            {"id": "readable", "question": "آیا متن اسلاید از فاصلهٔ کلاس خوانا است؟"},
        ],
        "mind_map": [
            {"id": "balanced", "question": "آیا شاخه‌ها متعادل‌اند و یک شاخه همه‌چیز را نمی‌بلعد؟"},
            {"id": "labelled", "question": "آیا هر شاخه برچسب کوتاه و معنادار دارد؟"},
        ],
        "infographic": [
            {"id": "hierarchy", "question": "آیا سلسله‌مراتب بصری با اهمیت مطلب هم‌خوان است؟"},
            {"id": "no_filler", "question": "آیا هیچ بلوکی فقط پرکننده است؟"},
        ],
    }
    return common + specifics.get(kind, [])


__all__ = [
    "PROVENANCE_SOURCE",
    "PROVENANCE_USER_PROMPT",
    "Script",
    "ScriptRequest",
    "build_script",
    "estimate_duration",
    "outline_for",
    "quality_checklist",
    "to_persian_digits",
]
