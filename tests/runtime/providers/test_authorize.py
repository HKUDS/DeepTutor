"""MCP authorisation across caller kind × grant source.

The matrix matters because the four callers fail in different directions:
an administrator must not be narrowed by a resource-derived grant, an
ungranted user must not be widened by one beyond that resource, a partner is
governed by its own configured filter rather than a (nonexistent) grant, and
an exclusive knowledge capability must suppress everything it does not own.
"""

from __future__ import annotations

from deeptutor.runtime.providers.allowlist import Allowlist
from deeptutor.runtime.providers.authorize import authorize_mcp_tools
from deeptutor.runtime.providers.scope import ToolScope

ADMIN_GRANT = Allowlist.unrestricted()
GRANTED = Allowlist.of(["mcp_gh_search"])
UNGRANTED = Allowlist.of([])  # what allowed_mcp_tools() returns for a plain user


def test_admin_stays_unrestricted_even_with_an_implicit_grant() -> None:
    allowed = authorize_mcp_tools(
        scope=ToolScope(owner_id="admin"),
        user_grant=ADMIN_GRANT,
        implicit_names=["mcp_pageindex_search"],
    )
    assert allowed.is_unrestricted
    assert allowed.allows("mcp_anything_else")


def test_ungranted_user_fails_closed() -> None:
    allowed = authorize_mcp_tools(scope=ToolScope(owner_id="u1"), user_grant=UNGRANTED)
    assert allowed.names == frozenset()


def test_ungranted_user_gets_only_the_resource_they_hold() -> None:
    allowed = authorize_mcp_tools(
        scope=ToolScope(owner_id="u1"),
        user_grant=UNGRANTED,
        implicit_names=["mcp_pageindex_search"],
    )
    assert allowed.names == frozenset({"mcp_pageindex_search"})


def test_granted_user_keeps_grant_plus_resource() -> None:
    allowed = authorize_mcp_tools(
        scope=ToolScope(owner_id="u1"),
        user_grant=GRANTED,
        implicit_names=["mcp_pageindex_search"],
    )
    assert allowed.names == frozenset({"mcp_gh_search", "mcp_pageindex_search"})


def test_owned_servers_are_authorised_by_ownership_not_by_grant() -> None:
    """A user's self-configured server is their own property.

    Running it through ``grant.mcp_tools`` (which is deny-by-default) would
    make self-service configuration silently useless.
    """
    allowed = authorize_mcp_tools(
        scope=ToolScope(owner_id="u1"),
        user_grant=UNGRANTED,
        owned_names=["mcp_mynotion_search"],
    )
    assert allowed.allows("mcp_mynotion_search")
    assert not allowed.allows("mcp_gh_search")


def test_partner_is_governed_by_its_own_filter_not_the_user_grant() -> None:
    scope = ToolScope(
        owner_id="owner",
        is_partner=True,
        caller_whitelist=frozenset({"mcp_gh_search"}),
    )
    # Even an empty user grant must not narrow a partner: it has no account.
    allowed = authorize_mcp_tools(scope=scope, user_grant=UNGRANTED)
    assert allowed.names == frozenset({"mcp_gh_search"})


def test_partner_with_empty_filter_gets_nothing() -> None:
    scope = ToolScope(owner_id="owner", is_partner=True, caller_whitelist=frozenset())
    allowed = authorize_mcp_tools(scope=scope, user_grant=ADMIN_GRANT)
    assert allowed.names == frozenset()


def test_partner_with_explicit_none_filter_is_unrestricted() -> None:
    """An owner deliberately setting "no filter" is a legitimate allow-all.

    The *default* denying is enforced where the partner config is defined, not
    here — this function must keep the tri-state honest.
    """
    scope = ToolScope(owner_id="owner", is_partner=True, caller_whitelist=None)
    allowed = authorize_mcp_tools(scope=scope, user_grant=UNGRANTED)
    assert allowed.is_unrestricted


def test_exclusive_capability_suppresses_everything_but_the_resource() -> None:
    for grant in (ADMIN_GRANT, GRANTED, UNGRANTED):
        allowed = authorize_mcp_tools(
            scope=ToolScope(owner_id="u1", exclusive_capability=True),
            user_grant=grant,
            implicit_names=["mcp_pageindex_search"],
            owned_names=["mcp_mynotion_search"],
        )
        assert allowed.names == frozenset({"mcp_pageindex_search"})
        assert not allowed.allows("mcp_mynotion_search")


def test_caller_filter_narrows_a_granted_user() -> None:
    scope = ToolScope(owner_id="u1", caller_whitelist=frozenset({"mcp_other"}))
    allowed = authorize_mcp_tools(scope=scope, user_grant=GRANTED)
    assert allowed.names == frozenset()
