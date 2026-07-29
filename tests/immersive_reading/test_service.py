from __future__ import annotations

import asyncio
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest

from deeptutor.immersive_reading import service as service_module
from deeptutor.immersive_reading.service import ImmersiveReadingService
from deeptutor.services.path_service import PathService


@pytest.fixture
def reading_service(tmp_path, monkeypatch) -> ImmersiveReadingService:
    paths = PathService(tmp_path)
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    return ImmersiveReadingService()


def _chapter_book() -> bytes:
    return (
        "# Chapter One\n" + "A first event happened because of an earlier choice. " * 12 + "\n\n"
        "# Chapter Two\n" + "A consequence changed the characters and their plans. " * 12 + "\n\n"
        "# Chapter Three\n" + "The final decision resolved the central conflict. " * 12
    ).encode()


def _front_matter_book() -> bytes:
    return (
        "Title page, copyright notice, and publication details.\n\n"
        "# Chapter One\n" + "The journey begins with a difficult choice. " * 15 + "\n\n"
        "# Chapter Two\n" + "The choice creates an unexpected consequence. " * 15 + "\n\n"
        "# Chapter Three\n" + "The characters understand what the journey changed. " * 15
    ).encode()


def _minimal_epub() -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>",
            compress_type=ZIP_DEFLATED,
        )
        manifest_items = []
        spine_items = []
        nav_points = []
        for index in range(1, 4):
            name = f"chapter{index}.xhtml"
            body = f"Chapter {index} source text. " * 80
            archive.writestr(
                f"OEBPS/{name}",
                f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Chapter {index}</title></head>'
                f"<body><h1>Chapter {index}</h1><p>{body}</p></body></html>",
                compress_type=ZIP_DEFLATED,
            )
            manifest_items.append(
                f'<item id="c{index}" href="{name}" media-type="application/xhtml+xml"/>'
            )
            spine_items.append(f'<itemref idref="c{index}"/>')
            nav_points.append(
                f'<navPoint id="n{index}" playOrder="{index}"><navLabel><text>Chapter {index}</text>'
                f'</navLabel><content src="{name}"/></navPoint>'
            )
        archive.writestr(
            "OEBPS/toc.ncx",
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            "<head/><docTitle><text>Test EPUB</text></docTitle><navMap>"
            + "".join(nav_points)
            + "</navMap></ncx>",
            compress_type=ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
            'unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>Test EPUB</dc:title><dc:creator>Test Author</dc:creator><dc:identifier id="id">test</dc:identifier>'
            '</metadata><manifest><item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            + "".join(manifest_items)
            + '</manifest><spine toc="ncx">'
            + "".join(spine_items)
            + "</spine></package>",
            compress_type=ZIP_DEFLATED,
        )
    return output.getvalue()


def test_import_search_progress_and_citations(reading_service: ImmersiveReadingService) -> None:
    document = reading_service.import_document("novel.txt", _chapter_book())

    assert document["reading_mode"] == "chapters"
    assert len(document["sections"]) == 3
    document_id = document["id"]
    first, second, third = document["sections"]

    exact = reading_service.exact_search(document_id, "central conflict")
    assert exact and exact[0].section_id == third["id"]
    fuzzy = reading_service.fuzzy_search(document_id, "characters plans")
    assert fuzzy and fuzzy[0].section_id == second["id"]

    with pytest.raises(PermissionError):
        reading_service.update_progress(document_id, third["id"], 10)

    citation = reading_service.add_citation(
        document_id,
        first["id"],
        "A first event happened because of an earlier choice.",
    )
    assert reading_service.list_citations(document_id)[0].id == citation.id


def test_short_or_missing_toc_uses_twenty_thousand_character_checkpoints(
    reading_service: ImmersiveReadingService,
) -> None:
    document = reading_service.import_document("long.txt", ("one two three.\n\n" * 5000).encode())

    assert document["reading_mode"] == "chunks"
    assert len(document["sections"]) >= 3
    assert max(section["char_count"] for section in document["sections"]) < 22_000


