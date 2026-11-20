"""Storage backend selection for the identity layer.

``deeptutor.multi_user.identity`` owns the *semantics* of identity: canonicali-
sation, role rules, the bootstrap admin merge, the write lock. It should not
own the question "where do the bytes live", because that question now has two
answers and will have more.

This module answers it. :func:`active_store` returns the file store (the default
and the only option without ``DEEPTUTOR_DATABASE_URL``) or the Postgres
repository, behind one protocol:

.. code-block:: python

    store = active_store()
    users = store.load()             # {username: record}
    store.save(username, record)
    store.patch(username, {"disabled": 1})

The protocol is deliberately tiny and *dict-shaped* so the existing call-sites
in ``identity.py`` keep working unchanged. That matters: identity.py has ~30
functions and 9 test files pinning its behaviour, and rewriting them all to a
new interface would be a far larger change than moving the storage.

Failure policy
--------------
If the database is configured but unreachable, the store raises rather than
silently falling back to JSON. A silent fallback would split the user list
between two stores — the exact failure mode that makes "I can't log in" bugs
unreproducible.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from deeptutor.db.config import get_database_settings
from deeptutor.db.connection import Database, DatabaseUnavailable, open_database
from deeptutor.db.repositories.identity import IdentityRepository

logger = logging.getLogger(__name__)


@runtime_checkable
class IdentityStore(Protocol):
    """Where identity records live."""

    backend: str

    def load(self) -> dict[str, dict[str, Any]]: ...

    def save(self, username: str, record: dict[str, Any]) -> None: ...

    def delete(self, username: str) -> bool: ...

    def patch(self, username: str, **changes: Any) -> bool: ...

    def bump_token_version(self, username: str) -> bool: ...

    def backfill(self, users: dict[str, dict[str, Any]]) -> dict[str, int]: ...

    def replace_all(self, users: dict[str, dict[str, Any]]) -> None:
        """Make the store match *users* exactly, deleting anything absent."""
        ...


class PostgresIdentityStore:
    """The repository, dressed as an :class:`IdentityStore`."""

    backend = "postgres"

    def __init__(self, db: Database) -> None:
        self._db = db
        self._repo = IdentityRepository(db)

    def load(self) -> dict[str, dict[str, Any]]:
        return self._repo.load_users()

    def save(self, username: str, record: dict[str, Any]) -> None:
        self._repo.save(username, record)

    def delete(self, username: str) -> bool:
        return self._repo.delete(username)

    def patch(self, username: str, **changes: Any) -> bool:
        # Column names, not record keys, so ``phone`` maps to ``phone_number``.
        mapping = {"phone": "phone_number"}
        applied = {mapping.get(k, k): v for k, v in changes.items()}
        if "disabled" in applied:
            applied["disabled"] = 1 if applied["disabled"] else 0
        if "must_change_password" in applied:
            applied["must_change_password"] = 1 if applied["must_change_password"] else 0
        return self._repo._patch(username, applied)  # noqa: SLF001 - same package

    def bump_token_version(self, username: str) -> bool:
        return self._repo.bump_token_version(username)

    def backfill(self, users: dict[str, dict[str, Any]]) -> dict[str, int]:
        return self._repo.backfill(list(users.items()))

    def replace_all(self, users: dict[str, dict[str, Any]]) -> None:
        self._repo.replace_all(users, prune=True)


def active_store(db: Database | None = None) -> IdentityStore | None:
    """The configured identity store, or ``None`` for the JSON file store.

    ``None`` is not an error: it means "use the file store", which is what
    happens in every deployment that has not set a database URL, including the
    whole existing test suite.
    """
    settings = get_database_settings()
    if not settings.enabled:
        return None
    database = db if db is not None else open_database(settings)
    if database is None:  # pragma: no cover - enabled implies a database
        return None
    ok, detail = database.ping()
    if not ok:
        # Fail loudly rather than degrade to a second source of truth.
        raise DatabaseUnavailable(
            f"identity database is configured but unreachable ({detail}); "
            "refusing to fall back to the JSON store"
        )
    return PostgresIdentityStore(database)


def store_health() -> dict[str, Any]:
    """Readiness payload fragment. Never raises."""
    settings = get_database_settings()
    if not settings.enabled:
        return {"enabled": False, "backend": "json-file"}
    try:
        database = open_database(settings)
    except Exception as exc:  # noqa: BLE001
        return {"enabled": True, "ok": False, "reason": type(exc).__name__}
    if database is None:  # pragma: no cover
        return {"enabled": False, "backend": "json-file"}
    ok, detail = database.ping()
    database.close()
    payload: dict[str, Any] = {
        "enabled": True,
        "backend": "postgres",
        "ok": ok,
        "host": settings.describe()["host"],
    }
    if not ok:
        payload["reason"] = detail
    return payload
