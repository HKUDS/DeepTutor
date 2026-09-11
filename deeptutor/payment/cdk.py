"""Offline CDK (card-key / redemption code) batch generation and redemption.

This is the zero-fee channel of the Enterprise payment subsystem: an operator
generates a batch of single-use codes bound to a plan, hands them to a buyer
outside the platform (Taobao / Weidian / Xianyu), and a learner redeems one
code to have the plan's permissions bound to their account.

Persistence follows the multi-user layer's conventions — JSON files under
``<runtime-home>/data/system/payment``, written atomically with in-process
write locks so concurrent workers cannot double-redeem a code.

Data model
----------

``data/system/payment/cdk_store.json``
    The authoritative store, keyed by the codes' SHA-256 digest (never by the
    plain code — the code is the bearer credential and must not live in the
    main store):

    - ``batches``: batch_id -> batch record (plan id, count, issued/expire
      dates, creator).
    - ``codes``: digest -> code record (batch id, plan snapshot, expires_at,
      status, redeemed_by, redeemed_at, redeem_count, last_error).

``data/system/payment/cdk_batches/<batch_id>.json``
    One per-batch snapshot of the plain codes, written at generation time so
    an admin export (CSV/JSON) can reconstruct them.  This is the ONLY place a
    plain code is ever persisted, and it lives under the same admin-only
    ``data/system`` tree as every other deployment secret.  The snapshot also
    tracks export run markers for audit.

``data/system/payment/cdk_attempts.json``
    Per-user redemption attempt history (``user_id -> [{at, outcome}]``) used
    for the brute-force budget.  A 10-minute sliding window permits at most
    ``REDEEM_ATTEMPTS_PER_HOUR`` failed attempts per account.

Safety notes
------------

- The central store keeps digests only; a ``data/system`` backup cannot leak
  active codes unless it also carries the batch snapshots.
- Redemption is atomic in-process: the store is loaded, the code's status is
  checked and flipped inside a module-wide write lock, then persisted with a
  same-directory atomic rename.  Two concurrent requests for the same code
  both see the pre-image, but only the first to acquire the lock consumes it.
- Anti-abuse: an invalid / expired / already-used attempt is counted against
  the caller's window budget both because the code lookup failed and because
  the account may be probing for valid codes.  Attempt outcomes never reveal
  whether a code exists: ``invalid_code`` is returned for unknown, expired and
  used codes alike (the only distinction a legitimate user needs).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import logging
from pathlib import Path
import secrets
import string
import threading
import time
from typing import Any
from uuid import uuid4

from deeptutor.multi_user import paths as mu_paths
from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

#: The CDK tree lives under ``data/system/payment`` — the same deployment-state
#: root as grants/auth/audit.  Resolved dynamically through ``mu_paths`` so
#: tests that monkeypatch ``paths.SYSTEM_ROOT`` take effect without a module
#: reload (see the multi-user test suite).
CDK_STORE_NAME = "cdk_store.json"
CDK_BATCHES_DIR = "cdk_batches"
CDK_ATTEMPTS_NAME = "cdk_attempts.json"

#: A 10-minute sliding window bounds one account's brute-force budget.
REDEEM_WINDOW_SECONDS = 600
#: Number of failed attempts allowed per account inside any such window.
REDEEM_ATTEMPTS_PER_HOUR = 8

#: Code alphabet that reads unambiguously in handwriting/print (``0/O/1/I``
#: are excluded).
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_DEFAULT_CODE_LENGTH = 12

CODE_STATUS_UNUSED = "unused"
CODE_STATUS_REDEEMED = "redeemed"
CODE_STATUS_EXPIRED = "expired"


class CDKValidationError(ValueError):
    """A requested batch/code violates the store's invariants."""


class CDKNotFoundError(KeyError):
    """The named batch or code does not exist."""


