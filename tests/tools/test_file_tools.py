from __future__ import annotations

import pytest

from deeptutor.tools.file_tools import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool


def _ctx(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return {"_workspace_dir": str(workspace), "_allowed_dir": str(workspace)}, workspace


@pytest.mark.asyncio
async def test_file_tools_round_trip_and_pagination(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    write = await WriteFileTool().execute(path="notes/a.txt", content="one\ntwo\nthree", **kwargs)
    assert write.success

    read = await ReadFileTool().execute(path="notes/a.txt", offset=2, limit=1, **kwargs)
    assert read.success
    assert "2| two" in read.content
    assert "use offset=3" in read.content

    listed = await ListDirTool().execute(path=".", recursive=True, **kwargs)
    assert listed.success
    assert "notes/" in listed.content
    assert "notes/a.txt" in listed.content
    assert (workspace / "notes" / "a.txt").read_text(encoding="utf-8") == "one\ntwo\nthree"


@pytest.mark.asyncio
async def test_edit_file_requires_unique_match_unless_replace_all(tmp_path) -> None:
    kwargs, workspace = _ctx(tmp_path)
    (workspace / "a.txt").write_text("x\nx\n", encoding="utf-8")

    ambiguous = await EditFileTool().execute(path="a.txt", old_text="x", new_text="y", **kwargs)
    assert not ambiguous.success
    assert "appears 2 times" in ambiguous.content

    edited = await EditFileTool().execute(
        path="a.txt",
        old_text="x",
        new_text="y",
        replace_all=True,
        **kwargs,
    )
    assert edited.success
    assert (workspace / "a.txt").read_text(encoding="utf-8") == "y\ny\n"


@pytest.mark.asyncio
async def test_file_tools_block_paths_outside_workspace(tmp_path) -> None:
    kwargs, _workspace = _ctx(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    result = await ReadFileTool().execute(path=str(outside), **kwargs)
    assert not result.success
    assert "outside the turn workspace" in result.content
