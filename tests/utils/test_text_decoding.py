"""Legacy single-byte encodings decode to the text the author wrote."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.utils.file_types import FileTypeRouter

TURKISH_PARAGRAPH = (
    "Öğrenciler sınav haftasında kütüphanede çalışıyor. Şirketin İstanbul'daki "
    "eğitim merkezi, ağaç gölgesinde ders işlemeyi seviyor. Ilık bir sabahta "
    "öğretmen, sorulara cevap verirken öğrencilerin dikkatini çekti. "
)

CHINESE = "这是一个中文测试文件，用于检查编码识别是否正确。用Python编程很有趣。"


@pytest.mark.parametrize("repeat", [1, 2, 4])
def test_windows_1254_turkish_keeps_its_letters(repeat: int) -> None:
    text = TURKISH_PARAGRAPH * repeat
    assert FileTypeRouter.decode_bytes(text.encode("cp1254"), language_hint="tr-TR") == text


@pytest.mark.parametrize("text", ["Çiçek", "İyi günler"])
def test_short_windows_1254_turkish(text: str) -> None:
    assert FileTypeRouter.decode_bytes(text.encode("cp1254"), language_hint="tr-TR") == text


@pytest.mark.parametrize("encoding", ["gbk", "gb18030"])
def test_chinese_encodings_are_unchanged(encoding: str) -> None:
    assert FileTypeRouter.decode_bytes(CHINESE.encode(encoding)) == CHINESE


@pytest.mark.parametrize(
    "text",
    [
        "Les élèves révisent à la bibliothèque, « c’est l’été ».",
        "Die Schüler lernen für die Prüfung – „schön“ und groß.",
    ],
)
def test_windows_1252_text_and_smart_quotes(text: str) -> None:
    assert FileTypeRouter.decode_bytes(text.encode("cp1252")) == text


def test_utf8_with_bom() -> None:
    assert FileTypeRouter.decode_bytes("﻿Çalışma notu".encode("utf-8")) == "﻿Çalışma notu"


def test_read_text_file_uses_the_same_chain(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_bytes((TURKISH_PARAGRAPH * 2).encode("cp1254"))
    assert (
        asyncio.run(FileTypeRouter.read_text_file(str(path), language_hint="tr"))
        == TURKISH_PARAGRAPH * 2
    )


def test_upload_extractor_uses_account_locale_without_affecting_utf8(monkeypatch):
    from deeptutor.services.settings import interface_settings
    from deeptutor.utils.document_extractor import extract_text_from_bytes

    monkeypatch.setattr(interface_settings, "get_ui_language", lambda: "tr")
    assert extract_text_from_bytes("flower.txt", "Çiçek".encode("cp1254")) == "Çiçek"
    assert extract_text_from_bytes("notes.txt", CHINESE.encode("utf-8")) == CHINESE
    assert FileTypeRouter.decode_bytes(CHINESE.encode("gbk"), encoding="gbk") == CHINESE


def test_explicit_encoding_is_strict_and_keeps_other_latin_alphabets():
    icelandic = "Það er góð hugmynd"
    assert FileTypeRouter.decode_bytes(icelandic.encode("cp1252"), encoding="cp1252") == icelandic
    with pytest.raises(UnicodeDecodeError):
        FileTypeRouter.decode_bytes(b"\xff", encoding="utf-8")
