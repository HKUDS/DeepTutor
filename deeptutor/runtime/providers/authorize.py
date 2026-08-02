"""Per-kind authorisation for external-provider tools.

One function per provider kind, on purpose. The two kinds do not share an
authorisation rule:

* **MCP** is granted per *tool name* (``grant.mcp_tools``) for deployment
  servers, and by *ownership* for servers a user configured themselves;
* **CLI apps** will be granted per *app id* (``grant.cli_apps``) and are
  installed by an administrator, never self-service.

Collapsing both into one "allowed set" is what makes a CLI app accidentally
governed by an MCP whitelist. Keeping them as two named functions over the
same :class:`~deeptutor.runtime.providers.allowlist.Allowlist` type keeps the
shared plumbing (the deferred-tool manifest, the loader, the session's loaded
names) shared without pretending the policies are one policy.
"""

from __future__ import annotations

from collections.abc import Iterable

from deeptutor.runtime.providers.allowlist import Allowlist
from deeptutor.runtime.providers.scope import ToolScope


def authorize_mcp_tools(
    *,
    scope: ToolScope,
    user_grant: Allowlist,
    implicit_names: Iterable[str] = (),
    owned_names: Iterable[str] = (),
) -> Allowlist:
    """Which MCP tool names *scope* may see and call.

    ``user_grant`` is the caller's ``grant.mcp_tools`` as an
    :class:`Allowlist` (unrestricted for administrators, and — by design —
    *empty* for a non-admin whose grant omits the field, so deployment
    servers fail closed).

    ``implicit_names`` are the tool names that ``scope.implicit_provider_ids``
    resolved to against the live pool — authorised by holding the resource.

    ``owned_names`` are tools from servers the caller configured themselves.
    They are authorised by ownership: the admin grant governs the deployment's
    shared servers, and applying it to a user's own server would make
    self-service configuration silently useless.
    """
    if scope.exclusive_capability:
        # An exclusive knowledge capability replaces the tool surface. Only
        # tools authorised by an attached resource survive — they are already
        # preloaded, so the turn never needs to advertise anything else.
        return Allowlist.of(implicit_names)

    caller = Allowlist.of(scope.caller_whitelist)
    # A partner turn is gated by the partner's own configured filter. It must
    # not fall back to "unrestricted" implicitly: that is enforced where the
    # partner config is defined (its ``mcp_tools`` default denies), because a
    # deliberate ``None`` set by the owner is a legitimate "allow everything".
    shared_gate = caller if scope.is_partner else caller.narrow(user_grant)
    if shared_gate.is_unrestricted:
        return Allowlist.unrestricted()

    return shared_gate.widen(owned_names).widen(implicit_names)


__all__ = ["authorize_mcp_tools"]
