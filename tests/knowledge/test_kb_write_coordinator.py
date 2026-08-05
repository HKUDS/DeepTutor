"""Unit tests for the per-KB write coordinator (KB-01).

Covers the frozen acceptance contract v1 at the coordinator level:

* only one mutation operates on a KB at a time (``kb_busy``),
* expired leases reconcile before new work,
* crash reconciliation preserves raw files, hash metadata and index state,
* unresolved ``reconcile_required`` operations block new mutations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

import pytest

from deeptutor.knowledge.write_coordinator import (
    KbBusyError,
    KbLeaseStateError,
    KbLedgerError,
    KbOwnershipLostError,
    KbWriteCoordinator,
    KbWriteOperation,
    LeaseHeartbeat,
    _parse_ts,
    redact_secrets,
)


class _Clock:
    """Injectable time source so lease expiry is deterministic in tests."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


def _start() -> datetime:
    return datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)


def _coordinator(tmp_path: Path, *, lease_seconds: int = 600) -> tuple[KbWriteCoordinator, _Clock]:
    clock = _Clock(_start())
    return (
        KbWriteCoordinator(
            base_dir=tmp_path,
            lease_seconds=lease_seconds,
            owner="test-owner",
            now=clock,
        ),
        clock,
    )


def _ledger_ops(tmp_path: Path) -> dict:
    ledger = tmp_path / "kb_write_operations.json"
    if not ledger.exists():
        return {}
    payload = json.loads(ledger.read_text(encoding="utf-8"))
    return payload.get("operations", {})


# ---------------------------------------------------------------------------
# Single-writer contract
# ---------------------------------------------------------------------------


def test_acquire_creates_running_op_with_lease(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)

    op = coordinator.acquire("kb", "upload")

    assert op.kb_name == "kb"
    assert op.operation_type == "upload"
    assert op.status == "running"
    assert op.lease_owner == "test-owner"
    assert op.lease_expires_at is not None
    assert op.reconciles_operation_id is None
    # The lease is in the future.
    assert op.lease_expires_at > op.created_at


