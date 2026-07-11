"""KBConfigStore: atomic, lock-guarded kb_config.json persistence.

Pins the three failure modes the store exists to prevent:

* lost updates — two writers doing read-modify-write with no lock spanning
  the cycle, so the slower one commits a stale snapshot over the faster one;
* torn reads — the legacy writer truncated the file (``open(..., "w")``)
  before locking, so readers observed an empty/partial file and fell back to
  an empty default that a later write persisted;
* silent corruption recovery — a file that exists but does not parse must
  raise, never become a mutable default payload.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from deeptutor.knowledge import config_store as config_store_module
from deeptutor.knowledge.config_store import (
    KBConfigCorruptionError,
    KBConfigStore,
)
from deeptutor.knowledge.manager import KnowledgeBaseManager
from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService


class TestStoreBasics:
    def test_missing_file_reads_as_default(self, tmp_path: Path) -> None:
        store = KBConfigStore(tmp_path / "kb_config.json")
        assert store.read() == {"knowledge_bases": {}}

    def test_zero_byte_file_raises_and_is_preserved(self, tmp_path: Path) -> None:
        """An empty file is the legacy truncate-crash artifact, not a fresh
        install — rebuilding a default over it would hide the damage."""
        path = tmp_path / "kb_config.json"
        path.write_text("", encoding="utf-8")
        store = KBConfigStore(path)

        with pytest.raises(KBConfigCorruptionError, match="empty"):
            store.read()
        with pytest.raises(KBConfigCorruptionError, match="empty"):
            store.transaction(lambda config: config.update(marker=1))

        assert path.read_text(encoding="utf-8") == ""

    def test_invalid_json_raises_and_preserves_file(self, tmp_path: Path) -> None:
        path = tmp_path / "kb_config.json"
        damaged = '{"knowledge_bases": {"kb": {"path": "kb"'
        path.write_text(damaged, encoding="utf-8")
        store = KBConfigStore(path)

        with pytest.raises(KBConfigCorruptionError):
            store.read()
        with pytest.raises(KBConfigCorruptionError):
            store.transaction(lambda config: None)

        # The damaged file must survive both attempts byte-for-byte.
        assert path.read_text(encoding="utf-8") == damaged

    def test_non_object_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "kb_config.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(KBConfigCorruptionError):
            KBConfigStore(path).read()

    def test_transaction_commits_and_returns_result(self, tmp_path: Path) -> None:
        path = tmp_path / "kb_config.json"
        store = KBConfigStore(path)

        def mutate(config: dict) -> str:
            config["knowledge_bases"]["kb"] = {"path": "kb"}
            return "done"

        state, result = store.transaction(mutate)
        assert result == "done"
        assert state["knowledge_bases"]["kb"] == {"path": "kb"}
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == state

    def test_mutator_exception_writes_nothing_and_releases_lock(self, tmp_path: Path) -> None:
        path = tmp_path / "kb_config.json"
        store = KBConfigStore(path)
        store.transaction(lambda config: config.update(marker=1))

        with pytest.raises(RuntimeError, match="boom"):
            store.transaction(lambda config: (_ for _ in ()).throw(RuntimeError("boom")))

        assert json.loads(path.read_text(encoding="utf-8"))["marker"] == 1
        # Lock must be free again for the next writer.
        store.transaction(lambda config: config.update(marker=2))
        assert json.loads(path.read_text(encoding="utf-8"))["marker"] == 2

    def test_unserializable_payload_preserves_file_and_cleans_temp(self, tmp_path: Path) -> None:
        path = tmp_path / "kb_config.json"
        store = KBConfigStore(path)
        store.transaction(lambda config: config.update(ok=True))
        before = path.read_bytes()

        with pytest.raises(TypeError):
            store.transaction(lambda config: config.update(bad=object()))

        assert path.read_bytes() == before
        leftovers = {p.name for p in tmp_path.iterdir()}
        assert leftovers == {"kb_config.json", ".kb_config.json.lock"}

    def test_replace_failure_preserves_file_and_cleans_temp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "kb_config.json"
        store = KBConfigStore(path)
        store.transaction(lambda config: config.update(ok=True))
        before = path.read_bytes()

        def failing_replace(src: str, dst: str) -> None:
            raise OSError("simulated cross-process interference")

        monkeypatch.setattr(config_store_module.os, "replace", failing_replace)
        with pytest.raises(OSError, match="simulated"):
            store.transaction(lambda config: config.update(ok=False))
        monkeypatch.undo()

        assert path.read_bytes() == before
        leftovers = {p.name for p in tmp_path.iterdir()}
        assert leftovers == {"kb_config.json", ".kb_config.json.lock"}

    def test_lock_contention_retries_until_acquired(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Contention surfaces as a failed non-blocking attempt (this is how
        Windows' ``msvcrt.locking(LK_NBLCK)`` behaves); the store must retry
        within its deadline instead of failing on the first attempt."""
        attempts = {"count": 0}
        real_try = config_store_module._try_lock_exclusive

        def flaky(fd: int) -> bool:
            attempts["count"] += 1
            if attempts["count"] <= 2:
                return False
            return real_try(fd)

        monkeypatch.setattr(config_store_module, "_try_lock_exclusive", flaky)
        store = KBConfigStore(tmp_path / "kb_config.json")
        store.transaction(lambda config: None)
        assert attempts["count"] == 3

    def test_lock_timeout_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "kb_config.json"
        holder = KBConfigStore(path)
        waiter = KBConfigStore(path, lock_timeout=0.2)
        entered = threading.Event()
        release = threading.Event()

        def hold(config: dict) -> None:
            entered.set()
            assert release.wait(10)

        thread = threading.Thread(target=holder.transaction, args=(hold,))
        thread.start()
        try:
            assert entered.wait(10)
            with pytest.raises(TimeoutError):
                waiter.transaction(lambda config: None)
        finally:
            release.set()
            thread.join(10)