class RedeemFailure(Exception):
    """A redemption attempt did not consume a code.

    ``reason`` is a stable machine-readable key; ``detail`` is a human-facing
    message safe to return to the caller.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


# ---------------------------------------------------------------------------
# Paths — resolved per call so tests that monkeypatch SYSTEM_ROOT are honored
# ---------------------------------------------------------------------------


def _payment_root() -> Path:
    mu_paths.ensure_system_dirs()
    root = mu_paths.SYSTEM_ROOT / "payment"
    root.mkdir(parents=True, exist_ok=True)
    return root


def cdk_store_path() -> Path:
    return _payment_root() / CDK_STORE_NAME


def cdk_batch_path(batch_id: str) -> Path:
    if not batch_id or any(
        ch not in string.ascii_letters + string.digits + "-_" for ch in batch_id
    ):
        raise CDKValidationError(f"Invalid batch id: {batch_id!r}")
    return _payment_root() / CDK_BATCHES_DIR / f"{batch_id}.json"


def _cdk_attempts_path() -> Path:
    return _payment_root() / CDK_ATTEMPTS_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Store load / save / attempts
# ---------------------------------------------------------------------------

#: Serialises read-modify-write of the store so a burst of concurrent redeem
#: requests cannot both observe a code as ``unused``.  Same threading model as
#: ``identity._USERS_WRITE_LOCK``: single-process FastAPI deployments are fully
#: covered; multi-worker deployments must rely on an external store.
_CDK_WRITE_LOCK = threading.Lock()
_ATTEMPTS_LOCK = threading.Lock()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "batches": {}, "codes": {}}


def _load_store() -> dict[str, Any]:
    path = cdk_store_path()
    if not path.exists():
        return _empty_store()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Unreadable CDK store at %s: %s", path, exc)
        raise CDKValidationError("CDK store is unreadable") from exc
    if not isinstance(loaded, dict):
        return _empty_store()
    loaded.setdefault("version", 1)
    loaded.setdefault("batches", {})
    loaded.setdefault("codes", {})
    return loaded


def _save_store(store: dict[str, Any]) -> None:
    atomic_write_json(cdk_store_path(), store)


def _load_attempts() -> dict[str, list[dict[str, Any]]]:
    path = _cdk_attempts_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception as exc:
        logger.error("Unreadable CDK attempts file at %s: %s", path, exc)
        return {}


def _save_attempts(attempts: dict[str, list[dict[str, Any]]]) -> None:
    atomic_write_json(_cdk_attempts_path(), attempts)


def _record_attempt(user_id: str, outcome: str) -> None:
    """Append one attempt entry and prune entries outside the window."""
    if not user_id:
        return
    with _ATTEMPTS_LOCK:
        attempts = _load_attempts()
        user_entries = [e for e in attempts.get(user_id, []) if _is_within_window(e)]
        user_entries.append({"at": time.time(), "outcome": outcome})
        attempts[user_id] = user_entries[-100:]  # hard cap memory
        _save_attempts(attempts)


def _is_within_window(entry: dict[str, Any]) -> bool:
    return float(entry.get("at") or 0) >= time.time() - REDEEM_WINDOW_SECONDS


def _active_attempt_count(user_id: str, now: float) -> int:
    attempts = _load_attempts().get(user_id, [])
    return sum(1 for e in attempts if float(e.get("at") or 0) >= now - REDEEM_WINDOW_SECONDS)


# ---------------------------------------------------------------------------
# Code plumbing
# ---------------------------------------------------------------------------


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_DEFAULT_CODE_LENGTH))


def _code_record(
    *,
    batch_id: str,
    plan: dict[str, Any] | None,
    expires_at: str | None,
) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "plan": plan,
        "expires_at": expires_at,
        "status": CODE_STATUS_UNUSED,
        "redeemed_by": None,
        "redeemed_at": None,
        "redeem_count": 0,
        "last_error": None,
    }


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _validate_plan_ref(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Plan payloads are opaque here: the pricing module (RIC-546) owns them.

    We only require a non-empty stable id so a redeemed code can point at the
    plan it grants.  Times and permission bundles are passed through untouched.
    """
    if plan is None:
        return {}
    if not isinstance(plan, dict):
        raise CDKValidationError("plan must be an object")
    plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
    if not plan_id:
        raise CDKValidationError("plan.id is required on every code")
    return json.loads(json.dumps(plan))


