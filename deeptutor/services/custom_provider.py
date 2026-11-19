"""A user-supplied AI endpoint, vetted before it is stored or used.

The risk this contains
----------------------
"Bring your own provider" means a student can type a URL and the server will
make an authenticated request to it. That is an SSRF primitive with a UI, and
the interesting targets are the ones nobody types on purpose: the metadata
service at 169.254.169.254 that hands out instance credentials, an internal
admin endpoint at 10.x, or `localhost:11434` where a model server may be
listening without auth.

So the order is: validate the destination, and only then store it. A URL that
is stored without being checked is a URL that will be used later by a code path
that assumes it was checked.

Secrets
-------
The key is never stored in the row and never returned. It goes to the encrypted
secret store, the row keeps a reference, and :meth:`PublicProvider.as_dict`
exists so that "show me my provider" cannot accidentally serialise the secret —
an object with no field for it cannot leak it.

Actual versus estimated cost
----------------------------
A custom provider returns no price. :meth:`PublicProvider` therefore records
`cost_basis = "actual"` only when the provider reported usage, and
`"estimated"` otherwise, so a report can say which numbers are measurements.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid

from deeptutor.db.connection import Database
from deeptutor.services import net_guard


class ProviderError(ValueError):
    """A provider configuration that must not be accepted."""

    def __init__(self, rule: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message
        self.extra = extra

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "message": self.message, **self.extra}


@dataclass(frozen=True)
class PublicProvider:
    """A provider as it is safe to show: no secret, no secret reference.

    Deliberately has no field for the key. A class that cannot hold a secret is
    a stronger guarantee than a serialiser that omits one, because the omission
    survives refactoring and the empty field does not.
    """

    id: str
    user_id: str
    name: str
    base_url: str
    model: str
    cost_basis: str
    verified_at: str | None
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "cost_basis": self.cost_basis,
            "verified_at": self.verified_at,
            "created_at": self.created_at,
            "has_key": True,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_public(row: dict[str, Any]) -> PublicProvider:
    return PublicProvider(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        name=str(row["name"]),
        base_url=str(row["base_url"]),
        model=str(row["model"]),
        cost_basis=str(row["cost_basis"]),
        verified_at=row["verified_at"],
        created_at=str(row["created_at"]),
    )


def create(
    db: Database,
    *,
    user_id: str,
    name: str,
    base_url: str,
    model: str,
    secret_ref: str,
    allow_hosts: frozenset[str] | None = None,
    seal: Any = None,
) -> PublicProvider:
    """Validate, then store. Never the other way round.

    ``seal`` is the secret store's ``put`` callable. The key itself is handed to
    it and never touches this module's arguments beyond this call -- so it
    cannot appear in an exception message, a log line or a row.
    """
    if not str(name or "").strip():
        raise ProviderError("missing_name", "a provider needs a name")

    try:
        resolution = net_guard.check_url(base_url, allow_hosts=allow_hosts)
    except net_guard.BlockedTarget as exc:
        raise ProviderError("blocked_target", exc.message, check=exc.as_dict()) from exc

    if not str(model or "").strip():
        raise ProviderError("missing_model", "a provider needs a model id")

    provider_id = f"cp_{uuid.uuid4().hex}"
    created = _now()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO custom_providers (id, user_id, name, base_url, model, "
            "secret_ref, cost_basis, verified_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'estimated', NULL, ?)",
            (
                provider_id,
                user_id,
                str(name).strip(),
                resolution.url,
                str(model).strip(),
                secret_ref,
                created,
            ),
        )
    if seal is not None:
        seal(provider_id, secret_ref)
    return PublicProvider(
        id=provider_id,
        user_id=user_id,
        name=str(name).strip(),
        base_url=resolution.url,
        model=str(model).strip(),
        cost_basis="estimated",
        verified_at=None,
        created_at=created,
    )


def list_for_user(db: Database, user_id: str) -> list[PublicProvider]:
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT * FROM custom_providers WHERE user_id = ? ORDER BY created_at",
                (user_id,),
            )
        )
    return [_row_to_public(row) for row in rows]


def get(db: Database, user_id: str, provider_id: str) -> PublicProvider | None:
    """Scoped by user: an id from another account must not be readable."""
    with db.read() as conn:
        row = conn.query_one(
            "SELECT * FROM custom_providers WHERE id = ? AND user_id = ?",
            (provider_id, user_id),
        )
    return _row_to_public(row) if row else None


def verify(
    db: Database,
    *,
    user_id: str,
    provider_id: str,
    responded: bool,
    reported_usage: bool,
    allow_hosts: frozenset[str] | None = None,
) -> PublicProvider:
    """Record a probe's outcome, re-checking the address at use time.

    The URL was checked when it was stored; it is checked again here because
    between those two moments DNS can change. A stored-then-trusted URL is an
    SSRF with a delay on it.

    ``reported_usage`` decides ``cost_basis``: a provider that reports tokens
    gives an actual figure, one that does not gives an estimate, and a report
    that calls both "cost" without saying which is a report that cannot be
    audited.
    """
    row = get(db, user_id, provider_id)
    if row is None:
        raise ProviderError("not_found", "no such provider for this account")

    try:
        net_guard.check_url(row.base_url, allow_hosts=allow_hosts)
    except net_guard.BlockedTarget as exc:
        raise ProviderError(
            "blocked_at_use", f"{exc.message} (the address changed since it was saved)",
            check=exc.as_dict(),
        ) from exc

    basis = "actual" if (responded and reported_usage) else "estimated"
    verified = _now() if responded else None
    with db.transaction() as conn:
        conn.execute(
            "UPDATE custom_providers SET cost_basis = ?, verified_at = ? WHERE id = ?",
            (basis, verified, provider_id),
        )
    updated = get(db, user_id, provider_id)
    if updated is None:  # pragma: no cover - deleted concurrently
        raise ProviderError("not_found", "the provider disappeared during verification")
    return updated


def delete(db: Database, *, user_id: str, provider_id: str) -> bool:
    with db.transaction() as conn:
        return (
            conn.execute(
                "DELETE FROM custom_providers WHERE id = ? AND user_id = ?",
                (provider_id, user_id),
            )
            == 1
        )


__all__ = [
    "ProviderError",
    "PublicProvider",
    "create",
    "delete",
    "get",
    "list_for_user",
    "verify",
]
