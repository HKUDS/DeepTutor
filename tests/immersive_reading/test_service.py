"""Regression coverage for source-faithful immersive reading workflows."""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from deeptutor.immersive_reading.models import (
    FocusAttempt,
    ReadingDocument,
    ReadingProgress,
    ReadingSection,
)
from deeptutor.immersive_reading.service import ImmersiveReadingService


def _minimal_epub_bytes() -> bytes:
    chapters = [
        (
            "chapter-1.xhtml",
            "Chapter 1: The Observatory",
            "Ada follows the brass compass through the old observatory. ",
        ),
        (
            "chapter-2.xhtml",
            "Chapter 2: The Harbor",
            "At the harbor, Ada maps the compass bearings against the tide. ",
        ),
        (
            "chapter-3.xhtml",
            "Chapter 3: The Library",
            "The library records reveal why the compass points north at dusk. ",
        ),
    ]
    manifest = "\n".join(
        f'<item id="chapter-{index}" href="{filename}" media-type="application/xhtml+xml"/>'
        for index, (filename, _title, _text) in enumerate(chapters, start=1)
    )
    spine = "\n".join(
        f'<itemref idref="chapter-{index}"/>' for index in range(1, len(chapters) + 1)
    )
    nav_points = "\n".join(
        (
            f'<navPoint id="nav-{index}" playOrder="{index}">'
            f"<navLabel><text>{title}</text></navLabel>"
            f'<content src="{filename}"/></navPoint>'
        )
        for index, (filename, title, _text) in enumerate(chapters, start=1)
    )
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    package = f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="2.0" unique-identifier="book-id" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>The Compass Book</dc:title>
    <dc:creator>Ada Writer</dc:creator>
    <dc:identifier id="book-id">urn:uuid:compass-book</dc:identifier>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    {manifest}
  </manifest>
  <spine toc="ncx">{spine}</spine>
