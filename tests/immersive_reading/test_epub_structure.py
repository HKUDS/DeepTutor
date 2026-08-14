"""EPUB href extraction, backfill, and progress mapping."""

from __future__ import annotations

from deeptutor.immersive_reading.epub_structure import (
    apply_source_hrefs,
    hrefs_match,
    normalize_epub_href,
    parse_epub_structure,
    resolve_section_titles,
    resolve_section_for_href,
    section_needs_title,
)
from deeptutor.immersive_reading.models import ReadingSection
from deeptutor.immersive_reading.service import ImmersiveReadingService
from tests.immersive_reading.epub_fixtures import build_epub


def test_normalize_epub_href_collapses_relative_segments() -> None:
    assert normalize_epub_href("./Text/ch1.xhtml#note", opf_dir="OEBPS") == "Text/ch1.xhtml#note"
    assert normalize_epub_href("../ch1.xhtml", base_dir="OEBPS/Text", opf_dir="OEBPS") == "ch1.xhtml"
    assert hrefs_match("OEBPS/chapter-1.xhtml", "chapter-1.xhtml")


def test_parse_epub2_ncx_and_spine_hrefs() -> None:
    structure = parse_epub_structure(build_epub(version="2.0", include_ncx=True))

    assert structure.title == "The Compass Book"
    assert structure.author == "Ada Writer"
    assert structure.spine_hrefs == [
        "chapter-1.xhtml",
        "chapter-2.xhtml",
        "chapter-3.xhtml",
    ]
    assert [item.href for item in structure.nav_items] == structure.spine_hrefs
    assert [item.title for item in structure.nav_items][0].startswith("Chapter 1")
    assert structure.is_pre_paginated is False


def test_parse_epub3_nav_nested_cover_and_pre_paginated() -> None:
    structure = parse_epub_structure(
        build_epub(
            version="3.0",
            include_ncx=False,
            include_nav=True,
            include_cover=True,
            pre_paginated=True,
            nested_nav=True,
        )
    )

    assert structure.cover_href == "cover.png"
    assert structure.is_pre_paginated is True
    assert structure.spine_hrefs[0] == "cover.xhtml"
    assert "chapter-1.xhtml" in structure.spine_hrefs
    assert any(item.title == "Part One" for item in structure.nav_items)
    assert any(item.href == "chapter-2.xhtml" for item in structure.nav_items)


def test_apply_source_hrefs_shares_href_across_split_sections() -> None:
    sections = [
        ReadingSection(id="section_0001", title="Chapter 1: The Observatory", index=0, source_start=1, source_end=3),
        ReadingSection(
            id="section_0002",
            title="Chapter 1: The Observatory – 1",
            index=1,
            parent_id="section_0001",
            source_start=1,
            source_end=3,
        ),
        ReadingSection(
            id="section_0003",
            title="Chapter 1: The Observatory – 2",
            index=2,
            parent_id="section_0001",
            source_start=1,
            source_end=3,
        ),
        ReadingSection(id="section_0004", title="Chapter 2: The Harbor", index=3, source_start=4, source_end=6),
    ]

    changed = apply_source_hrefs(sections, build_epub(), reading_mode="chapters")

    assert changed is True
    assert sections[0].source_href == "chapter-1.xhtml"
    assert sections[1].source_href == "chapter-1.xhtml"
    assert sections[2].source_href == "chapter-1.xhtml"
    assert sections[3].source_href == "chapter-2.xhtml"


def test_apply_source_hrefs_does_not_clobber_existing_values() -> None:
    sections = [
        ReadingSection(id="section_0001", title="Chapter 1: The Observatory", index=0, source_href="kept.xhtml"),
    ]
    changed = apply_source_hrefs(sections, build_epub(), reading_mode="chapters")
    assert changed is False
    assert sections[0].source_href == "kept.xhtml"


def test_unreadable_epub_does_not_mutate_sections() -> None:
    sections = [ReadingSection(id="section_0001", title="Chapter 1", index=0)]
    changed = apply_source_hrefs(sections, b"not-an-epub", reading_mode="chapters")
    assert changed is False
    assert sections[0].source_href == ""


def test_resolve_section_for_href_prefers_current_then_first_leaf() -> None:
    sections = [
        ReadingSection(id="parent", title="Chapter 1", index=0, source_href="chapter-1.xhtml", checkpoint_kind="none"),
        ReadingSection(id="leaf-a", title="Chapter 1 – 1", index=1, source_href="chapter-1.xhtml"),
        ReadingSection(id="leaf-b", title="Chapter 1 – 2", index=2, source_href="chapter-1.xhtml"),
    ]
    assert resolve_section_for_href(sections, "OEBPS/chapter-1.xhtml", preferred_section_id="leaf-b").id == "leaf-b"
    assert resolve_section_for_href(sections, "chapter-1.xhtml").id == "leaf-a"


def test_import_real_epub_writes_source_hrefs(reading_service: ImmersiveReadingService) -> None:
    document = reading_service.import_document("compass.epub", build_epub())
    hrefs = [section["source_href"] for section in document["sections"]]
    assert hrefs == ["chapter-1.xhtml", "chapter-2.xhtml", "chapter-3.xhtml"]