class TestStoreConcurrency:
    def test_second_writer_blocks_and_neither_update_is_lost(self, tmp_path: Path) -> None:
        """The historic lost-update: writer B commits while writer A holds a
        pre-B snapshot, then A commits and erases B. With the lock spanning
        read-modify-write, B cannot even read until A commits."""
        path = tmp_path / "kb_config.json"
        first = KBConfigStore(path)
        second = KBConfigStore(path)
        entered = threading.Event()
        release = threading.Event()

        def slow_mutate(config: dict) -> None:
            config["knowledge_bases"]["first"] = {"path": "first"}
            entered.set()
            assert release.wait(10)

        t1 = threading.Thread(target=first.transaction, args=(slow_mutate,))
        t1.start()
        assert entered.wait(10)

        t2 = threading.Thread(
            target=second.transaction,
            args=(lambda config: config["knowledge_bases"].update(second={"path": "second"}),),
        )
        t2.start()
        time.sleep(0.05)  # give t2 the chance to (wrongly) slip past the lock
        release.set()
        t1.join(10)
        t2.join(10)

        kbs = json.loads(path.read_text(encoding="utf-8"))["knowledge_bases"]
        assert kbs["first"] == {"path": "first"}
        assert kbs["second"] == {"path": "second"}

    def test_reader_sees_only_complete_snapshots_mid_transaction(self, tmp_path: Path) -> None:
        """The legacy writer truncated the file before locking; a mid-write
        reader saw an empty file. Now the file must stay the complete old
        snapshot until the commit lands."""
        path = tmp_path / "kb_config.json"
        store = KBConfigStore(path)
        store.transaction(lambda config: config.update(marker="old"))
        entered = threading.Event()
        release = threading.Event()

        def mutate(config: dict) -> None:
            config["marker"] = "new"
            entered.set()
            assert release.wait(10)

        thread = threading.Thread(target=store.transaction, args=(mutate,))
        thread.start()
        try:
            assert entered.wait(10)
            assert json.loads(path.read_text(encoding="utf-8"))["marker"] == "old"
            assert KBConfigStore(path).read()["marker"] == "old"
        finally:
            release.set()
            thread.join(10)
        assert json.loads(path.read_text(encoding="utf-8"))["marker"] == "new"

    def test_multiprocess_writers_lose_no_updates(self, tmp_path: Path) -> None:
        """The lock must exclude other processes, not just other threads."""
        path = tmp_path / "kb_config.json"
        workers = [
            subprocess.Popen(
                [sys.executable, "-c", _MP_WORKER_CODE, str(path), str(worker_id), str(_MP_ROUNDS)]
            )
            for worker_id in range(2)
        ]
        for proc in workers:
            assert proc.wait(timeout=120) == 0

        kbs = json.loads(path.read_text(encoding="utf-8"))["knowledge_bases"]
        expected = {f"w{w}-{i}" for w in range(2) for i in range(_MP_ROUNDS)}
        assert set(kbs) == expected


_MP_ROUNDS = 10

# Runs in a separate interpreter: hammer the shared config with distinct keys.
_MP_WORKER_CODE = """
import sys

from deeptutor.knowledge.config_store import KBConfigStore

config_path, worker_id, rounds = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
store = KBConfigStore(config_path)
for i in range(rounds):
    key = f"w{worker_id}-{i}"

    def mutate(config, key=key):
        config.setdefault("knowledge_bases", {})[key] = {"path": key}

    store.transaction(mutate)
"""


def _stall_transactions(manager: KnowledgeBaseManager) -> tuple[threading.Event, threading.Event]:
    """Make the manager's next transaction park inside the lock until released."""
    entered = threading.Event()
    release = threading.Event()
    original = manager._store.transaction

    def stalled(mutate):
        def wrapped(config: dict):
            entered.set()
            assert release.wait(10)
            return mutate(config)

        return original(wrapped)

    manager._store.transaction = stalled  # type: ignore[method-assign]
    return entered, release


