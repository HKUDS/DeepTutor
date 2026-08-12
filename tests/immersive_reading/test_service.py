"""Regression coverage for source-faithful immersive reading workflows."""

from __future__ import annotations

import pytest

from deeptutor.immersive_reading.models import ReadingDocument, ReadingProgress, ReadingSection
from deeptutor.immersive_reading.service import ImmersiveReadingService


def test_models_round_trip_with_sections_and_progress() -> None:
    document = ReadingDocument(
        id="doc-1",
        title="Ada's Journey",
        source_filename="ada.epub",
        source_format="epub",
        sections=[
            ReadingSection(id="section_0001", title="Chapter 1", index=0, char_count=42),
        ],
    )
    restored_document = ReadingDocument.model_validate(document.model_dump(mode="json"))
    progress = ReadingProgress(document_id=document.id, current_section_id="section_0001")
    restored_progress = ReadingProgress.model_validate(progress.model_dump(mode="json"))

    assert restored_document.sections[0].title == "Chapter 1"
    assert restored_document.reading_mode == "chapters"
    assert restored_progress.current_section_id == "section_0001"
    assert restored_progress.immersive_run == 1


def test_import_text_extracts_chapters_and_preserves_source(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document = imported_document
    document_id = document["id"]

    assert document["title"] == "ada-journey"
    assert document["reading_mode"] == "chapters"
    assert [section["title"] for section in document["sections"]] == [
        "Front Matter",
        "Chapter 1",
        "Chapter 2",
        "Chapter 3",
    ]
    assert document["sections"][0]["checkpoint_kind"] == "none"
    assert "brass compass" in reading_service.get_section(document_id, "section_0002")["content"]
    assert reading_service.original_path(document_id).read_bytes().startswith(b"Title page")


def test_import_rejects_empty_and_unsupported_documents(reading_service: ImmersiveReadingService) -> None:
    with pytest.raises(ValueError, match="empty"):
        reading_service.import_document("empty.txt", b"")
    with pytest.raises(ValueError, match="Unsupported"):
        reading_service.import_document("book.docx", b"not a book")


def test_import_epub_uses_source_extractor(
    reading_service: ImmersiveReadingService, monkeypatch
) -> None:
    import deeptutor.immersive_reading.service as service_module

    monkeypatch.setattr(
        service_module,
        "_fitz_sections",
        lambda path: (
            "The Compass Book",
            "Ada Writer",
            "chapters",
            [("Chapter 1", "The original EPUB chapter text.", 1, 1)],
            None,
        ),
    )

    document = reading_service.import_document("compass.epub", b"fixture epub bytes")

    assert document["title"] == "The Compass Book"
    assert document["author"] == "Ada Writer"
    assert document["source_format"] == "epub"
    assert reading_service.original_path(document["id"]).name == "original.epub"
    assert reading_service.get_section(document["id"], "section_0001")["content"] == (
        "The original EPUB chapter text."
    )


def test_exact_search_is_case_insensitive_and_keeps_source_offsets(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    hits = reading_service.exact_search(imported_document["id"], "BRASS COMPASS")

    assert len(hits) == 3
    assert {hit.section_title for hit in hits} == {"Chapter 1", "Chapter 2", "Chapter 3"}
    assert all(hit.score == 1.0 for hit in hits)
    assert all(hit.start_offset < hit.end_offset for hit in hits)


def test_fuzzy_search_normalizes_whitespace(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    hits = reading_service.fuzzy_search(
        imported_document["id"], "Ada follows a brass compass through the oldobservatory"
    )

    assert hits
    assert hits[0].section_title == "Chapter 1"
    assert "brass compass" in hits[0].excerpt


def test_progress_blocks_later_chapters_until_focus_check_passes(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document_id = imported_document["id"]
    chapter_one = imported_document["sections"][1]["id"]
    chapter_two = imported_document["sections"][2]["id"]

    progress = reading_service.update_progress(document_id, chapter_one, 64.5)

    assert progress.current_section_id == chapter_one
    assert progress.scroll_percent == 64.5
    with pytest.raises(PermissionError, match="Focus-Check"):
        reading_service.update_progress(document_id, chapter_two, 1)


def test_citations_round_trip_and_delete(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]

    citation = reading_service.add_citation(document_id, section_id, "Ada follows the compass.", "Key clue")

    assert reading_service.list_citations(document_id) == [citation]
    reading_service.delete_citation(citation.id)
    assert reading_service.list_citations(document_id) == []


def test_render_reference_can_scope_to_selected_sections(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document_id = imported_document["id"]
    chapter_two = imported_document["sections"][2]["id"]

    reference, title = reading_service.render_reference(document_id, [chapter_two])

    assert title == "ada-journey"
    assert "## Chapter 2" in reference
    assert "## Chapter 1" not in reference