def test_old_manifest_is_backfilled_on_open(reading_service: ImmersiveReadingService) -> None:
    document = reading_service.import_document("compass.epub", build_epub())
    document_id = document["id"]
    loaded = reading_service.load_document(document_id)
    assert loaded is not None
    for section in loaded.sections:
        section.source_href = ""
    reading_service._manifest_path(document_id).write_text(
        loaded.model_dump_json(), encoding="utf-8"
    )

    detailed = reading_service.document_detail(document_id)
    assert [section["source_href"] for section in detailed["sections"]] == [
        "chapter-1.xhtml",
        "chapter-2.xhtml",
        "chapter-3.xhtml",
    ]


def test_epub_progress_maps_href_to_current_fragment(
    reading_service: ImmersiveReadingService,
) -> None:
    document = reading_service.import_document("compass.epub", build_epub())
    document_id = document["id"]
    loaded = reading_service.load_document(document_id)
    assert loaded is not None
    loaded.sections[0].checkpoint_kind = "none"
    child = ReadingSection(
        id="section_0099",
        title="Chapter 1: The Observatory – 2",
        index=1,
        parent_id=loaded.sections[0].id,
        source_href="chapter-1.xhtml",
    )
    loaded.sections.insert(1, child)
    for index, section in enumerate(loaded.sections):
        section.index = index
    reading_service._manifest_path(document_id).write_text(
        loaded.model_dump_json(), encoding="utf-8"
    )
    progress = reading_service.load_progress(document_id)
    progress.current_section_id = "section_0099"
    progress.current_section_index = 1
    reading_service._save_progress(progress)

    updated = reading_service.update_epub_progress(
        document_id,
        epub_cfi="epubcfi(/6/4!/4/2/2)",
        section_href="chapter-1.xhtml",
        scroll_percent=42,
    )
    assert updated.current_section_id == "section_0099"
    assert updated.epub_cfi == "epubcfi(/6/4!/4/2/2)"
    assert updated.section_href == "chapter-1.xhtml"
    assert updated.scroll_percent == 42


# ── Chapter title resolution (replace file-stem titles) ────────────────


def test_resolve_section_titles_replaces_filename_stems() -> None:
    """Bare file-stem titles (e.g. ``index_split_004``) become real nav labels."""
    epub = build_epub()
    sections = [
        ReadingSection(id="section_0001", title="chapter-1", index=0, source_href="chapter-1.xhtml"),
        ReadingSection(id="section_0002", title="chapter-2", index=1, source_href="chapter-2.xhtml"),
        ReadingSection(id="section_0003", title="chapter-3", index=2, source_href="chapter-3.xhtml"),
    ]

    changed = resolve_section_titles(sections, epub)

    assert changed is True
    assert sections[0].title == "Chapter 1: The Observatory"
    assert sections[1].title == "Chapter 2: The Harbor"
    assert sections[2].title == "Chapter 3: The Library"


def test_resolve_section_titles_preserves_meaningful_titles() -> None:
    """A section that already has a real chapter name is left untouched."""
    epub = build_epub()
    sections = [
        ReadingSection(
            id="section_0001",
            title="Chapter 1: The Observatory",
            index=0,
            source_href="chapter-1.xhtml",
        ),
    ]

    assert resolve_section_titles(sections, epub) is False
    assert sections[0].title == "Chapter 1: The Observatory"


def test_resolve_section_titles_keeps_chunk_suffix() -> None:
    """An oversized-chapter split keeps its ``– N`` suffix but uses the real name."""
    epub = build_epub()
    sections = [
        ReadingSection(
            id="section_0001", title="chapter-1 \u2013 1", index=0, source_href="chapter-1.xhtml"
        ),
        ReadingSection(
            id="section_0002", title="chapter-1 \u2013 2", index=1, source_href="chapter-1.xhtml"
        ),
    ]

    assert resolve_section_titles(sections, epub) is True
    assert sections[0].title == "Chapter 1: The Observatory \u2013 1"
    assert sections[1].title == "Chapter 1: The Observatory \u2013 2"


def test_resolve_section_titles_falls_back_to_headings() -> None:
    """With no nav/NCX, titles are read from the first heading in each spine file."""
    epub = build_epub(include_ncx=False, include_nav=False)
    sections = [
        ReadingSection(id="section_0001", title="chapter-1", index=0, source_href="chapter-1.xhtml"),
        ReadingSection(id="section_0002", title="chapter-2", index=1, source_href="chapter-2.xhtml"),
    ]

    changed = resolve_section_titles(sections, epub)

    assert changed is True
    assert sections[0].title == "Chapter 1: The Observatory"
    assert sections[1].title == "Chapter 2: The Harbor"


def test_section_needs_title_detects_stem() -> None:
    assert section_needs_title(
        ReadingSection(id="s1", title="index_split_004", index=0, source_href="index_split_004.xhtml")
    )
    assert not section_needs_title(
        ReadingSection(id="s1", title="Chapter 1", index=0, source_href="index_split_004.xhtml")
    )
    assert not section_needs_title(
        ReadingSection(id="s1", title="anything", index=0, source_href="")
    )