def test_fast_index_material_removes_an_obvious_leading_contents_block() -> None:
    source = (
        "第二章 火车\n第三章 山中\n第四章 城市\n第五章 旅店\n第六章 告别\n\n"
        "序言\n\n这是需要被索引的序言正文。"
    )

    indexed = ImmersiveReadingService._indexable_section_text(source)

    assert indexed.startswith("序言")
    assert "第二章 火车" not in indexed


@pytest.mark.asyncio
async def test_front_matter_skips_focus_check_and_unlocks_first_chapter(
    reading_service: ImmersiveReadingService,
    monkeypatch,
) -> None:
    async def unexpected_complete(**_kwargs):
        raise AssertionError("Front matter must not call the LLM")

    monkeypatch.setattr(service_module, "complete", unexpected_complete)
    document = reading_service.import_document("front-matter.txt", _front_matter_book())
    document_id = document["id"]
    front_matter, first_chapter = document["sections"][:2]

    assert front_matter["title"] == "Front Matter"
    assert front_matter["checkpoint_kind"] == "none"
    assert reading_service.get_section(document_id, front_matter["id"])["passed"] is True

    reading_service.update_progress(document_id, first_chapter["id"], 1)
    result = await reading_service.focus_check(
        document_id,
        front_matter["id"],
        "",
        "",
        "en",
    )
    assert result.passed is True
    assert result.score == 100


def test_existing_front_matter_manifest_is_migrated(
    reading_service: ImmersiveReadingService,
) -> None:
    document = reading_service.import_document("legacy.txt", _front_matter_book())
    manifest_path = reading_service._manifest_path(document["id"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sections"][0]["checkpoint_kind"] = "chapter"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    migrated = reading_service.load_document(document["id"])

    assert migrated is not None
    assert migrated.sections[0].checkpoint_kind == "none"


def test_epub_import_uses_embedded_title_author_and_toc(
    reading_service: ImmersiveReadingService,
) -> None:
    document = reading_service.import_document("book.epub", _minimal_epub())

    assert document["title"] == "Test EPUB"
    assert document["author"] == "Test Author"
    assert document["source_format"] == "epub"
    assert document["reading_mode"] == "chapters"
    assert len(document["sections"]) == 3
    assert document["has_cover"] is True


@pytest.mark.asyncio
async def test_focus_check_unlocks_next_section_and_restart_modes(
    reading_service: ImmersiveReadingService,
    monkeypatch,
) -> None:
    completion_kwargs = {}

    async def fake_complete(**kwargs):
        completion_kwargs.update(kwargs)
        return json.dumps(
            {
                "passed": True,
                "score": 82,
                "feedback": "You identified the central event and connected your response to it.",
                "strengths": ["Accurate causality"],
                "missing_points": [],
            }
        )

    monkeypatch.setattr(service_module, "complete", fake_complete)
    document = reading_service.import_document("novel.txt", _chapter_book())
    document_id = document["id"]
    first, second, _third = document["sections"]

    result = await reading_service.focus_check(
        document_id,
        first["id"],
        "The first event happens because an earlier choice creates the main conflict.",
        "The consequence affected me because the character had to accept responsibility.",
        "en",
    )
    assert result.passed is True
    assert completion_kwargs["max_tokens"] == 255_000
    assert completion_kwargs["reasoning_effort"] == "minimal"
    assert completion_kwargs["max_retries"] == 0
    assert completion_kwargs["timeout"] == 30
    reading_service.update_progress(document_id, second["id"], 5)

    kept = reading_service.restart(document_id, reset_focus_checks=False)
    assert first["id"] in kept.passed_section_ids
    reset = reading_service.restart(document_id, reset_focus_checks=True)
    assert reset.passed_section_ids == []
    assert reset.immersive_run == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["", "not valid json", '{"feedback":"missing fields"}'])
async def test_invalid_focus_response_is_an_error_not_a_zero_score(
    reading_service: ImmersiveReadingService,
    monkeypatch,
    response: str,
) -> None:
    async def invalid_complete(**_kwargs):
        return response

    monkeypatch.setattr(service_module, "complete", invalid_complete)
    document = reading_service.import_document("novel.txt", _chapter_book())
    section = document["sections"][0]

    with pytest.raises(RuntimeError, match="Focus-Check"):
        await reading_service.focus_check(
            document["id"],
            section["id"],
            "The main event follows from the character's earlier decision and changes the conflict.",
            "I was affected by the character accepting responsibility for the result.",
            "en",
        )

    progress = reading_service.load_progress(document["id"])
    assert section["id"] not in progress.focus_attempts
    assert section["id"] not in progress.passed_section_ids


@pytest.mark.asyncio
async def test_description_search_is_context_gated_and_uses_default_llm(
    reading_service: ImmersiveReadingService,
    monkeypatch,
) -> None:
    document = reading_service.import_document("novel.txt", _chapter_book())

    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="small-context",
            context_window=32_000,
            max_tokens=4096,
            binding="openai",
        ),
    )
    with pytest.raises(PermissionError):
        await reading_service.description_search(document["id"], "a final choice")

    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="large-context",
            context_window=64_000,
            max_tokens=4096,
            binding="openai",
        ),
    )

    async def semantic_complete(**_kwargs):
        return '{"matches":[{"ref":"s2-p0-c0","score":93,"reason":"The final decision resolves the conflict."}]}'

    monkeypatch.setattr(service_module, "complete", semantic_complete)
    hits = await reading_service.description_search(
        document["id"], "the choice that ends everything"
    )
    assert hits and hits[0].section_index == 2
    assert hits[0].score == pytest.approx(0.93)
    fine_hits = await reading_service.search(
        document["id"], "the choice that ends everything", "description_fine"
    )
    assert fine_hits and fine_hits[0].section_index == 2
    assert fine_hits[0].score == pytest.approx(0.93)


