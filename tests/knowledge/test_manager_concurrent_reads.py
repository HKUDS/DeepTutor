"""Concurrent readers of ``kb_config.json`` must never see, or save, an empty catalog.

``msvcrt`` has no shared lock: the Windows branch of ``file_lock_shared`` took
an exclusive, mandatory byte-range lock, so a reader that overlapped another
one failed, ``_read_and_reconcile_config`` returned ``{"knowledge_bases": {}}``,
and the next ``update_kb_status`` re-registered its own KB into that empty
catalog and saved it over every other entry.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import deeptutor.knowledge.manager as manager_module
from deeptutor.knowledge.manager import KnowledgeBaseManager


def _seed(tmp_path: Path) -> Path:
    config = {
        "knowledge_bases": {
            name: {"path": name, "description": f"notes for {name}", "status": "ready"}
            for name in ("kb0", "kb1", "kb2")
        }
    }
    for name in config["knowledge_bases"]:
        (tmp_path / name).mkdir()
    config_file = tmp_path / "kb_config.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    return config_file


def test_windows_reader_does_not_take_an_exclusive_lock(tmp_path, monkeypatch) -> None:
    config_file = _seed(tmp_path)

    def held_by_another_reader(*_args):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(manager_module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setitem(
        sys.modules,
        "msvcrt",
        SimpleNamespace(LK_NBLCK=2, LK_UNLCK=0, locking=held_by_another_reader),
    )

    # Every read below overlaps another reader's byte-range lock.
    manager = KnowledgeBaseManager(base_dir=str(tmp_path))
    manager.update_kb_status(name="kb0", status="processing")

    saved = json.loads(config_file.read_text(encoding="utf-8"))["knowledge_bases"]
    assert sorted(saved) == ["kb0", "kb1", "kb2"]
    assert saved["kb1"]["description"] == "notes for kb1"


def test_status_updates_racing_readers_keep_the_catalog(tmp_path) -> None:
    config_file = _seed(tmp_path)
    stop = threading.Event()

    def read_until_stopped() -> None:
        reader = KnowledgeBaseManager(base_dir=str(tmp_path))
        while not stop.is_set():
            reader._read_and_reconcile_config()

    readers = [threading.Thread(target=read_until_stopped) for _ in range(6)]
    for thread in readers:
        thread.start()
    try:
        writer = KnowledgeBaseManager(base_dir=str(tmp_path))
        for _ in range(200):
            writer.update_kb_status(name="kb0", status="ready")
    finally:
        stop.set()
        for thread in readers:
            thread.join()

    saved = json.loads(config_file.read_text(encoding="utf-8"))["knowledge_bases"]
    assert sorted(saved) == ["kb0", "kb1", "kb2"]
