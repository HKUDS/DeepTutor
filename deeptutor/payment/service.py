"""Order-creation entry point: plan resolution + gateway cashier + QR rendering.

This is the seam the API router calls.  It:

1. reads the active plan catalogue (``data/system/payment/plans.json``,
   maintained by the admin console / RIC-546) and resolves the requested
   plan into a snapshot the order will own;
2. builds the gateway cashier request for the chosen channel (WeChat Native
   scan-to-pay, WeChat H5 jump, or EPay redirect);
3. renders the scan payload as an inline QR SVG when the channel pays by
   scan-code;
4. persists the order via :mod:`deeptutor.payment.orders` and returns it.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

from deeptutor.multi_user.paths import SYSTEM_ROOT, ensure_system_dirs
from deeptutor.payment.gateways import (
    GATEWAY_EPAY,
    GATEWAY_WECHAT,
    GatewayError,
    active_gateway,
    epay_notify_body,
    format_price_fen,
    iso_after,
    wechat_h5_payload,
    wechat_native_payload,
)
from deeptutor.payment.orders import create_order, new_out_trade_no

logger = logging.getLogger(__name__)

PLANS_FILE_NAME = "plans.json"

DEFAULT_ORDER_EXPIRE_MINUTES = 30

#: Plan price/period keys the admin console writes and the learner UI reads.
_PLAN_EXPECTED_KEYS = ("id", "name", "price_fen", "duration_days")


class PaymentServiceError(ValueError):
    """Order creation failed with a stable machine-readable reason."""


class PlanNotFoundError(PaymentServiceError):
    """The requested plan does not exist or is not published."""


def _payment_root() -> Path:
    ensure_system_dirs()
    root = SYSTEM_ROOT / "payment"
    root.mkdir(parents=True, exist_ok=True)
    return root


def plans_path() -> Path:
    return _payment_root() / PLANS_FILE_NAME


def load_plans() -> list[dict[str, Any]]:
    """Return the published plan catalogue, sorted by price ascending."""
    path = plans_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read plans at %s: %s", path, exc)
        return []
    raw = payload.get("plans") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return []
    plans = [plan for plan in raw if isinstance(plan, dict) and plan.get("published", True)]
    plans.sort(key=lambda plan: int(plan.get("price_fen") or 0))
    return plans


def find_plan(plan_id: str) -> dict[str, Any]:
    if not plan_id:
        raise PlanNotFoundError("plan_id is required")
    for plan in load_plans():
        if str(plan.get("id") or "") == plan_id:
            return plan
    raise PlanNotFoundError(f"plan not found: {plan_id}")


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """The learner-facing plan shape (mirrors the web contract)."""
    price_fen = int(plan.get("price_fen") or 0)
    duration_days = int(plan.get("duration_days") or 0) or None
    return {
        "id": plan.get("id"),
        "name": plan.get("name"),
        "period": plan.get("period", "monthly"),
        "price_fen": price_fen,
        "price_display": format_price_fen(price_fen),
        "duration_days": duration_days,
        "perks": list(plan.get("perks") or []),
        "tag": plan.get("tag"),
        "recommended": bool(plan.get("recommended")),
    }


def public_plans() -> list[dict[str, Any]]:
    return [public_plan(plan) for plan in load_plans()]


def _make_qr_svg(payload: str) -> str:
    """Render a WeChat/EPay code URL as an inline QR SVG."""
    if not payload:
        return ""
    try:
        import qrcode
        import qrcode.image.svg

        image = qrcode.make(
            payload,
            image_factory=qrcode.image.svg.SvgPathImage,
            box_size=10,
            border=2,
        )
        buffer = io.BytesIO()
        image.save(buffer)
        return buffer.getvalue().decode("utf-8")
    except Exception:
        logger.debug("qrcode unavailable; returning raw code payload", exc_info=True)
        return ""


def _resolve_wechat_cashier(
    plan: dict[str, Any],
    out_trade_no: str,
    notify_url: str,
    cfg: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return ``(pay_url, qr_svg)`` for the active WeChat channel."""
    channel = str(cfg.get("channel") or "native").lower()
    description = f"{plan.get('name') or 'DeepTutor 商业版'}"
    total_fen = int(plan.get("price_fen") or 0)
    expires_at = iso_after(DEFAULT_ORDER_EXPIRE_MINUTES)
    if channel in ("native", "qr", "scan"):
        payload = wechat_native_payload(
            cfg,
            description=description,
            out_trade_no=out_trade_no,
            total_fen=total_fen,
            notify_url=notify_url,
            expires_at=expires_at,
        )
        return None, _make_qr_svg(json.dumps(payload))
    if channel in ("h5", "wap", "jsapi"):
        payload = wechat_h5_payload(
            cfg,
            description=description,
            out_trade_no=out_trade_no,
            total_fen=total_fen,
            notify_url=notify_url,
            expires_at=expires_at,
        )
        return json.dumps(payload), None
    raise GatewayError(f"unsupported wechat channel: {channel}")


