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


def test_staging_never_overwrites_a_name_taken_after_the_check(tmp_path: Path, monkeypatch) -> None:
    """A concurrent writer that takes the name first keeps its file."""
    dest = tmp_path / "raw" / "notes.md"
    dest.parent.mkdir()
    source = tmp_path / "notes.md"
    source.write_text("mine", encoding="utf-8")
    real_exists = Path.exists
    raced = []

    def exists_racing(self: Path, *args, **kwargs) -> bool:
        if self == dest and not raced:
            raced.append(True)
            dest.write_text("theirs", encoding="utf-8")  # lands between check and copy
            return False
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", exists_racing)
    staged, copied = stage_source(source, dest)

    assert dest.read_text(encoding="utf-8") == "theirs"
    assert (staged, copied) == (dest.with_name("notes (2).md"), True)
    assert staged.read_text(encoding="utf-8") == "mine"


def test_failed_copy_leaves_no_partial_file(tmp_path: Path, monkeypatch) -> None:
    import shutil

    dest = tmp_path / "raw" / "notes.md"
    source = tmp_path / "notes.md"
    source.write_text("content", encoding="utf-8")

    def broken_copy(src, dst, *args, **kwargs):
        dst.write(b"half")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(shutil, "copyfileobj", broken_copy)
    with pytest.raises(OSError):
        stage_source(source, dest)

    assert not dest.exists()


def test_dangling_symlink_at_the_name_is_skipped_not_followed(tmp_path: Path) -> None:
    dest = tmp_path / "raw" / "notes.md"
    dest.parent.mkdir()
    target = tmp_path / "elsewhere.md"
    dest.symlink_to(target)
    source = tmp_path / "notes.md"
    source.write_text("content", encoding="utf-8")

    staged, copied = stage_source(source, dest)

    assert (staged, copied) == (dest.with_name("notes (2).md"), True)
    assert not target.exists()
