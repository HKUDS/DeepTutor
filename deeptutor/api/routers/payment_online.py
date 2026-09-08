"""Online payment cashier + gateway-notify routers for DeepTutor Enterprise.

Learner-facing:
    POST /api/payment/orders/create
        Resolve a plan + active gateway, create the order and return the scan
        payload (``qr_svg`` for WeChat native, ``pay_url`` for H5/EPay).
    GET  /api/payment/orders/{order_id}/status
        Status-polling endpoint the QR modal watches.

Gateway-facing (public — neither JWT nor session auth):
    POST /api/payment/notify/{gateway}
        Async payment callbacks from WeChat Pay / EPay.  These endpoints must
        be reachable without credentials, so they are a separate router with
        no ``Depends(require_*)``; each handler verifies the gateway's own
        signature before touching any order.
    GET  /api/payment/notify/return
        BPay/user browser redirect after payment (only flips a displayed page).

The CDK router (``payment.py``) continues to serve ``/api/payment/cdk/*``;
this router owns the online order + callback surface.  They share the same
``/api/payment`` prefix, so the tags keep docs grouped under ``payment``.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_auth
from deeptutor.multi_user.context import get_current_user
from deeptutor.payment.gateways import (
    GATEWAY_EPAY,
    GATEWAY_WECHAT,
    GatewayError,
    list_active_gateways,
)
from deeptutor.payment.notify import NotifyError, handle_epay_notify, handle_wechat_notify
from deeptutor.payment.orders import (
    OrderNotFoundError,
    order_status_view,
)
from deeptutor.payment.service import (
    PaymentServiceError,
    PlanNotFoundError,
    create_payment_order,
    public_plans,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class CreateOrderRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=64)
    gateway: Literal["wechat", "epay"] = "wechat"


class OrderStatusResponse(BaseModel):
    order_id: str
    status: str
    granted: bool = False
    message: str | None = None


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PlanNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, (PaymentServiceError, GatewayError, NotifyError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, OrderNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Learner-facing
# ---------------------------------------------------------------------------


@router.get("/plans", tags=["payment"])
async def get_plans(_: Any = Depends(require_auth)) -> dict[str, Any]:
    """Public plan catalogue + the active gateways the learner may pay via."""
    return {
        "plans": public_plans(),
        "gateways": list_active_gateways(),
        "cdk_enabled": True,
        "currency": "CNY",
    }


@router.post("/orders/create", status_code=201, tags=["payment"])
async def create_order_endpoint(
    payload: CreateOrderRequest,
    request: Request,
    _: Any = Depends(require_auth),
) -> dict[str, Any]:
    """Create an order for ``plan_id`` on ``gateway`` and return the scan payload.

    The notification URL is derived from the incoming request's public base so
    the gateway can call it back (deployment fronting land on a configured
    public base in production).
    """
    user = get_current_user()
    notify_url = _public_base(request).rstrip("/") + "/api/payment/notify/wechat"
    if payload.gateway == GATEWAY_EPAY:
        notify_url = _public_base(request).rstrip("/") + "/api/payment/notify/epay"
    return_url = _public_base(request).rstrip("/") + "/api/payment/notify/return"
    try:
        order = create_payment_order(
            user_id=user.id,
            username=user.username,
            plan_id=payload.plan_id,
            gateway=payload.gateway,
            notify_url=notify_url,
            return_url=return_url,
        )
    except Exception as exc:
        raise _http_error(exc) from exc
    return order


@router.get("/orders/{order_id}/status", response_model=OrderStatusResponse, tags=["payment"])
async def order_status(
    order_id: str,
    _: Any = Depends(require_auth),
) -> OrderStatusResponse:
    """Status-polling view for the QR modal (idempotent read)."""
    try:
        view = order_status_view(order_id)
    except OrderNotFoundError as exc:
        raise _http_error(exc) from exc
    return OrderStatusResponse(**view)


@router.get("/orders", tags=["payment"])
async def my_orders(
    _: Any = Depends(require_auth),
) -> list[dict[str, Any]]:
    """The caller's recent orders (newest first) for the order-audit view."""
    user = get_current_user()
    from deeptutor.payment.orders import list_orders

    return list_orders(user_id=user.id, limit=200)


# ---------------------------------------------------------------------------
# Gateway-facing (public)
# ---------------------------------------------------------------------------


@router.post("/notify/{gateway}", tags=["payment-notify"])
async def payment_notify(
    gateway: Literal["wechat", "epay"],
    request: Request,
) -> Response:
    """Async gateway callback endpoint.

    Public by design — the gateway cannot carry a session JWT.  Each handler
    verifies the gateway's signature before fulfilling; a failed verification
    returns the gateway's failure body so it retries.

    Returns a literal (non-JSON) body matching each gateway's contract: EPay
    expects ``"success"``/``"fail"`` plain text; WeChat expects a JSON object
    with ``code`` SUCCESS/FAIL.
    """
    if gateway == GATEWAY_WECHAT:
        raw_body = await request.body()
        headers = {key.lower(): value for key, value in request.headers.items()}
        result = handle_wechat_notify(headers, raw_body)
        return Response(
            content=__import__("json").dumps(result),
            media_type="application/json",
        )
    if gateway == GATEWAY_EPAY:
        form = dict(await request.form())
        body = handle_epay_notify(form)
        return Response(content=body, media_type="text/plain")
    raise HTTPException(status_code=404, detail="unknown gateway")


@router.get("/notify/return", tags=["payment-notify"])
async def payment_return() -> HTMLResponse:
    """Browser redirect target after a gateway payment:
    show a page that fires the success flow and closes.
    """
    html = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>支付结果</title></head><body>
<script>
  try {
    if (window.opener) { window.opener.postMessage({type:"dt-payment-return"}, "*"); }
  } catch (e) {}
  window.close();
  document.title = "支付完成，可关闭此窗口";
  document.write('<h2 style="font-family:sans-serif;text-align:center;margin-top:60px">'
    + '支付已完成，此页面可关闭。</h2>');
</script>
</body></html>"""
    return HTMLResponse(content=html)


def _public_base(request: Request) -> str:
    """Derive the deployment's public base URL for callback URLs.

    Honors ``X-Forwarded-Proto``/``Host`` (reverse-proxy) and falls back to
    the request URL.  Production deployments set the site URL explicitly; this
    keeps local-dev and Docker default routes functional.
    """
    try:
        forwarded_proto = request.headers.get("x-forwarded-proto", "")
        base = request.base_url
        if forwarded_proto:
            return f"{forwarded_proto}://{base.netloc}"
        return str(base)
    except Exception:
        return "http://localhost:3001"


__all__ = ["router"]
