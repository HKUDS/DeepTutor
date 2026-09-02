"""Canonical catalog for turn capabilities and chat-loop extensions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

CapabilityKind = Literal["turn", "loop_extension"]
CapabilityFactory = Callable[[], object]


class EmptyConfig(BaseModel):
    """Explicit no-options schema; unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True)
class CapabilityCatalogEntry:
    name: str
    kind: CapabilityKind
    manifest: Any
    factory: CapabilityFactory
    config_model: type[BaseModel]

    def create(self) -> object:
        return self.factory()


class CapabilityCatalog:
    """Factory-only registry shared by both capability execution levels."""

    def __init__(self) -> None:
        self._entries: dict[tuple[CapabilityKind, str], CapabilityCatalogEntry] = {}

    def register(
        self,
        *,
        name: str,
        kind: CapabilityKind,
        manifest: Any,
        factory: CapabilityFactory,
        config_model: type[BaseModel] = EmptyConfig,
        replace: bool = False,
    ) -> CapabilityCatalogEntry:
        normalized = str(name or "").strip()
        if not normalized:
            raise ValueError("Capability name must not be empty")
        key = (kind, normalized)
        if key in self._entries and not replace:
            raise ValueError(f"Capability already registered: {kind}:{normalized}")
        entry = CapabilityCatalogEntry(
            name=normalized,
            kind=kind,
            manifest=manifest,
            factory=factory,
            config_model=config_model,
        )
        self._entries[key] = entry
        return entry

    def get(self, kind: CapabilityKind, name: str) -> CapabilityCatalogEntry | None:
        return self._entries.get((kind, str(name or "").strip()))

    def create(self, kind: CapabilityKind, name: str) -> object | None:
        entry = self.get(kind, name)
        return entry.create() if entry is not None else None

    def entries(self, kind: CapabilityKind | None = None) -> tuple[CapabilityCatalogEntry, ...]:
        values: Iterable[CapabilityCatalogEntry] = self._entries.values()
        if kind is not None:
            values = (entry for entry in values if entry.kind == kind)
        return tuple(values)

    def clear(self) -> None:
        self._entries.clear()


_default_catalog: CapabilityCatalog | None = None


def get_capability_catalog() -> CapabilityCatalog:
    global _default_catalog
    if _default_catalog is None:
        _default_catalog = CapabilityCatalog()
    return _default_catalog


def set_capability_catalog(catalog: CapabilityCatalog | None) -> None:
    global _default_catalog
    _default_catalog = catalog


__all__ = [
    "CapabilityCatalog",
    "CapabilityCatalogEntry",
    "CapabilityKind",
    "EmptyConfig",
    "get_capability_catalog",
    "set_capability_catalog",
]
