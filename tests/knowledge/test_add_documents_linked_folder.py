"""``DocumentAdder.add_documents(source_root=...)`` staging for linked-folder sync.

Without ``source_root``, every externally-sourced file is staged to
``raw/<basename>`` regardless of where it lived, so syncing a linked folder
with subdirectories collapses them all into raw/'s top level (#866) and two
subfolders with a same-named file collide. These tests pin the fix: a file
under ``source_root`` stages at the same path relative to it.
"""

from __future__ import annotations

import json
from pathlib import Path

from deeptutor.knowledge.add_documents import DocumentAdder


def _ready_llamaindex_kb(kb_dir: Path) -> None:
    (kb_dir / "raw").mkdir(parents=True)
    version_dir = kb_dir / "version-1"
    version_dir.mkdir()
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "llamaindex", "version": "version-1"}),
        encoding="utf-8",
    )


def test_add_documents_preserves_subfolder_structure_under_source_root(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    _ready_llamaindex_kb(kb_dir)

    linked_folder = tmp_path / "linked"
    sub = linked_folder / "sub"
    sub.mkdir(parents=True)
    doc = sub / "note.md"
    doc.write_text("hello", encoding="utf-8")

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path))
    staged = adder.add_documents([str(doc)], source_root=str(linked_folder))

    assert staged == [kb_dir / "raw" / "sub" / "note.md"]
    assert (kb_dir / "raw" / "sub" / "note.md").read_text(encoding="utf-8") == "hello"
    assert not (kb_dir / "raw" / "note.md").exists()


def test_add_documents_same_name_in_different_subfolders_does_not_collide(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    _ready_llamaindex_kb(kb_dir)

    linked_folder = tmp_path / "linked"
    (linked_folder / "a").mkdir(parents=True)
    (linked_folder / "b").mkdir(parents=True)
    doc_a = linked_folder / "a" / "note.md"
    doc_b = linked_folder / "b" / "note.md"
    doc_a.write_text("from a", encoding="utf-8")
    doc_b.write_text("from b", encoding="utf-8")

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path))
    staged = adder.add_documents([str(doc_a), str(doc_b)], source_root=str(linked_folder))

    assert set(staged) == {
        kb_dir / "raw" / "a" / "note.md",
        kb_dir / "raw" / "b" / "note.md",
    }
    assert (kb_dir / "raw" / "a" / "note.md").read_text(encoding="utf-8") == "from a"
    assert (kb_dir / "raw" / "b" / "note.md").read_text(encoding="utf-8") == "from b"


def test_add_documents_without_source_root_still_flattens_to_basename(tmp_path: Path) -> None:
    """Direct (non-folder-sync) uploads are unaffected: no source_root, same as before."""
    kb_dir = tmp_path / "kb"
    _ready_llamaindex_kb(kb_dir)

    external = tmp_path / "somewhere-else" / "deep" / "path"
    external.mkdir(parents=True)
    doc = external / "note.md"
    doc.write_text("hello", encoding="utf-8")

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path))
    staged = adder.add_documents([str(doc)])

    assert staged == [kb_dir / "raw" / "note.md"]


def test_add_documents_source_outside_source_root_falls_back_to_basename(
    tmp_path: Path,
) -> None:
    """A file that is not actually under source_root still flattens, not KeyErrors."""
    kb_dir = tmp_path / "kb"
    _ready_llamaindex_kb(kb_dir)

    linked_folder = tmp_path / "linked"
    linked_folder.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    doc = unrelated / "note.md"
    doc.write_text("hello", encoding="utf-8")

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path))
    staged = adder.add_documents([str(doc)], source_root=str(linked_folder))

    assert staged == [kb_dir / "raw" / "note.md"]
