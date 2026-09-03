"""Content-addressed chat attachment dedup (#1138 stage 1)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore
from deeptutor.services.storage.blob_store import ContentAddressedBlobStore, sha256_hex


def test_blob_store_dedups_and_releases(tmp_path: Path) -> None:
    store = ContentAddressedBlobStore(tmp_path / "blobs")
    payload = b"identical-bytes"

    first = store.put(payload, label="attachment:s1:a1")
    second = store.put(payload, label="attachment:s1:a2")
    assert first == second == sha256_hex(payload)
    assert store.object_count() == 1
    assert set(store.labels_for(first)) == {"attachment:s1:a1", "attachment:s1:a2"}

    dest_a = tmp_path / "a.bin"
    dest_b = tmp_path / "b.bin"
    mode_a = store.link_or_copy(first, dest_a)
    mode_b = store.link_or_copy(first, dest_b)
    assert dest_a.read_bytes() == payload
    assert dest_b.read_bytes() == payload
    if mode_a == "link" and mode_b == "link":
        assert dest_a.stat().st_ino == dest_b.stat().st_ino == store.object_path(first).stat().st_ino

    removed = store.release("attachment:s1:a1", digest=first)
    assert removed == []
    assert store.object_count() == 1
    assert store.labels_for(first) == ("attachment:s1:a2",)

    removed = store.release("attachment:s1:a2", digest=first)
    assert removed == [first]
    assert store.object_count() == 0


def test_blob_store_link_falls_back_to_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = ContentAddressedBlobStore(tmp_path / "blobs")
    digest = store.put(b"payload", label="attachment:s:a")

    def _no_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("hardlink unsupported")

    monkeypatch.setattr(os, "link", _no_link)
    dest = tmp_path / "out.bin"
    assert store.link_or_copy(digest, dest) == "copy"
    assert dest.read_bytes() == b"payload"


def test_attachment_store_shares_blob_across_uploads(tmp_path: Path) -> None:
    root = tmp_path / "attachments"
    blobs = ContentAddressedBlobStore(tmp_path / "blobs")
    store = LocalDiskAttachmentStore(root=root, blob_store=blobs)
    payload = b"%PDF-same-document"

    async def _run() -> None:
        url1 = await store.put(
            session_id="sess-a",
            attachment_id="att-1",
            filename="notes.pdf",
            data=payload,
        )
        url2 = await store.put(
            session_id="sess-b",
            attachment_id="att-2",
            filename="notes.pdf",
            data=payload,
        )
        assert url1 == "/files/attachments/sess-a/att-1/notes.pdf"
        assert url2 == "/files/attachments/sess-b/att-2/notes.pdf"
        assert blobs.object_count() == 1

        path1 = store.resolve_path(session_id="sess-a", attachment_id="att-1", filename="notes.pdf")
        path2 = store.resolve_path(session_id="sess-b", attachment_id="att-2", filename="notes.pdf")
        assert path1 is not None and path2 is not None
        assert path1.read_bytes() == path2.read_bytes() == payload
        # Prefer hardlinks when the filesystem allows them.
        if path1.stat().st_ino == path2.stat().st_ino:
            assert path1.stat().st_nlink >= 2

        await store.delete_attachment(session_id="sess-a", attachment_id="att-1")
        assert (
            store.resolve_path(session_id="sess-a", attachment_id="att-1", filename="notes.pdf")
            is None
        )
        assert (
            store.resolve_path(session_id="sess-b", attachment_id="att-2", filename="notes.pdf")
            is not None
        )
        assert blobs.object_count() == 1

        await store.delete_session("sess-b")
        assert blobs.object_count() == 0
        assert (
            store.resolve_path(session_id="sess-b", attachment_id="att-2", filename="notes.pdf")
            is None
        )

    asyncio.run(_run())


def test_attachment_store_distinct_bytes_stay_separate(tmp_path: Path) -> None:
    store = LocalDiskAttachmentStore(
        root=tmp_path / "attachments",
        blob_store=ContentAddressedBlobStore(tmp_path / "blobs"),
    )

    async def _run() -> None:
        await store.put(session_id="s", attachment_id="a", filename="a.txt", data=b"one")
        await store.put(session_id="s", attachment_id="b", filename="b.txt", data=b"two")
        assert store.blob_store.object_count() == 2

    asyncio.run(_run())