def test_second_acquire_while_live_lease_raises_busy(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    coordinator.acquire("kb", "upload")

    with pytest.raises(KbBusyError) as excinfo:
        coordinator.acquire("kb", "reindex")

    assert excinfo.value.error_code == "kb_busy"
    assert excinfo.value.kb_name == "kb"
    assert "kb_busy" in str(excinfo.value)


def test_acquire_on_different_kb_is_independent(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    coordinator.acquire("kb-a", "upload")

    op_b = coordinator.acquire("kb-b", "reindex")

    assert op_b.kb_name == "kb-b"
    assert op_b.status == "running"


def test_terminal_operation_does_not_block_new_work(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload")
    coordinator.complete("kb", op.id, "succeeded", owner="test-owner")

    next_op = coordinator.acquire("kb", "delete")

    assert next_op.status == "running"
    assert next_op.id != op.id


# ---------------------------------------------------------------------------
# Lease expiry + reconciliation
# ---------------------------------------------------------------------------


def test_expired_lease_reconciles_before_new_work(tmp_path: Path) -> None:
    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "upload")
    clock.advance(601)  # lease has expired

    second = coordinator.acquire("kb", "reindex")

    # The new mutation proceeds, and it records which expired op it reconciled.
    assert second.status == "running"
    assert second.reconciles_operation_id == first.id
    # The ledger now holds only the new operation.
    ops = _ledger_ops(tmp_path)
    assert set(ops) == {"kb"}
    assert ops["kb"]["id"] == second.id


def test_acquire_after_completed_operation_has_no_lineage(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    first = coordinator.acquire("kb", "upload")
    coordinator.complete("kb", first.id, "succeeded", owner="test-owner")

    second = coordinator.acquire("kb", "delete")

    assert second.reconciles_operation_id is None


def test_crash_reconcile_preserves_raw_files_and_prunes_stale_hashes(
    tmp_path: Path,
) -> None:
    """A crashed upload leaves raw files and a stale hash registry behind.

    On take-over the coordinator must preserve the staged raw file, drop hash
    records whose file is gone, and only then allow the next mutation.
    """
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    staged = raw_dir / "staged.txt"
    staged.write_text("content", encoding="utf-8")
    (kb_dir / "metadata.json").write_text(
        json.dumps(
            {
                "file_hashes": {
                    "staged.txt": "abc123",
                    "missing.pdf": "deadbeef",
                },
                "keep": "untouched",
            }
        ),
        encoding="utf-8",
    )

    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "upload")
    clock.advance(601)  # crash: lease expired, op never completed

    second = coordinator.acquire("kb", "upload")

    assert second.reconciles_operation_id == first.id
    # Raw file preserved.
    assert staged.exists()
    # Stale hash for the missing file pruned; live hash + unrelated metadata kept.
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"] == {"staged.txt": "abc123"}
    assert metadata["keep"] == "untouched"


def test_crash_reconcile_does_not_create_hash_for_unindexed_raw_file(
    tmp_path: Path,
) -> None:
    """A staged-but-never-indexed raw file must stay unindexed, not invented."""
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    orphan = raw_dir / "orphan.pdf"
    orphan.write_text("x", encoding="utf-8")
    (kb_dir / "metadata.json").write_text(json.dumps({"file_hashes": {}}), encoding="utf-8")

    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    coordinator.acquire("kb", "upload")
    clock.advance(601)

    coordinator.acquire("kb", "reindex")

    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"] == {}
    assert orphan.exists()


def test_delete_reconcile_succeeds_when_file_already_removed(tmp_path: Path) -> None:
    """A crashed delete whose file is gone converges to succeeded on take-over."""
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    # The file was already removed (crash after unlink, before hash prune).
    (kb_dir / "metadata.json").write_text(
        json.dumps({"file_hashes": {"gone.txt": "abc"}}),
        encoding="utf-8",
    )

    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "delete", subject_id="gone.txt")
    clock.advance(601)

    second = coordinator.acquire("kb", "upload")

    assert second.reconciles_operation_id == first.id
    # The stale hash for the already-removed file was pruned during reconcile.
    metadata = json.loads((kb_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["file_hashes"] == {}


def test_delete_reconcile_fails_when_file_still_present(tmp_path: Path) -> None:
    """A crashed delete whose file still exists did not complete → failed."""
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    target = raw_dir / "still-here.txt"
    target.write_text("x", encoding="utf-8")

    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    coordinator.acquire("kb", "delete", subject_id="still-here.txt")
    clock.advance(601)

    coordinator.acquire("kb", "reindex")

    # The raw file is untouched.
    assert target.exists()


def test_reindex_reconcile_succeeds_when_matching_ready_version_exists(
    tmp_path: Path,
) -> None:
    kb_dir = tmp_path / "kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig-target", "version": "version-1"}),
        encoding="utf-8",
    )

    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "reindex", input_snapshot_hash="sig-target")
    clock.advance(601)

    second = coordinator.acquire("kb", "upload")

    assert second.reconciles_operation_id == first.id


def test_reindex_reconcile_fails_without_ready_matching_version(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir(parents=True)

    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "reindex", input_snapshot_hash="sig-missing")
    clock.advance(601)

    second = coordinator.acquire("kb", "upload")

    assert second.reconciles_operation_id == first.id


# ---------------------------------------------------------------------------
# Unresolved reconciliation blocks new work
# ---------------------------------------------------------------------------