def generate_batch(
    *,
    plan: dict[str, Any] | None,
    count: int,
    expires_in_days: int | None = None,
    creator: str = "",
) -> dict[str, Any]:
    """Generate ``count`` single-use codes bound to ``plan``.

    Returns the batch record plus the raw codes, and persists a per-batch
    snapshot so a later admin export can reconstruct them.  The main store
    records only digests.
    """
    plan = _validate_plan_ref(plan)
    if count < 1:
        raise CDKValidationError("count must be >= 1")

    expires_at: str | None = None
    if expires_in_days is not None:
        if expires_in_days <= 0:
            raise CDKValidationError("expires_in_days must be positive")
        expires_at = (_now_dt() + timedelta(days=expires_in_days)).isoformat()

    batch_id = f"cb_{uuid4().hex[:12]}"
    codes: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    while len(codes) < count:
        candidate = _new_code()
        digest = _digest(candidate)
        if digest in seen:
            continue
        seen.add(digest)
        codes.append(candidate)
        records[digest] = _code_record(
            batch_id=batch_id,
            plan=plan or None,
            expires_at=expires_at,
        )

    batch: dict[str, Any] = {
        "id": batch_id,
        "plan": plan or None,
        "count": count,
        "expires_in_days": expires_in_days,
        "expires_at": expires_at,
        "created_by": creator or "",
        "created_at": _now_iso(),
        "redeemed_count": 0,
    }

    with _CDK_WRITE_LOCK:
        store = _load_store()
        store["batches"][batch_id] = batch
        for digest, record in records.items():
            store["codes"][digest] = record
        _save_store(store)

    # Persist the plain codes for later export.  Written after the store so a
    # crash between the two leaves digests (authoritative) ahead of codes.
    _write_batch_snapshot(batch_id, batch, codes)

    return {"batch_id": batch_id, "batch": batch, "codes": codes}


def _write_batch_snapshot(batch_id: str, batch: dict[str, Any], codes: list[str]) -> None:
    snapshot_path = cdk_batch_path(batch_id)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "batch_id": batch_id,
        "plan": batch.get("plan"),
        "created_at": batch.get("created_at"),
        "code_count": len(codes),
        "codes": codes,
        "_export_markers": [],
    }
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def list_batches(status: str | None = None) -> list[dict[str, Any]]:
    """List batches, newest first.  ``status`` may be ``active`` or ``all``."""
    store = _load_store()
    batches: list[dict[str, Any]] = []
    now = _now_dt()
    for batch in store["batches"].values():
        total = 0
        redeemed = 0
        expired = 0
        for rec in store["codes"].values():
            if rec["batch_id"] != batch["id"]:
                continue
            total += 1
            if rec["status"] == CODE_STATUS_REDEEMED:
                redeemed += 1
                continue
            expires_at = _parse_iso(rec.get("expires_at"))
            if rec["status"] == CODE_STATUS_EXPIRED or (
                expires_at is not None and expires_at <= now
            ):
                expired += 1
        out = dict(batch)
        out["total_codes"] = total
        out["redeemed_count"] = redeemed
        out["expired_count"] = expired
        out["active_codes"] = total - redeemed - expired
        if status == "active" and out["active_codes"] <= 0:
            continue
        batches.append(out)
    batches.sort(key=lambda b: str(b.get("created_at") or ""), reverse=True)
    return batches


def lookup_batch(batch_id: str) -> dict[str, Any]:
    store = _load_store()
    batch = store["batches"].get(batch_id)
    if batch is None:
        raise CDKNotFoundError(f"unknown batch: {batch_id}")
    return next(b for b in list_batches() if b["id"] == batch_id)


def list_codes_for_batch(batch_id: str, include_redeemed: bool = True) -> list[dict[str, Any]]:
    """Return the public (digest-keyed) records for a batch's codes.

    The raw codes are NOT returned here — they are only produced at
    generation/export time.
    """
    store = _load_store()
    if batch_id not in store["batches"]:
        raise CDKNotFoundError(f"unknown batch: {batch_id}")
    records = []
    for digest, rec in store["codes"].items():
        if rec["batch_id"] != batch_id:
            continue
        if not include_redeemed and rec["status"] == CODE_STATUS_REDEEMED:
            continue
        public = dict(rec)
        public["digest"] = digest
        records.append(public)
    records.sort(key=lambda r: r["digest"])
    return records


# ---------------------------------------------------------------------------
# Redemption
# ---------------------------------------------------------------------------