class TestManagerAndServiceRaces:
    def test_two_managers_concurrent_status_updates_both_persist(self, tmp_path: Path) -> None:
        """The audit reproduction: manager A pauses mid-update while manager B
        commits; A's commit used to erase B's entirely."""
        base = tmp_path / "kbs"
        first = KnowledgeBaseManager(base_dir=str(base))
        second = KnowledgeBaseManager(base_dir=str(base))
        entered, release = _stall_transactions(first)

        t1 = threading.Thread(target=first.update_kb_status, args=("kb", "ready"))
        t1.start()
        assert entered.wait(10)

        t2 = threading.Thread(
            target=second.update_kb_status,
            args=("other", "error", {"message": "second writer"}),
        )
        t2.start()
        time.sleep(0.05)
        release.set()
        t1.join(10)
        t2.join(10)

        kbs = json.loads((base / "kb_config.json").read_text(encoding="utf-8"))["knowledge_bases"]
        assert kbs["kb"]["status"] == "ready"
        assert kbs["other"]["status"] == "error"

    def test_manager_and_config_service_concurrent_writes_both_persist(
        self, tmp_path: Path
    ) -> None:
        base = tmp_path / "kbs"
        manager = KnowledgeBaseManager(base_dir=str(base))
        service = KnowledgeBaseConfigService(config_path=base / "kb_config.json")
        entered, release = _stall_transactions(manager)

        t1 = threading.Thread(target=manager.update_kb_status, args=("kb", "ready"))
        t1.start()
        assert entered.wait(10)

        t2 = threading.Thread(target=service.set_provider_mode, args=("lightrag", "mix"))
        t2.start()
        time.sleep(0.05)
        release.set()
        t1.join(10)
        t2.join(10)

        on_disk = json.loads((base / "kb_config.json").read_text(encoding="utf-8"))
        assert on_disk["knowledge_bases"]["kb"]["status"] == "ready"
        assert on_disk["defaults"]["provider_modes"]["lightrag"] == "mix"

    def test_concurrent_registration_of_same_name_fails_second_writer(self, tmp_path: Path) -> None:
        base = tmp_path / "kbs"
        first = KnowledgeBaseManager(base_dir=str(base))
        second = KnowledgeBaseManager(base_dir=str(base))
        vault = tmp_path / "vault"
        vault.mkdir()

        first.register_obsidian_vault("Vault", str(vault))
        with pytest.raises(ValueError, match="already exists"):
            second.register_obsidian_vault("Vault", str(vault))

    def test_manager_init_raises_on_corrupt_config(self, tmp_path: Path) -> None:
        base = tmp_path / "kbs"
        base.mkdir()
        damaged = '{"knowledge_bases": {"kb": '
        (base / "kb_config.json").write_text(damaged, encoding="utf-8")

        with pytest.raises(KBConfigCorruptionError):
            KnowledgeBaseManager(base_dir=str(base))

        assert (base / "kb_config.json").read_text(encoding="utf-8") == damaged

    def test_service_init_raises_on_corrupt_config(self, tmp_path: Path) -> None:
        path = tmp_path / "kb_config.json"
        path.write_text('{"defaults": ', encoding="utf-8")

        with pytest.raises(KBConfigCorruptionError):
            KnowledgeBaseConfigService(config_path=path)

    def test_legacy_default_field_removal_is_committed(self, tmp_path: Path) -> None:
        """Migrating away the legacy top-level ``default`` field must be
        persisted — an in-memory-only pop meant every later transaction read
        the raw file and faithfully wrote the stale field back."""
        base = tmp_path / "kbs"
        base.mkdir()
        (base / "kb").mkdir()
        seed = {
            "default": "legacy-kb",
            "knowledge_bases": {
                "kb": {"path": "kb", "description": "", "rag_provider": "llamaindex"}
            },
        }
        (base / "kb_config.json").write_text(json.dumps(seed), encoding="utf-8")

        manager = KnowledgeBaseManager(base_dir=str(base))
        on_disk = json.loads((base / "kb_config.json").read_text(encoding="utf-8"))
        assert "default" not in on_disk

        manager.update_kb_status("kb", "processing")
        on_disk = json.loads((base / "kb_config.json").read_text(encoding="utf-8"))
        assert "default" not in on_disk
        assert on_disk["knowledge_bases"]["kb"]["status"] == "processing"

    def test_service_cache_updates_from_committed_snapshot(self, tmp_path: Path) -> None:
        """A mutation must fold in changes other writers committed since the
        service last read the file — the cache is the transaction's output,
        not its input."""
        path = tmp_path / "kb_config.json"
        service = KnowledgeBaseConfigService(config_path=path)
        manager = KnowledgeBaseManager(base_dir=str(tmp_path))
        manager.update_kb_status("external", "ready")

        service.set_provider_mode("lightrag", "mix")

        assert "external" in service._config["knowledge_bases"]
        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert "external" in on_disk["knowledge_bases"]
        assert on_disk["defaults"]["provider_modes"]["lightrag"] == "mix"
