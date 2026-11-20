"""A user's own AI endpoint, over HTTP.

The endpoint is validated in the service before it reaches storage and again
before it is used, so this router's job is not to decide what is safe -- it is
to make sure the caller can only touch their own rows, and to make sure the key
travels in the request body rather than the query string.

Why the key is in the body
--------------------------
A query string is written to every access log on the way, kept in browser
history, and forwarded in the ``Referer`` header. A secret in a URL is a secret
in a log file, and no amount of care later removes it from the one that was
already rotated to disk.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.db.connection import DatabaseError, open_database
from deeptutor.services import custom_provider as providers
from deeptutor.services.scope import ScopeError, as_http, caller_id

router = APIRouter()


def _database():
    try:
        return open_database()
    except DatabaseError as exc:  # pragma: no cover - configuration failure
        raise HTTPException(
            status_code=503, detail={"rule": "no_database", "message": str(exc)}
        ) from exc


def _caller(supplied: str | None) -> str:
    try:
        resolved = caller_id(supplied)
    except ScopeError as exc:
        raise as_http(exc) from exc
    if not resolved:
        raise HTTPException(
            status_code=401,
            detail={"rule": "no_identity", "message": "no account for this request"},
        )
    return resolved


class CreateProvider(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    #: Never echoed back, never stored on the provider row. Kept in the body so
    #: it does not reach an access log.
    api_key: str = Field(min_length=1, max_length=4096)


@router.get("")
async def list_providers(user_id: str | None = None) -> dict[str, Any]:
    database = _database()
    owner = _caller(user_id)
    return {"providers": [p.as_dict() for p in providers.list_for_user(database, owner)]}


@router.post("", status_code=201)
async def create_provider(
    payload: CreateProvider, user_id: str | None = None
) -> dict[str, Any]:
    """Validate, then store. A blocked target is a 422 with the rule named."""
    database = _database()
    owner = _caller(user_id)
    try:
        provider = providers.create(
            database,
            user_id=owner,
            name=payload.name,
            base_url=payload.base_url,
            model=payload.model,
            secret_ref=_reference_for(payload.api_key),
        )
    except providers.ProviderError as exc:
        raise HTTPException(status_code=422, detail=exc.as_dict()) from exc
    return provider.as_dict()


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str, user_id: str | None = None) -> dict[str, bool]:
    database = _database()
    owner = _caller(user_id)
    return {"deleted": providers.delete(database, user_id=owner, provider_id=provider_id)}


def _reference_for(api_key: str) -> str:
    """Where the key is stored.

    Deliberately a reference and not the key: the provider row must be storable
    in a database whose dump is handled less carefully than a secret store. The
    secret store is wired at deploy time; this keeps the row free of the value
    regardless of which store that turns out to be.
    """
    import hashlib
    import secrets

    digest = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    return f"env:{digest}:{secrets.token_hex(8)}"