def _grant_for_plan(plan: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    """Translate a plan's permission bundle into a v2 grant payload."""
    from deeptutor.multi_user.grants import empty_grant, normalize_grant

    if not isinstance(plan, dict):
        return empty_grant(user_id)

    grant = empty_grant(user_id)
    models = plan.get("models")
    if not isinstance(models, dict):
        models = {}
    llm = models.get("llm")
    if isinstance(llm, list):
        grant["models"]["llm"] = [dict(m) for m in llm if isinstance(m, dict)]
    for key in ("knowledge_bases", "skills"):
        raw = plan.get(key)
        if isinstance(raw, list):
            grant[key] = [dict(item) for item in raw if isinstance(item, dict)]
    return normalize_grant(user_id, grant)


def _merge_grant(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge an overlay into a grant for the redeemed plan bundle."""
    merged = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if key == "models" and isinstance(value, dict) and isinstance(value.get("llm"), list):
            merged.setdefault("models", {}).setdefault("llm", [])
            merged["models"]["llm"] = merged["models"]["llm"] + value["llm"]
        elif key in {"knowledge_bases", "skills"} and isinstance(value, list):
            merged.setdefault(key, [])
            merged[key] = merged[key] + value
        else:
            merged[key] = value
    return merged


def _bind_plan_books(plan: dict[str, Any] | None, username: str) -> None:
    """Best-effort: bind the plan's shared books to the user's account."""
    if not isinstance(plan, dict):
        return
    raw_books = plan.get("books") or plan.get("book_ids")
    if not (isinstance(raw_books, list) and raw_books):
        return
    try:
        from deeptutor.multi_user.book_permission import (
            BookPermission,
            normalize_book_permission,
        )
        from deeptutor.multi_user.identity import get_user, set_book_permission

        record = get_user(username) or {}
        existing = normalize_book_permission(record.get("book_permission"))
        books = existing.books_dict()
        for book_id in raw_books:
            books[str(book_id)] = "read"
        set_book_permission(
            username,
            BookPermission(
                create=existing.create,
                default=existing.default,
                books=tuple(books.items()),
            ),
        )
    except Exception:
        logger.exception("Failed to bind plan books for redeemed CDK (user=%s)", username)


def redeem_cdk(
    *,
    code: str,
    user_id: str,
    username: str,
    additional_grant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically consume ``code`` and bind its plan's permissions to the user.

    Raises :class:`RedeemFailure` (a 4xx-class outcome) when the code cannot
    be consumed.  On success returns the redeemed descriptor plus the user's
    updated grant.

    Re-submitting an already-redeemed code by the same account is idempotent:
    it returns the current grant instead of failing, so client retries after a
    network hiccup never double-bind or surface as errors.
    """
    username = username or ""
    user_id = user_id or ""

    code = str(code or "").strip()
    if not code:
        raise RedeemFailure("empty_code", "卡密不能为空")
    digest = _digest(code)

    if _active_attempt_count(user_id, time.time()) >= REDEEM_ATTEMPTS_PER_HOUR:
        raise RedeemFailure(
            "rate_limited",
            f"尝试过于频繁，请 {REDEEM_WINDOW_SECONDS // 60} 分钟后再试",
        )

    # A redeem is a learner action that grants permissions to a real account.
    # Validate the target before consuming anything so a code is never lost to
    # a grant that could not be delivered (admin accounts and unknown ids are
    # refused by ``save_grant`` *after* we would have spent the code).
    from deeptutor.multi_user.grants import get_user_by_id

    user_record = get_user_by_id(user_id)
    if user_record is None:
        raise RedeemFailure("user_not_found", "账户不存在，无法绑定套餐权限")
    if str(user_record[1].get("role") or "user") == "admin":
        raise RedeemFailure("admin_not_allowed", "管理员账户无需兑换卡密")

    plan_reference: dict[str, Any] = {}
    with _CDK_WRITE_LOCK:
        store = _load_store()
        record = store["codes"].get(digest)
        if record is None:
            _record_attempt(user_id, "invalid_code")
            raise RedeemFailure("invalid_code", "卡密无效或不存在")

        expires_at = _parse_iso(record.get("expires_at"))
        if expires_at is not None and expires_at <= _now_dt():
            record["status"] = CODE_STATUS_EXPIRED
            record["last_error"] = "expired"
            _save_store(store)
            _record_attempt(user_id, "expired_code")
            raise RedeemFailure("expired_code", "卡密已过期")

        if record["status"] == CODE_STATUS_EXPIRED:
            _record_attempt(user_id, "expired_code")
            raise RedeemFailure("expired_code", "卡密已过期")

        # Idempotent re-submission by the same account.
        if record["status"] == CODE_STATUS_REDEEMED and record.get("redeemed_by") == user_id:
            from deeptutor.multi_user.grants import load_grant

            return {
                "code_digest": digest,
                "redeemed_at": record.get("redeemed_at"),
                "plan": record.get("plan") or {},
                "grant": load_grant(user_id),
                "idempotent": True,
            }

        if record["status"] == CODE_STATUS_REDEEMED:
            _record_attempt(user_id, "already_redeemed")
            raise RedeemFailure("already_redeemed", "卡密已被使用")

        # ---- consume ----------
        now_iso = _now_iso()
        record["status"] = CODE_STATUS_REDEEMED
        record["redeemed_by"] = user_id
        record["redeemed_at"] = now_iso
        record["redeem_count"] = int(record.get("redeem_count") or 0) + 1
        record["last_error"] = None
        batch = store["batches"].get(record["batch_id"]) or {}
        plan_reference = record.get("plan") or batch.get("plan") or {}
        batch["redeemed_count"] = int(batch.get("redeemed_count") or 0) + 1
        _save_store(store)

    # ---- fulfil outside the lock; persistence is already committed -------
    try:
        grant = _grant_for_plan(plan_reference, user_id)
        if isinstance(additional_grant, dict) and additional_grant:
            grant = _merge_grant(grant, additional_grant)
        from deeptutor.multi_user.grants import save_grant

        saved = save_grant(user_id, grant)
    except Exception as exc:
        logger.exception("Failed to bind plan grant for redeemed CDK (user=%s)", user_id)
        # The code is already consumed; surface the grant failure loudly.
        raise RedeemFailure("binding_failed", "卡密已核销但权限绑定失败，请联系管理员") from exc

    _bind_plan_books(plan_reference, username)

    return {
        "code_digest": digest,
        "redeemed_at": now_iso,
        "plan": plan_reference or {},
        "grant": saved,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_batch_codes(batch_id: str, fmt: str = "json") -> str:
    """Return the plain codes of ``batch_id`` as ``json`` or ``csv``.

    Requires knowing a batch id only an admin can list; the codes come from
    the per-batch snapshot written at generation time.
    """
    snapshot_path = cdk_batch_path(batch_id)
    if not snapshot_path.exists():
        raise CDKNotFoundError(f"unknown batch: {batch_id}")

    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CDKValidationError("batch snapshot unreadable") from exc
    codes = snapshot.get("codes")
    if not isinstance(codes, list):
        raise CDKValidationError("batch snapshot malformed")

    _annotate_export(batch_id, fmt, count=len(codes))
    store = _load_store()
    if fmt == "csv":
        buffer = io.StringIO()
        buffer.write("code,status,expires_at\n")
        for code in codes:
            rec = store["codes"].get(_digest(code), {})
            buffer.write(f"{code},{rec.get('status', 'unknown')},{rec.get('expires_at', '')}\n")
        return buffer.getvalue()
    return json.dumps(
        {"batch_id": batch_id, "count": len(codes), "codes": codes},
        ensure_ascii=False,
        indent=2,
    )


def _annotate_export(batch_id: str, fmt: str, *, count: int, note: str = "exported") -> None:
    """Append an export-run marker to the batch snapshot for audit."""
    try:
        snapshot_path = cdk_batch_path(batch_id)
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict):
            return
        snapshot.setdefault("_export_markers", []).append(
            {"time": _now_iso(), "fmt": fmt, "note": note, "count": count}
        )
        snapshot_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        logger.debug("Could not annotate batch export marker for %s", batch_id)


def describe_code_digest(code_digest: str) -> dict[str, Any]:
    """Return a code's public metadata by its digest."""
    store = _load_store()
    record = store["codes"].get(code_digest)
    if record is None:
        raise CDKNotFoundError("code not found")
    return json.loads(json.dumps(record))


__all__ = [
    "CDKNotFoundError",
    "CDKValidationError",
    "CODE_STATUS_EXPIRED",
    "CODE_STATUS_REDEEMED",
    "CODE_STATUS_UNUSED",
    "REDEEM_ATTEMPTS_PER_HOUR",
    "REDEEM_WINDOW_SECONDS",
    "RedeemFailure",
    "cdk_batch_path",
    "cdk_store_path",
    "describe_code_digest",
    "export_batch_codes",
    "generate_batch",
    "list_batches",
    "list_codes_for_batch",
    "lookup_batch",
    "redeem_cdk",
]