def test_reconcile_required_blocks_new_work(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    coordinator._save(
        {
            "kb": KbWriteOperation.from_dict(
                {
                    "id": "r1",
                    "kb_name": "kb",
                    "operation_type": "card_publish",
                    "status": "reconcile_required",
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                    "lease_owner": None,
                }
            )
        }
    )

    with pytest.raises(KbBusyError) as excinfo:
        coordinator.acquire("kb", "upload")

    assert excinfo.value.error_code == "kb_busy"
    assert excinfo.value.status == "reconcile_required"


def test_future_card_operation_reconciles_to_reconcile_required(tmp_path: Path) -> None:
    """card_publish/card_retract cannot be auto-reconciled from the filesystem."""
    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "card_publish")
    clock.advance(601)

    with pytest.raises(KbBusyError) as excinfo:
        coordinator.acquire("kb", "upload")

    assert excinfo.value.error_code == "kb_busy"
    assert excinfo.value.status == "reconcile_required"


# ---------------------------------------------------------------------------
# complete / renew semantics
# ---------------------------------------------------------------------------


def test_complete_marks_terminal_with_error_details(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload")

    done = coordinator.complete(
        "kb",
        op.id,
        "failed",
        owner="test-owner",
        error_code="upload_index_failed",
        error="2/3 file(s) failed to index",
        index_task_id="task-1",
    )

    assert done is not None
    assert done.status == "failed"
    assert done.error_code == "upload_index_failed"
    assert done.sanitized_error == "2/3 file(s) failed to index"
    assert done.index_task_id == "task-1"
    assert done.finished_at is not None


def test_complete_requires_matching_owner(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload", owner="holder-a")

    result = coordinator.complete("kb", op.id, "succeeded", owner="holder-b")

    assert result is None
    # The op is still running — the wrong owner could not clobber it.
    assert coordinator.current_operation("kb").status == "running"


def test_complete_after_takeover_is_noop(tmp_path: Path) -> None:
    """A slow worker finishing after its lease was reconciled must not clobber."""
    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "upload", owner="holder-a")
    clock.advance(601)
    coordinator.acquire("kb", "reindex", owner="holder-b")  # takes over + reconciles

    result = coordinator.complete("kb", first.id, "succeeded", owner="holder-a")

    assert result is None
    current = coordinator.current_operation("kb")
    assert current.id != first.id


def test_complete_is_idempotent(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload")

    first = coordinator.complete("kb", op.id, "succeeded", owner="test-owner")
    second = coordinator.complete("kb", op.id, "succeeded", owner="test-owner")

    assert first is not None
    assert second is not None
    assert first.status == second.status == "succeeded"


def test_renew_extends_lease(tmp_path: Path) -> None:
    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    op = coordinator.acquire("kb", "upload")
    original_expiry = op.lease_expires_at
    clock.advance(300)

    renewed = coordinator.renew("kb", op.id, owner="test-owner")

    assert renewed is not None
    assert renewed.lease_expires_at > original_expiry


def test_renew_does_not_work_after_takeover(tmp_path: Path) -> None:
    coordinator, clock = _coordinator(tmp_path, lease_seconds=600)
    first = coordinator.acquire("kb", "upload", owner="holder-a")
    clock.advance(601)
    coordinator.acquire("kb", "reindex", owner="holder-b")

    renewed = coordinator.renew("kb", first.id, owner="holder-a")

    assert renewed is None


# ---------------------------------------------------------------------------
# Persistence / restart
# ---------------------------------------------------------------------------


def test_ledger_persists_across_instances(tmp_path: Path) -> None:
    """A new coordinator instance (simulated restart) sees the running lease."""
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload")

    fresh = KbWriteCoordinator(base_dir=tmp_path)
    current = fresh.current_operation("kb")

    assert current is not None
    assert current.id == op.id
    assert current.status == "running"


# ---------------------------------------------------------------------------
# Inter-process serialization (blocker #2/#4)
# ---------------------------------------------------------------------------


def _mp_acquire_worker(base_dir: str, barrier, queue) -> None:
    """One process in the simultaneous-acquire race (exactly one must win)."""
    coordinator = KbWriteCoordinator(base_dir=base_dir)
    barrier.wait()  # both processes reach acquire at the same time
    try:
        op = coordinator.acquire("kb", "upload")
        queue.put(("ok", op.id))
    except KbBusyError as exc:
        queue.put(("busy", exc.error_code))
    except Exception as exc:  # pragma: no cover - diagnostic for the coordinator
        queue.put(("error", f"{type(exc).__name__}: {exc}"))


def test_simultaneous_acquire_has_exactly_one_winner(tmp_path: Path) -> None:
    """Two processes racing for the same KB must not both enter the mutation.

    The OS-level ledger lock serializes the read-modify-write: the loser reads
    the winner's live lease and is refused with ``kb_busy``. This is the
    regression test for the read-check-write race.
    """
    import multiprocessing as mp

    ctx = mp.get_context("fork")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    base_dir = str(tmp_path)
    processes = [
        ctx.Process(target=_mp_acquire_worker, args=(base_dir, barrier, queue)) for _ in range(2)
    ]
    for proc in processes:
        proc.start()
    for proc in processes:
        proc.join(timeout=30)

    for proc in processes:
        assert proc.exitcode == 0
    results = [queue.get(timeout=5) for _ in processes]
    outcomes = sorted(entry[0] for entry in results)
    assert outcomes == ["busy", "ok"]
    # Exactly one operation was persisted — no lost update from the loser.
    ops = _ledger_ops(tmp_path)
    assert set(ops) == {"kb"}
    assert ops["kb"]["status"] == "running"


# ---------------------------------------------------------------------------
# Periodic heartbeat (blocker #3)
# ---------------------------------------------------------------------------


def test_heartbeat_renews_lease_for_long_running_writer(tmp_path: Path) -> None:
    """A healthy long-running writer is not taken over: the periodic heartbeat
    keeps the lease alive past the point a naive writer would have expired."""
    import asyncio

    clock = _Clock(_start())
    coordinator = KbWriteCoordinator(
        base_dir=tmp_path, lease_seconds=2, owner="writer-a", now=clock
    )
    op = coordinator.acquire("kb", "upload")
    heartbeat = LeaseHeartbeat(coordinator, "kb", op.id, owner="writer-a", interval=0.05)

    async def _run() -> None:
        heartbeat.start()
        try:
            for _ in range(5):
                # Advance far past the 2s lease; only a renewal keeps it alive.
                clock.advance(1)
                await asyncio.sleep(0.06)
        finally:
            await heartbeat.stop()

    asyncio.run(_run())

    current = coordinator.current_operation("kb")
    assert current is not None
    assert current.id == op.id
    assert _parse_ts(current.lease_expires_at) > clock.now
    # A second writer is still refused while the heartbeat holds the lease.
    with pytest.raises(KbBusyError):
        coordinator.acquire("kb", "reindex", owner="writer-b")


def test_heartbeat_detects_ownership_loss_and_stops_stale_writer(
    tmp_path: Path,
) -> None:
    """When a newer holder reconciles the lease, the stale writer's heartbeat
    reports ownership loss so it stops before its next write step."""
    import asyncio

    clock = _Clock(_start())
    coordinator = KbWriteCoordinator(
        base_dir=tmp_path, lease_seconds=2, owner="writer-a", now=clock
    )
    op = coordinator.acquire("kb", "upload")
    heartbeat = LeaseHeartbeat(coordinator, "kb", op.id, owner="writer-a", interval=0.05)

    async def _run() -> None:
        heartbeat.start()
        try:
            clock.advance(3)  # writer-a's lease expires
            # writer-b takes over, reconciling the expired lease.
            coordinator.acquire("kb", "reindex", owner="writer-b")
            deadline = time.monotonic() + 5
            while not heartbeat.has_lost() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert heartbeat.has_lost()
        finally:
            await heartbeat.stop()

    asyncio.run(_run())

    assert heartbeat.has_lost()
    with pytest.raises(KbOwnershipLostError):
        heartbeat.check()


# ---------------------------------------------------------------------------
# Secret redaction (blocker #5)
# ---------------------------------------------------------------------------


def test_sanitized_error_redacts_secrets_before_persist(tmp_path: Path) -> None:
    """API keys, bearer tokens and authorization headers never persist."""
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload")

    done = coordinator.complete(
        "kb",
        op.id,
        "failed",
        owner="test-owner",
        error_code="upload_failed",
        error=(
            "GET https://api.example.com/v1/embeddings?api_key=sk-ABCDEF1234567890 "
            "failed with 401: Authorization: Bearer "
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        ),
    )

    assert done is not None
    assert done.error_code == "upload_failed"  # stable error code preserved
    assert "sk-ABCDEF1234567890" not in (done.sanitized_error or "")
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in (done.sanitized_error or "")
    assert "<redacted>" in (done.sanitized_error or "")
    # The persisted ledger holds no raw secret material either.
    raw = _ledger_ops(tmp_path)["kb"]["sanitized_error"]
    assert "sk-ABCDEF" not in raw
    assert "eyJhbGci" not in raw


def test_sanitized_error_preserves_human_readable_messages(tmp_path: Path) -> None:
    """Messages without credentials pass through unchanged."""
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload")

    done = coordinator.complete(
        "kb",
        op.id,
        "failed",
        owner="test-owner",
        error_code="upload_index_failed",
        error="2/3 file(s) failed to index",
    )

    assert done is not None
    assert done.error_code == "upload_index_failed"
    assert done.sanitized_error == "2/3 file(s) failed to index"


def test_redact_secrets_is_centralized_and_library_level() -> None:
    """The redaction helper is directly usable by any caller that persists text."""
    assert redact_secrets("api_key=sk-1234567890abcdef") == "api_key=<redacted>"
    assert redact_secrets("Authorization: Bearer tok1234567890") == ("Authorization: <redacted>")
    assert redact_secrets("normal error message") == "normal error message"
    assert redact_secrets(None) is None


# ---------------------------------------------------------------------------
# Fail-closed ledger (corrupt / invalid shape / unreadable)
# ---------------------------------------------------------------------------


def test_corrupt_json_ledger_fails_closed_and_is_never_overwritten(
    tmp_path: Path,
) -> None:
    """A corrupt ledger is never treated as an empty ledger and never clobbered.

    Every acquire/renew/complete/reconcile/read path must fail closed so a
    second writer cannot start while the coordinator cannot know who owns the
    KB.
    """
    ledger = tmp_path / "kb_write_operations.json"
    original = "{ this is not valid json ]"
    ledger.write_text(original, encoding="utf-8")
    coordinator, _clock = _coordinator(tmp_path)

    with pytest.raises(KbLedgerError) as excinfo:
        coordinator.acquire("kb", "upload")
    assert excinfo.value.error_code == "kb_ledger_unreadable"
    # The diagnostic is sanitized and does not embed the whole corrupt payload.
    assert "ledger" in str(excinfo.value)
    assert original not in str(excinfo.value)
    assert ledger.read_text(encoding="utf-8") == original

    with pytest.raises(KbLedgerError):
        coordinator.renew("kb", "op", owner="test-owner")
    with pytest.raises(KbLedgerError):
        coordinator.complete("kb", "op", "succeeded", owner="test-owner")
    with pytest.raises(KbLedgerError):
        coordinator.reconcile("kb")
    with pytest.raises(KbLedgerError):
        coordinator.current_operation("kb")
    with pytest.raises(KbLeaseStateError):
        coordinator.verify_lease("kb", "op", owner="test-owner")
    # Still untouched.
    assert ledger.read_text(encoding="utf-8") == original


def test_invalid_ledger_shape_fails_closed(tmp_path: Path) -> None:
    """An existing ledger whose shape is wrong is unusable, not empty."""
    ledger = tmp_path / "kb_write_operations.json"

    ledger.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    coordinator, _clock = _coordinator(tmp_path)
    with pytest.raises(KbLedgerError):
        coordinator.acquire("kb", "upload")

    ledger.write_text(json.dumps({"version": 1, "operations": []}), encoding="utf-8")
    with pytest.raises(KbLedgerError):
        coordinator.acquire("kb", "upload")

    ledger.write_text(
        json.dumps({"version": 1, "operations": {"kb": ["not-an-operation"]}}),
        encoding="utf-8",
    )
    with pytest.raises(KbLedgerError):
        coordinator.acquire("kb", "upload")


def test_unreadable_ledger_fails_closed(tmp_path: Path) -> None:
    """A ledger path that cannot be read fails closed and is not replaced."""
    ledger = tmp_path / "kb_write_operations.json"
    ledger.mkdir()  # a directory where the ledger file should be → read fails
    coordinator, _clock = _coordinator(tmp_path)

    with pytest.raises(KbLedgerError):
        coordinator.acquire("kb", "upload")

    # The unreadable ledger was not overwritten as `{}` (still a directory).
    assert ledger.is_dir()


# ---------------------------------------------------------------------------
# Terminal operations are invalid renewals (fail-closed ownership loss)
# ---------------------------------------------------------------------------


def test_renew_on_terminal_operation_returns_none(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "upload")
    coordinator.complete("kb", op.id, "succeeded", owner="test-owner")

    assert coordinator.renew("kb", op.id, owner="test-owner") is None


def test_renew_on_reconcile_required_returns_none(tmp_path: Path) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    coordinator._save(
        {
            "kb": KbWriteOperation.from_dict(
                {
                    "id": "r1",
                    "kb_name": "kb",
                    "operation_type": "card_publish",
                    "status": "reconcile_required",
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                    "lease_owner": "test-owner",
                }
            )
        }
    )

    # A reconcile_required operation is terminal: renewing it is ownership loss.
    assert coordinator.renew("kb", "r1", owner="test-owner") is None
    with pytest.raises(KbOwnershipLostError):
        coordinator.verify_lease("kb", "r1", owner="test-owner")


# ---------------------------------------------------------------------------
# Heartbeat renew exception → fail-closed lease-state loss
# ---------------------------------------------------------------------------


def test_heartbeat_renew_exception_records_lease_state_loss(tmp_path: Path) -> None:
    """A corrupt ledger mid-flight is a fail-closed lease-state loss.

    The renewer must never die silently: it records the loss so
    ``check()``/``run_guarded()`` raise a stable coordinator error.
    """
    import asyncio

    clock = _Clock(_start())
    coordinator = KbWriteCoordinator(
        base_dir=tmp_path, lease_seconds=2, owner="writer-a", now=clock
    )
    op = coordinator.acquire("kb", "upload")
    heartbeat = LeaseHeartbeat(coordinator, "kb", op.id, owner="writer-a", interval=0.05)

    async def _run() -> None:
        heartbeat.start()
        try:
            # Corrupt the ledger so the next renewal fails closed.
            (tmp_path / "kb_write_operations.json").write_text("{corrupt", encoding="utf-8")
            deadline = time.monotonic() + 5
            while not heartbeat.has_lost() and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            assert heartbeat.has_lost()
        finally:
            await heartbeat.stop()

    asyncio.run(_run())

    with pytest.raises(KbLeaseStateError):
        heartbeat.check()


# ---------------------------------------------------------------------------
# resolve_manual ownership hardening (KB-03 review finding 1)
# ---------------------------------------------------------------------------


def test_resolve_manual_refuses_live_op_without_matching_owner(
    tmp_path: Path,
) -> None:
    """A live active operation belongs to its lease holder; a card-level
    reconcile must never resolve another holder's in-flight operation."""
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "card_publish", owner="writer-a")

    # No owner supplied → refuse.
    assert coordinator.resolve_manual("kb", op.id, "failed") is None
    # Wrong owner supplied → refuse.
    assert coordinator.resolve_manual("kb", op.id, "failed", owner="writer-b") is None
    # The op is untouched and still running.
    current = coordinator.current_operation("kb")
    assert current.status == "running"
    assert current.id == op.id


def test_resolve_manual_allows_live_op_with_matching_owner(tmp_path: Path) -> None:
    """The normal writer path (matching owner) may resolve its own live op."""
    coordinator, _clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "card_publish", owner="writer-a")
    updated = coordinator.resolve_manual("kb", op.id, "succeeded", owner="writer-a")
    assert updated is not None
    assert updated.status == "succeeded"


