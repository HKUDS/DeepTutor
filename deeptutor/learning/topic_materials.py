"""Expose a mastery topic's selected materials to the tutoring turn.

A topic's sources are chosen once, in the create-topic wizard, and were until
now consumed exactly once — to ground the outline generation. Nothing carried
them into tutoring, so the tutor taught a learner's own book from parametric
memory alone while its system prompt claimed to be teaching *from* it.

This module closes that gap by expressing topic materials as an *Attached
Sources* manifest plus a ``{source_id: full_text}`` index — the same shape
chat uses. Unlike chat, that index is never fed into
``context.metadata["source_index"]``: that key wakes
:class:`~deeptutor.capabilities.explore_context.ExploreContextCapability`'s
forced pre-pass, which reads everything relevant *before* the model's first
token. Tutoring wants the opposite posture — the tutor decides for itself,
knowledge point by knowledge point, whether a material is worth reading this
turn. The manifest (announced every turn) and the index (read on demand
through ``read_source``, mounted directly by
:class:`~deeptutor.capabilities.mastery.loop.MasteryLoopCapability`) are wired
up in :mod:`deeptutor.services.session.turn_runtime`.

Granularity is per **chapter**, not per book: a whole book cannot be read into
one tool result, and a chapter is the unit a tutor actually needs for one
knowledge point. Notebooks stay whole — they are already record-sized.

Knowledge bases are listed but carry no ``source_id``: they are searched with
``rag``, not read. Listing them anyway is the point — the tutor must be able to
tell what it has from what it merely knows the name of.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# One chapter's serialized text. Matches the chat book-context page budget, so
# a chapter read here costs the tutor what a page selection costs chat.
MAX_CHAPTER_CHARS = 24_000
# Whole-book and whole-notebook ceilings. These bound the in-memory index only
# (the manifest itself lists identities, never full text), so they can be
# generous without touching the prompt budget.
MAX_BOOK_CHARS = 240_000
MAX_NOTEBOOK_CHARS = 120_000
MAX_TOTAL_CHARS = 600_000
# A book with hundreds of chapters would otherwise bury the manifest.
MAX_CHAPTERS_PER_BOOK = 40
# Per-row hint length. Long enough to choose a chapter, short enough that a
# 40-chapter book stays readable.
MAX_OUTLINE_CHARS = 220


@dataclass(frozen=True)
class TopicMaterial:
    """One row of the topic-materials manifest.

    ``sid`` is empty for materials that are searched rather than read (a
    knowledge base), and for materials that could not be loaded. Only rows with
    a ``sid`` reach ``source_index``.
    """

    sid: str
    kind: str
    name: str
    outline: str = ""
    full_text: str = ""
    available: bool = True
    note: str = ""

    @property
    def readable(self) -> bool:
        return bool(self.sid and self.full_text.strip())


@dataclass
class TopicMaterials:
    materials: list[TopicMaterial] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.materials

    def source_index(self) -> dict[str, str]:
        return {m.sid: m.full_text for m in self.materials if m.readable}


def _clip(text: str, limit: int) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def _format_size(char_count: int) -> str:
    if char_count >= 1024:
        return f"~{round(char_count / 1024)} KB"
    return f"~{char_count} chars"


def _load_book_materials(source_id: str, label: str, budget: int) -> list[TopicMaterial]:
    """One material per chapter, so the tutor can read the part it needs.

    A chapter with no generated pages yet is still listed — as unreadable, with
    the reason — because "this chapter exists but has not been written" is
    something the tutor must be able to say instead of inventing its contents.
    """
    from deeptutor.book.context import build_book_context
    from deeptutor.book.storage import get_book_storage

    storage = get_book_storage()
    book = storage.load_book(source_id)
    spine = storage.load_spine(source_id)
    if book is None or spine is None or not spine.chapters:
        return [
            TopicMaterial(
                sid="",
                kind="book",
                name=label,
                available=False,
                note="book has no generated chapters yet",
            )
        ]

    title = str(getattr(book, "title", "") or label).strip() or label
    materials: list[TopicMaterial] = []
    spent = 0
    chapters = sorted(spine.chapters, key=lambda chapter: chapter.order)
    for index, chapter in enumerate(chapters[:MAX_CHAPTERS_PER_BOOK], start=1):
        chapter_name = f"{title} · {index}. {_clean_name(chapter.title) or chapter.id}"
        outline = _clip(
            chapter.summary or "; ".join(chapter.learning_objectives),
            MAX_OUTLINE_CHARS,
        )
        if not chapter.page_ids:
            materials.append(
                TopicMaterial(
                    sid="",
                    kind="book",
                    name=chapter_name,
                    outline=outline,
                    available=False,
                    note="not written yet",
                )
            )
            continue
        if spent >= budget:
            materials.append(
                TopicMaterial(
                    sid="",
                    kind="book",
                    name=chapter_name,
                    outline=outline,
                    available=False,
                    note="beyond this turn's material budget",
                )
            )
            continue
        result = build_book_context(
            [{"book_id": source_id, "page_ids": list(chapter.page_ids)}],
            storage=storage,
            max_chars=min(MAX_CHAPTER_CHARS, budget - spent),
        )
        text = result.text.strip()
        if not text:
            materials.append(
                TopicMaterial(
                    sid="",
                    kind="book",
                    name=chapter_name,
                    outline=outline,
                    available=False,
                    note="no readable content",
                )
            )
            continue
        spent += len(text)
        materials.append(
            TopicMaterial(
                sid=f"bk-{source_id}-{chapter.id}",
                kind="book",
                name=chapter_name,
                outline=outline,
                full_text=text,
            )
        )
    if len(chapters) > MAX_CHAPTERS_PER_BOOK:
        materials.append(
            TopicMaterial(
                sid="",
                kind="book",
                name=f"{title} · +{len(chapters) - MAX_CHAPTERS_PER_BOOK} more chapters",
                available=False,
                note="not listed this turn",
            )
        )
    return materials


def _load_notebook_material(source_id: str, label: str, budget: int) -> TopicMaterial:
    """A notebook stays one material: its records are already record-sized."""
    from deeptutor.services.notebook import get_notebook_manager

    records = get_notebook_manager().get_records_by_references(
        [{"notebook_id": source_id, "record_ids": []}]
    )
    if not records:
        return TopicMaterial(
            sid="",
            kind="notebook",
            name=label,
            available=False,
            note="notebook is empty or unreadable",
        )
    blocks: list[str] = []
    spent = 0
    limit = min(MAX_NOTEBOOK_CHARS, budget)
    for record in records:
        title = _clean_name(str(record.get("title") or record.get("name") or "")) or "Untitled"
        body = str(record.get("output") or record.get("summary") or "").strip()
        if not body:
            continue
        block = f"## {title}\n{body}"
        if spent + len(block) > limit:
            break
        blocks.append(block)
        spent += len(block)
    if not blocks:
        return TopicMaterial(
            sid="",
            kind="notebook",
            name=label,
            available=False,
            note="records have no readable content",
        )
    outline = _clip(
        "; ".join(
            _clean_name(str(record.get("title") or ""))
            for record in records[:8]
            if record.get("title")
        ),
        MAX_OUTLINE_CHARS,
    )
    return TopicMaterial(
        sid=f"nb-topic-{source_id}",
        kind="notebook",
        name=f"{label} ({len(blocks)} records)",
        outline=outline,
        full_text="\n\n".join(blocks),
    )


def _clean_name(value: str) -> str:
    return " ".join(str(value or "").split())


def build_topic_materials(sources: Iterable[Any]) -> TopicMaterials:
    """Resolve a topic's persisted sources into readable / searchable rows.

    Synchronous storage I/O — call it off the event loop. One unloadable source
    degrades to an ``unavailable`` row and never takes the turn down with it:
    tutoring that silently loses a material is worse than tutoring that says so.
    """
    result = TopicMaterials()
    budget = MAX_TOTAL_CHARS
    for source in sorted(sources, key=lambda item: getattr(item, "position", 0)):
        kind = getattr(getattr(source, "kind", None), "value", None) or str(
            getattr(source, "kind", "")
        )
        label = _clean_name(str(getattr(source, "label", "") or "")) or "Untitled"
        source_id = str(getattr(source, "source_id", "") or "").strip()
        available = bool(getattr(source, "available", True))
        # The goal is already the topic's stated objective; repeating it as a
        # readable material would only invite the tutor to "read" it.
        if kind == "goal":
            continue
        if not available or not source_id:
            result.materials.append(
                TopicMaterial(
                    sid="",
                    kind=kind or "unknown",
                    name=label,
                    available=False,
                    note="marked unavailable when the topic was created",
                )
            )
            continue
        if kind == "knowledge_base":
            result.materials.append(
                TopicMaterial(
                    sid="", kind=kind, name=label, note=f"search with rag: kb_name={source_id!r}"
                )
            )
            continue
        try:
            if kind == "book":
                loaded = _load_book_materials(source_id, label, budget)
            elif kind == "notebook":
                loaded = [_load_notebook_material(source_id, label, budget)]
            else:
                loaded = [
                    TopicMaterial(
                        sid="",
                        kind=kind or "unknown",
                        name=label,
                        available=False,
                        note="this material type cannot be read during tutoring",
                    )
                ]
        except Exception:
            logger.exception("Failed to load topic material kind=%s id=%s", kind, source_id)
            result.warnings.append(f"{kind}:{source_id}")
            loaded = [
                TopicMaterial(
                    sid="",
                    kind=kind or "unknown",
                    name=label,
                    available=False,
                    note="could not be loaded",
                )
            ]
        for material in loaded:
            budget -= len(material.full_text)
            result.materials.append(material)
    return result


def render_topic_manifest(materials: TopicMaterials) -> tuple[str, dict[str, str]]:
    """Render the manifest block and the ``read_source`` index.

    The closing rule is the whole point of the block: an unreadable material
    must be *named* as unreadable, so the tutor answers "I can see the outline
    but not the text" instead of asserting it has read a book it never saw.
    """
    if materials.is_empty():
        return "", {}

    rows: list[str] = []
    for material in materials.materials:
        if material.readable:
            row = (
                f"- id={material.sid}  type={material.kind}  name={material.name!r}"
                f"  size={_format_size(len(material.full_text))}"
            )
        elif material.available and material.note:
            row = f"- type={material.kind}  name={material.name!r}  {material.note}"
        else:
            row = (
                f"- type={material.kind}  name={material.name!r}"
                f"  unavailable: {material.note or 'unknown reason'}"
            )
        if material.outline:
            row += f"\n  about: {material.outline!r}"
        rows.append(row)

    header = (
        "[Topic Materials]\n"
        "The materials the learner chose for this mastery topic. They are the "
        "ground truth for this topic — teach from them, not from memory.\n"
        "- Rows with an `id` hold real text: call read_source(id) for the one a "
        "knowledge point actually needs. Do not read them all up front.\n"
        "- Rows marked `search with rag` are knowledge bases: query them with the "
        "rag tool using the kb_name shown.\n"
        "- Rows marked `unavailable` cannot be read at all. Never describe or "
        "quote their contents. Say plainly that the material is not readable and "
        "offer to teach from what is available."
    )
    return header + "\n\n" + "\n\n".join(rows), materials.source_index()


__all__ = [
    "TopicMaterial",
    "TopicMaterials",
    "build_topic_materials",
    "render_topic_manifest",
]
