"""Online order store and fulfillment state machine.

Orders are the online counterpart of CDK redemption: a learner picks a plan
and a gateway, the engine creates an order and returns the scan-to-pay
payload, and the gateway's async notify flips the order through
``pending -> paid -> granted`` (``-> completed``) while provisioning the
plan's entitlements exactly once.

Persistence follows the commerce subsystem's file-store convention under
``data/system/payment``:

``data/system/payment/orders.json``
    The authoritative order store, keyed by ``order_id``:

    - ``order_id``: internal id (``po_<hex>``), stable across statuses.
    - ``out_trade_no``: the merchant-facing trade number sent to the gateway
      (``DT<ts><rand>``), the callback's idempotency key.
    - ``user_id`` / ``username``: who bought it.
    - ``plan``: the full plan snapshot at purchase time (price, duration,
      permission bundle), so fulfillment never depends on a later-edited plan.
    - ``gateway``: ``wechat`` or ``epay``.
    - ``amount_fen``, ``currency``, ``status``, ``expires_at``, timestamps.

Status machine
--------------

    ``pending``  order created, not yet paid (or already expired).
    ``paid``     gateway callback verified payment; provisioning not started.
    ``granted``  plan entitlements provisioned (grant + book permission).
    ``completed`` terminal alias for granted (kept for future e.g. invoice).
    ``expired``  no payment before ``expires_at`` (or backend timeout).
    ``refunded`` admin/gateway marked refunded; entitlements may remain.
    ``failed``   terminal failure (signature fail is usually just dropped,
                 so the gateway retries — see the notify handler).

Transitions are idempotent: a duplicate callback for an already-paid/granted
order is a no-op, and ``fulfill_order`` only provisions when moving from
``paid`` to ``granted`` under the write lock, so concurrent duplicate notifies
cannot double-provision.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
import secrets
import string
import threading
import time
from typing import Any
from uuid import uuid4

from deeptutor.multi_user.paths import SYSTEM_ROOT, ensure_system_dirs
from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

ORDER_ROOT = SYSTEM_ROOT / "payment"
ORDERS_FILE_NAME = "orders.json"

ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PAID = "paid"
ORDER_STATUS_GRANTED = "granted"
ORDER_STATUS_COMPLETED = "completed"
ORDER_STATUS_EXPIRED = "expired"
ORDER_STATUS_REFUNDED = "refunded"
ORDER_STATUS_FAILED = "failed"

ORDER_STATUSES = frozenset(
    {
        ORDER_STATUS_PENDING,
        ORDER_STATUS_PAID,
        ORDER_STATUS_GRANTED,
        ORDER_STATUS_COMPLETED,
        ORDER_STATUS_EXPIRED,
        ORDER_STATUS_REFUNDED,
        ORDER_STATUS_FAILED,
    }
)

TERMINAL_STATUSES = frozenset(
    {
        ORDER_STATUS_GRANTED,
        ORDER_STATUS_COMPLETED,
        ORDER_STATUS_EXPIRED,
        ORDER_STATUS_REFUNDED,
        ORDER_STATUS_FAILED,
    }
)

#: Transitions allowed by :func:`transition_order` (in either direction an
#: idempotent same-status no-op is always permitted).
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ORDER_STATUS_PENDING: {
        ORDER_STATUS_PAID,
        ORDER_STATUS_EXPIRED,
        ORDER_STATUS_REFUNDED,
        ORDER_STATUS_FAILED,
    },
    ORDER_STATUS_PAID: {ORDER_STATUS_GRANTED, ORDER_STATUS_REFUNDED, ORDER_STATUS_FAILED},
    ORDER_STATUS_GRANTED: {ORDER_STATUS_COMPLETED, ORDER_STATUS_REFUNDED},
    ORDER_STATUS_COMPLETED: {ORDER_STATUS_REFUNDED},
    ORDER_STATUS_EXPIRED: set(),
    ORDER_STATUS_REFUNDED: set(),
    ORDER_STATUS_FAILED: set(),
}

#: Keep the store keyed by order id and provide a small lookup index by
#: out_trade_no to make callback routing O(1).
_CREATE_INDEX = "out_trade_no"

_ORDERS_WRITE_LOCK = threading.Lock()

DEFAULT_ORDER_EXPIRE_MINUTES = 30


class OrderError(ValueError):
    """An order operation failed with a stable machine-readable reason."""


class OrderNotFoundError(OrderError):
    """The named order does not exist."""


# ---------------------------------------------------------------------------
# Paths (resolved per call so tests can monkeypatch SYSTEM_ROOT)
# ---------------------------------------------------------------------------


def _orders_root() -> Path:
    ensure_system_dirs()
    root = SYSTEM_ROOT / "payment"
    root.mkdir(parents=True, exist_ok=True)
    return root


def orders_path() -> Path:
    return _orders_root() / ORDERS_FILE_NAME


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


def TRANSITION_EXTRA_REFUND(reason: str = "") -> dict[str, Any]:
    """Extra fields for an admin-driven ``pending -> refunded`` transition.

    Timestamps a refund and records a stable, non-secret reason so the ledger
    keeps an audit trail.  Deliberately not part of the learner-facing
    ``_public_order`` projection (refund reason is admin bookkeeping, not
    something the status-polling QR modal needs).
    """
    return {
        "refunded_at": _now_iso(),
        "refund_reason": str(reason or "")[:200],
        "refunded_by": "admin",
    }


def _new_order_id() -> str:
    return f"po_{uuid4().hex}"


def new_out_trade_no() -> str:
    stamp = int(time.time() * 1000)
    return f"DT{stamp}{secrets.choice(string.ascii_uppercase)}{uuid4().hex[:8].upper()}"


def _empty_store() -> dict[str, Any]:
    return {"orders": {}}


def _load_store() -> dict[str, Any]:
    path = orders_path()
    if not path.exists():
        return _empty_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("orders"), dict):
            return payload
    except Exception as exc:
        logger.warning("Failed to read orders store at %s: %s", path, exc)
    return _empty_store()


def _save_store(store: dict[str, Any]) -> None:
    atomic_write_json(orders_path(), store)


def _public_order(order: dict[str, Any]) -> dict[str, Any]:
    """Wire-safe order view (no internal bookkeeping)."""
    return {
        "order_id": order.get("order_id"),
        "order_no": order.get("out_trade_no"),
        "amount_fen": order.get("amount_fen"),
        "currency": order.get("currency", "CNY"),
        "gateway": order.get("gateway"),
        "status": order.get("status"),
        "plan_id": (order.get("plan") or {}).get("id"),
        "plan_name": (order.get("plan") or {}).get("name"),
        "expires_at": order.get("expires_at"),
        "created_at": order.get("created_at"),
        "paid_at": order.get("paid_at"),
        "granted_at": order.get("granted_at"),
        "qr_svg": order.get("qr_svg"),
        "pay_url": order.get("pay_url"),
    }


def normalize_order(order: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(order, dict):
        return None
    status = str(order.get("status") or ORDER_STATUS_PENDING)
    if status not in ORDER_STATUSES:
        status = ORDER_STATUS_PENDING
    order = dict(order)
    order["status"] = status
    order["order_id"] = str(order.get("order_id") or "")
    order["out_trade_no"] = str(order.get("out_trade_no") or "")
    return order


def get_order(order_id: str) -> dict[str, Any] | None:
    store = _load_store()
    order = store["orders"].get(str(order_id or ""))
    return normalize_order(order)


def get_order_by_trade_no(out_trade_no: str) -> dict[str, Any] | None:
    store = _load_store()
    index = store.get(_CREATE_INDEX) or {}
    order_id = index.get(str(out_trade_no or ""))
    if not order_id:
        return None
    order = store["orders"].get(order_id)
    return normalize_order(order)


def list_orders(
    *,
    user_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    store = _load_store()
    rows = list(store["orders"].values())
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    out: list[dict[str, Any]] = []
    for row in rows:
        if user_id is not None and str(row.get("user_id") or "") != user_id:
            continue
        if status is not None and str(row.get("status") or "") != status:
            continue
        out.append(_public_order(row))
        if len(out) >= max(1, limit):
            break
    return out


def list_order_records(*, limit: int = 10_000) -> list[dict[str, Any]]:
    """Full store rows (not the learner-facing projection) for admin/ledger.

    Exposes every field the store persists — including the plan snapshot and
    refund bookkeeping — for the admin order-listing surface.  ``limit``
    bounds the row scan; callers apply their own pagination after filtering.
    """
    store = _load_store()
    rows = list(store["orders"].values())
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return [normalize_order(row) for row in rows[: max(1, limit)]]


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_order(
    *,
    user_id: str,
    username: str,
    plan: dict[str, Any],
    gateway: str,
    out_trade_no: str | None = None,
    qr_svg: str | None = None,
    pay_url: str | None = None,
    expire_minutes: int = DEFAULT_ORDER_EXPIRE_MINUTES,
) -> dict[str, Any]:
    """Persist a new order and return its wire view.

    The caller has already resolved the plan and gateway (validated price and
    permissions) and prepared the scan payload (``qr_svg`` or ``pay_url``).
    ``out_trade_no`` is normally left None (the store generates one); pass a
    caller-generated value when the cashier payload must embed it — for
    example a prepaid random token whose QR was rendered before the order id
    existed.
    """
    if not user_id or not plan or not gateway:
        raise OrderError("user_id, plan and gateway are required")
    plan = json.loads(json.dumps(plan))  # snapshot — never reference a mutable plan
    order_id = _new_order_id()
    out_trade_no = out_trade_no or new_out_trade_no()
    expires_at = (_now_dt() + timedelta(minutes=max(1, expire_minutes))).isoformat()
    now = _now_iso()
    order: dict[str, Any] = {
        "order_id": order_id,
        "out_trade_no": out_trade_no,
        "user_id": user_id,
        "username": username,
        "plan": plan,
        "gateway": gateway,
        "amount_fen": int(plan.get("price_fen") or 0),
        "currency": str(plan.get("currency") or "CNY"),
        "status": ORDER_STATUS_PENDING,
        "expires_at": expires_at,
        "created_at": now,
        "paid_at": None,
        "granted_at": None,
        "notify_count": 0,
        "last_notify_at": None,
        "last_error": None,
        "qr_svg": qr_svg,
        "pay_url": pay_url,
    }
    with _ORDERS_WRITE_LOCK:
        store = _load_store()
        store.setdefault(_CREATE_INDEX, {})
        store[_CREATE_INDEX][out_trade_no] = order_id
        store["orders"][order_id] = order
        _save_store(store)
    logger.info(
        "payment order %s created gateway=%s amount=%s", order_id, gateway, order["amount_fen"]
    )
    return _public_order(order)


def expire_stale_orders(now: datetime | None = None) -> int:
    """Flip overdue pending orders to ``expired``; returns count expired."""
    now = now or _now_dt()
    store = _load_store()
    changed = 0
    with _ORDERS_WRITE_LOCK:
        for order in store["orders"].values():
            if order.get("status") != ORDER_STATUS_PENDING:
                continue
            try:
                expires_at = datetime.fromisoformat(str(order.get("expires_at") or ""))
            except ValueError:
                expires_at = None
            if expires_at is not None and expires_at <= now:
                order["status"] = ORDER_STATUS_EXPIRED
                order["last_error"] = "expired"
                changed += 1
        if changed:
            _save_store(store)
    return changed


# ---------------------------------------------------------------------------
# Transition + fulfillment
# ---------------------------------------------------------------------------


def transition_order(
    order_id: str,
    new_status: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply a status transition under the write lock (idempotent no-op on same)."""
    if new_status not in ORDER_STATUSES:
        raise OrderError(f"unknown order status: {new_status}")
    with _ORDERS_WRITE_LOCK:
        store = _load_store()
        order = store["orders"].get(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)
        current = str(order.get("status") or ORDER_STATUS_PENDING)
        if current == new_status:
            if extra:
                order.update(extra)
                _save_store(store)
            return normalize_order(order)
        allowed = _ALLOWED_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise OrderError(f"invalid transition {current} -> {new_status}")
        order["status"] = new_status
        if extra:
            order.update(extra)
        _save_store(store)
        logger.info("payment order %s %s -> %s", order_id, current, new_status)
        return normalize_order(order)


