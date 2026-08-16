"""Request-local ownership for a human's interaction with a Partner.

Partner configuration and knowledge assets are shared, admin-managed resources.
Conversation history and learned preferences are relationship state, however,
and must follow the authenticated human rather than the process-wide Partner.
This module keeps that distinction in one place and exposes it to Partner-only
tools through a ContextVar that is safe across concurrent async turns.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator

from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import (
    ensure_scope_workspace,
    get_admin_path_service,
    get_path_service_for_scope,
)
from deeptutor.partners.config.paths import get_partner_user_workspace
from deeptutor.services.path_service import PathService

from .scope import is_partner_user_id
from .sessions import PartnerSessionStore


def personal_actor_id(actor: CurrentUser | None) -> str | None:
    """Account id requiring private Partner state, or ``None`` for legacy scope."""
    if actor is None or actor.is_admin or is_partner_user_id(actor.id):
        return None
    return actor.id


@dataclass(frozen=True, slots=True)
class PartnerTurnContext:
    partner_id: str
    actor: CurrentUser | None
    store: PartnerSessionStore
    own_memory: PathService
    shared_memory: PathService

    @property
    def actor_id(self) -> str | None:
        return personal_actor_id(self.actor)


_current_turn: ContextVar[PartnerTurnContext | None] = ContextVar(
    "deeptutor_partner_turn", default=None
)


def build_partner_turn_context(
    partner_id: str,
    actor: CurrentUser | None,
    store: PartnerSessionStore,
    *,
    legacy_own_memory: PathService,
) -> PartnerTurnContext:
    actor_id = personal_actor_id(actor)
    if actor_id is None:
        return PartnerTurnContext(
            partner_id=partner_id,
            actor=actor,
            store=store,
            own_memory=legacy_own_memory,
            shared_memory=get_admin_path_service(),
        )

    assert actor is not None
    ensure_scope_workspace(actor.scope)
    private_workspace = get_partner_user_workspace(partner_id, actor_id)
    private_memory = private_workspace / "memory"
    private_memory.mkdir(parents=True, exist_ok=True)
    return PartnerTurnContext(
        partner_id=partner_id,
        actor=actor,
        store=store,
        own_memory=PathService(workspace_root=private_workspace),
        shared_memory=get_path_service_for_scope(actor.scope),
    )


def get_partner_turn_context() -> PartnerTurnContext | None:
    return _current_turn.get()


@contextmanager
def partner_turn_context(context: PartnerTurnContext) -> Iterator[None]:
    token: Token[PartnerTurnContext | None] = _current_turn.set(context)
    try:
        yield
    finally:
        _current_turn.reset(token)


__all__ = [
    "PartnerTurnContext",
    "build_partner_turn_context",
    "get_partner_turn_context",
    "partner_turn_context",
    "personal_actor_id",
]
