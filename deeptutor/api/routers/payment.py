"""Commerce APIs for DeepTutor Enterprise — CDK (offline redemption codes).

Admin-facing:
    GET   /api/payment/cdk/batches
    GET   /api/payment/cdk/batches/{batch_id}
    GET   /api/payment/cdk/batches/{batch_id}/codes
    POST  /api/payment/cdk/batches             (generate)
    GET   /api/payment/cdk/batches/{batch_id}/export?fmt=json|csv

Learner-facing:
    POST  /api/payment/cdk/redeem              (redeem a code)

Admin endpoints use ``Depends(require_admin)`` (the same dependency already
used across ``multi_user`` and other admin-gated routers); the redeem endpoint
uses ``Depends(require_auth)`` so any authenticated learner can redeem a code.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from deeptutor.api.routers.auth import require_admin, require_auth
from deeptutor.multi_user.context import get_current_user
from deeptutor.payment.cdk import (
    CDKNotFoundError,
    CDKValidationError,
    RedeemFailure,
    export_batch_codes,
    generate_batch,
    list_batches,
    list_codes_for_batch,
    lookup_batch,
    redeem_cdk,
)

router = APIRouter()


class GenerateBatchRequest(BaseModel):
    plan: dict[str, Any] | None = Field(default=None)
    count: int = Field(ge=1, le=10_000, description="Number of single-use codes to generate")
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class RedeemRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64, description="The CDK to redeem")


class RedeemResponse(BaseModel):
    code_digest: str
    redeemed_at: str | None = None
    idempotent: bool = False
    plan: dict[str, Any] = Field(default_factory=dict)
    grant: dict[str, Any] = Field(default_factory=dict)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RedeemFailure):
        return HTTPException(status_code=400, detail={"code": exc.reason, "message": exc.detail})
    if isinstance(exc, CDKValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, CDKNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail="CDK operation failed")


@router.get("/cdk/batches", tags=["payment-cdk"])
async def get_cdk_batches(
    _: Any = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List generated batches with code/redemption/expiry counts."""
    return list_batches()


@router.get("/cdk/batches/{batch_id}", tags=["payment-cdk"])
async def get_cdk_batch(
    batch_id: str,
    _: Any = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return lookup_batch(batch_id)
    except CDKNotFoundError as exc:
        raise _http_error(exc) from exc


@router.get("/cdk/batches/{batch_id}/codes", tags=["payment-cdk"])
async def get_cdk_batch_codes(
    batch_id: str,
    include_redeemed: bool = Query(default=True),
    _: Any = Depends(require_admin),
) -> list[dict[str, Any]]:
    try:
        return list_codes_for_batch(batch_id, include_redeemed=include_redeemed)
    except CDKNotFoundError as exc:
        raise _http_error(exc) from exc


@router.post("/cdk/batches", status_code=201, tags=["payment-cdk"])
async def create_cdk_batch(
    payload: GenerateBatchRequest,
    _: Any = Depends(require_admin),
) -> dict[str, Any]:
    """Generate a batch of single-use CDK codes bound to ``plan``.

    Returns the batch descriptor plus the raw codes (once only); subsequent
    reads through the list/export endpoints reconstruct them from the batch
    snapshot.
    """
    user = get_current_user()
    try:
        result = generate_batch(
            plan=payload.plan,
            count=payload.count,
            expires_in_days=payload.expires_in_days,
            creator=user.username,
        )
    except CDKValidationError as exc:
        raise _http_error(exc) from exc
    return result


@router.get("/cdk/batches/{batch_id}/export", tags=["payment-cdk"])
async def export_cdk_batch(
    batch_id: str,
    fmt: Literal["json", "csv"] = Query(default="json"),
    _: Any = Depends(require_admin),
) -> Response:
    """Export a batch's plain codes as JSON or CSV for offline distribution."""
    try:
        text = export_batch_codes(batch_id, fmt=fmt)
    except (CDKNotFoundError, CDKValidationError) as exc:
        raise _http_error(exc) from exc
    if fmt == "csv":
        return Response(
            content=text,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="cdk_{batch_id}.csv"'},
        )
    return Response(
        content=text,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="cdk_{batch_id}.json"'},
    )


@router.post("/cdk/redeem", response_model=RedeemResponse, tags=["payment-cdk"])
async def redeem_cdk_code(
    payload: RedeemRequest,
    _: Any = Depends(require_auth),
) -> RedeemResponse:
    """Redeem a single-use CDK and bind its plan's permissions to the caller.

    Anti-abuse: a sliding 10-minute attempt budget bounds brute-force
    guessing, and invalid / already-used attempts never reveal whether a code
    exists.  Re-submitting an already-redeemed code by the same account is
    idempotent.
    """
    user = get_current_user()
    try:
        result = redeem_cdk(
            code=payload.code,
            user_id=user.id,
            username=user.username,
        )
    except RedeemFailure as exc:
        raise _http_error(exc) from exc
    return RedeemResponse(
        code_digest=result["code_digest"],
        redeemed_at=result.get("redeemed_at"),
        idempotent=bool(result.get("idempotent")),
        plan=result.get("plan") or {},
        grant=result.get("grant") or {},
    )


__all__ = ["router"]
