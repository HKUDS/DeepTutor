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


def _run_sync(coro: Any) -> Any:
    """Await *coro* from this synchronous loader.

    ``build_topic_materials`` is documented as storage-bound and is called off
    the event loop, so a private loop here is safe. If some future caller runs
    it *on* a loop, close the coroutine and report nothing rather than
    deadlocking the turn — a missing material degrades the lesson, a wedged
    turn ends it.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    logger.warning("Topic material loader called on a running event loop; skipping")
    return None


def _session_store() -> Any:
    from deeptutor.services.session import get_sqlite_session_store

    return get_sqlite_session_store()


def _load_chat_material(source_id: str, label: str, budget: int) -> TopicMaterial:
    """One conversation the learner pointed this goal at.

    Reuses chat's own reader, so a transcript attached to a mastery goal reads
    exactly like one attached to a chat turn — including the ``partner:``
    reference form, which resolves through the partner store.
    """
    from deeptutor.services.session.source_inventory import _load_history_session

    loaded = _run_sync(_load_history_session(_session_store(), source_id))
    transcript, title = loaded if loaded else ("", "")
    if not transcript:
        return TopicMaterial(
            sid="",
            kind="chat",
            name=label,
            available=False,
            note="this conversation could not be read",
        )
    text = _clip(transcript, min(MAX_NOTEBOOK_CHARS, budget))
    return TopicMaterial(
        sid=f"tc-{source_id}",
        kind="chat",
        name=_clean_name(title) or label,
        full_text=text,
        outline=_clip(text, MAX_OUTLINE_CHARS),
    )


def _load_question_bank_material(source_id: str, label: str, budget: int) -> TopicMaterial:
    """One question the learner has already answered.

    Their own attempts are the sharpest evidence of where they actually stand,
    which is why a question bank entry is worth attaching to a goal at all.
    """
    from deeptutor.services.session.source_inventory import _load_question_entry

    try:
        entry_id = int(str(source_id).strip())
    except (TypeError, ValueError):
        return TopicMaterial(
            sid="",
            kind="question_bank",
            name=label,
            available=False,
            note="this question-bank reference is not a valid entry id",
        )
    loaded = _run_sync(_load_question_entry(_session_store(), entry_id))
    block, stem = loaded if loaded else ("", "")
    if not block:
        return TopicMaterial(
            sid="",
            kind="question_bank",
            name=label,
            available=False,
            note="this question-bank entry no longer exists",
        )
    text = _clip(block, min(MAX_CHAPTER_CHARS, budget))
    return TopicMaterial(
        sid=f"tq-{entry_id}",
        kind="question_bank",
        name=_clean_name(stem) or label,
        full_text=text,
        outline=_clip(text, MAX_OUTLINE_CHARS),
    )


def _load_cowriter_material(source_id: str, label: str, budget: int) -> TopicMaterial:
    """One Co-Writer draft, read as the learner's own writing on the subject."""
    from deeptutor.co_writer.storage import get_co_writer_storage

    document = get_co_writer_storage().load_document(source_id)
    if document is None:
        return TopicMaterial(
            sid="",
            kind="cowriter",
            name=label,
            available=False,
            note="this draft no longer exists",
        )
    content = str(getattr(document, "content", "") or "")
    if not content.strip():
        return TopicMaterial(
            sid="",
            kind="cowriter",
            name=_clean_name(str(getattr(document, "title", "") or "")) or label,
            available=False,
            note="this draft is empty",
        )
    text = _clip(content, min(MAX_NOTEBOOK_CHARS, budget))
    return TopicMaterial(
        sid=f"tw-{source_id}",
        kind="cowriter",
        name=_clean_name(str(getattr(document, "title", "") or "")) or label,
        full_text=text,
        outline=_clip(text, MAX_OUTLINE_CHARS),
    )


def _load_partner_group_material(source_id: str, label: str, budget: int) -> TopicMaterial:
    """One partner-group conversation, addressed as ``{group_id}:{session_key}``."""
    from deeptutor.services.session.source_inventory import _load_partner_group_reference

    group_id, _, session_key = str(source_id).partition(":")
    if not group_id.strip() or not session_key.strip():
        return TopicMaterial(
            sid="",
            kind="partner_group",
            name=label,
            available=False,
            note="this partner-group reference is malformed",
        )
    transcript, title = _load_partner_group_reference(
        {"group_id": group_id.strip(), "session_key": session_key.strip()},
        language="en",
    )
    if not transcript:
        return TopicMaterial(
            sid="",
            kind="partner_group",
            name=label,
            available=False,
            note="this partner-group conversation could not be read",
        )
    text = _clip(transcript, min(MAX_NOTEBOOK_CHARS, budget))
    return TopicMaterial(
        sid=f"tg-{group_id.strip()}-{session_key.strip()}",
        kind="partner_group",
        name=_clean_name(title) or label,
        full_text=text,
        outline=_clip(text, MAX_OUTLINE_CHARS),
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
        if kind == "file":
            # One document the learner picked out of a knowledge base. Its text
            # lives only inside that base's index — parsing the original here
            # would mean re-running the ingest pipeline mid-turn — so it is
            # searched, not read. Saying which base and which document is the
            # point: before this row existed, hand-picking a file produced a
            # material the tutor was told it could never read.
            kb_name = str((getattr(source, "metadata", None) or {}).get("kb_name") or "").strip()
            where = f"kb_name={kb_name!r}" if kb_name else "the attached knowledge base"
            result.materials.append(
                TopicMaterial(
                    sid="",
                    kind=kind,
                    name=label,
                    note=f"search with rag ({where}); this goal uses only this document",
                )
            )
            continue
        try:
            if kind == "book":
                loaded = _load_book_materials(source_id, label, budget)
            elif kind == "notebook":
                loaded = [_load_notebook_material(source_id, label, budget)]
            elif kind == "chat":
                loaded = [_load_chat_material(source_id, label, budget)]
            elif kind == "question_bank":
                loaded = [_load_question_bank_material(source_id, label, budget)]
            elif kind == "cowriter":
                loaded = [_load_cowriter_material(source_id, label, budget)]
            elif kind == "partner_group":
                loaded = [_load_partner_group_material(source_id, label, budget)]
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
