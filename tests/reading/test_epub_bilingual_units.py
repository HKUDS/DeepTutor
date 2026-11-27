"""Direct unit tests for the bilingual EPUB pairing pipeline.

Covers the failure-facing surface the pairing engine relies on: OPF
entity decoding, whitespace normalisation, degraded reads of corrupt
archives and ledgers, recommendation scoring and its skip paths, and
pairing CRUD edge behaviour.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import zipfile

import pytest

import deeptutor.reading.epub_bilingual as bilingual
from deeptutor.reading.epub_bilingual import (
    PAIRINGS_NAME,
    create_epub_pairing,
    delete_epub_pairing,
    delete_epub_pairings_for_material,
    list_epub_pairings,
    recommend_epub_candidates,
)
from deeptutor.reading.models import ReadingError
from deeptutor.reading.store import ReadingStore

_CONTAINER = (
    "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
    "<rootfiles><rootfile full-path='{opf}'/></rootfiles></container>"
)

_OPF_TEMPLATE = (
    "<package xmlns='http://www.idpf.org/2007/opf' "
    "xmlns:dc='http://purl.org/dc/elements/1.1/' version='3.0'>"
    "<metadata>{metadata}</metadata>"
    "<manifest><item id='one' href='one.xhtml' "
    "media-type='application/xhtml+xml'/></manifest>"
    "<spine><itemref idref='one'/></spine></package>"
)


def _write_epub(
    path: Path,
    *,
    metadata: str = "<dc:identifier>urn:uuid:unit-tests</dc:identifier>"
    "<dc:title>Unit Test Book</dc:title><dc:language>en</dc:language>"
    "<dc:creator>Fixture Author</dc:creator>",
    chapter: str = "Chapter One",
    body: str = "<p>Some story text.</p>",
    container: str | None = None,
    opf_name: str = "OPS/book.opf",
    include_opf: bool = True,
) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            container if container is not None else _CONTAINER.format(opf=opf_name),
        )
        if include_opf:
            archive.writestr(opf_name, _OPF_TEMPLATE.format(metadata=metadata))
        archive.writestr(
            "OPS/one.xhtml",
            "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>"
            f"{chapter}</title></head><body><h1>{chapter}</h1>{body}</body></html>",
        )
    return path


def _drop_raw(store: ReadingStore, material_id: str) -> None:
    raw_file = store.raw_path(material_id)
    assert raw_file is not None
    shutil.rmtree(raw_file.parent)


# ---------------------------------------------------------------------------
# OPF metadata: encoding, entities, normalisation
# ---------------------------------------------------------------------------


def test_metadata_decodes_entities_and_normalises_whitespace(tmp_path: Path) -> None:
    epub = _write_epub(
        tmp_path / "entities.epub",
        metadata=(
            "<dc:title>A &amp; B &#x4e2d;&#25991;</dc:title>"
            "<dc:creator>\n\tFixture&#160;Author\n</dc:creator>"
        ),
    )

    values = bilingual._metadata(epub)

    assert values["title"] == "A & B 中文"
    assert values["creator"] == "Fixture Author"


def test_metadata_keeps_the_first_tag_and_records_empty_values(tmp_path: Path) -> None:
    epub = _write_epub(
        tmp_path / "dupes.epub",
        metadata=(
            "<dc:title>First title</dc:title><dc:title>Second title</dc:title>"
            "<dc:language></dc:language>"
        ),
    )

    values = bilingual._metadata(epub)

    assert values["title"] == "First title"
    assert values["language"] == ""
    assert "creator" not in values
    assert "identifier" not in values


def test_metadata_on_an_empty_metadata_block_is_empty(tmp_path: Path) -> None:
    epub = _write_epub(tmp_path / "bare.epub", metadata="")

    assert bilingual._metadata(epub) == {}


def test_local_name_strips_the_namespace_and_casefolds() -> None:
    assert bilingual._local_name("{http://www.idpf.org/2007/opf}Title") == "title"
    assert bilingual._local_name("TITLE") == "title"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("en-US", "en"),
        ("ZH-Hans-CN", "zh"),
        (" fr ", "fr"),
        ("", ""),
        ("ja", "ja"),
    ],
)
def test_language_normalises_tags(value: str, expected: str) -> None:
    assert bilingual._language(value) == expected


def test_tokens_casefold_and_keep_cjk_and_accents() -> None:
    tokens = bilingual._tokens("Hello CAFÉ 中文")

    assert tokens == {"hello", "café", "中文"}
    assert bilingual._tokens("CAFÉ") & bilingual._tokens("café") == {"café"}


# ---------------------------------------------------------------------------
# Corrupt archives degrade to empty metadata
# ---------------------------------------------------------------------------


def test_metadata_returns_empty_for_a_non_archive(tmp_path: Path) -> None:
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"this is not a zip archive")

    assert bilingual._metadata(bad) == {}


def test_metadata_returns_empty_for_malformed_container(tmp_path: Path) -> None:
    epub = _write_epub(tmp_path / "broken.epub", container="<container><unclosed")

    assert bilingual._metadata(epub) == {}


def test_metadata_returns_empty_without_a_rootfile(tmp_path: Path) -> None:
    epub = _write_epub(
        tmp_path / "noroot.epub",
        container=(
            "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
            "<rootfiles/></container>"
        ),
    )

    assert bilingual._metadata(epub) == {}


@pytest.mark.parametrize(
    "full_path",
    ["../evil.opf", "/abs/book.opf", "OPS/../book.opf"],
)
def test_metadata_rejects_opf_path_traversal(tmp_path: Path, full_path: str) -> None:
    epub = _write_epub(
        tmp_path / "traversal.epub",
        container=(
            "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
            f"<rootfiles><rootfile full-path='{full_path}'/></rootfiles></container>"
        ),
    )

    assert bilingual._metadata(epub) == {}


@pytest.mark.parametrize("missing", ["META-INF/container.xml", "OPS/book.opf"])
def test_metadata_returns_empty_for_missing_archive_entries(tmp_path: Path, missing: str) -> None:
    path = tmp_path / "incomplete.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        if missing != "META-INF/container.xml":
            archive.writestr("META-INF/container.xml", _CONTAINER.format(opf="OPS/book.opf"))
        if missing != "OPS/book.opf":
            archive.writestr("OPS/book.opf", _OPF_TEMPLATE.format(metadata=""))

    assert bilingual._metadata(path) == {}


# ---------------------------------------------------------------------------
# Recommendation scoring: aligning two editions
# ---------------------------------------------------------------------------


def test_ranking_prefers_identifier_author_and_language_bonus(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            metadata=(
                "<dc:identifier>urn:uuid:twin</dc:identifier>"
                "<dc:title>Twin Study</dc:title><dc:language>en</dc:language>"
                "<dc:creator>A. Author</dc:creator>"
            ),
            chapter="Twin Study",
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            metadata=(
                "<dc:identifier>urn:uuid:twin</dc:identifier>"
                "<dc:title>Twin Study</dc:title><dc:language>zh</dc:language>"
                "<dc:creator>A. Author</dc:creator>"
            ),
            chapter="别的章节",
            body="<p>别的故事。</p>",
        )
    )
    english_twin = store.ingest(
        _write_epub(
            tmp_path / "english-twin.epub",
            metadata=(
                "<dc:identifier>urn:uuid:twin</dc:identifier>"
                "<dc:title>Twin Study</dc:title><dc:language>en</dc:language>"
                "<dc:creator>A. Author</dc:creator>"
            ),
            chapter="Other Chapter",
            body="<p>Another telling.</p>",
        )
    )

    candidates = recommend_epub_candidates(store, english.material_id)

    assert [row["material_id"] for row in candidates] == [
        chinese.material_id,
        english_twin.material_id,
    ]
    assert candidates[0]["reasons"] == {
        "title": 1.0,
        "toc": 0.0,
        "identifier": True,
        "author": True,
        "different_language": True,
    }
    assert candidates[1]["reasons"]["different_language"] is False
    assert candidates[0]["score"] - candidates[1]["score"] == pytest.approx(0.1)


def test_outline_title_overlap_scores_without_metadata(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            metadata="<dc:language>en</dc:language>",
            chapter="Shared Heading",
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            metadata="<dc:language>zh</dc:language>",
            chapter="Shared Heading",
            body="<p>中文正文。</p>",
        )
    )

    candidates = recommend_epub_candidates(store, english.material_id)

    assert [row["material_id"] for row in candidates] == [chinese.material_id]
    assert candidates[0]["reasons"]["toc"] == 1.0
    assert candidates[0]["reasons"]["different_language"] is True
    assert candidates[0]["score"] == pytest.approx(0.3)


def test_a_bare_candidate_is_listed_with_a_zero_score(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))
    bare = store.ingest(
        _write_epub(
            tmp_path / "bare.epub",
            metadata="",
            chapter="完全不同",
            body="<p>无元数据。</p>",
        )
    )

    candidates = recommend_epub_candidates(store, english.material_id)

    assert [row["material_id"] for row in candidates] == [bare.material_id]
    row = candidates[0]
    assert row["score"] == 0.0
    assert row["language"] == ""
    assert row["author"] == ""
    assert row["reasons"] == {
        "title": 0.0,
        "toc": 0.0,
        "identifier": False,
        "author": False,
        "different_language": False,
    }


# ---------------------------------------------------------------------------
# Degraded recommendation paths
# ---------------------------------------------------------------------------


def test_candidates_skip_text_materials_and_unreadable_epubs(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            metadata="<dc:identifier>urn:uuid:twin</dc:identifier><dc:language>zh</dc:language>",
            chapter="别的章节",
        )
    )
    broken = store.ingest(
        _write_epub(
            tmp_path / "broken.epub",
            metadata="<dc:identifier>urn:uuid:twin</dc:identifier><dc:language>zh</dc:language>",
            chapter="损坏章节",
            body="<p>原文丢失。</p>",
        )
    )
    notes = store.ingest(_write_text(tmp_path / "notes.md", "# Notes\n\nSome text."))
    _drop_raw(store, broken.material_id)

    candidates = recommend_epub_candidates(store, english.material_id)

    assert notes.render_mode == "text"
    assert [row["material_id"] for row in candidates] == [chinese.material_id]


def test_recommendation_requires_an_epub_source(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    notes = store.ingest(_write_text(tmp_path / "notes.md", "# Notes\n\nSome text."))

    with pytest.raises(ReadingError, match="only available for EPUB materials"):
        recommend_epub_candidates(store, notes.material_id)


def test_recommendation_fails_when_the_source_epub_is_unreadable(
    tmp_path: Path,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))
    _drop_raw(store, english.material_id)

    with pytest.raises(ReadingError, match="The source EPUB is unavailable."):
        recommend_epub_candidates(store, english.material_id)


# ---------------------------------------------------------------------------
# Pairing CRUD edges
# ---------------------------------------------------------------------------


def test_pairing_rejects_pairing_a_material_with_itself(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))

    with pytest.raises(ReadingError, match="two different"):
        create_epub_pairing(store, english.material_id, english.material_id)
    assert list_epub_pairings(store) == []


def test_pairing_requires_available_raw_files(tmp_path: Path) -> None:
    english_store = ReadingStore(root=tmp_path / "english-side")
    english = english_store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))
    chinese = english_store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            metadata="<dc:language>zh</dc:language>",
            chapter="第一章",
        )
    )
    _drop_raw(english_store, english.material_id)

    with pytest.raises(ReadingError, match="The English EPUB is unavailable."):
        create_epub_pairing(english_store, english.material_id, chinese.material_id)

    chinese_store = ReadingStore(root=tmp_path / "chinese-side")
    english_again = chinese_store.ingest(
        _write_epub(tmp_path / "english-2.epub", chapter="Chapter Two")
    )
    chinese_again = chinese_store.ingest(
        _write_epub(
            tmp_path / "chinese-2.epub",
            metadata="<dc:language>zh</dc:language>",
            chapter="第二章",
        )
    )
    _drop_raw(chinese_store, chinese_again.material_id)

    with pytest.raises(ReadingError, match="The Chinese EPUB is unavailable."):
        create_epub_pairing(chinese_store, english_again.material_id, chinese_again.material_id)
    assert list_epub_pairings(english_store) == []
    assert list_epub_pairings(chinese_store) == []


def test_creating_the_same_pair_twice_keeps_one_row(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            metadata="<dc:language>zh</dc:language>",
            chapter="第一章",
        )
    )

    first = create_epub_pairing(store, english.material_id, chinese.material_id)
    second = create_epub_pairing(store, english.material_id, chinese.material_id)

    assert first["pairing_id"] == second["pairing_id"]
    assert list_epub_pairings(store) == [second]


def test_deleting_an_unknown_pairing_is_a_noop(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    pairing_path = store.root / PAIRINGS_NAME

    assert delete_epub_pairing(store, "missing-id") is False
    assert not pairing_path.exists()

    english = store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            metadata="<dc:language>zh</dc:language>",
            chapter="第一章",
        )
    )
    pairing = create_epub_pairing(store, english.material_id, chinese.material_id)

    assert delete_epub_pairing(store, "missing-id") is False
    assert list_epub_pairings(store) == [pairing]


def test_deleting_pairings_for_a_material_removes_both_roles(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(_write_epub(tmp_path / "english.epub", chapter="Chapter One"))
    first_chinese = store.ingest(
        _write_epub(
            tmp_path / "first-chinese.epub",
            metadata="<dc:language>zh</dc:language>",
            chapter="第一章",
        )
    )
    second_chinese = store.ingest(
        _write_epub(
            tmp_path / "second-chinese.epub",
            metadata="<dc:language>zh</dc:language>",
            chapter="第二章",
        )
    )
    create_epub_pairing(store, english.material_id, first_chinese.material_id)
    create_epub_pairing(store, english.material_id, second_chinese.material_id)

    assert delete_epub_pairings_for_material(store, first_chinese.material_id) == 1
    remaining = list_epub_pairings(store)
    assert [row["chinese_material_id"] for row in remaining] == [second_chinese.material_id]

    assert delete_epub_pairings_for_material(store, english.material_id) == 1
    assert list_epub_pairings(store) == []


def test_deleting_pairings_for_an_unknown_material_writes_nothing(
    tmp_path: Path,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")

    assert delete_epub_pairings_for_material(store, "unknown-material") == 0
    assert bilingual._pairing_path(store) == store.root / PAIRINGS_NAME
    assert not (store.root / PAIRINGS_NAME).exists()
    assert list_epub_pairings(store) == []


@pytest.mark.parametrize("payload", [None, "not json", '{"pairing_id": "x"}'])
def test_pairing_ledger_degrades_to_empty_on_unreadable_files(
    tmp_path: Path, payload: str | None
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    pairing_path = bilingual._pairing_path(store)
    pairing_path.parent.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        pairing_path.write_text(payload, encoding="utf-8")

    assert list_epub_pairings(store) == []


def _write_text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path
