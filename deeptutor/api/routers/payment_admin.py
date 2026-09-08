"""Admin commerce-management API for DeepTutor Enterprise (RIC-546).

Admin-facing configuration and ledger surface for the payment subsystem:

    GET    /api/payment/admin/gateways           read gateway config (redacted)
    POST   /api/payment/admin/gateways           replace gateway config
    PUT    /api/payment/admin/gateways           replace gateway config (alias)

    GET    /api/payment/admin/plans              list plans (all, incl. drafts)
    POST   /api/payment/admin/plans              create a plan
    GET    /api/payment/admin/plans/{plan_id}    read one plan
    PUT    /api/payment/admin/plans/{plan_id}    update (upsert) a plan
    DELETE /api/payment/admin/plans/{plan_id}    remove a plan from the catalogue

    GET    /api/payment/admin/orders             ledger listing (filters below)
    GET    /api/payment/admin/orders/{order_id}  one order, full view
    POST   /api/payment/admin/orders/{order_id}/refund   mark refunded

Every endpoint carries ``Depends(require_admin)`` — configuration is
deployment-global state and the order ledger exposes every learner's records,
so this router is deliberately admin-only.  The learner-facing cashier and
CDK surfaces live in ``payment_online.py`` / ``payment.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin
from deeptutor.payment.admin import (
    PlanValidationError,
    admin_get_order,
    admin_list_orders,
    admin_refund_order,
    delete_plan,
    find_plan,
    load_plans,
    public_gateways,
    save_gateways,
    upsert_plan,
)

router = APIRouter(dependencies=[Depends(require_admin)])


class PlanPayload(BaseModel):
    """One plan document wrapped under ``plan`` (the admin-console contract)."""

    plan: dict[str, Any]


class RefundPayload(BaseModel):
    reason: str = Field(default="", max_length=200)


# ---------------------------------------------------------------------------
# Gateway configuration
# ---------------------------------------------------------------------------


@router.get("/admin/gateways", tags=["payment-admin"])
async def get_gateway_config() -> dict[str, Any]:
    """Read the stored gateway configuration, credentials redacted."""
    return {"gateways": public_gateways()}


def _save_gateway_config(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        saved = save_gateways(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    from deeptutor.payment.admin import redact_gateways

    return {"gateways": redact_gateways(saved)}


@router.post("/admin/gateways", tags=["payment-admin"])
async def save_gateway_config(payload: dict[str, Any]) -> dict[str, Any]:
    """Atomically replace the gateway configuration.

    Secret-shaped keys submitted as ``GATEWAY_SECRET_MASK`` keep their stored
    value, so a load/edit/save round trip never loses credentials.  Unknown
    channel names are rejected (fail-closed) so a typo cannot silently disable
    a payment path.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="gateway config must be an object")
    return _save_gateway_config(payload)


@router.put("/admin/gateways", tags=["payment-admin"])
async def put_gateway_config(payload: dict[str, Any]) -> dict[str, Any]:
    """PUT alias of POST /admin/gateways (idempotent full replace)."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="gateway config must be an object")
    return _save_gateway_config(payload)


# ---------------------------------------------------------------------------
# Pricing plans
# ---------------------------------------------------------------------------


@router.get("/admin/plans", tags=["payment-admin"])
async def get_plans() -> dict[str, Any]:
    """List the full plan catalogue, drafts and unpublished included."""
    return {"plans": load_plans()}


@router.post("/admin/plans", status_code=201, tags=["payment-admin"])
async def create_plan(payload: PlanPayload) -> dict[str, Any]:
    """Create a plan.  The id is caller-supplied in the body."""
    try:
        plan = upsert_plan(payload.plan)
    except (PlanValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"plan": plan}


@router.get("/admin/plans/{plan_id}", tags=["payment-admin"])
async def get_plan(plan_id: str) -> dict[str, Any]:
    plan = find_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")
    return {"plan": plan}


@router.put("/admin/plans/{plan_id}", tags=["payment-admin"])
async def update_plan(plan_id: str, payload: PlanPayload) -> dict[str, Any]:
    """Upsert a plan by id (id in the path wins over a body mismatch)."""
    proposed = dict(payload.plan)
    proposed["id"] = proposed.get("id") or plan_id
    if proposed.get("id") != plan_id:
        raise HTTPException(status_code=400, detail="plan id in body does not match path")
    try:
        plan = upsert_plan(proposed)
    except (PlanValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"plan": plan}


@router.delete("/admin/plans/{plan_id}", tags=["payment-admin"])
async def remove_plan(plan_id: str) -> dict[str, Any]:
    if not delete_plan(plan_id):
        raise HTTPException(status_code=404, detail=f"plan not found: {plan_id}")
    return {"deleted": plan_id}


# ---------------------------------------------------------------------------
# Order ledger
# ---------------------------------------------------------------------------


@router.get("/admin/orders", tags=["payment-admin"])
async def get_orders(
    user_id: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    gateway: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Ledger listing with optional filters (user, status, gateway)."""
    rows = admin_list_orders(
        user_id=user_id,
        status=status,
        gateway=gateway,
        limit=limit,
        offset=offset,
    )
    return {"orders": rows, "count": len(rows)}


@router.get("/admin/orders/{order_id}", tags=["payment-admin"])
async def get_order_detail(order_id: str) -> dict[str, Any]:
    try:
        order = admin_get_order(order_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"order": order}


@router.post("/admin/orders/{order_id}/refund", tags=["payment-admin"])
async def refund_order(order_id: str, payload: RefundPayload) -> dict[str, Any]:
    """Mark an order refunded on the ledger (idempotent on terminal status)."""
    try:
        order = admin_refund_order(order_id, reason=payload.reason)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"order": order}