def test_resolve_manual_converges_expired_op_without_owner(tmp_path: Path) -> None:
    """An expired (crash-orphaned) operation may be converged by reconcile with
    no owner — the crash owner is gone and cannot be matched."""
    coordinator, clock = _coordinator(tmp_path)
    op = coordinator.acquire("kb", "card_publish", owner="crash-owner")
    clock.advance(1000)  # lease expires
    updated = coordinator.resolve_manual("kb", op.id, "failed")
    assert updated is not None
    assert updated.status == "failed"


def test_resolve_manual_converges_reconcile_required_without_owner(
    tmp_path: Path,
) -> None:
    coordinator, _clock = _coordinator(tmp_path)
    coordinator._save(
        {
            "kb": KbWriteOperation.from_dict(
                {
                    "id": "r1",
                    "kb_name": "kb",
                    "operation_type": "card_publish",
                    "status": "reconcile_required",
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                    "lease_owner": "crash-owner",
                }
            )
        }
    )
    updated = coordinator.resolve_manual("kb", "r1", "failed")
    assert updated is not None
    assert updated.status == "failed"


# ---------------------------------------------------------------------------
# Cooperative staging lease-awareness (blocker: cancelling to_thread is not
# enough to stop the underlying thread)
# ---------------------------------------------------------------------------


