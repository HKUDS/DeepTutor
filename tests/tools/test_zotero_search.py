from __future__ import annotations

import pytest

from deeptutor.tools.zotero_search import ZoteroSearchTool


def _zotero_item(title: str, key: str, year: str, authors: list[dict]) -> dict:
    return {
        "key": key,
        "version": 1,
        "library": {"type": "user", "id": 12345},
        "links": {"alternate": {"href": f"https://www.zotero.org/users/12345/items/{key}"}},
        "data": {
            "key": key,
            "version": 1,
            "itemType": "journalArticle",
            "title": title,
            "creators": authors,
            "date": year,
            "DOI": f"10.1234/{key}",
            "url": "",
            "abstractNote": f"Abstract for {title}",
        },
    }


def test_normalize_zotero_item() -> None:
    raw = _zotero_item(
        "Attention Is All You Need",
        "ABCD1234",
        "2017",
        [{"firstName": "Ashish", "lastName": "Vaswani"}],
    )
    result = ZoteroSearchTool._normalize(raw)
    assert result["title"] == "Attention Is All You Need"
    assert result["authors"] == ["Ashish Vaswani"]
    assert result["year"] == "2017"
    assert result["doi"] == "10.1234/ABCD1234"
    assert result["zotero_key"] == "ABCD1234"


def test_normalize_empty_creators() -> None:
    raw = _zotero_item("Test", "TEST1", "2024", [])
    result = ZoteroSearchTool._normalize(raw)
    assert result["authors"] == []