@pytest.mark.asyncio
async def test_fast_index_builds_deep_chapter_cards_and_skips_front_matter(
    reading_service: ImmersiveReadingService,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="deepseek-v4-pro",
            context_window=1_000_000,
            max_tokens=4096,
            binding="deepseek",
        ),
    )
    document = reading_service.import_document("front-matter.txt", _front_matter_book())
    calls: list[dict] = []
    active = 0
    maximum_active = 0

    async def card_complete(**kwargs):
        nonlocal active, maximum_active
        calls.append(kwargs)
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0)
        active -= 1
        return json.dumps(
            {
                "summary": "A source-faithful chapter summary.",
                "characters": ["The traveller"],
                "locations": ["The station"],
                "time_markers": ["At dawn"],
                "timeline": ["A choice changes the journey."],
                "causal_links": ["The choice causes a consequence."],
                "turning_points": ["The plan changes."],
                "themes_and_motifs": ["Responsibility"],
                "searchable_phrases": ["unexpected consequence"],
            }
        )

    monkeypatch.setattr(service_module, "complete", card_complete)
    status = await reading_service.build_fast_index(document["id"])

    assert status["status"] == "ready"
    assert status["completed_sections"] == 3
    assert len(calls) == 3
    assert maximum_active > 1
    assert all(call["reasoning_effort"] == "high" for call in calls)
    assert all(call["max_tokens"] == 32_000 for call in calls)
    state = reading_service._load_fast_index(reading_service.load_document(document["id"]))
    assert document["sections"][0]["id"] not in state.cards


@pytest.mark.asyncio
async def test_fast_index_keeps_partial_progress_and_retries_only_failed_chapters(
    reading_service: ImmersiveReadingService,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="deepseek-v4-pro",
            context_window=1_000_000,
            max_tokens=4096,
            binding="deepseek",
        ),
    )
    document = reading_service.import_document("novel.txt", _chapter_book())

    async def partly_failing_complete(**kwargs):
        if "Chapter ID: section_0002" in kwargs["prompt"]:
            raise RuntimeError("temporary provider failure")
        return json.dumps({"summary": "Indexed chapter"})

    monkeypatch.setattr(service_module, "complete", partly_failing_complete)
    partial = await reading_service.build_fast_index(document["id"])

    assert partial["status"] == "partial"
    assert partial["completed_sections"] == 2
    assert partial["failed_sections"] == 1
    assert reading_service.load_document(document["id"]) is not None

    retry_calls: list[str] = []

    async def successful_retry(**kwargs):
        retry_calls.append(kwargs["prompt"])
        return json.dumps({"summary": "Recovered chapter"})

    monkeypatch.setattr(service_module, "complete", successful_retry)
    ready = await reading_service.build_fast_index(document["id"])

    assert ready["status"] == "ready"
    assert ready["completed_sections"] == 3
    assert len(retry_calls) == 1


