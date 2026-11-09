"""GitHub source sync must treat .mdx as documentation, not as an unknown file.

A source configured with ``glob=*.mdx`` used to finish with ``files_synced: 0``
and ``status: success``, because the sync filter only recognised .md and
.markdown, so nothing was downloaded and re-indexing then failed with
"no source files in raw/".
"""

from __future__ import annotations

from deeptutor.services.github_source.sync import (
    MARKDOWN_EXTENSIONS,
    _filter_markdown_entries,
    _is_markdown,
)
from deeptutor.utils.file_types import FileTypeRouter


class _Entry:
    def __init__(self, path: str) -> None:
        self.path = path


def test_mdx_is_a_markdown_extension() -> None:
    assert ".mdx" in MARKDOWN_EXTENSIONS
    assert _is_markdown("docs/widgets/button.mdx") is True


def test_mdx_entries_survive_the_sync_filter() -> None:
    entries = [
        _Entry("docs/widgets/button.mdx"),
        _Entry("docs/README.md"),
        _Entry("docs/logo.png"),
    ]

    kept = _filter_markdown_entries(entries, "docs", "*.mdx")

    assert [entry.path for entry in kept] == ["docs/widgets/button.mdx"]


def test_file_type_router_accepts_mdx() -> None:
    assert ".mdx" in FileTypeRouter.get_supported_extensions()
