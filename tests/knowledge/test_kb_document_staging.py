"""Staging sources into ``raw/`` must never drop a document the user asked for (#2041).

Creating a KB flattened every source to its basename and copied straight onto
the taken name, so a docs tree holding one ``full.md`` per volume indexed only
the last file — while still reporting that the knowledge base was created. The
incremental add path already kept both, so the rule now lives in one place and
these tests pin the create path to it.
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
from deeptutor.knowledge.staging import stage_source


def _initializer(tmp_path: Path) -> KnowledgeBaseInitializer:
    initializer = KnowledgeBaseInitializer(kb_name="kb", base_dir=str(tmp_path))
    initializer.raw_dir.mkdir(parents=True, exist_ok=True)
    return initializer


def test_copy_documents_keeps_same_named_documents(tmp_path: Path) -> None:
    volumes = []
    for index, volume in enumerate(("a", "b", "c")):
        source = tmp_path / volume / "full.md"
        source.parent.mkdir(parents=True)
        source.write_text(f"volume {index}", encoding="utf-8")
        volumes.append(str(source))

    staged = _initializer(tmp_path).copy_documents(volumes)

    raw_dir = tmp_path / "kb" / "raw"
    assert len(staged) == 3
    assert sorted(path.name for path in raw_dir.iterdir()) == sorted(
        Path(path).name for path in staged
    )
    assert {Path(path).read_text(encoding="utf-8") for path in staged} == {
        "volume 0",
        "volume 1",
        "volume 2",
    }


def test_copy_documents_stages_identical_document_once(tmp_path: Path) -> None:
    first = tmp_path / "a" / "notes.md"
    first.parent.mkdir(parents=True)
    first.write_text("same text", encoding="utf-8")
    second = tmp_path / "b" / "notes.md"
    second.parent.mkdir(parents=True)
    second.write_text("same text", encoding="utf-8")

    staged = _initializer(tmp_path).copy_documents([str(first), str(second)])

    assert [Path(path).name for path in staged] == ["notes.md"]
    assert sorted(path.name for path in (tmp_path / "kb" / "raw").iterdir()) == ["notes.md"]


def test_copy_documents_reports_missing_source_without_indexing_it(tmp_path: Path) -> None:
    real = tmp_path / "real.md"
    real.write_text("content", encoding="utf-8")

    staged = _initializer(tmp_path).copy_documents([str(tmp_path / "gone.md"), str(real)])

    assert [Path(path).name for path in staged] == ["real.md"]


def test_stage_source_renames_only_when_content_differs(tmp_path: Path) -> None:
    dest = tmp_path / "raw" / "src.md"
    first = tmp_path / "first.md"
    first.write_text("first", encoding="utf-8")

    staged, copied = stage_source(first, dest)
    assert copied is True and staged == dest

    identical = tmp_path / "copy.md"
    identical.write_text("first", encoding="utf-8")
    reused, copied_again = stage_source(identical, dest)
    assert copied_again is False and reused == dest

    different = tmp_path / "other.md"
    different.write_text("second", encoding="utf-8")
    renamed, renamed_copied = stage_source(different, dest)
    assert renamed_copied is True and renamed != dest
    assert renamed.read_text(encoding="utf-8") == "second"
    assert dest.read_text(encoding="utf-8") == "first"
