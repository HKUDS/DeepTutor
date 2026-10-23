"""Resolve Obsidian backlink destinations using real vault notes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.capabilities.obsidian.tools import ObsidianBacklinksTool


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "link",
    [
        "[[concepts/Photosynthesis]]",
        "[[concepts/Photosynthesis.md#Light|Overview]]",
        "![[concepts/Photosynthesis#^block]]",
    ],
)
async def test_backlinks_include_folder_qualified_targets(tmp_path: Path, link: str) -> None:
    """Folder paths, headings, aliases and embeds retain their destination."""
    target = tmp_path / "concepts" / "Photosynthesis.md"
    target.parent.mkdir()
    target.write_text("Plant energy.\n", encoding="utf-8")
    (tmp_path / "Index.md").write_text(link + "\n", encoding="utf-8")

    result = await ObsidianBacklinksTool().execute(
        _vault_path=str(tmp_path), note="concepts/Photosynthesis.md"
    )

    assert result.success
    assert [item["path"] for item in json.loads(result.content)["backlinks"]] == ["Index.md"]


@pytest.mark.asyncio
async def test_backlinks_do_not_attribute_same_stem_to_another_note(tmp_path: Path) -> None:
    """The link resolver chooses one note when basenames are duplicated."""
    for folder in ("concepts", "other"):
        target = tmp_path / folder / "Photosynthesis.md"
        target.parent.mkdir()
        target.write_text(folder + "\n", encoding="utf-8")
    (tmp_path / "Index.md").write_text("[[Photosynthesis]]\n", encoding="utf-8")

    chosen = await ObsidianBacklinksTool().execute(
        _vault_path=str(tmp_path), note="concepts/Photosynthesis.md"
    )
    other = await ObsidianBacklinksTool().execute(
        _vault_path=str(tmp_path), note="other/Photosynthesis.md"
    )

    assert chosen.success and other.success
    assert [item["path"] for item in json.loads(chosen.content)["backlinks"]] == ["Index.md"]
    assert json.loads(other.content)["backlinks"] == []