def _write_llamaindex_version(kb_dir: Path) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )


def test_staging_stops_on_ownership_loss_before_mutating_next_file(
    tmp_path: Path,
) -> None:
    """Staging must not keep copying files under a new holder.

    Cancelling an ``asyncio.to_thread`` await would not stop the underlying
    staging thread, so ``add_documents`` is cooperatively lease-aware: its
    ``lease_check`` callback aborts the thread at the next file once the lease
    was taken over.
    """
    import threading

    from deeptutor.knowledge.add_documents import DocumentAdder

    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    _write_llamaindex_version(kb_dir)
    (kb_dir / "metadata.json").write_text(json.dumps({"file_hashes": {}}), encoding="utf-8")

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    src_a = src_dir / "a.txt"
    src_a.write_text("a", encoding="utf-8")
    src_b = src_dir / "b.txt"
    src_b.write_text("b", encoding="utf-8")
    src_c = src_dir / "c.txt"
    src_c.write_text("c", encoding="utf-8")

    clock = _Clock(_start())
    coordinator = KbWriteCoordinator(
        base_dir=tmp_path, lease_seconds=600, owner="holder-a", now=clock
    )
    op = coordinator.acquire("kb", "upload")

    calls = {"n": 0}
    first_staged = threading.Event()
    takeover_done = threading.Event()

    def _lease_check() -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            # File 1 is staged; pause the thread, take over the lease, then let
            # the staging thread observe the takeover at its next checkpoint.
            first_staged.set()
            assert takeover_done.wait(timeout=10)
        if coordinator.renew("kb", op.id, owner="holder-a") is None:
            raise KbOwnershipLostError("kb", op.id)

    adder = DocumentAdder(kb_name="kb", base_dir=str(tmp_path))
    worker = threading.Thread(
        target=adder.add_documents,
        args=([str(src_a), str(src_b), str(src_c)],),
        kwargs={"allow_duplicates": False, "lease_check": _lease_check},
    )
    worker.start()
    assert first_staged.wait(timeout=10)

    # holder-b takes over: holder-a's lease expires and is reconciled.
    clock.advance(601)
    coordinator.acquire("kb", "reindex", owner="holder-b")
    takeover_done.set()
    worker.join(timeout=10)
    assert not worker.is_alive()

    # The first file was staged; the stale worker stopped before b/c.
    assert (raw_dir / "a.txt").exists()
    assert not (raw_dir / "b.txt").exists()
    assert not (raw_dir / "c.txt").exists()
