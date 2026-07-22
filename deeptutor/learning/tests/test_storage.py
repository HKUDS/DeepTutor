from pathlib import Path
import time

import pytest

from deeptutor.learning.models import KnowledgeType, LearningProgress, RepetitionState
from deeptutor.learning.storage import LearningStore, _atomic_write_text


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


# ── save / load ──────────────────────────────────────────────────────────


class TestSaveLoad:
    def test_save_and_load(self, store):
        lp = LearningProgress(book_id="book1")
        lp.mastery_levels["kp1"] = 0.75
        store.save(lp)
        loaded = store.load("book1")
        assert loaded is not None
        assert loaded.book_id == "book1"
        assert loaded.mastery_levels["kp1"] == 0.75

    def test_enum_roundtrip(self, store):
        lp = LearningProgress(book_id="book1")
        lp.knowledge_types["kp1"] = KnowledgeType.MEMORY
        store.save(lp)
        loaded = store.load("book1")
        assert loaded.knowledge_types["kp1"] == KnowledgeType.MEMORY

    def test_repetition_state_roundtrip(self, store):
        lp = LearningProgress(book_id="book1")
        state = RepetitionState(interval_index=2, next_review_at=time.time() + 86400)
        lp.repetition_states["kp1"] = state
        store.save(lp)
        loaded = store.load("book1")
        assert loaded.repetition_states["kp1"].interval_index == 2

    def test_updated_at_auto_updates(self, store):
        lp = LearningProgress(book_id="book1")
        old_updated = lp.updated_at
        time.sleep(0.01)
        store.save(lp)
        loaded = store.load("book1")
        assert loaded.updated_at >= old_updated

    def test_version_increments_on_each_save(self, store):
        lp = LearningProgress(book_id="book1")
        assert lp.version == 0
        store.save(lp)
        assert store.load("book1").version == 1
        store.save(lp)
        assert store.load("book1").version == 2

    def test_save_overwrites_previous(self, store):
        lp = LearningProgress(book_id="book1")
        lp.mastery_levels["kp1"] = 0.2
        store.save(lp)
        lp.mastery_levels["kp1"] = 0.9
        store.save(lp)
        assert store.load("book1").mastery_levels["kp1"] == 0.9


# ── load nonexistent ─────────────────────────────────────────────────────


class TestLoadNonexistent:
    def test_returns_none(self, store):
        assert store.load("nonexistent") is None


# ── exists ───────────────────────────────────────────────────────────────


class TestExists:
    def test_true_after_save(self, store):
        store.save(LearningProgress(book_id="book1"))
        assert store.exists("book1") is True

    def test_false_when_missing(self, store):
        assert store.exists("nonexistent") is False


# ── delete ───────────────────────────────────────────────────────────────


class TestDelete:
    def test_removes_progress_file(self, store, tmp_path):
        store.save(LearningProgress(book_id="book1"))
        assert (tmp_path / "book1.json").exists()
        store.delete("book1")
        assert store.load("book1") is None
        assert not (tmp_path / "book1.json").exists()

    def test_delete_nonexistent_no_error(self, store):
        store.delete("nonexistent")  # should not raise

    def test_delete_only_targets_named_book(self, store):
        store.save(LearningProgress(book_id="keep"))
        store.save(LearningProgress(book_id="drop"))
        store.delete("drop")
        assert store.exists("keep") is True
        assert store.exists("drop") is False


# ── path traversal ───────────────────────────────────────────────────────


class TestPathTraversal:
    def test_rejects_slash(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("../settings/foo")

    def test_rejects_backslash(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("a\\b")

    def test_rejects_dotdot(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("..")

    def test_rejects_colon(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.load("D:foo")

    def test_rejects_in_save(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.save(LearningProgress(book_id="../evil"))

    def test_rejects_in_delete(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.delete("../evil")

    def test_rejects_in_exists(self, store):
        with pytest.raises(ValueError, match="Invalid book_id"):
            store.exists("../evil")


# ── list_all ──────────────────────────────────────────────────────────────


class TestListAll:
    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_list_all_multiple(self, store):
        store.save(LearningProgress(book_id="a"))
        store.save(LearningProgress(book_id="b"))
        ids = store.list_all()
        assert sorted(ids) == ["a", "b"]

    def test_list_all_after_delete(self, store):
        store.save(LearningProgress(book_id="x"))
        store.save(LearningProgress(book_id="y"))
        store.delete("x")
        assert store.list_all() == ["y"]

    def test_list_all_ignores_dotfiles(self, store, tmp_path):
        store.save(LearningProgress(book_id="visible"))
        (tmp_path / ".hidden.json").write_text("{}", encoding="utf-8")
        assert store.list_all() == ["visible"]


# ── atomic write ──────────────────────────────────────────────────────────


class TestAtomicWrite:
    def test_writes_content(self, tmp_path):
        target = tmp_path / "nested" / "out.json"
        _atomic_write_text(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "a" / "b" / "c.json"
        _atomic_write_text(target, "x")
        assert target.exists()

    def test_no_orphan_temp_files_on_success(self, tmp_path):
        target = tmp_path / "out.json"
        _atomic_write_text(target, "data")
        leftovers = [p for p in tmp_path.iterdir() if ".tmp." in p.name]
        assert leftovers == []

    def test_cleans_up_temp_on_replace_failure(self, tmp_path, monkeypatch):
        target = tmp_path / "out.json"

        def boom(self, _dst):  # noqa: ANN001
            raise OSError("simulated replace failure")

        monkeypatch.setattr(Path, "replace", boom)
        with pytest.raises(OSError, match="simulated replace failure"):
            _atomic_write_text(target, "data")
        # The original target must not exist, and no .tmp leftover should remain.
        assert not target.exists()
        leftovers = [p for p in tmp_path.iterdir() if ".tmp." in p.name]
        assert leftovers == []