@pytest.mark.asyncio
async def test_fast_search_routes_without_thinking_then_deep_searches_candidates(
    reading_service: ImmersiveReadingService,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="deepseek-v4-pro",
            context_window=1_000_000,
            max_tokens=4096,
            binding="deepseek",
        ),
    )
    document = reading_service.import_document("novel.txt", _chapter_book())

    async def card_complete(**_kwargs):
        return json.dumps(
            {
                "summary": "Chapter events and consequences.",
                "characters": [],
                "locations": [],
                "time_markers": [],
                "timeline": [],
                "causal_links": [],
                "turning_points": [],
                "themes_and_motifs": [],
                "searchable_phrases": [],
            }
        )

    monkeypatch.setattr(service_module, "complete", card_complete)
    await reading_service.build_fast_index(document["id"])
    target = document["sections"][1]
    modes: list[str] = []

    async def search_complete(**kwargs):
        modes.append(kwargs["reasoning_effort"])
        if kwargs["reasoning_effort"] == "minimal":
            return json.dumps(
                {
                    "candidates": [
                        {
                            "section_id": target["id"],
                            "confidence": 92,
                            "reason": "The consequence changes the plan.",
                            "search_instructions": ["Find the changed plan"],
                        }
                    ],
                    "cross_chapter": False,
                }
            )
        return json.dumps(
            {
                "matches": [
                    {
                        "ref": f"{target['id']}:p0",
                        "score": 95,
                        "reason": "The passage directly describes the consequence.",
                    }
                ]
            }
        )

    monkeypatch.setattr(service_module, "complete", search_complete)
    hits, metadata = await reading_service.fast_description_search(
        document["id"], "where did the consequence change their plans?"
    )

    assert hits and hits[0].section_id == target["id"]
    assert modes == ["minimal", "high"]
    assert metadata["fallback_used"] is False
    assert metadata["resolved_mode"] == "description_fast"


@pytest.mark.asyncio
async def test_fast_search_low_confidence_uses_existing_fine_search(
    reading_service: ImmersiveReadingService,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="deepseek-v4-pro",
            context_window=1_000_000,
            max_tokens=4096,
            binding="deepseek",
        ),
    )
    document = reading_service.import_document("novel.txt", _chapter_book())

    async def card_complete(**_kwargs):
        return json.dumps(
            {
                "summary": "Chapter summary.",
                "characters": [],
                "locations": [],
                "time_markers": [],
                "timeline": [],
                "causal_links": [],
                "turning_points": [],
                "themes_and_motifs": [],
                "searchable_phrases": [],
            }
        )

    monkeypatch.setattr(service_module, "complete", card_complete)
    await reading_service.build_fast_index(document["id"])
    first = document["sections"][0]

    async def low_confidence_route(**_kwargs):
        return json.dumps(
            {
                "candidates": [
                    {
                        "section_id": first["id"],
                        "confidence": 41,
                        "reason": "Weak match",
                        "search_instructions": [],
                    }
                ],
                "cross_chapter": False,
            }
        )

    fine_calls: list[str] = []

    async def existing_fine(document_id: str, query: str, limit: int = 20):
        fine_calls.append(query)
        return [
            service_module.SearchHit(
                section_id=first["id"],
                section_title=first["title"],
                section_index=first["index"],
                excerpt="Fine-search result",
                score=0.9,
            )
        ]

    monkeypatch.setattr(service_module, "complete", low_confidence_route)
    monkeypatch.setattr(reading_service, "description_search", existing_fine)
    hits, metadata = await reading_service.fast_description_search(
        document["id"], "an uncertain memory"
    )

    assert hits and hits[0].excerpt == "Fine-search result"
    assert fine_calls == ["an uncertain memory"]
    assert metadata["fallback_used"] is True
    assert metadata["resolved_mode"] == "description_fine"
    assert metadata["fallback_reason"] == "low_router_confidence"
