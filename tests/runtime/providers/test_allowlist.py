"""Allowlist algebra: the unrestricted state must survive both operations."""

from __future__ import annotations

from deeptutor.runtime.providers.allowlist import Allowlist


def test_none_is_unrestricted_but_empty_is_not() -> None:
    assert Allowlist.of(None).is_unrestricted
    assert not Allowlist.of([]).is_unrestricted
    assert Allowlist.of([]).allows("anything") is False
    assert Allowlist.of(None).allows("anything") is True


def test_widen_keeps_unrestricted_unrestricted() -> None:
    """The bug this type exists to prevent.

    Bare set arithmetic either raises (``None | {...}``) or "repairs" itself
    into *only* the widening names, silently stripping an administrator down
    to a single resource-derived grant.
    """
    widened = Allowlist.unrestricted().widen(["mcp_pageindex_search"])
    assert widened.is_unrestricted
    assert widened.allows("mcp_other_tool")


def test_widen_unions_a_restricted_list() -> None:
    widened = Allowlist.of(["a"]).widen(["b", "b"])
    assert widened.names == frozenset({"a", "b"})


def test_narrow_intersects_and_treats_unrestricted_as_no_limit() -> None:
    a = Allowlist.of(["a", "b"])
    b = Allowlist.of(["b", "c"])
    assert a.narrow(b).names == frozenset({"b"})
    assert Allowlist.unrestricted().narrow(a) == a
    assert a.narrow(Allowlist.unrestricted()) == a


def test_narrow_to_disjoint_denies_everything() -> None:
    assert Allowlist.of(["a"]).narrow(Allowlist.of(["b"])).names == frozenset()


def test_as_set_round_trips_the_none_convention() -> None:
    assert Allowlist.unrestricted().as_set() is None
    assert Allowlist.of(["a"]).as_set() == {"a"}
