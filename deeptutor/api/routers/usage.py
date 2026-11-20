"""Spend, for the person who spent it and for the operator.

Two audiences again, and for the same reason as the studio: a student must be
able to see their own usage and must never see anyone else's, while an operator
needs the aggregate. The split is the mount policy, so it is enforced by the
router table rather than by remembering to check an ``is_admin`` flag inside a
handler.

``router`` — mounted at ``/api/usage`` with the ``learning`` policy.
``admin_router`` — mounted at ``/api/usage/admin`` with the ``admin`` policy.

A student's endpoints take no user id at all. The scope helper resolves the
caller from the session, which means there is no parameter to tamper with --
the same rule the studio follows, applied here from the start rather than
retrofitted.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from deeptutor.db.connection import DatabaseError, open_database
from deeptutor.services import usage as ledger
from deeptutor.services.scope import ScopeError, as_http, caller_id

router = APIRouter()
admin_router = APIRouter()

_Days = Annotated[int, Query(ge=1, le=3650)]
_Limit = Annotated[int, Query(ge=1, le=500)]


def _database():
    try:
        return open_database()
    except DatabaseError as exc:  # pragma: no cover - configuration failure
        raise HTTPException(
            status_code=503, detail={"rule": "no_database", "message": str(exc)}
        ) from exc


def _caller(supplied: str | None) -> str:
    """The account whose spend is being read.

    With authentication on, ``supplied`` is discarded and the session decides --
    the same rule as the studio, because a user id that can be changed in the
    query string is a way to read another account's spending. With it off, this
    is the documented single-operator dev mode and the id is all there is.
    """
    try:
        resolved = caller_id(supplied)
    except ScopeError as exc:
        raise as_http(exc) from exc
    if not resolved:
        raise HTTPException(
            status_code=401,
            detail={
                "rule": "no_identity",
                "message": "no account to report on; authenticate or supply user_id "
                "in the single-operator dev configuration",
            },
        )
    return resolved


# ---------------------------------------------------------------------------
# The student's own spend
# ---------------------------------------------------------------------------


@router.get("")
async def my_usage(days: _Days | None = None, user_id: str | None = None) -> dict[str, Any]:
    """What I have spent, by surface.

    Takes no user id: the caller is the account. A parameter here would be a
    way to read someone else's spending, and no amount of validation makes an
    absent parameter safer than one that looks safe.
    """
    database = _database()
    return ledger.summary(database, _caller(user_id), days=days)


@router.get("/recent")
async def my_recent(
    limit: _Limit = 50, user_id: str | None = None
) -> dict[str, Any]:
    database = _database()
    caller = _caller(user_id)
    return {"rows": [row.as_dict() for row in ledger.recent(database, caller, limit=limit)]}


@router.get("/reconciliation")
async def my_reconciliation(user_id: str | None = None) -> dict[str, Any]:
    """Does my balance match my history?

    Exposed to the user, not only to an operator: a ledger the user cannot
    check is a ledger they have no reason to trust.
    """
    database = _database()
    return ledger.assert_consistent(database, _caller(user_id))


# ---------------------------------------------------------------------------
# Operator surface
# ---------------------------------------------------------------------------


@admin_router.get("")
async def all_usage(days: _Days = 30) -> dict[str, Any]:
    """Spend across every account. Mounted with the admin policy."""
    return ledger.operator_totals(_database(), days=days)
