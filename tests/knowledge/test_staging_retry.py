"""文件名冲突后的暂存重试应复用原文件，避免重复索引。"""

from pathlib import Path

import pytest

from deeptutor.knowledge.staging import content_hash, stage_source


@pytest.mark.parametrize("supplied_hash", [False, True])
@pytest.mark.parametrize("collisions", [1, 3])
def test_retry_reuses_renamed_source(tmp_path: Path, supplied_hash: bool, collisions: int) -> None:
    """重试时找到已改名的同内容文件，且不改写先前文档。"""
    dest = tmp_path / "raw" / "notes.md"
    source = tmp_path / "notes.md"
    for index in range(collisions):
        source.write_text(f"existing {index}", encoding="utf-8")
        stage_source(source, dest)

    source.write_text("retry me", encoding="utf-8")
    expected, copied = stage_source(source, dest)
    assert copied is True
    before = {path.name: path.read_bytes() for path in dest.parent.iterdir()}

    actual, copied_again = stage_source(
        source, dest, source_hash=content_hash(source) if supplied_hash else None
    )

    assert actual == expected
    assert copied_again is False
    assert {path.name: path.read_bytes() for path in dest.parent.iterdir()} == before


def test_staging_preserves_distinct_content_and_reuses_original(tmp_path: Path) -> None:
    """保持首次复制、原名去重及不同内容保留的既有规则。"""
    dest = tmp_path / "raw" / "notes.md"
    source = tmp_path / "notes.md"
    source.write_text("original", encoding="utf-8")
    assert stage_source(source, dest) == (dest, True)
    assert stage_source(source, dest) == (dest, False)
    source.write_text("different", encoding="utf-8")
    renamed, copied = stage_source(source, dest)
    assert copied is True
    assert renamed.name == "notes (2).md"
    assert renamed.read_text(encoding="utf-8") == "different"
    assert dest.read_text(encoding="utf-8") == "original"
