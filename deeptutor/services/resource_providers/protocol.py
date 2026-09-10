"""Lookup request/result schema and the in-process provider interface.

The schema is provider-neutral: a dictionary, glossary, or future external
bridge answers the same :class:`LookupRequest` with the same
:class:`LookupResult`, so callers never branch on the provider kind.
Provider-specific presentation stays inside the provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

LOOKUP_OK = "ok"
LOOKUP_NOT_FOUND = "not_found"
LOOKUP_ERROR = "error"
LOOKUP_DISABLED = "disabled"


@dataclass(frozen=True)
class LookupRequest:
    """One bounded lookup ask.

    ``context`` is optional surrounding text a provider may use for
    disambiguation; it is never required, and providers receive only this
    request — not arbitrary reading history.
    """

    term: str
    source_lang: str = "en"
    target_lang: str = "zh"
    context: str = ""


@dataclass(frozen=True)
class LookupEntry:
    """One rendered-ready result entry."""

    headword: str = ""
    definition: str = ""
    translation: str = ""
    phonetic: str = ""
    examples: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class LookupResult:
    """Explicit outcome for one lookup.

    ``status`` is one of ``ok`` / ``not_found`` / ``error`` / ``disabled``.
    Failures degrade to a result instead of raising so the caller's main
    learning flow can continue.
    """

    status: str
    provider: str = ""
    entries: tuple[LookupEntry, ...] = field(default_factory=tuple)
    message: str = ""


@runtime_checkable
class ResourceProvider(Protocol):
    """In-process provider contract.

    ``manifest`` is read without importing heavy state; ``lookup`` performs
    the actual resource request. ``startup``/``shutdown`` are optional
    lifecycle hooks for providers that need them.
    """

    @property
    def manifest(self):  # -> ProviderManifest (kept untyped to avoid import cycle)
        ...

    async def lookup(self, request: LookupRequest) -> LookupResult: ...