def record_notify(order_id: str, *, ok: bool, detail: str = "") -> None:
    """Append a notify-delivery bookkeeping row (never raises)."""
    try:
        with _ORDERS_WRITE_LOCK:
            store = _load_store()
            order = store["orders"].get(order_id)
            if order is None:
                return
            order["notify_count"] = int(order.get("notify_count") or 0) + 1
            order["last_notify_at"] = _now_iso()
            order["last_error"] = None if ok else (detail or "notify_failed")
            _save_store(store)
    except Exception:
        logger.exception("Failed to record notify for order %s", order_id)


def fulfill_order(
    order_id: str,
    *,
    user_id: str,
    username: str,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    """Provision a paid order's entitlements exactly once.

    Expected to be called after a verified gateway callback.  If the order is
    already ``granted``/``completed`` it is a no-op (idempotent); if it is not
    yet ``paid`` the order is advanced to ``paid`` first, then fulfilled.  The
    grant/books are provisioned outside the store lock because they have their
    own locking, but the status flip to ``granted`` happens under the lock so
    concurrent duplicate callbacks cannot double-provision.

    Returns the persisted order view.
    """
    from deeptutor.payment.provisioning import provision_plan

    with _ORDERS_WRITE_LOCK:
        store = _load_store()
        order = store["orders"].get(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)
        current = str(order.get("status") or ORDER_STATUS_PENDING)
        if current in (ORDER_STATUS_GRANTED, ORDER_STATUS_COMPLETED):
            return normalize_order(order)
        if current not in (ORDER_STATUS_PAID, ORDER_STATUS_PENDING):
            raise OrderError(f"cannot fulfill order in status {current}")
        # Claim the transition under the lock; provisioning happens below.
        order["status"] = ORDER_STATUS_PAID if current == ORDER_STATUS_PENDING else current
        order.setdefault("paid_at", order.get("paid_at") or _now_iso())
        _save_store(store)

    provisioned = provision_plan(
        plan=plan,
        user_id=user_id,
        username=username,
    )

    with _ORDERS_WRITE_LOCK:
        store = _load_store()
        order = store["orders"].get(order_id)
        if order is None:
            raise OrderNotFoundError(order_id)
        if str(order.get("status") or "") in (ORDER_STATUS_GRANTED, ORDER_STATUS_COMPLETED):
            return normalize_order(order)
        order["status"] = ORDER_STATUS_GRANTED
        order["granted_at"] = _now_iso()
        order["last_error"] = None
        _save_store(store)
    logger.info("payment order %s fulfilled for user %s", order_id, user_id)
    return normalize_order(order)


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def order_status_view(order_id: str) -> dict[str, Any]:
    """The status-polling view the learner UI reads."""
    order = get_order(order_id)
    if order is None:
        raise OrderNotFoundError(order_id)
    status = order.get("status")
    granted = status in (ORDER_STATUS_GRANTED, ORDER_STATUS_COMPLETED)
    view: dict[str, Any] = {
        "order_id": order_id,
        "status": status,
        "granted": granted,
    }
    if status in TERMINAL_STATUSES and not granted:
        view["message"] = order.get("last_error") or status
    return view


__all__ = [
    "DEFAULT_ORDER_EXPIRE_MINUTES",
    "ORDER_STATUS_COMPLETED",
    "ORDER_STATUS_EXPIRED",
    "ORDER_STATUS_FAILED",
    "ORDER_STATUS_GRANTED",
    "ORDER_STATUS_PAID",
    "ORDER_STATUS_PENDING",
    "ORDER_STATUS_REFUNDED",
    "ORDER_STATUSES",
    "TERMINAL_STATUSES",
    "TRANSITION_EXTRA_REFUND",
    "OrderError",
    "OrderNotFoundError",
    "create_order",
    "expire_stale_orders",
    "fulfill_order",
    "get_order",
    "get_order_by_trade_no",
    "list_order_records",
    "list_orders",
    "new_out_trade_no",
    "normalize_order",
    "order_status_view",
    "orders_path",
    "record_notify",
    "transition_order",
]
