"""Tests for web-source bilingual page pairing and persistence."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deeptutor.services.web_source.bilingual import (
    detect_bilingual_pairings,
    extract_url_language_and_stem,
    is_supported_pair,
    normalize_language,
)
from deeptutor.services.web_source.crawler import CrawledPage
from deeptutor.services.web_source.html_extractor import extract_page_language_and_alternates
from deeptutor.services.web_source.repository import (
    SQLiteWebSourceSyncRepository,
    WebSourceBilingualPairing,
)


def test_normalize_language() -> None:
    assert normalize_language("en-US") == "en"
    assert normalize_language("EN") == "en"
    assert normalize_language("zh-CN") == "zh"
    assert normalize_language("zh_cn") == "zh"
    assert normalize_language("zh-Hans") == "zh"
    assert normalize_language("zh-Hant") == "zh"
    assert normalize_language("ja-JP") == "ja"
    assert normalize_language("x-default") == ""
    assert normalize_language("") == ""
    assert normalize_language(None) == ""


def test_is_supported_pair() -> None:
    assert is_supported_pair("en", "zh") is True
    assert is_supported_pair("zh", "en") is True
    assert is_supported_pair("en", "ja") is True
    assert is_supported_pair("en", "fr") is True
    assert is_supported_pair("en", "en") is False
    assert is_supported_pair("", "en") is False


def test_extract_url_language_and_stem() -> None:
    assert extract_url_language_and_stem("https://example.com/en/docs/intro") == (
        "en",
        "/docs/intro",
    )
    assert extract_url_language_and_stem("https://example.com/zh-cn/docs/intro") == (
        "zh",
        "/docs/intro",
    )
    assert extract_url_language_and_stem("https://example.com/docs/en/intro") == (
        "en",
        "/docs/intro",
    )
    assert extract_url_language_and_stem("https://example.com/docs/zh/intro") == (
        "zh",
        "/docs/intro",
    )
    assert extract_url_language_and_stem("https://example.com/docs/intro") == (
        "",
        "/docs/intro",
    )
    assert extract_url_language_and_stem("https://example.com/") == ("", "/")


def test_extract_page_language_and_alternates() -> None:
    html = """<!DOCTYPE html>
    <html lang="en">
    <head>
        <link rel="alternate" hreflang="zh-CN" href="/zh/docs/intro" />
        <link rel="alternate" hreflang="en" href="/docs/intro" />
        <link rel="alternate" hreflang="x-default" href="/docs/intro" />
    </head>
    <body><h1>Introduction</h1></body>
    </html>"""
    lang, alternates = extract_page_language_and_alternates(html, "https://example.com/docs/intro")
    assert lang == "en"
    assert alternates == {
        "zh": "https://example.com/zh/docs/intro",
        "en": "https://example.com/docs/intro",
    }


def test_detect_bilingual_pairings_hreflang() -> None:
    p_en = CrawledPage(
        url="https://example.com/docs/intro",
        title="Intro",
        markdown="# Intro",
        content_hash="hash-en",
        language="en",
        alternate_links={"zh": "https://example.com/zh/docs/intro"},
    )
    p_zh = CrawledPage(
        url="https://example.com/zh/docs/intro",
        title="介绍",
        markdown="# 介绍",
        content_hash="hash-zh",
        language="zh",
        alternate_links={"en": "https://example.com/docs/intro"},
    )

    file_map = {
        "https://example.com/docs/intro": "_web/abc/docs/intro.md",
        "https://example.com/zh/docs/intro": "_web/abc/zh/docs/intro.md",
    }

    pairings = detect_bilingual_pairings([p_en, p_zh], file_map)
    assert len(pairings) == 1
    pair = pairings[0]
    assert pair["source_url"] == "https://example.com/docs/intro"
    assert pair["target_url"] == "https://example.com/zh/docs/intro"
    assert pair["source_lang"] == "en"
    assert pair["target_lang"] == "zh"
    assert pair["source_file"] == "_web/abc/docs/intro.md"
    assert pair["target_file"] == "_web/abc/zh/docs/intro.md"
    assert pair["pairing_method"] == "hreflang"


def test_detect_bilingual_pairings_url_pattern() -> None:
    p_en = CrawledPage(
        url="https://example.com/en/guide/install",
        title="Install",
        markdown="# Install",
        content_hash="hash-en",
        language="en",
    )
    p_zh = CrawledPage(
        url="https://example.com/zh/guide/install",
        title="安装",
        markdown="# 安装",
        content_hash="hash-zh",
        language="zh",
    )

    pairings = detect_bilingual_pairings([p_en, p_zh])
    assert len(pairings) == 1
    pair = pairings[0]
    assert pair["source_url"] == "https://example.com/en/guide/install"
    assert pair["target_url"] == "https://example.com/zh/guide/install"
    assert pair["source_lang"] == "en"
    assert pair["target_lang"] == "zh"
    assert pair["pairing_method"] == "url_pattern"


def test_repository_pairings_crud(tmp_path: Path) -> None:
    repo = SQLiteWebSourceSyncRepository(tmp_path / "test-jobs.sqlite")
    owner_id = "user-123"
    kb_name = "test-kb"
    source_id = "src-456"

    pairings_data = [
        {
            "pairing_id": "pair-001",
            "source_url": "https://example.com/docs/intro",
            "target_url": "https://example.com/zh/docs/intro",
            "source_file": "_web/s1/docs/intro.md",
            "target_file": "_web/s1/zh/docs/intro.md",
            "source_lang": "en",
            "target_lang": "zh",
            "pairing_method": "hreflang",
        }
    ]

    saved = repo.record_pairings(owner_id, kb_name, source_id, pairings_data)
    assert len(saved) == 1
    assert isinstance(saved[0], WebSourceBilingualPairing)
    assert saved[0].pairing_id == "pair-001"
    assert saved[0].source_url == "https://example.com/docs/intro"

    # List pairings for specific source
    listed = repo.list_pairings(owner_id, kb_name, source_id)
    assert len(listed) == 1
    assert listed[0].public_dict()["pairing_id"] == "pair-001"

    # List pairings across all sources in KB
    all_kb_pairs = repo.list_pairings(owner_id, kb_name)
    assert len(all_kb_pairs) == 1

    # Atomic replace with empty
    replaced = repo.record_pairings(owner_id, kb_name, source_id, [])
    assert len(replaced) == 0
    assert len(repo.list_pairings(owner_id, kb_name, source_id)) == 0


def test_delete_source_cleans_up_pairings(tmp_path: Path) -> None:
    repo = SQLiteWebSourceSyncRepository(tmp_path / "test-jobs.sqlite")
    owner_id = "user-123"
    kb_name = "test-kb"
    source_id = "src-456"

    repo.ensure_source((owner_id, kb_name, source_id))
    repo.record_pairings(
        owner_id,
        kb_name,
        source_id,
        [
            {
                "pairing_id": "pair-001",
                "source_url": "https://example.com/docs/intro",
                "target_url": "https://example.com/zh/docs/intro",
                "source_file": "_web/s1/docs/intro.md",
                "target_file": "_web/s1/zh/docs/intro.md",
                "source_lang": "en",
                "target_lang": "zh",
                "pairing_method": "hreflang",
            }
        ],
    )
    assert len(repo.list_pairings(owner_id, kb_name, source_id)) == 1

    # Deleting source deletes both job and pairings
    repo.delete((owner_id, kb_name, source_id))
    assert repo.get((owner_id, kb_name, source_id)) is None
    assert len(repo.list_pairings(owner_id, kb_name, source_id)) == 0


def test_non_web_kb_isolation(tmp_path: Path) -> None:
    """Ensure non-web knowledge bases are isolated and do not interact with pairings."""
    repo = SQLiteWebSourceSyncRepository(tmp_path / "test-jobs.sqlite")
    owner_id = "user-123"

    # Querying a non-web KB returns empty list, never raises
    pairs = repo.list_pairings(owner_id, "marginnote-kb")
    assert pairs == []

    # Deleting non-existent returns 0
    deleted = repo.delete_pairings(owner_id, "marginnote-kb", "src-nonexistent")
    assert deleted == 0
