"""What a turn needs to know to decide which provider tools it may use.

Deliberately a plain input record, not a protocol every provider must
implement: MCP and CLI apps differ in what their grants are keyed by (tool
names vs. app ids), in what "not ready" means, and in whether preloading is
even meaningful. Forcing one policy interface over both would buy a shared
type and pay for it with per-kind branches hidden inside it. The branches
live in :mod:`deeptutor.runtime.providers.authorize`, named and readable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ToolScope:
    """Identity + per-turn policy inputs for external-provider tools."""

    #: Id of the **owning account** — a partner resolves to the person who owns
    #: it, and an administrator to the deployment id. Deliberately not "the
    #: current user id": owner-keyed state (a caller's own MCP servers, their
    #: secrets) is addressed by this, and reading it under one identity while
    #: writing it under another is how one account's servers become invisible to
    #: itself. Comes from ``multi_user.paths.current_owner_id``.
    owner_id: str = ""
    #: A partner is a synthetic non-admin user anchored to an owner's
    #: workspace; its own configured filter is the authority for its surface,
    #: not the (absent) per-user grant.
    is_partner: bool = False
    session_id: str = ""
    #: The caller's own configured whitelist (a partner's ``mcp_tools``).
    #: ``None`` = the caller imposes no restriction.
    caller_whitelist: frozenset[str] | None = None
    #: An exclusive knowledge capability owns the turn and replaces the tool
    #: surface, so provider tools must not be advertised (see ``authorize``).
    exclusive_capability: bool = False


__all__ = ["ToolScope"]
