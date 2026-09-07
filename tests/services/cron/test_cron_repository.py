"""SQLiteCronRepository migration lock: cross-platform branches and mutual exclusion."""

from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace

import pytest

from deeptutor.services.cron import repository


class TestMigrationLock:
    def test_acquire_release_round_trip(self, tmp_path):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        with repo._migration_lock():
            assert repo._migration_lock_path.exists()

    def test_mutually_excludes_concurrent_holders(self, tmp_path):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        entered = threading.Event()

        def holder():
            with repo._migration_lock():
                entered.set()
                time.sleep(0.3)

        t = threading.Thread(target=holder)
        t.start()
        assert entered.wait(2)
        started = time.monotonic()
        with repo._migration_lock():
            waited = time.monotonic() - started
        t.join(timeout=5)
        assert not t.is_alive()
        # A second acquirer must block until the holder releases its lock.
        assert waited >= 0.2

    def test_module_does_not_bind_fcntl_at_import(self):
        # Top-level ``import fcntl`` breaks cron startup on Windows (#1183).
        assert "fcntl" not in repository.__dict__

    def test_uses_msvcrt_locking_on_windows(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        calls: list[tuple[int, int]] = []
        fake_msvcrt = SimpleNamespace(
            LK_LOCK=1,
            LK_UNLCK=2,
            locking=lambda _fileno, mode, length: calls.append((mode, length)),
        )
        monkeypatch.setattr(repository, "sys", SimpleNamespace(platform="win32"))
        monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)

        with repo._migration_lock():
            assert calls == [(fake_msvcrt.LK_LOCK, 1)]

        assert calls == [
            (fake_msvcrt.LK_LOCK, 1),
            (fake_msvcrt.LK_UNLCK, 1),
        ]

    def test_uses_fcntl_locking_on_posix(self, tmp_path, monkeypatch: pytest.MonkeyPatch):
        repo = repository.SQLiteCronRepository(tmp_path / "cron.db")
        calls: list[int] = []
        fake_fcntl = SimpleNamespace(
            LOCK_EX=1,
            LOCK_UN=2,
            flock=lambda _fileno, mode: calls.append(mode),
        )
        monkeypatch.setattr(repository, "sys", SimpleNamespace(platform="linux"))
        monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)

        with repo._migration_lock():
            assert calls == [fake_fcntl.LOCK_EX]

        assert calls == [
            fake_fcntl.LOCK_EX,
            fake_fcntl.LOCK_UN,
        ]