</package>"""
    ncx = f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">
  <head><meta name="dtb:uid" content="urn:uuid:compass-book"/></head>
  <docTitle><text>The Compass Book</text></docTitle>
  <navMap>{nav_points}</navMap>
</ncx>"""

    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", container, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", package, compress_type=ZIP_DEFLATED)
        archive.writestr("OEBPS/toc.ncx", ncx, compress_type=ZIP_DEFLATED)
        for filename, title, sentence in chapters:
            body = sentence * 80
            xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body><h1>{title}</h1><p>{body}</p></body></html>"""
            archive.writestr(f"OEBPS/{filename}", xhtml, compress_type=ZIP_DEFLATED)
    return output.getvalue()


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
            [("Chapter 1", "The original EPUB chapter text.", 1, 1, -1, 1)],
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


def test_import_real_epub_extracts_metadata_toc_and_text(
    reading_service: ImmersiveReadingService,
) -> None:
    document = reading_service.import_document("compass.epub", _minimal_epub_bytes())

    assert document["title"] == "The Compass Book"
    assert document["author"] == "Ada Writer"
    assert document["source_format"] == "epub"
    assert document["reading_mode"] == "chapters"
    assert [section["title"] for section in document["sections"]] == [
        "Chapter 1: The Observatory",
        "Chapter 2: The Harbor",
        "Chapter 3: The Library",
    ]
    chapter_text = reading_service.get_section(document["id"], "section_0002")["content"]
    assert "Ada maps the compass bearings" in chapter_text


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


def test_progress_allows_non_linear_technical_reading(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document_id = imported_document["id"]
    chapter_one = imported_document["sections"][1]["id"]
    chapter_two = imported_document["sections"][2]["id"]

    progress = reading_service.update_progress(document_id, chapter_one, 64.5)

    assert progress.current_section_id == chapter_one
    assert progress.scroll_percent == 64.5
    later = reading_service.update_progress(document_id, chapter_two, 1)

    assert later.current_section_id == chapter_two
    assert reading_service.get_section(document_id, chapter_two)["locked"] is False


def test_contents_pages_are_exempted_for_existing_imports(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document_id = imported_document["id"]
    manifest_path = reading_service._manifest_path(document_id)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sections"][0]["title"] = "目錄"
    manifest["sections"][0]["checkpoint_kind"] = "chapter"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    document = reading_service.load_document(document_id)

    assert document is not None
    assert document.sections[0].checkpoint_kind == "none"


def test_skip_section_is_recorded_and_does_not_erase_attempts(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]
    progress = reading_service.load_progress(document_id)
    progress.focus_attempts[section_id] = FocusAttempt(
        section_id=section_id, score=25, attempt_count=1
    )
    reading_service._save_progress(progress)

    skipped = reading_service.skip_section(document_id, section_id)

    assert skipped.skipped_section_ids == [section_id]
    assert skipped.focus_attempts[section_id].score == 25
    assert skipped.focus_history[section_id][0].answer_recorded is False


@pytest.mark.asyncio
async def test_focus_check_saves_answers_feedback_and_history(
    reading_service: ImmersiveReadingService, imported_document: dict, monkeypatch
) -> None:
    import deeptutor.immersive_reading.service as service_module

    monkeypatch.setattr(
        service_module,
        "complete",
        lambda **_kwargs: asyncio.sleep(
            0,
            result=(
                '{"passed":true,"score":82,"feedback":"Useful and accurate.",'
                '"strengths":["clear"],"missing_points":[]}'
            ),
        ),
    )
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]

    result = await reading_service.focus_check(
        document_id,
        section_id,
        "Ada follows the brass compass through the observatory and learns where it points.",
        "The navigation idea is useful for deciding what to inspect next.",
        "en",
    )
    stored = reading_service.load_progress(document_id)
    record = stored.focus_history[section_id][0]

    assert result.passed is True
    assert record.summary.startswith("Ada follows")
    assert record.reflection.startswith("The navigation idea")
    assert record.status == "graded"
    assert record.score == 82
    assert record.feedback == "Useful and accurate."
    assert record.model == "test-model"
    assert record.prompt_version.startswith("focus-check-v4-structured-")
    assert record.pass_threshold == 65


@pytest.mark.asyncio
async def test_focus_check_keeps_submitted_answer_when_grading_fails(
    reading_service: ImmersiveReadingService, imported_document: dict, monkeypatch
) -> None:
    import deeptutor.immersive_reading.service as service_module

    monkeypatch.setattr(
        service_module,
        "complete",
        lambda **_kwargs: asyncio.sleep(0, result="not json"),
    )
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]

    with pytest.raises(RuntimeError, match="invalid Focus-Check response"):
        await reading_service.focus_check(
            document_id,
            section_id,
            "This answer is long enough and describes the chapter's central event.",
            "This detail is practically useful to me.",
            "en",
        )

    record = reading_service.load_progress(document_id).focus_history[section_id][0]
    assert record.summary.startswith("This answer")
    assert record.status == "error"
    assert "invalid Focus-Check response" in record.error


def test_restart_resets_current_status_but_preserves_focus_history(
    reading_service: ImmersiveReadingService, imported_document: dict
) -> None:
    document_id = imported_document["id"]
    section_id = imported_document["sections"][1]["id"]
    progress = reading_service.load_progress(document_id)
    progress.focus_attempts[section_id] = FocusAttempt(
        section_id=section_id, passed=False, score=25, attempt_count=1
    )
    reading_service._save_progress(progress)
    reading_service.load_progress(document_id)

    restarted = reading_service.restart(document_id, reset_focus_checks=True)

    assert restarted.focus_attempts == {}
    assert restarted.skipped_section_ids == []
    assert restarted.focus_history[section_id][0].score == 25


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


def test_oversized_chapter_is_split_with_parent_navigation(
    reading_service: ImmersiveReadingService,
) -> None:
    """Large chapters should be split into a navigational parent + readable children."""
    padding = "This is a long sentence that pads the chapter to exceed the split threshold. " * 800
    intro = "An introduction that is long enough to pass the heading distance filter. " * 10
    outro = "A brief conclusion with enough text to clear the filter too. " * 10
    source = "\n\n".join(
        [
            "# Intro\n" + intro,
            "# Mega Chapter\n" + padding,
            "# Outro\n" + outro,
        ]
    )
    document = reading_service.import_document("mega-book.txt", source.encode("utf-8"))

    # Parent should be navigational; children should be readable.
    parent = document["sections"][1]
    assert parent["title"] == "Mega Chapter"
    assert parent["checkpoint_kind"] == "none"
    assert parent["level"] == 1

    children = [s for s in document["sections"] if s.get("parent_id") == parent["id"]]
    assert len(children) >= 2
    assert all(c["level"] == 2 for c in children)
    assert all(c["checkpoint_kind"] != "none" for c in children)

    # Each child should have actual content
    for child in children:
        content = reading_service.get_section(document["id"], child["id"])["content"]
        assert len(content) > 100
