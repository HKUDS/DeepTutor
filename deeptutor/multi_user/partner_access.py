"""Who may see, use, and manage a Partner.

Three roles matter, and they nest:

* **Manage** — the human who created the partner (its ``owner_id``), plus any
  admin. Managing means the whole configuration surface: soul, channels,
  assets, models, lifecycle, deletion.
* **Use** — everyone who may manage it, plus any user an admin has *assigned*
  it to through the grant system (the same mechanism that shares knowledge
  bases and skills). Using means holding a conversation with it.
* **Neither** — the partner does not exist as far as that user is concerned.

A partner always runs in its own isolated workspace scope
(``data/partners/{id}/``), never the caller's, so "use" only ever exchanges
messages. Conversations, however, follow the human: each user's history and
learned preferences live under their own account
(:mod:`deeptutor.services.partners.interaction`), so two people talking to the
same partner never see each other's threads.

This module is the single source of truth for those three answers; routes and
backends ask it rather than re-deriving the rule.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from .context import get_current_user
from .grants import load_grant
from .models import CurrentUser


def _manager() -> Any:
    # Imported lazily: the partner service pulls in the whole runtime stack,
    # which imports this module back.
    from deeptutor.services.partners import get_partner_manager

    return get_partner_manager()


def partner_owner_id(partner_id: str) -> str:
    """The account that owns *partner_id*, or ``""`` when it is admin-managed.

    Partners created before ownership existed have no ``owner_id``; they read
    as admin-managed, which is exactly what they were.
    """
    return _manager().owner_id(partner_id)


def assigned_partner_ids(user_id: str | None = None) -> set[str]:
    """The partner ids an admin has assigned to the user (empty for admins)."""
    user = get_current_user()
    uid = user_id or user.id
    return {
        str(item.get("partner_id") or item.get("id") or "").strip()
        for item in load_grant(uid).get("partners", []) or []
        if str(item.get("partner_id") or item.get("id") or "").strip()
    }


def can_manage_partner(partner_id: str, user: CurrentUser | None = None) -> bool:
    """Whether the user may configure *partner_id* — its owner, or any admin."""
    actor = user or get_current_user()
    if actor.is_admin:
        return True
    owner = partner_owner_id(partner_id)
    return bool(owner) and owner == actor.id


def can_use_partner(partner_id: str, user: CurrentUser | None = None) -> bool:
    """Whether the user may talk to *partner_id* — manage it, or be assigned it."""
    actor = user or get_current_user()
    if can_manage_partner(partner_id, actor):
        return True
    return str(partner_id or "").strip() in assigned_partner_ids(actor.id)


def assert_partner_allowed(partner_id: str, user_id: str | None = None) -> None:
    """Raise 403 unless the current user may talk to *partner_id*.

    A no-op for admins, for the partner's owner, and for single-user
    deployments (where the current user resolves to the local admin).
    """
    user = get_current_user()
    if can_manage_partner(partner_id, user):
        return
    if str(partner_id or "").strip() in assigned_partner_ids(user_id or user.id):
        return
    raise HTTPException(status_code=403, detail="Partner is not assigned to you")


def assert_partner_manageable(partner_id: str) -> None:
    """Raise 403 unless the current user may configure *partner_id*.

    Deliberately the same 403 an unassigned partner gets: someone who may only
    talk to a partner learns nothing new about who owns it.
    """
    if not can_manage_partner(partner_id):
        raise HTTPException(status_code=403, detail="You cannot manage this partner")


# Identity-only card fields a consumer needs (partner list page, connect modal).
# Deliberately excludes channels / llm_selection / tool config so a user who was
# merely *assigned* a partner sees its face, never its wiring.
_CARD_FIELDS = (
    "partner_id",
    "name",
    "description",
    "emoji",
    "color",
    "avatar",
    "language",
    "running",
)


def identity_card(partner: dict[str, Any]) -> dict[str, Any]:
    """Reduce a partner dict to the fields a non-owner may see."""
    card = {field: partner.get(field) for field in _CARD_FIELDS}
    card["partner_id"] = str(partner.get("partner_id") or "")
    card["can_manage"] = False
    return card


def visible_partners() -> list[dict[str, Any]]:
    """Every partner the current user may talk to, projected by what they may do.

    Partners they manage come through whole (the list page renders channel
    badges and drills into configuration); partners merely assigned to them are
    reduced to an identity card. ``can_manage`` tells the client which is which
    so it doesn't have to re-derive ownership.
    """
    user = get_current_user()
    out: list[dict[str, Any]] = []
    for partner in _manager().list_partners():
        pid = str(partner.get("partner_id") or "")
        if can_manage_partner(pid, user):
            out.append({**partner, "can_manage": True})
        elif can_use_partner(pid, user):
            out.append(identity_card(partner))
    return out


def visible_partner_cards() -> list[dict[str, Any]]:
    """Identity-only cards for every partner the current user may talk to.

    The read surface behind the connect flow, where the wiring is never needed.
    """
    return [
        identity_card(partner) | {"can_manage": bool(partner.get("can_manage"))}
        for partner in visible_partners()
    ]
