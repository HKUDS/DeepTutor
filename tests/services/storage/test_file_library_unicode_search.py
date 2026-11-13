"""Case-insensitive library search also works for multilingual filenames."""

import asyncio
from pathlib import Path

import pytest

from deeptutor.services.storage.file_library import FileLibraryStore


@pytest.mark.parametrize(
    ("filename", "query"),
    [
        ("ÉCOLE.pdf", "école"),
        ("ПЛАН.pdf", "план"),
        ("ΜΆΘΗΜΑ.pdf", "μάθημα"),
        ("Straße.pdf", "STRASSE"),
        ("ÜBERBLICK.pdf", "überblick"),
        ("Notes.pdf", "notes"),
    ],
)
def test_filename_search_matches_unicode_case(
    tmp_path: Path,
    filename: str,
    query: str,
) -> None:
    store = FileLibraryStore(tmp_path / "library.db", root=tmp_path / "files")
    expected = asyncio.run(store.add_file(data=b"selected", filename=filename))
    asyncio.run(store.add_file(data=b"other", filename="unrelated.pdf"))
    found = asyncio.run(store.search_files(query))
    assert [entry["id"] for entry in found] == [expected["id"]]
    asyncio.run(store.delete_file(expected["id"]))
    assert asyncio.run(store.search_files(query)) == []


@pytest.mark.parametrize(
    ("filename", "query", "decoy"),
    [
        ("ÉCOLE_80%.pdf", "école_80%", "ÉCOLEa800.pdf"),
        ("ÉCOLE\\draft.pdf", "école\\draft", "ÉCOLEdraft.pdf"),
    ],
)
def test_unicode_search_preserves_literal_like_metacharacters(
    tmp_path: Path,
    filename: str,
    query: str,
    decoy: str,
) -> None:
    store = FileLibraryStore(tmp_path / "library.db", root=tmp_path / "files")
    expected = asyncio.run(store.add_file(data=b"selected", filename=filename))
    asyncio.run(store.add_file(data=b"other", filename=decoy))
    assert [entry["id"] for entry in asyncio.run(store.search_files(query))] == [expected["id"]]
