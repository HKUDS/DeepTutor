"""Gateway async-notify handling: verify, then fulfill exactly once.

Both gateways push payment results asynchronously; this module is the seam
between the HTTP notify endpoints and :mod:`deeptutor.payment.orders`.

Workflow
--------

1. **Verify** the callback cryptographically (WeChat APIv3 platform-cert
   signature + AEAD decrypt of the ``resource`` envelope; EPay MD5 over the
   sorted form params).  A failed verification returns the gateway's failure
   body so it will retry, and never touches an order.
2. **Route** the callback's trade number to the persisted order.
3. **Reconcile amount** — the callback amount must match the order's
   ``amount_fen`` or the payment is treated as a failure (a partial / over /
   cross-order payment must never grant entitlements).
4. **Fulfill** — :func:`fulfill_order` advances the order to ``paid`` then
   ``granted`` and provisions the plan's grant + book permissions exactly
   once under the order lock.

Every handler is idempotent for the gateway's retry semantics: a duplicate
callback for an already-granted order re-verifies and returns success without
double-provisioning.
"""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.payment.gateways import (
    GATEWAY_EPAY,
    GATEWAY_WECHAT,
    GatewayError,
    SignatureVerificationError,
    active_gateway,
    decrypt_wechat_notify_body,
    verify_epay_signature,
)
from deeptutor.payment.orders import (
    OrderNotFoundError,
    fulfill_order,
    get_order_by_trade_no,
    record_notify,
)

logger = logging.getLogger(__name__)


class NotifyError(ValueError):
    """A callback could not be accepted (4xx-class for the gateway)."""


def _resolve_order_for_trade(trade_no: str) -> dict[str, Any]:
    order = get_order_by_trade_no(trade_no)
    if order is None:
        raise NotifyError(f"unknown trade no: {trade_no}")
    return order


def _reconcile_amount(order: dict[str, Any], paid_fen: int) -> None:
    expected = int(order.get("amount_fen") or 0)
    if expected <= 0:
        raise NotifyError("order has no amount; refusing to grant")
    if int(paid_fen) != expected:
        logger.warning(
            "payment amount mismatch order=%s expected=%s got=%s",
            order.get("order_id"),
            expected,
            paid_fen,
        )
        raise NotifyError(f"amount mismatch: expected {expected}, got {paid_fen}")


def _handle_paid_order(order: dict[str, Any]) -> dict[str, Any]:
    """Advance a verified paid order to ``granted`` and provision.

    Idempotent: if the order is already granted/completed this is a no-op.
    """
    user_id = str(order.get("user_id") or "")
    username = str(order.get("username") or "")
    plan = order.get("plan") or {}
    if not user_id:
        raise NotifyError("order has no user_id")
    try:
        return fulfill_order(
            order["order_id"],
            user_id=user_id,
            username=username,
            plan=plan,
        )
    except OrderNotFoundError as exc:
        raise NotifyError(str(exc)) from exc


# ---------------------------------------------------------------------------
# WeChat Pay APIv3
# ---------------------------------------------------------------------------


def handle_wechat_notify(headers: dict[str, str], raw_body: bytes) -> dict[str, Any]:
    """Verify and fulfil a WeChat Pay APIv3 notify.

    Returns the body WeChat Pay expects (``{"code": "SUCCESS"}`` on success,
    ``{"code": "FAIL", "message": ...}`` on a retryable failure).  The WeChat
    gateway will retry a FAIL until we answer SUCCESS.
    """
    from deeptutor.payment.gateways import (
        _verify_wechat_signature,
        wechat_notify_result,
    )

    try:
        cfg = active_gateway(GATEWAY_WECHAT)
        _verify_wechat_signature(cfg, headers, raw_body)
        envelope = _load_wechat_body(raw_body)
        resource = envelope.get("resource") or {}
        payload = decrypt_wechat_notify_body(cfg, resource)
        trade_no = str(payload.get("out_trade_no") or "")
        trade_state = str(payload.get("trade_state") or "")
        if not trade_no:
            raise NotifyError("wechat notify missing out_trade_no")
        order = _resolve_order_for_trade(trade_no)
        if trade_state not in ("SUCCESS", "REFUND"):
            # Non-success callback — WeChat may later retry with SUCCESS.
            record_notify(order["order_id"], ok=True, detail=f"trade_state={trade_state}")
            return wechat_notify_result(ok=True, message="acknowledged")
        amount = payload.get("amount") or {}
        paid_fen = int(amount.get("total") or 0)
        _reconcile_amount(order, paid_fen)
        _handle_paid_order(order)
        record_notify(order["order_id"], ok=True, detail="wechat SUCCESS")
        return wechat_notify_result(ok=True)
    except (NotifyError, GatewayError, SignatureVerificationError) as exc:
        logger.warning("wechat notify rejected: %s", exc)
        return wechat_notify_result(ok=False, message=str(exc))
    except Exception as exc:
        logger.exception("wechat notify crashed")
        return wechat_notify_result(ok=False, message="internal error")


def _load_wechat_body(raw_body: bytes) -> dict[str, Any]:
    import json

    try:
        envelope = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise NotifyError("wechat notify body is not valid JSON") from exc
    if not isinstance(envelope, dict):
        raise NotifyError("wechat notify body is not an object")
    return envelope


# ---------------------------------------------------------------------------
# EPay (易支付)
# ---------------------------------------------------------------------------


def handle_epay_notify(form: dict[str, Any]) -> str:
    """Verify and fulfil an EPay form POST.

    Returns the literal body EPay expects: ``"success"`` on acceptance,
    ``"fail"`` on a retryable failure.  EPay keeps re-posting until it sees
    ``"success"``.
    """
    try:
        cfg = active_gateway(GATEWAY_EPAY)
        verify_epay_signature(cfg, form)
        trade_no = str(form.get("out_trade_no") or "")
        trade_status = str(form.get("trade_status") or "")
        if not trade_no:
            raise NotifyError("epay notify missing out_trade_no")
        order = _resolve_order_for_trade(trade_no)
        if trade_status not in ("TRADE_SUCCESS", "TRADE_FINISHED", "SUCCESS"):
            record_notify(order["order_id"], ok=True, detail=f"trade_status={trade_status}")
            return "success"
        paid_fen = _epay_fen(form)
        _reconcile_amount(order, paid_fen)
        _handle_paid_order(order)
        record_notify(order["order_id"], ok=True, detail="epay TRADE_SUCCESS")
        return "success"
    except (NotifyError, GatewayError, SignatureVerificationError) as exc:
        logger.warning("epay notify rejected: %s", exc)
        return "fail"
    except Exception as exc:
        logger.exception("epay notify crashed")
        return "fail"


def _epay_fen(form: dict[str, Any]) -> int:
    """Parse EPay's money amount (yuan string, e.g. ``"29.90"``) into fen."""
    raw = str(form.get("money") or "").strip()
    try:
        return int(round(float(raw) * 100))
    except (TypeError, ValueError) as exc:
        raise NotifyError(f"epay money unparseable: {raw!r}") from exc


__all__ = [
    "NotifyError",
    "handle_epay_notify",
    "handle_wechat_notify",
]
