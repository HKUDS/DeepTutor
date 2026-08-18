"""An allowlist of tool names with an explicit *unrestricted* state.

The turn's provider authorisation has to combine several optional whitelists
(a partner's configured filter, the caller's grant, an implicit
resource-derived grant). Modelling "no restriction" as ``None`` inside bare
set arithmetic makes both directions of mistake easy and silent:

* ``None | {"x"}`` raises, so a widening step crashes on an unrestricted
  caller (an administrator);
* "repairing" it as ``(base or set()) | extra`` turns *unrestricted* into
  *only the extra names* — a silent, total loss of tool access.

This type makes the state explicit so both operations are total: narrowing an
unrestricted list yields the other list, widening one stays unrestricted.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Allowlist:
    """Allowed tool names, or unrestricted when :attr:`names` is ``None``."""

    names: frozenset[str] | None = None

    @classmethod
    def unrestricted(cls) -> "Allowlist":
        return cls(names=None)

    @classmethod
    def of(cls, names: Iterable[str] | None) -> "Allowlist":
        """Build from an optional iterable; ``None`` means unrestricted."""
        if names is None:
            return cls(names=None)
        return cls(names=frozenset(str(name) for name in names))

    @property
    def is_unrestricted(self) -> bool:
        return self.names is None

    def allows(self, name: str) -> bool:
        return self.names is None or name in self.names

    def narrow(self, other: "Allowlist") -> "Allowlist":
        """Intersect with *other*; an unrestricted side imposes no limit."""
        if self.names is None:
            return other
        if other.names is None:
            return self
        return Allowlist(names=self.names & other.names)

    def widen(self, extra: Iterable[str]) -> "Allowlist":
        """Add *extra* names. Unrestricted stays unrestricted."""
        if self.names is None:
            return self
        return Allowlist(names=self.names | frozenset(str(name) for name in extra))

    def as_set(self) -> set[str] | None:
        """Plain-set form for APIs that use the ``set | None`` convention."""
        return None if self.names is None else set(self.names)


__all__ = ["Allowlist"]
