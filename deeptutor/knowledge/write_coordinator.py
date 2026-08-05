"""Per-knowledge-base write coordinator.

Implements the durable per-KB operation/lease contract from the Feynman design
(``KbWriteOperation`` / ``KbWriteCoordinator``). Every mutation of a local
indexed KB — upload, delete, reindex — runs through one coordinator so at most
one write operation owns a KB at a time. Knowledge-card publish/retract reuse
this coordinator in later waves; their operation types are reserved here but
cannot be auto-reconciled, so an interrupted publish/retract is surfaced as
``reconcile_required``.

Guarantees provided:

* At most one ``running``/``queued`` or ``reconcile_required`` operation per
  KB. A second mutation while a live lease is held (or while an unresolved
  reconciliation is pending) is refused with :class:`KbBusyError`, a
  *recoverable* condition the API maps to a retryable ``kb_busy`` response.
* Every ledger read-modify-write transaction (``acquire``/``complete``/
  ``renew``/explicit ``reconcile``) is serialized with an OS-level
  ``fcntl.flock`` on ``<ledger>.lock``, so two processes or threads cannot both
  read "no active lease" and both enter the mutation. The lock is held only for
  the ledger transaction — never while the KB write itself runs.
* An *expired* lease does not let a new mutation start directly: the new holder
  first takes over the interrupted operation and reconciles it against the
  on-disk state (raw files, hash registry, index versions), converging it to a
  terminal ``succeeded`` / ``failed`` state (or ``reconcile_required`` for
  future types that cannot be verified from the filesystem). Only then does the
  new mutation begin.
* Reconciliation is conservative: it never deletes raw files and never guesses
  about a provider's internals. It prunes stale hash records (raw file gone)
  and otherwise marks the interrupted operation ``failed`` with a sanitized
  ``interrupted`` reason so the next mutation can safely re-run.
* Long-running background writers renew their lease periodically via
  :class:`LeaseHeartbeat`. If a renewal reports ownership loss (a newer holder
  took over), the stale writer aborts before its next KB write step instead of
  silently continuing and corrupting state.

State is persisted in ``<base_dir>/kb_write_operations.json`` with atomic
writes, so leases and reconciliation survive process restarts. Connected KBs
(Obsidian, linked, subagent, LightRAG server, IMA) are read-only pointers and
never reach this coordinator — the router refuses them before any acquire.

``sanitized_error`` is redacted (:func:`redact_secrets`) before it is persisted
so raw API keys, bearer tokens, authorization headers and equivalent secrets
never land in the ledger; stable error codes are separate fields and are kept.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import sys
from typing import Any
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

#: Default duration of a KB write lease. Long enough for a normal upload /
#: reindex; background tasks renew the lease as they progress.
DEFAULT_LEASE_SECONDS = 30 * 60

#: File that holds the per-KB operation ledger, next to ``kb_config.json``.
LEDGER_FILENAME = "kb_write_operations.json"

#: Operation families the coordinator serializes. ``card_publish`` /
#: ``card_retract`` are reserved for the knowledge-card waves and cannot be
#: auto-reconciled from the filesystem.
OPERATION_TYPES = frozenset({"upload", "delete", "reindex", "card_publish", "card_retract"})

#: Statuses that hold a lease and therefore block new mutations.
ACTIVE_STATUSES = frozenset({"queued", "running"})

#: Terminal statuses. ``reconcile_required`` blocks new work until an explicit
#: reconcile converges it.
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "reconcile_required"})

VALID_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _format_ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def default_owner() -> str:
    """A process-scoped default lease owner for callers that pass none."""
    return f"process:{os.getpid()}"


def _safe_relpath_under(raw_dir: Path, rel_path: str) -> Path | None:
    """Resolve ``rel_path`` under ``raw_dir``, or ``None`` when it escapes."""
    if not rel_path or not raw_dir.is_dir():
        return None
    try:
        target = (raw_dir / rel_path).resolve()
        target.relative_to(raw_dir.resolve())
    except (ValueError, OSError):
        return None
    return target


#: Credential patterns that must never persist in ``sanitized_error``.
#: Each entry is ``(compiled_pattern, replacement)``; replacement may reference
#: group 1 when it is a stable label (e.g. ``api_key=``) that should be kept.
_SECRET_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenAI-style API keys and AWS access-key IDs (bare, no label).
    (re.compile(r"\b(sk-[A-Za-z0-9_-]{8,})\b"), r"<redacted>"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), r"<redacted>"),
    # JWTs: three dot-separated base64url segments.
    (
        re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b"),
        r"<redacted>",
    ),
    # Labeled secrets: keep the label, replace the value.
    (re.compile(r"(?i)(\bapi[_-]?key\b\s*[:=]\s*)[^\s,;&'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bx-api-key\b\s*[:=]\s*)[^\s,;&'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\baccess[_-]?token\b\s*[:=]\s*)[^\s,;&'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bauth[_-]?token\b\s*[:=]\s*)[^\s,;&'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bclient[_-]?secret\b\s*[:=]\s*)[^\s,;&'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bpassword\b\s*[:=]\s*)[^\s,;&'\"]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\btoken\b\s*[:=]\s*)[^\s,;&'\"]+"), r"\1<redacted>"),
    # Authorization headers: "Authorization: Bearer <jwt>" / "authorization: <x>".
    (re.compile(r"(?i)(\bauthorization\b\s*[:=]\s*)[^\n,;]+"), r"\1<redacted>"),
    (re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1<redacted>"),
)


def redact_secrets(text: str | None) -> str | None:
    """Replace likely credential material with a stable placeholder.

    Applied before any error string is persisted as ``sanitized_error`` so raw
    API keys, bearer tokens, authorization headers and equivalent secrets never
    land in the write-operation ledger. Stable error *codes* are separate
    fields and are never touched; human-readable messages without credentials
    pass through unchanged.
    """
    if not text:
        return text
    result = str(text)
    for pattern, replacement in _SECRET_REDACTIONS:
        result = pattern.sub(replacement, result)
    return result


class KbBusyError(Exception):
    """Raised when a mutation is refused because another operation owns the KB.

    This is a *recoverable* condition: the caller may retry after the current
    operation completes or its lease is reconciled. The API maps it to a
    retryable ``kb_busy`` response.
    """

    error_code = "kb_busy"

    def __init__(
        self,
        *,
        kb_name: str,
        operation_type: str,
        status: str,
        lease_owner: str | None,
        lease_expires_at: str | None,
        message: str | None = None,
    ) -> None:
        self.kb_name = kb_name
        self.operation_type = operation_type
        self.status = status
        self.lease_owner = lease_owner
        self.lease_expires_at = lease_expires_at
        super().__init__(message or self._default_message())

    def _default_message(self) -> str:
        owner = f" held by {self.lease_owner}" if self.lease_owner else ""
        return (
            f"Knowledge base '{self.kb_name}' is busy (kb_busy): a "
            f"{self.operation_type} operation is {self.status}{owner}. "
            "Retry after it completes or is reconciled."
        )


class KbLedgerError(Exception):
    """Raised when the write-operation ledger is corrupt, invalid, or unreadable.

    This is a *hard*, non-recoverable condition: the coordinator cannot know
    which KB holds a lease, so every acquire/renew/complete/reconcile path fails
    closed rather than treating the ledger as empty and silently allowing a
    second writer. The message carries only a sanitized diagnostic (path +
    reason), never raw ledger content or secrets, and the ledger file itself is
    never overwritten while it is unreadable.
    """

    error_code = "kb_ledger_unreadable"

    def __init__(self, ledger_path: str | Path, detail: str) -> None:
        self.ledger_path = str(ledger_path)
        self.detail = detail
        super().__init__(f"KB write-operation ledger is unusable ({self.error_code}): {detail}")


class KbLeaseError(Exception):
    """Base class for lease failures that must stop a stale background writer.

    Both ownership loss (:class:`KbOwnershipLostError`) and an unreadable /
    indeterminate lease state (:class:`KbLeaseStateError`) mean the writer can
    no longer prove it owns the KB, so it must abort before its next KB write
    step instead of mutating under unknown ownership.
    """

    error_code = "kb_lease_error"


class KbOwnershipLostError(KbLeaseError):
    """Raised when a background writer's lease was taken over by a newer holder.

    The stale writer must stop before its next KB write step: the new holder
    owns the KB and may be mutating raw/hash/index state concurrently, so
    continuing would risk corrupting that state.
    """

    error_code = "kb_ownership_lost"

    def __init__(self, kb_name: str, operation_id: str) -> None:
        self.kb_name = kb_name
        self.operation_id = operation_id
        super().__init__(
            f"Knowledge base '{kb_name}' write lease was lost (kb_ownership_lost): "
            f"operation {operation_id} is no longer the current holder. "
            "The stale writer stopped before its next write step."
        )


class KbLeaseStateError(KbLeaseError):
    """Raised when the coordinator can no longer determine lease ownership.

    The heartbeat records this when a renewal or ledger I/O fails (e.g. a
    corrupt ledger), so ``check()``/``run_guarded()`` raise it and the stale
    writer stops exactly as it would for ownership loss rather than silently
    continuing to mutate KB state under unknown ownership.
    """

    error_code = "kb_lease_state"

    def __init__(self, kb_name: str, operation_id: str, *, detail: str | None = None) -> None:
        self.kb_name = kb_name
        self.operation_id = operation_id
        suffix = f": {detail}" if detail else ""
        super().__init__(
            f"Knowledge base '{kb_name}' write lease state is unknown "
            f"(kb_lease_state) for operation {operation_id}{suffix}"
        )


@dataclass
class KbWriteOperation:
    """One durable KB write operation / lease record (spec ``KbWriteOperation``)."""

    id: str
    kb_name: str
    operation_type: str
    status: str
    created_at: str
    updated_at: str
    user_id: str | None = None
    subject_id: str | None = None
    request_id: str | None = None
    lease_owner: str | None = None
    lease_expires_at: str | None = None
    input_snapshot_hash: str | None = None
    index_task_id: str | None = None
    error_code: str | None = None
    sanitized_error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    #: Id of the expired operation reconciled before this one started.
    reconciles_operation_id: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KbWriteOperation":
        unknown = data.get("operation_type")
        if unknown not in OPERATION_TYPES:
            unknown = "upload"
        status = data.get("status")
        if status not in VALID_STATUSES:
            status = "failed"
        return cls(
            id=str(data.get("id") or uuid4().hex),
            kb_name=str(data.get("kb_name") or ""),
            user_id=data.get("user_id"),
            operation_type=unknown,
            subject_id=data.get("subject_id"),
            request_id=data.get("request_id"),
            status=status,
            lease_owner=data.get("lease_owner"),
            lease_expires_at=data.get("lease_expires_at"),
            input_snapshot_hash=data.get("input_snapshot_hash"),
            index_task_id=data.get("index_task_id"),
            error_code=data.get("error_code"),
            sanitized_error=redact_secrets(data.get("sanitized_error")),
            created_at=str(data.get("created_at") or _format_ts(_now_utc())),
            started_at=data.get("started_at"),
            updated_at=str(data.get("updated_at") or _format_ts(_now_utc())),
            finished_at=data.get("finished_at"),
            reconciles_operation_id=data.get("reconciles_operation_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kb_name": self.kb_name,
            "user_id": self.user_id,
            "operation_type": self.operation_type,
            "subject_id": self.subject_id,
            "request_id": self.request_id,
            "status": self.status,
            "lease_owner": self.lease_owner,
            "lease_expires_at": self.lease_expires_at,
            "input_snapshot_hash": self.input_snapshot_hash,
            "index_task_id": self.index_task_id,
            "error_code": self.error_code,
            "sanitized_error": self.sanitized_error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "reconciles_operation_id": self.reconciles_operation_id,
        }

    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def _replace(self, **kwargs: Any) -> "KbWriteOperation":
        """Return a new operation with ``kwargs`` applied (immutable replace)."""
        return replace(self, **kwargs)

    def renewed(self, owner: str, expires_at: datetime, now: datetime) -> "KbWriteOperation":
        return self._replace(
            lease_owner=owner,
            lease_expires_at=_format_ts(expires_at),
            updated_at=_format_ts(now),
        )

    def terminal(
        self,
        status: str,
        now: datetime,
        *,
        error_code: str | None = None,
        sanitized_error: str | None = None,
        index_task_id: str | None = None,
    ) -> "KbWriteOperation":
        return self._replace(
            status=status,
            updated_at=_format_ts(now),
            finished_at=_format_ts(now),
            error_code=error_code,
            sanitized_error=redact_secrets(sanitized_error),
            index_task_id=index_task_id,
        )


class LeaseHeartbeat:
    """Bounded periodic lease renewal for a long-running background writer.

    Starts an asyncio task that renews the coordinator lease every
    ``interval`` seconds. If a renewal reports ownership loss (the operation is
    no longer the current one, the owner no longer matches, or it is already
    terminal), the heartbeat records the loss and cancels any
    :meth:`run_guarded` coroutine so the stale writer aborts instead of writing
    over the new holder's state. Every other renewal / ledger I/O exception is
    caught the same way and recorded as a fail-closed lease-state loss — the
    renewer never dies silently.

    ``check()`` re-raises a recorded loss at explicit sync checkpoints (before
    a write step that is not guarded by ``run_guarded``).
    """

    def __init__(
        self,
        coordinator: KbWriteCoordinator,
        kb_name: str,
        operation_id: str,
        *,
        owner: str,
        interval: float,
    ) -> None:
        self._coordinator = coordinator
        self._kb_name = kb_name
        self._operation_id = operation_id
        self._owner = owner
        self._interval = float(interval)
        self._loss: Exception | None = None
        self._renewer: asyncio.Task[None] | None = None
        self._guarded: asyncio.Task[Any] | None = None

    def start(self) -> None:
        """Begin periodic renewal. Idempotent."""
        if self._renewer is None or self._renewer.done():
            self._renewer = asyncio.create_task(self._renew_loop())

    async def _renew_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                try:
                    await asyncio.to_thread(
                        self._coordinator.verify_lease,
                        self._kb_name,
                        self._operation_id,
                        owner=self._owner,
                    )
                except asyncio.CancelledError:
                    raise  # intentional cancellation propagates to the outer catch
                except KbLeaseError as exc:
                    self._fail_closed(exc)
                    return
                except Exception as exc:
                    # Any other renewal/ledger I/O failure is still a fail-closed
                    # lease-state loss — the renewer must never die silently and
                    # let the stale writer keep mutating under unknown ownership.
                    self._fail_closed(
                        KbLeaseStateError(
                            self._kb_name,
                            self._operation_id,
                            detail=(
                                f"lease renewal raised {type(exc).__name__}: "
                                f"{redact_secrets(str(exc))}"
                            ),
                        )
                    )
                    return
        except asyncio.CancelledError:
            pass

    def _fail_closed(self, loss: Exception) -> None:
        """Record a fail-closed lease-state loss and cancel guarded work."""
        if self._loss is None:
            self._loss = loss
        if self._guarded is not None:
            self._guarded.cancel()

    def has_lost(self) -> bool:
        return self._loss is not None

    def check(self) -> None:
        """Raise a recorded ownership loss before the next KB write step."""
        if self._loss is not None:
            raise self._loss

    async def run_guarded(self, coro: Any) -> Any:
        """Await ``coro`` while renewing; abort it when ownership is lost.

        If the heartbeat detects that another holder took over the lease, the
        running ``coro`` is cancelled and :class:`KbOwnershipLostError` is
        raised instead of silently continuing the write.
        """
        if self._loss is not None:
            raise self._loss
        if self._renewer is None or self._renewer.done():
            self.start()
        self._guarded = asyncio.create_task(coro)
        try:
            result = await self._guarded
        except asyncio.CancelledError:
            if self._loss is not None:
                raise self._loss
            raise
        finally:
            self._guarded = None
        if self._loss is not None:
            raise self._loss
        return result

    async def stop(self) -> None:
        """Cancel the renewer. Idempotent; safe to call from a finally block."""
        if self._renewer is not None:
            self._renewer.cancel()
            try:
                await self._renewer
            except asyncio.CancelledError:
                pass
            self._renewer = None


class KbWriteCoordinator:
    """Durable per-KB lease + operation ledger.

    Instances are cheap and stateless apart from their base directory; construct
    one per request/background task with the owning base directory.
    """

    def __init__(
        self,
        base_dir: str | Path,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        owner: str | None = None,
        now=None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.base_dir / LEDGER_FILENAME
        self.lease_seconds = int(lease_seconds)
        self.owner = owner or default_owner()
        self._now_fn = now or _now_utc

    # -- persistence ---------------------------------------------------------

    def _now(self) -> datetime:
        return self._now_fn()

    @contextmanager
    def _ledger_lock(self):
        """OS-level inter-process lock around one ledger read-modify-write.

        Uses ``fcntl.flock`` on Linux (the established repository pattern);
        ``msvcrt.locking`` on Windows. A dedicated ``.lock`` sibling file is
        used because the ledger itself is atomically *replaced* on save, which
        would invalidate a lock held on the old inode.
        """
        lock_path = self.ledger_path.with_name(self.ledger_path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = lock_path.open("a+", encoding="utf-8")
        try:
            if sys.platform == "win32":  # pragma: no cover - exercised on Windows
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _load(self) -> dict[str, KbWriteOperation]:
        """Read the ledger, failing closed when it exists but is unusable.

        A genuinely absent ledger is the valid empty initial state and returns
        ``{}``. An existing ledger that cannot be read or parsed, or whose shape
        is wrong, raises :class:`KbLedgerError` — it is never treated as empty
        (which would silently allow a second writer) and never overwritten.
        """
        if not self.ledger_path.exists():
            return {}
        try:
            payload = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise self._ledger_error(
                f"ledger could not be read or parsed ({type(exc).__name__}): {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise self._ledger_error(f"ledger root is {type(payload).__name__}, expected an object")
        operations = payload.get("operations")
        if not isinstance(operations, dict):
            raise self._ledger_error(
                f"ledger 'operations' is {type(operations).__name__}, expected an object"
            )
        out: dict[str, KbWriteOperation] = {}
        for kb_name, raw in operations.items():
            if not isinstance(raw, dict):
                raise self._ledger_error(
                    f"ledger entry for '{kb_name}' is {type(raw).__name__}, expected an object"
                )
            out[str(kb_name)] = KbWriteOperation.from_dict(raw)
        return out

    def _ledger_error(self, detail: str) -> KbLedgerError:
        """Build a sanitized, length-capped ledger error without raw content."""
        safe = redact_secrets(detail)
        if len(safe) > 300:
            safe = safe[:300] + "…"
        return KbLedgerError(self.ledger_path, safe)

    def _save(self, operations: dict[str, KbWriteOperation]) -> None:
        atomic_write_json(
            self.ledger_path,
            {
                "version": 1,
                "operations": {name: op.to_dict() for name, op in operations.items()},
            },
        )

    # -- public API ----------------------------------------------------------

    def current_operation(self, kb_name: str) -> KbWriteOperation | None:
        """The latest recorded operation for ``kb_name``, or ``None``."""
        return self._load().get(kb_name)

    def acquire(
        self,
        kb_name: str,
        operation_type: str,
        *,
        owner: str | None = None,
        request_id: str | None = None,
        subject_id: str | None = None,
        input_snapshot_hash: str | None = None,
        user_id: str | None = None,
    ) -> KbWriteOperation:
        """Start a new mutation, reconciling any expired lease first.

        Refuses (``KbBusyError``) while another operation holds a live lease or
        an unresolved ``reconcile_required`` operation owns the KB.

        The whole read-modify-write (including lease-expiry reconciliation) runs
        under the inter-process ledger lock, so two concurrent acquirers cannot
        both observe "no active lease" and both start a mutation. The lock is
        released before the caller performs the actual KB write.
        """
        if operation_type not in OPERATION_TYPES:
            raise ValueError(f"Unknown KB write operation type: {operation_type}")
        with self._ledger_lock():
            operations = self._load()
            now = self._now()
            owner = owner or self.owner
            current = operations.get(kb_name)
            reconciles_operation_id = None

            if current is not None:
                if current.status == "reconcile_required":
                    raise self._busy(current)
                if current.status in ACTIVE_STATUSES:
                    if not self._lease_expired(current, now):
                        raise self._busy(current)
                    resolved = self._reconcile(current, now=now, new_owner=owner)
                    if resolved.status == "reconcile_required":
                        operations[kb_name] = resolved
                        self._save(operations)
                        raise self._busy(resolved)
                    # Converged to a terminal state; record lineage on the new op.
                    reconciles_operation_id = current.id
                # terminal → the new op simply replaces it

            operation = self._new_operation(
                kb_name,
                operation_type,
                now=now,
                owner=owner,
                request_id=request_id,
                subject_id=subject_id,
                input_snapshot_hash=input_snapshot_hash,
                user_id=user_id,
                reconciles_operation_id=reconciles_operation_id,
            )
            operations[kb_name] = operation
            self._save(operations)
            return operation

    def complete(
        self,
        kb_name: str,
        operation_id: str,
        status: str,
        *,
        owner: str | None = None,
        error_code: str | None = None,
        error: str | None = None,
        index_task_id: str | None = None,
    ) -> KbWriteOperation | None:
        """Finish an operation as ``succeeded``/``failed``/``reconcile_required``.

        Returns the updated operation, or ``None`` when the operation is no
        longer the current one (already reconciled / taken over) — the caller
        must not clobber the new holder's state.
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"Not a terminal operation status: {status}")
        with self._ledger_lock():
            operations = self._load()
            current = operations.get(kb_name)
            owner = owner or self.owner
            now = self._now()
            if current is None or current.id != operation_id:
                return None
            if current.status in TERMINAL_STATUSES:
                return current  # idempotent
            if current.lease_owner is not None and current.lease_owner != owner:
                return None
            updated = current.terminal(
                status,
                now,
                error_code=error_code,
                sanitized_error=error,
                index_task_id=index_task_id,
            )
            operations[kb_name] = updated
            self._save(operations)
            return updated

    def resolve_manual(
        self,
        kb_name: str,
        operation_id: str,
        status: str,
        *,
        error_code: str | None = None,
        error: str | None = None,
        owner: str | None = None,
    ) -> KbWriteOperation | None:
        """Force-converge the exact interrupted write operation to a terminal state.

        Used by the knowledge-card publication endpoints' card-level reconcile,
        which has enough card-specific evidence (fixed raw file, content hash,
        index hash registry, KB metadata) to decide the outcome of an
        interrupted ``card_publish``/``card_retract`` operation that the
        filesystem-only :meth:`_reconcile` intentionally cannot (§7.9.2
        requirement 11/12).

        Conservative in three respects:

        * it only ever transitions the operation whose id exactly matches
          ``operation_id`` — if a newer holder already replaced it, ``None`` is
          returned and the caller must not clobber that newer state;
        * a *live* active operation (a lease that has not expired) requires the
          caller's ``owner`` to match the recorded ``lease_owner``; without a
          matching owner (or when ``owner`` is ``None``) it is left untouched so
          a card-level reconcile can never resolve another holder's in-flight
          operation;
        * an expired / ``reconcile_required`` operation is converged freely — a
          crash orphan or an explicit reconcile target.

        It is the caller's responsibility to only invoke this after an explicit
        user-initiated reconciliation has decided the state.
        """
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"Not a terminal operation status: {status}")
        with self._ledger_lock():
            operations = self._load()
            current = operations.get(kb_name)
            now = self._now()
            if current is None or current.id != operation_id:
                return None
            if current.status in TERMINAL_STATUSES and current.status != "reconcile_required":
                return current  # already terminal; do not rewrite history
            # A live active operation belongs to its lease holder; never resolve
            # it without proof of matching ownership.
            if (
                current.status in ACTIVE_STATUSES
                and not self._lease_expired(current, now)
                and (owner is None or current.lease_owner != owner)
            ):
                return None
            updated = current.terminal(
                status,
                now,
                error_code=error_code,
                sanitized_error=error,
            )
            operations[kb_name] = updated
            self._save(operations)
            return updated

    def renew(
        self,
        kb_name: str,
        operation_id: str,
        *,
        owner: str | None = None,
        lease_seconds: int | None = None,
    ) -> KbWriteOperation | None:
        """Extend the lease on a running operation the caller still owns.

        Returns ``None`` — i.e. reports ownership loss / invalid renewal — when
        the operation is no longer the current one, the owner no longer
        matches, *or the operation has already reached a terminal status*
        (including ``reconcile_required``). A terminal operation means the
        writer no longer holds a live lease, so a background renewer must not
        treat it as a success.
        """
        with self._ledger_lock():
            operations = self._load()
            current = operations.get(kb_name)
            owner = owner or self.owner
            now = self._now()
            if current is None or current.id != operation_id:
                return None
            if current.status not in ACTIVE_STATUSES:
                return None
            if current.lease_owner != owner:
                return None
            updated = current.renewed(
                owner, now + timedelta(seconds=lease_seconds or self.lease_seconds), now
            )
            operations[kb_name] = updated
            self._save(operations)
            return updated

    def verify_lease(self, kb_name: str, operation_id: str, *, owner: str | None = None) -> None:
        """Confirm the caller still owns a live lease on ``operation_id``.

        Called synchronously at every KB write checkpoint (before a metadata /
        status / config completion write). Raises
        :class:`KbOwnershipLostError` when the operation is no longer the
        current one (including a terminal / ``reconcile_required`` operation)
        and :class:`KbLeaseStateError` when the ledger cannot be read, so a
        stale writer never marks the KB or task successful after its lease was
        taken over or ownership became unknown.
        """
        try:
            renewed = self.renew(kb_name, operation_id, owner=owner or self.owner)
        except KbLeaseError:
            raise
        except Exception as exc:
            raise KbLeaseStateError(
                kb_name,
                operation_id,
                detail=(f"lease renewal failed ({type(exc).__name__}): {redact_secrets(str(exc))}"),
            ) from exc
        if renewed is None:
            raise KbOwnershipLostError(kb_name, operation_id)

    def is_lease_live(self, kb_name: str, operation_id: str) -> bool:
        """True when the current operation is active with an unexpired lease.

        Lets the card-level reconcile-publication refuse to force a decision
        while a genuinely live writer may still be mutating the KB (§7.9.2
        requirement 12). Uses the coordinator's own clock so injected test time
        is honoured.
        """
        with self._ledger_lock():
            current = self._load().get(kb_name)
            if current is None or current.id != operation_id:
                return False
            if current.status not in ACTIVE_STATUSES:
                return False
            return not self._lease_expired(current, self._now())

    def reconcile(self, kb_name: str, *, owner: str | None = None) -> KbWriteOperation | None:
        """Explicitly reconcile the latest operation for a KB.

        Used to converge a ``reconcile_required`` operation (or an expired one)
        to a terminal state. Returns the resolved operation, or ``None`` when
        there is nothing to reconcile or the live lease belongs to someone else.
        """
        with self._ledger_lock():
            operations = self._load()
            current = operations.get(kb_name)
            now = self._now()
            if current is None:
                return None
            if current.status in TERMINAL_STATUSES and current.status != "reconcile_required":
                return current
            if current.status == "reconcile_required" or self._lease_expired(current, now):
                resolved = self._reconcile(current, now=now, new_owner=owner or self.owner)
                operations[kb_name] = resolved
                self._save(operations)
                return resolved
            return current

    # -- internals -----------------------------------------------------------

    def _lease_expired(self, operation: KbWriteOperation, now: datetime) -> bool:
        expires = _parse_ts(operation.lease_expires_at)
        return expires is None or expires <= now

    def _busy(self, current: KbWriteOperation) -> KbBusyError:
        return KbBusyError(
            kb_name=current.kb_name,
            operation_type=current.operation_type,
            status=current.status,
            lease_owner=current.lease_owner,
            lease_expires_at=current.lease_expires_at,
        )

    def _new_operation(
        self,
        kb_name: str,
        operation_type: str,
        *,
        now: datetime,
        owner: str,
        request_id: str | None,
        subject_id: str | None,
        input_snapshot_hash: str | None,
        user_id: str | None,
        reconciles_operation_id: str | None,
    ) -> KbWriteOperation:
        created = _format_ts(now)
        return KbWriteOperation(
            id=uuid4().hex,
            kb_name=kb_name,
            user_id=user_id,
            operation_type=operation_type,
            subject_id=subject_id,
            request_id=request_id,
            status="running",
            lease_owner=owner,
            lease_expires_at=_format_ts(now + timedelta(seconds=self.lease_seconds)),
            input_snapshot_hash=input_snapshot_hash,
            created_at=created,
            started_at=created,
            updated_at=created,
            reconciles_operation_id=reconciles_operation_id,
        )

    def _reconcile(
        self, operation: KbWriteOperation, *, now: datetime, new_owner: str
    ) -> KbWriteOperation:
        """Take over an interrupted operation and converge it to a terminal state.

        Conservative: only mutates state it can verify (raw files, hash
        registry, index versions) and never deletes raw files.
        """
        del new_owner  # reconciliation is about on-disk state, not ownership
        kb_dir = self.base_dir / operation.kb_name

        if operation.operation_type == "upload":
            # A crashed upload may have staged files and recorded some hashes.
            # Prune stale hash records (raw file gone); preserve any raw file
            # still present — the next upload indexes it in place.
            self._prune_stale_hashes(operation.kb_name)
            return operation.terminal(
                "failed",
                now,
                error_code="interrupted",
                sanitized_error=(
                    "previous upload interrupted before completion; reconciled on take-over"
                ),
            )

        if operation.operation_type == "delete":
            if operation.subject_id is None:
                # Whole-KB delete: completed iff the KB directory is gone.
                if not kb_dir.exists():
                    return operation.terminal("succeeded", now)
                return operation.terminal(
                    "failed",
                    now,
                    error_code="interrupted",
                    sanitized_error=(
                        "previous delete interrupted before completion; reconciled on take-over"
                    ),
                )
            target = _safe_relpath_under(kb_dir / "raw", operation.subject_id)
            if target is None or not target.exists():
                # File already removed — converge the hash registry and accept.
                self._prune_stale_hashes(operation.kb_name)
                return operation.terminal("succeeded", now)
            return operation.terminal(
                "failed",
                now,
                error_code="interrupted",
                sanitized_error=(
                    "previous delete interrupted before completion; reconciled on take-over"
                ),
            )

        if operation.operation_type == "reindex":
            if operation.input_snapshot_hash and self._has_ready_version(
                kb_dir, operation.input_snapshot_hash
            ):
                return operation.terminal("succeeded", now)
            return operation.terminal(
                "failed",
                now,
                error_code="interrupted",
                sanitized_error=(
                    "previous reindex interrupted before completion; reconciled on take-over"
                ),
            )

        # card_publish / card_retract (future waves) cannot be auto-reconciled
        # from filesystem state alone; they require an explicit manual reconcile.
        return operation.terminal(
            "reconcile_required",
            now,
            error_code="manual_reconcile_required",
            sanitized_error=(
                f"{operation.operation_type} interrupted; manual reconciliation required"
            ),
        )

    def _has_ready_version(self, kb_dir: Path, signature_hash: str) -> bool:
        if not kb_dir.is_dir():
            return False
        try:
            from deeptutor.services.rag.index_versioning import list_kb_versions
        except Exception:  # pragma: no cover - dependency always importable
            return False
        try:
            return any(
                entry.get("signature") == signature_hash and entry.get("ready")
                for entry in list_kb_versions(kb_dir)
            )
        except Exception:
            return False

    def _prune_stale_hashes(self, kb_name: str) -> bool:
        """Drop ``file_hashes`` entries whose raw file is missing.

        Returns ``True`` when the registry changed. Never touches raw files.
        """
        kb_dir = self.base_dir / kb_name
        metadata_file = kb_dir / "metadata.json"
        raw_dir = kb_dir / "raw"
        if not metadata_file.exists() or not raw_dir.is_dir():
            return False
        try:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        except Exception:
            return False
        if not isinstance(metadata, dict):
            return False
        hashes = metadata.get("file_hashes")
        if not isinstance(hashes, dict) or not hashes:
            return False
        raw_resolved = raw_dir.resolve()
        stale: list[Any] = []
        for key, _value in hashes.items():
            if not isinstance(key, str) or not key:
                stale.append(key)
                continue
            try:
                target = (raw_dir / key).resolve()
                if not target.is_relative_to(raw_resolved) or not target.exists():
                    stale.append(key)
            except OSError:
                stale.append(key)
        if not stale:
            return False
        for key in stale:
            hashes.pop(key, None)
        atomic_write_json(metadata_file, metadata)
        return True


def heartbeat_interval_seconds(coordinator: KbWriteCoordinator) -> float:
    """A bounded renew cadence well inside the coordinator's lease window."""
    return max(1.0, min(coordinator.lease_seconds / 3.0, 300.0))


__all__ = [
    "ACTIVE_STATUSES",
    "DEFAULT_LEASE_SECONDS",
    "KbBusyError",
    "KbLedgerError",
    "KbLeaseError",
    "KbLeaseStateError",
    "KbOwnershipLostError",
    "KbWriteCoordinator",
    "KbWriteOperation",
    "LEDGER_FILENAME",
    "LeaseHeartbeat",
    "OPERATION_TYPES",
    "TERMINAL_STATUSES",
    "default_owner",
    "heartbeat_interval_seconds",
    "redact_secrets",
]
