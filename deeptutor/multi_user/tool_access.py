"""Per-user tool and exec access resolution (grant v2).

Optional built-in tools keep the partner config semantics for real users:
``None`` means "unrestricted / follow defaults", a set is an explicit
whitelist. MCP tools are different because they can proxy host-side
capabilities through configured MCP servers. For non-admin real users an
absent MCP grant is therefore deny-by-default; administrators remain
unrestricted. Synthetic scopes (partners) are handled by the chat pipeline,
where their owner-scoped whitelist travels through context metadata
(``mcp_tools_filter`` / ``enabled_tools``).

Enforcement points:

* ``allowed_optional_tools`` — turn_runtime filters every turn's ``tools``
  payload (single choke point for all capabilities), and the tools router
  filters the /settings/tools listing so the UI matches.
* ``allowed_mcp_tools`` — the chat pipeline intersects this with any
  caller-scoped ``mcp_tools_filter`` before building the deferred-tool
  loader, so a granted-away MCP tool can be neither listed nor loaded. For
  real non-admin users, missing ``mcp_tools`` means no MCP tools are listed
  or loadable until an admin grants specific names.
* ``exec_override`` — layered on top of the deployment exec policy in the
  chat pipeline's exec gate and in the exec tool itself.
"""

from __future__ import annotations

from .context import get_current_user
from .grants import load_grant


def _current_grant() -> dict | None:
    """The current user's grant, or ``None`` when unrestricted (admin)."""
    user = get_current_user()
    if user.is_admin:
        return None
    return load_grant(user.id)


def allowed_optional_tools() -> set[str] | None:
    """Whitelist of user-toggleable tool names, ``None`` = unrestricted."""
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("enabled_tools")
    if value is None:
        return None
    return {str(name) for name in value}


def allowed_mcp_tools() -> set[str] | None:
    """Whitelist of MCP (deferred) tool names.

    ``None`` means unrestricted and is reserved for administrators. Real
    non-admin users fail closed when the grant omits ``mcp_tools`` so a chat
    turn cannot discover or load deployment-wide MCP host tools until an admin
    explicitly grants the tool names.
    """
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("mcp_tools")
    if value is None:
        return set()
    return {str(name) for name in value}


def exec_override() -> bool | None:
    """Per-user exec override: ``None`` follows the deployment policy."""
    grant = _current_grant()
    if grant is None:
        return None
    value = grant.get("exec_enabled")
    return value if isinstance(value, bool) else None


def combine_whitelists(caller: set[str] | None, user: set[str] | None) -> set[str] | None:
    """Intersect two optional whitelists; ``None`` = unrestricted."""
    if caller is None:
        return user
    if user is None:
        return caller
    return caller & user


__all__ = [
    "allowed_mcp_tools",
    "allowed_optional_tools",
    "combine_whitelists",
    "exec_override",
]
