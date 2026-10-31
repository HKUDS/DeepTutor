"""Atomic attachment writes must own their temporary files."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from deeptutor.services.storage import attachment_store
from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


def test_concurrent_writes_to_same_attachment_publish_complete_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "session" / "attachment_notes.txt"
    payloads = (b"first upload" * 1000, b"second upload" * 1000)
    ready = threading.Barrier(2)
    replace = attachment_store.os.replace

    def replace_together(source: Path, destination: Path) -> None:
        ready.wait(timeout=5)
        replace(source, destination)

    monkeypatch.setattr(attachment_store.os, "replace", replace_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writes = [
            pool.submit(LocalDiskAttachmentStore._write_sync, target, data) for data in payloads
        ]
        for write in writes:
            write.result(timeout=10)

    assert target.read_bytes() in payloads
    assert list(target.parent.iterdir()) == [target]


def test_failed_replacement_preserves_attachment_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "attachment.txt"
    target.write_bytes(b"saved attachment")

    def fail_replace(source: Path, destination: Path) -> None:
        raise PermissionError("attachment is locked")

    monkeypatch.setattr(attachment_store.os, "replace", fail_replace)
    with pytest.raises(PermissionError, match="attachment is locked"):
        LocalDiskAttachmentStore._write_sync(target, b"replacement")

    assert target.read_bytes() == b"saved attachment"
    assert list(tmp_path.iterdir()) == [target]


def test_put_returns_resolvable_url(tmp_path: Path) -> None:
    import asyncio

    store = LocalDiskAttachmentStore(root=tmp_path)
    url = asyncio.run(
        store.put(
            session_id="session",
            attachment_id="attachment",
            filename="学习 notes.txt",
            data=b"notes",
        )
    )

    assert "/files/attachments/session/attachment/" in url
    path = store.resolve_path(
        session_id="session", attachment_id="attachment", filename="学习 notes.txt"
    )
    assert isinstance(path, Path)
    assert path.read_bytes() == b"notes"
