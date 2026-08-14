"""Tests for bilingual alignment sidecar persistence."""
import json
import pytest
from pathlib import Path

from deeptutor.services.web_source import bilingual_store


class TestBilingualStore:
    def test_save_and_load(self, tmp_path):
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        alignment = {
            "page_class": "bilingual",
            "groups": [{"group_id": "abc", "en_content": "Hello", "zh_content": "你好"}],
            "review_count": 0,
        }
        path = bilingual_store.save_alignment(kb_dir, "testkey", "guide/intro.md", alignment)
        assert path.exists()
        loaded = bilingual_store.load_alignment(kb_dir, "testkey", "guide/intro.md")
        assert loaded is not None
        assert loaded["page_class"] == "bilingual"
        assert loaded["groups"][0]["zh_content"] == "你好"

    def test_load_nonexistent(self, tmp_path):
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        result = bilingual_store.load_alignment(kb_dir, "testkey", "missing.md")
        assert result is None

    def test_load_for_any_pair(self, tmp_path):
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        alignment = {"page_class": "bilingual", "groups": []}
        bilingual_store.save_alignment(kb_dir, "pairA", "page.md", alignment)
        # Should find it searching all pairs
        result = bilingual_store.load_alignment_for_any_pair(kb_dir, "page.md")
        assert result is not None

    def test_list_aligned_pages(self, tmp_path):
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        bilingual_store.save_alignment(kb_dir, "key1", "a.md", {"page_class": "en_only", "groups": []})
        bilingual_store.save_alignment(kb_dir, "key1", "b.md", {"page_class": "bilingual", "groups": []})
        pages = bilingual_store.list_aligned_pages(kb_dir, "key1")
        assert set(pages) == {"a.md", "b.md"}

    def test_save_and_load_pair_index(self, tmp_path):
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        index = {"pair_key": "key1", "status": "bilingual", "paired_pages": 5}
        bilingual_store.save_pair_index(kb_dir, "key1", index)
        loaded = bilingual_store.load_pair_index(kb_dir, "key1")
        assert loaded is not None
        assert loaded["paired_pages"] == 5

    def test_list_pair_keys(self, tmp_path):
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        bilingual_store.save_alignment(kb_dir, "keyA", "a.md", {"page_class": "en_only", "groups": []})
        bilingual_store.save_alignment(kb_dir, "keyB", "b.md", {"page_class": "bilingual", "groups": []})
        keys = bilingual_store.list_pair_keys(kb_dir)
        assert set(keys) == {"keyA", "keyB"}

    def test_remove_pair(self, tmp_path):
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        bilingual_store.save_alignment(kb_dir, "keyA", "a.md", {"page_class": "en_only", "groups": []})
        bilingual_store.remove_pair(kb_dir, "keyA")
        assert bilingual_store.load_alignment(kb_dir, "keyA", "a.md") is None

    def test_nested_file_path(self, tmp_path):
        """Files in subdirectories should work (e.g. explore/book.md)."""
        kb_dir = tmp_path / "TestKB"
        kb_dir.mkdir()
        alignment = {"page_class": "bilingual", "groups": []}
        bilingual_store.save_alignment(kb_dir, "key1", "explore/book.md", alignment)
        loaded = bilingual_store.load_alignment(kb_dir, "key1", "explore/book.md")
        assert loaded is not None
        # Sidecar should be in a matching subdirectory
        sidecar = kb_dir / "bilingual" / "key1" / "explore" / "book.json"
        assert sidecar.exists()


# -- stale sidecar cleanup --------------------------------------------------

def test_cleanup_stale_sidecars(tmp_path):
    """Stale sidecars for removed pages should be cleaned up."""
    kb_dir = tmp_path / "DeepTutor"
    pair_key = "test.com"
    # Save 3 alignments
    bilingual_store.save_alignment(kb_dir, pair_key, "page1.md", {"page_class": "bilingual"})
    bilingual_store.save_alignment(kb_dir, pair_key, "page2.md", {"page_class": "bilingual"})
    bilingual_store.save_alignment(kb_dir, pair_key, "page3.md", {"page_class": "bilingual"})
    assert len(bilingual_store.list_aligned_pages(kb_dir, pair_key)) == 3

    # page2.md was removed from the site — only page1 and page3 remain
    removed = bilingual_store.cleanup_stale_sidecars(kb_dir, pair_key, {"page1.md", "page3.md"})
    assert removed == 1
    remaining = bilingual_store.list_aligned_pages(kb_dir, pair_key)
    assert "page2.md" not in remaining
    assert "page1.md" in remaining
    assert "page3.md" in remaining


def test_cleanup_stale_sidecars_no_pair_dir(tmp_path):
    """No crash when the pair directory doesn't exist."""
    removed = bilingual_store.cleanup_stale_sidecars(tmp_path, "nonexistent", {"page1.md"})
    assert removed == 0


def test_remove_single_alignment(tmp_path):
    """remove_alignment should delete one sidecar."""
    kb_dir = tmp_path / "DeepTutor"
    pair_key = "test.com"
    bilingual_store.save_alignment(kb_dir, pair_key, "page1.md", {"page_class": "bilingual"})
    assert bilingual_store.remove_alignment(kb_dir, pair_key, "page1.md") is True
    assert bilingual_store.remove_alignment(kb_dir, pair_key, "page1.md") is False  # already gone
