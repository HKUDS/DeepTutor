"""Shared entitlement provisioning for the commerce subsystem.

A *plan* is an opaque document the admin console builds (RIC-546 data model)
carrying the permission bundle that a successful purchase unlocks:

.. code-block:: python

    {
        "id": "plan_standard",
        "name": "标准版",
        "price_fen": 2990,
        "duration_days": 365,
        "models": {"llm": [{"profile_id": "...", "model_ids": ["..."]}]},
        "knowledge_bases": [{"name": "admin:kb:初中数学"}],
        "skills": [...],
        "books": ["bk_shared"],
    }

:func:`provision_plan` validates the grant payload with the same
``validate_grant`` enforcement the admin UI uses, persists the merged grant
with :func:`save_grant`, and binds shared-catalogue books with
:func:`set_book_permission` (each book id is applied only if it exists in the
shared catalogue; retired ids are skipped rather than failing the whole
purchase).  It is shared by the offline CDK engine and the online order/notify
engine so every purchase path provisions identically.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deeptutor.multi_user.grants import empty_grant, normalize_grant

logger = logging.getLogger(__name__)


def grant_for_plan(plan: dict[str, Any] | None, user_id: str) -> dict[str, Any]:
    """Translate a plan's permission bundle into a v2 grant payload."""
    if not isinstance(plan, dict):
        return empty_grant(user_id)

    grant = empty_grant(user_id)
    models = plan.get("models") if isinstance(plan.get("models"), dict) else {}
    llm = models.get("llm")
    if isinstance(llm, list):
        grant["models"]["llm"] = [dict(m) for m in llm if isinstance(m, dict)]
    for key in ("knowledge_bases", "skills"):
        raw = plan.get(key)
        if isinstance(raw, list):
            grant[key] = [dict(item) for item in raw if isinstance(item, dict)]
    return normalize_grant(user_id, grant)


def merge_grant(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge an overlay into a grant (models/KBs/skills concatenate)."""
    merged: dict[str, Any] = json.loads(json.dumps(base))
    for key, value in overlay.items():
        if key == "models" and isinstance(value, dict) and isinstance(value.get("llm"), list):
            merged.setdefault("models", {}).setdefault("llm", [])
            merged["models"]["llm"] = merged["models"]["llm"] + value["llm"]
        elif key in {"knowledge_bases", "skills"} and isinstance(value, list):
            merged.setdefault(key, [])
            merged[key] = merged[key] + value
        else:
            merged[key] = value
    return merged


def bind_plan_books(plan: dict[str, Any] | None, username: str) -> list[str]:
    """Bind a plan's shared-catalogue books read-only to ``username``.

    Returns the list of book ids actually bound.  Failures affecting one book
    are logged and skipped — provisioning must not give up the whole purchase
    because a catalogue entry was retired mid-sale.
    """
    bound: list[str] = []
    if not isinstance(plan, dict):
        return bound
    raw_books = plan.get("books") or plan.get("book_ids")
    if not (isinstance(raw_books, list) and raw_books):
        return bound
    try:
        from deeptutor.multi_user.book_permission import (
            BookPermission,
            normalize_book_permission,
        )
        from deeptutor.multi_user.identity import get_user, set_book_permission

        record = get_user(username) or {}
        existing = normalize_book_permission(record.get("book_permission"))
        books = existing.books_dict()
        for book_id in raw_books:
            canonical = str(book_id or "").strip()
            if not canonical or canonical in books:
                continue
            books[canonical] = "read"
            bound.append(canonical)
        if not bound:
            return bound
        set_book_permission(
            username,
            BookPermission(
                create=existing.create,
                default=existing.default,
                books=tuple(books.items()),
            ),
        )
    except Exception:
        logger.exception("Failed to bind plan books (user=%s)", username)
        bound = []
    return bound


def provision_plan(
    *,
    plan: dict[str, Any] | None,
    user_id: str,
    username: str,
    base_grant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind ``plan``'s permission bundle to ``user_id`` and persist it.

    ``base_grant`` is the user's current saved grant when known (the caller
    read it for its own bookkeeping); when omitted it is re-loaded from the
    grant store.  Plan permissions *merge over* existing entitlements so a
    renewal or a second plan never strips what the account already has.

    Returns the persisted grant on success.  Raises ``ValueError`` for a
    bundle that fails validation — the caller is expected to surface that as
    a 4xx and leave its own bookkeeping untouched.
    """
    from deeptutor.multi_user.grants import load_grant, save_grant, validate_grant

    grant = grant_for_plan(plan, user_id)
    if isinstance(base_grant, dict) and base_grant:
        grant = merge_grant(base_grant, grant)
    else:
        grant = merge_grant(load_grant(user_id), grant)
    validate_grant(grant)
    saved = save_grant(user_id, grant)
    bind_plan_books(plan, username)
    return saved


__all__ = [
    "bind_plan_books",
    "grant_for_plan",
    "merge_grant",
    "provision_plan",
]
