"""Engine tests for explicit bilingual EPUB pairing."""

from __future__ import annotations

import base64
from pathlib import Path
import threading
import zipfile

import pytest

import deeptutor.reading.epub_bilingual as bilingual
from deeptutor.reading.epub_bilingual import (
    create_epub_pairing,
    delete_epub_pairing,
    list_epub_pairings,
    recommend_epub_candidates,
)
from deeptutor.reading.models import ReadingError
from deeptutor.reading.store import ReadingStore

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _write_epub(
    path: Path,
    *,
    language: str,
    chapter: str,
    paragraph: str,
    include_image: bool = False,
    decoy_language: str | None = None,
) -> Path:
    image_manifest = (
        "<item id='picture' href='picture.png' media-type='image/png'/>" if include_image else ""
    )
    image_body = (
        "<img src='picture.png' alt='source illustration' width='240' height='80'/>"
        if include_image
        else ""
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", zipfile.ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            "<container xmlns='urn:oasis:names:tc:opendocument:xmlns:container'>"
            "<rootfiles><rootfile full-path='OPS/book.opf'/></rootfiles></container>",
        )
        if decoy_language is not None:
            archive.writestr(
                "AAA/decoy.opf",
                "<package xmlns='http://www.idpf.org/2007/opf' "
                "xmlns:dc='http://purl.org/dc/elements/1.1/' version='3.0'>"
                f"<metadata><dc:language>{decoy_language}</dc:language></metadata></package>",
            )
        archive.writestr(
            "OPS/book.opf",
            "<package xmlns='http://www.idpf.org/2007/opf' "
            "xmlns:dc='http://purl.org/dc/elements/1.1/' version='3.0'>"
            "<metadata><dc:identifier>urn:uuid:bilingual-test</dc:identifier>"
            f"<dc:title>Bilingual test</dc:title><dc:language>{language}</dc:language>"
            "<dc:creator>Fixture Author</dc:creator></metadata>"
            f"<manifest><item id='one' href='one.xhtml' media-type='application/xhtml+xml'/>{image_manifest}</manifest>"
            "<spine><itemref idref='one'/></spine></package>",
        )
        archive.writestr(
            "OPS/one.xhtml",
            "<html xmlns='http://www.w3.org/1999/xhtml'><head><title>"
            f"{chapter}</title></head><body><h1>{chapter}</h1>"
            f"<p>{paragraph}</p>{image_body}</body></html>",
        )
        if include_image:
            archive.writestr("OPS/picture.png", PNG_BYTES)
    return path


def test_candidates_rank_a_different_language_edition_without_auto_pairing(
    tmp_path: Path,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            language="en",
            chapter="Illustrated chapter",
            paragraph="English source paragraph.",
            include_image=True,
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            language="zh-CN",
            chapter="插图章节",
            paragraph="中文来源段落。",
        )
    )

    candidates = recommend_epub_candidates(store, english.material_id)

    assert candidates[0]["material_id"] == chinese.material_id
    assert candidates[0]["reasons"]["identifier"] is True
    assert candidates[0]["reasons"]["author"] is True
    assert candidates[0]["reasons"]["different_language"] is True
    assert list_epub_pairings(store) == []


def test_explicit_pairing_stores_metadata_without_deriving_material(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            language="en",
            chapter="Illustrated chapter",
            paragraph="English source paragraph.",
            include_image=True,
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            language="zh",
            chapter="插图章节",
            paragraph="中文来源段落。",
        )
    )

    material_ids = {row.material_id for row in store.list_materials()}
    pairing = create_epub_pairing(store, english.material_id, chinese.material_id)

    assert pairing["english_material_id"] == english.material_id
    assert pairing["chinese_material_id"] == chinese.material_id
    assert pairing["english_language"] == "en"
    assert pairing["chinese_language"] == "zh"
    assert pairing["status"] == "confirmed"
    assert list_epub_pairings(store) == [pairing]
    assert {row.material_id for row in store.list_materials()} == material_ids

    assert delete_epub_pairing(store, pairing["pairing_id"]) is True
    assert list_epub_pairings(store) == []
    assert {row.material_id for row in store.list_materials()} == material_ids


def test_metadata_uses_the_container_declared_opf(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            language="en-US",
            chapter="One",
            paragraph="English.",
            decoy_language="zh",
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            language="zh-Hans",
            chapter="一",
            paragraph="中文。",
            decoy_language="en",
        )
    )

    pairing = create_epub_pairing(store, english.material_id, chinese.material_id)

    assert pairing["english_language"] == "en"
    assert pairing["chinese_language"] == "zh"


@pytest.mark.parametrize(
    ("english_language", "chinese_language"),
    [
        ("", "zh"),
        ("fr", "zh"),
        ("en", ""),
        ("en", "ja"),
        ("zh", "en"),
    ],
)
def test_pairing_requires_declared_english_and_chinese_roles(
    tmp_path: Path,
    english_language: str,
    chinese_language: str,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "first.epub",
            language=english_language,
            chapter="One",
            paragraph="First edition.",
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "second.epub",
            language=chinese_language,
            chapter="Two",
            paragraph="Second edition.",
        )
    )

    with pytest.raises(ReadingError, match="must declare"):
        create_epub_pairing(store, english.material_id, chinese.material_id)


def test_deleting_material_removes_its_pairing(tmp_path: Path) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            language="en",
            chapter="One",
            paragraph="English.",
        )
    )
    chinese = store.ingest(
        _write_epub(
            tmp_path / "chinese.epub",
            language="zh",
            chapter="一",
            paragraph="中文。",
        )
    )
    create_epub_pairing(store, english.material_id, chinese.material_id)

    assert store.delete(english.material_id) is True
    assert list_epub_pairings(store) == []


def test_concurrent_delete_cannot_overwrite_a_new_pairing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ReadingStore(root=tmp_path / "materials")
    english = store.ingest(
        _write_epub(
            tmp_path / "english.epub",
            language="en",
            chapter="One",
            paragraph="English.",
        )
    )
    first_chinese = store.ingest(
        _write_epub(
            tmp_path / "first-chinese.epub",
            language="zh",
            chapter="一",
            paragraph="第一版。",
        )
    )
    second_chinese = store.ingest(
        _write_epub(
            tmp_path / "second-chinese.epub",
            language="zh",
            chapter="二",
            paragraph="第二版。",
        )
    )
    first = create_epub_pairing(store, english.material_id, first_chinese.material_id)
    real_list = bilingual.list_epub_pairings
    delete_read = threading.Event()
    allow_delete = threading.Event()

    def controlled_list(target: ReadingStore) -> list[dict]:
        rows = real_list(target)
        if threading.current_thread().name == "pairing-delete":
            delete_read.set()
            assert allow_delete.wait(timeout=2)
        return rows

    monkeypatch.setattr(bilingual, "list_epub_pairings", controlled_list)
    errors: list[BaseException] = []

    def deleting() -> None:
        try:
            bilingual.delete_epub_pairing(store, first["pairing_id"])
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    def creating() -> None:
        try:
            create_epub_pairing(store, english.material_id, second_chinese.material_id)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    delete_thread = threading.Thread(target=deleting, name="pairing-delete")
    create_thread = threading.Thread(target=creating, name="pairing-create")
    delete_thread.start()
    assert delete_read.wait(timeout=2)
    create_thread.start()
    allow_delete.set()
    delete_thread.join(timeout=2)
    create_thread.join(timeout=2)

    assert not delete_thread.is_alive()
    assert not create_thread.is_alive()
    assert errors == []
    assert [row["chinese_material_id"] for row in real_list(store)] == [second_chinese.material_id]
