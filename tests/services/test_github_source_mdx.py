"""GitHub sources must download ``.mdx`` docs, and re-index must see them.

Issue #2552: a source for ``lvgl/lvgl`` at ``docs/`` with glob ``*.mdx``
finished ``last_sync_status: success`` and ``files_synced: 0``. The sync
filter kept only ``.md`` and ``.markdown``, so nothing landed in ``raw/``.
Re-index then raised ``ValueError`` because that directory had no supported
source files.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from deeptutor.services.github_source import sync as sync_module
from deeptutor.services.github_source.client import FileChange
from deeptutor.services.rag.file_routing import DocumentType, FileTypeRouter


@dataclass
class _Entry:
    path: str


class _Client:
    def __init__(self, entries: list[_Entry]) -> None:
        self._entries = entries
        self.downloaded: list[str] = []

    async def get_tree(self, repo, branch, *, path_prefix="", glob="*"):
        return self._entries

    async def download_file(self, repo, path, sha):
        self.downloaded.append(path)
        return b"# Button\n\n<Demo />\n"


def test_filter_keeps_mdx_that_matches_the_glob_and_drops_other_types() -> None:
    entries = [
        _Entry("docs/widgets/button.mdx"),
        _Entry("docs/intro.md"),
        _Entry("docs/assets/logo.png"),
        _Entry("README.mdx"),
    ]

    kept = sync_module._filter_markdown_entries(entries, "docs/", "*.mdx")

    assert [entry.path for entry in kept] == ["docs/widgets/button.mdx"]


def test_default_markdown_glob_still_skips_mdx() -> None:
    entries = [_Entry("docs/intro.md"), _Entry("docs/widgets/button.mdx")]

    kept = sync_module._filter_markdown_entries(entries, "docs/", "*.md")

    assert [entry.path for entry in kept] == ["docs/intro.md"]


def test_incremental_filter_keeps_mdx_changes() -> None:
    changes = [
        FileChange("docs/widgets/button.mdx", "modified", "abc"),
        FileChange("docs/intro.mdx", "removed", "def"),
        FileChange("docs/assets/logo.png", "modified", "ghi"),
    ]

    kept = sync_module._filter_markdown_changes(changes, "docs/", "*.mdx")

    assert [(change.path, change.status) for change in kept] == [
        ("docs/widgets/button.mdx", "modified"),
        ("docs/intro.mdx", "removed"),
    ]


def test_full_sync_writes_mdx_into_raw(tmp_path: Path, monkeypatch) -> None:
    raw_dir = tmp_path / "LVGL" / "raw"
    raw_dir.mkdir(parents=True)
    indexed: list[str] = []

    async def _record_index(_kb_name, files, _base_dir):
        indexed.extend(files)

    monkeypatch.setattr(sync_module, "_index_files", _record_index)
    client = _Client(
        [
            _Entry("docs/widgets/button.mdx"),
            _Entry("docs/assets/logo.png"),
            _Entry("other/readme.mdx"),
        ]
    )

    result = asyncio.run(
        sync_module._full_sync(
            client,
            "LVGL",
            raw_dir,
            "lvgl/lvgl",
            "v9.6.0",
            "docs/",
            "*.mdx",
            "deadbeef",
            str(tmp_path),
        )
    )

    written = raw_dir / "widgets" / "button.mdx"
    assert result.ok is True
    assert result.files_added == 1
    assert client.downloaded == ["docs/widgets/button.mdx"]
    assert written.read_bytes() == b"# Button\n\n<Demo />\n"
    assert indexed == [str(written)]
    assert not (raw_dir / "assets" / "logo.png").exists()


def test_mdx_only_raw_directory_is_reindexable(tmp_path: Path) -> None:
    raw_dir = tmp_path / "LVGL" / "raw" / "widgets"
    raw_dir.mkdir(parents=True)
    source = raw_dir / "button.mdx"
    source.write_text("# Button\n\n<Demo />\n", encoding="utf-8")
    (raw_dir / "logo.bin").write_bytes(b"\x00\x01")

    discovered = FileTypeRouter.collect_supported_files(tmp_path / "LVGL" / "raw", recursive=True)
    classification = FileTypeRouter.classify_files([str(source)])

    assert [path.name for path in discovered] == ["button.mdx"]
    assert FileTypeRouter.get_document_type("guide.MDX") is DocumentType.TEXT
    assert ".mdx" in FileTypeRouter.get_supported_extensions()
    assert classification.text_files == [str(source)]
    assert classification.unsupported == []
