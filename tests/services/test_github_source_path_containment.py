"""The GitHub sync must not write outside the KB's raw directory.

Destination paths are derived from the tree/compare responses of a remote API,
so they are remote input. Two shapes escape a naive ``raw_dir / rel``: a ``..``
segment, and an absolute path — ``Path("/kb") / "/etc/x"`` evaluates to
``/etc/x``, silently dropping the base. git rejects both in tree entries today,
but a downloader must enforce where it writes rather than trust the remote to.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from deeptutor.services.github_source import sync as sync_module


@dataclass
class _Entry:
    path: str


class _Client:
    """Serves any requested path, recording what was asked for."""

    def __init__(self, entries: list[_Entry]) -> None:
        self._entries = entries
        self.downloaded: list[str] = []

    async def get_tree(self, repo, branch, *, path_prefix="", glob="*"):
        return self._entries

    async def download_file(self, repo, path, sha):
        self.downloaded.append(path)
        return b"# owned\n"


def _run_full_sync(tmp_path: Path, entries: list[_Entry], monkeypatch) -> Path:
    raw_dir = tmp_path / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    monkeypatch.setattr(sync_module, "_filter_markdown_entries", lambda e, p, g: e)

    async def _no_index(kb_name, files, base_dir):
        return None

    monkeypatch.setattr(sync_module, "_index_files", _no_index)
    client = _Client(entries)
    asyncio.run(
        sync_module._full_sync(
            client,
            "kb",
            raw_dir,
            "owner/repo",
            "main",
            "",
            "*",
            "deadbeef",
            str(tmp_path),
        )
    )
    return raw_dir


def test_parent_traversal_is_refused(tmp_path: Path, monkeypatch) -> None:
    raw_dir = _run_full_sync(tmp_path, [_Entry("../../escaped.md"), _Entry("kept.md")], monkeypatch)

    assert (raw_dir / "kept.md").read_bytes() == b"# owned\n"
    assert not (tmp_path / "escaped.md").exists()
    assert not (tmp_path.parent / "escaped.md").exists()


def test_absolute_path_is_refused(tmp_path: Path, monkeypatch) -> None:
    outside = tmp_path / "outside" / "absolute.md"
    outside.parent.mkdir(parents=True)
    raw_dir = _run_full_sync(tmp_path, [_Entry(str(outside)), _Entry("kept.md")], monkeypatch)

    assert (raw_dir / "kept.md").read_bytes() == b"# owned\n"
    assert not outside.exists(), "an absolute tree path discarded the raw dir"


def test_nested_paths_inside_the_raw_dir_still_sync(tmp_path: Path, monkeypatch) -> None:
    raw_dir = _run_full_sync(tmp_path, [_Entry("docs/guide/intro.md")], monkeypatch)

    assert (raw_dir / "docs" / "guide" / "intro.md").read_bytes() == b"# owned\n"


def test_removal_of_an_escaping_path_leaves_the_target_alone(tmp_path: Path) -> None:
    raw_dir = tmp_path / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    victim = tmp_path / "victim.md"
    victim.write_text("keep me", encoding="utf-8")

    assert sync_module._contained_dest(raw_dir, "../victim.md") is None
    assert victim.read_text(encoding="utf-8") == "keep me"
