import json
from pathlib import Path
import sqlite3

import pytest

from deeptutor.services.rag.version_lease import VersionInUseError, version_lease
from deeptutor.services.rag.version_retention import (
    apply_cleanup,
    cleanup_preview,
    obsolete_versions,
    prune_versions,
    referenced_versions,
)


def publish(root: Path, number: int, signature: str = "model-a") -> Path:
    path = root / f"version-{number}"
    path.mkdir()
    (path / "meta.json").write_text(
        json.dumps(
            {
                "provider": "llamaindex",
                "signature": signature,
                "state": "published",
            }
        )
    )
    (path / "docstore.json").write_text('{"docstore/data": {}}')
    (path / "index_store.json").write_text("{}")
    return path


def test_retains_two_per_signature_and_preserves_raw_and_unknown(tmp_path):
    for i in range(1, 7):
        publish(tmp_path, i, "model-a" if i <= 3 else "model-b")
    (tmp_path / "version-7").mkdir()
    (tmp_path / "version-7" / ".building.json").write_text("{}")
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "book.pdf").write_bytes(b"original")
    assert [p.name for p in obsolete_versions(tmp_path)] == ["version-1", "version-4"]
    with pytest.raises(ValueError, match="Stop DeepTutor"):
        prune_versions(tmp_path)
    assert prune_versions(tmp_path, offline=True) == ["version-1", "version-4"]
    assert (tmp_path / "raw" / "book.pdf").read_bytes() == b"original"
    assert (tmp_path / "version-7").is_dir()


def test_pins_and_unpublished_indexes_are_not_removed(tmp_path):
    for i in range(1, 5):
        publish(tmp_path, i)
    (tmp_path / "version-1" / "meta.json").write_text(
        '{"provider":"llamaindex","signature":"model-a"}'
    )
    assert obsolete_versions(tmp_path, protected=frozenset({"version-2"})) == []
    with pytest.raises(ValueError, match="at least two"):
        obsolete_versions(tmp_path, keep=1)


def test_changed_preview_cannot_delete_and_symlinks_are_rejected(tmp_path):
    for i in range(1, 4):
        publish(tmp_path, i)
    preview = cleanup_preview(tmp_path)
    publish(tmp_path, 4)
    with pytest.raises(ValueError, match="changed"):
        apply_cleanup(tmp_path, preview["fingerprint"])
    assert (tmp_path / "version-1").exists()
    (tmp_path / "version-1" / "redirect").symlink_to(
        tmp_path / "version-4", target_is_directory=True
    )
    with pytest.raises(ValueError, match="symbolic"):
        cleanup_preview(tmp_path)


def test_saved_references_protect_versions(tmp_path):
    db = tmp_path / "history.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE messages (text TEXT)")
        conn.execute("INSERT INTO messages VALUES (?)", ('{"source": "version-12/page-3"}',))
    assert referenced_versions([db, db, tmp_path / "absent"]) == {"version-12"}


def test_cleanup_excludes_readers_and_writers(tmp_path):
    kb = tmp_path / "kb"
    kb.mkdir()
    with version_lease(kb):
        with version_lease(kb):
            with pytest.raises(VersionInUseError):
                with version_lease(kb, cleanup=True):
                    pytest.fail("exclusive cleanup entered while index was in use")
    with version_lease(kb, cleanup=True):
        with pytest.raises(VersionInUseError):
            with version_lease(kb):
                pytest.fail("index operation entered during cleanup")


def test_apply_uses_fresh_protection(tmp_path):
    for i in range(1, 4):
        publish(tmp_path, i)
    preview = cleanup_preview(tmp_path)
    with pytest.raises(ValueError, match="changed"):
        apply_cleanup(tmp_path, preview["fingerprint"], protected=frozenset({"version-1"}))
    result = apply_cleanup(tmp_path, preview["fingerprint"])
    assert result["versions"] == ["version-1"]
    assert not (tmp_path / "version-1").exists()