def _resolve_epay_cashier(
    plan: dict[str, Any],
    out_trade_no: str,
    notify_url: str,
    return_url: str,
    cfg: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Return ``(pay_url, None)`` for the EPay channel (redirect flow)."""
    gateway = str(cfg.get("gateway_url") or "").rstrip("/")
    if not gateway:
        raise GatewayError("epay gateway_url is not configured")
    form = epay_notify_body(
        cfg,
        {
            "out_trade_no": out_trade_no,
            "notify_url": notify_url,
            "return_url": return_url,
            "name": plan.get("name") or "DeepTutor 商业版",
            "money": format_price_fen(int(plan.get("price_fen") or 0)).replace("¥", ""),
        },
    )
    query = "&".join(f"{k}={v}" for k, v in form.items())
    return f"{gateway}/submit.php?{query}", None


def create_payment_order(
    *,
    user_id: str,
    username: str,
    plan_id: str,
    gateway: str,
    notify_url: str,
    return_url: str | None = None,
) -> dict[str, Any]:
    """Resolve a plan + active gateway and create a persisted order.

    Returns the order's wire view (``qr_svg`` / ``pay_url`` included) so the
    learner can pay immediately.  Raises :class:`PaymentServiceError` for a
    missing plan/disabled gateway so the router translates it to a 4xx.

    ``notify_url`` / ``return_url`` are the deployment's own public URLs —
    caller-provided to keep the engine testable without network.

    The outgoing trade number is generated once before the cashier payload is
    built, so the QR/redirect the learner scans already embeds the definitive
    ``out_trade_no`` the callback will cite.
    """
    plan = find_plan(plan_id)
    cfg = active_gateway(gateway)
    notify_url = (notify_url or "").rstrip("/")
    return_url = (return_url or "").rstrip("/") or notify_url
    if not notify_url:
        raise PaymentServiceError("notify_url is required")
    if int(plan.get("price_fen") or 0) <= 0:
        raise PlanNotFoundError(f"plan {plan_id} has no valid price")

    out_trade_no = new_out_trade_no()

    # Prepare the cashier payload before persisting so a misconfigured
    # gateway fails fast without leaving an orphaned order.
    qr_svg: str | None = None
    pay_url: str | None = None
    if gateway == GATEWAY_WECHAT:
        pay_url, qr_svg = _resolve_wechat_cashier(plan, out_trade_no, notify_url, cfg)
    elif gateway == GATEWAY_EPAY:
        pay_url, _ = _resolve_epay_cashier(plan, out_trade_no, notify_url, return_url, cfg)
    else:
        raise GatewayError(f"unsupported gateway: {gateway}")

    order = create_order(
        user_id=user_id,
        username=username,
        plan=plan,
        gateway=gateway,
        out_trade_no=out_trade_no,
        qr_svg=qr_svg,
        pay_url=pay_url,
        expire_minutes=int(plan.get("expire_minutes") or DEFAULT_ORDER_EXPIRE_MINUTES),
    )
    return order


__all__ = [
    "PLANS_FILE_NAME",
    "PaymentServiceError",
    "PlanNotFoundError",
    "create_payment_order",
    "find_plan",
    "load_plans",
    "plans_path",
    "public_plan",
    "public_plans",
]
