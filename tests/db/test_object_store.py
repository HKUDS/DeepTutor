"""Object storage: content addressing, traversal safety, atomicity."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.db.storage import (
    LocalDiskObjectStore,
    ObjectKeyError,
    ObjectNotFound,
    content_key,
)


@pytest.fixture
def store(tmp_path: Path) -> LocalDiskObjectStore:
    return LocalDiskObjectStore(root=tmp_path / "objects")


class TestContentKey:
    def test_is_deterministic(self):
        assert content_key(b"hello") == content_key(b"hello")

    def test_differs_by_content(self):
        assert content_key(b"a") != content_key(b"b")

    def test_is_sharded_two_levels(self):
        key = content_key(b"hello")
        assert key.count("/") == 2

    def test_appends_suffix(self):
        assert content_key(b"x", suffix=".pdf").endswith(".pdf")

    def test_suffix_with_dot_is_not_doubled(self):
        key = content_key(b"x", suffix=".pdf")
        assert key.endswith(".pdf")
        assert not key.endswith("..pdf")
        assert key.count(".") == 1


class TestPutGet:
    def test_round_trip(self, store: LocalDiskObjectStore):
        key = store.put(b"payload", namespace="user-files")
        assert store.get(key) == b"payload"

    def test_returns_namespaced_key(self, store: LocalDiskObjectStore):
        key = store.put(b"x", namespace="user-files")
        assert key.startswith("user-files/")

    def test_identical_content_is_stored_once(self, store: LocalDiskObjectStore):
        first = store.put(b"same bytes", namespace="a")
        second = store.put(b"same bytes", namespace="a")
        assert first == second
        files = [p for p in store.root.rglob("*") if p.is_file()]
        assert len(files) == 1

    def test_same_content_different_namespace_is_two_objects(self, store: LocalDiskObjectStore):
        a = store.put(b"same", namespace="alpha")
        b = store.put(b"same", namespace="beta")
        assert a != b

    def test_explicit_key_is_honoured(self, store: LocalDiskObjectStore):
        key = store.put(b"data", namespace="ns", key="custom/name.bin")
        assert key == "ns/custom/name.bin"
        assert store.get(key) == b"data"

    def test_get_missing_raises(self, store: LocalDiskObjectStore):
        with pytest.raises(ObjectNotFound):
            store.get("ns/nope.bin")

    def test_exists(self, store: LocalDiskObjectStore):
        key = store.put(b"x", namespace="ns")
        assert store.exists(key) is True
        assert store.exists("ns/absent") is False

    def test_size(self, store: LocalDiskObjectStore):
        key = store.put(b"12345", namespace="ns")
        assert store.size(key) == 5

    def test_empty_payload_is_valid(self, store: LocalDiskObjectStore):
        key = store.put(b"", namespace="ns")
        assert store.get(key) == b""


class TestKeySafety:
    @pytest.mark.parametrize(
        "bad",
        [
            "../escape.bin",
            "ns/../../escape.bin",
            "/absolute.bin",
            "ns/./file.bin",
            "ns//double.bin",
            "",
            "\\windows\\path.bin",
        ],
    )
    def test_rejects_unsafe_keys(self, store: LocalDiskObjectStore, bad):
        with pytest.raises(ObjectKeyError):
            store.put(b"x", namespace="", key=bad)

    def test_rejects_traversal_on_read(self, store: LocalDiskObjectStore):
        with pytest.raises(ObjectKeyError):
            store.get("../../../etc/passwd")

    def test_exists_returns_false_rather_than_raising(self, store: LocalDiskObjectStore):
        assert store.exists("../../etc/passwd") is False

    def test_cannot_write_outside_the_root(self, store: LocalDiskObjectStore, tmp_path: Path):
        escaped = tmp_path / "escaped.bin"
        with pytest.raises(ObjectKeyError):
            store.put(b"x", namespace="", key=f"../{escaped.name}")
        assert not escaped.exists()


class TestDelete:
    def test_delete_removes_the_object(self, store: LocalDiskObjectStore):
        key = store.put(b"x", namespace="ns")
        assert store.delete(key) is True
        assert store.exists(key) is False

    def test_delete_absent_returns_false(self, store: LocalDiskObjectStore):
        assert store.delete("ns/absent") is False

    def test_purge_empties_the_root(self, store: LocalDiskObjectStore):
        store.put(b"x", namespace="ns")
        store.purge()
        assert not store.root.exists()


class TestOpenPath:
    def test_returns_a_readable_file(self, store: LocalDiskObjectStore):
        key = store.put(b"content", namespace="ns")
        path = store.open_path(key)
        assert path.is_file()
        assert path.read_bytes() == b"content"

    def test_missing_raises(self, store: LocalDiskObjectStore):
        with pytest.raises(ObjectNotFound):
            store.open_path("ns/absent")


class TestAtomicity:
    def test_a_failed_write_leaves_no_partial_file(self, store: LocalDiskObjectStore, monkeypatch):
        """The write goes through a temp file, so a crash mid-write is invisible."""

        def explode(*_args, **_kwargs):
            raise OSError("disk full")

        monkeypatch.setattr("os.replace", explode)
        with pytest.raises(OSError):
            store.put(b"x", namespace="ns", key="victim.bin")
        target = store.root / "ns" / "victim.bin"
        assert not target.exists()
        leftovers = list((store.root / "ns").glob(".tmp-*")) if (store.root / "ns").exists() else []
        assert leftovers == []

    def test_overwrite_replaces_atomically(self, store: LocalDiskObjectStore):
        store.put(b"old", namespace="ns", key="file.bin")
        store.put(b"new", namespace="ns", key="file.bin")
        assert store.get("ns/file.bin") == b"new"


class TestGetObjectStoreFactory:
    def test_defaults_to_local_disk(self, monkeypatch, tmp_path: Path, temp_home: Path):
        from deeptutor.db.storage import get_object_store, reset_object_store

        monkeypatch.delenv("DEEPTUTOR_OBJECT_STORE_URL", raising=False)
        reset_object_store(None)
        try:
            store = get_object_store()
            assert isinstance(store, LocalDiskObjectStore)
        finally:
            reset_object_store(None)

    def test_honours_a_file_url(self, monkeypatch, tmp_path: Path):
        from deeptutor.db.storage import get_object_store, reset_object_store

        target = tmp_path / "custom"
        monkeypatch.setenv("DEEPTUTOR_OBJECT_STORE_URL", f"file://{target}")
        reset_object_store(None)
        try:
            store = get_object_store()
            assert isinstance(store, LocalDiskObjectStore)
            assert store.root == target
        finally:
            reset_object_store(None)

    def test_refuses_an_unimplemented_scheme(self, monkeypatch):
        from deeptutor.db.storage import ObjectStoreError, get_object_store, reset_object_store

        monkeypatch.setenv("DEEPTUTOR_OBJECT_STORE_URL", "s3://bucket/prefix")
        reset_object_store(None)
        try:
            with pytest.raises(ObjectStoreError, match="unsupported object store scheme"):
                get_object_store()
        finally:
            reset_object_store(None)
