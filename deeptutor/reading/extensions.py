"""Safe, schema-driven extensions for the shared Reading pane.

Extensions are Python entry points, never browser JavaScript. They receive a
server-verified context and return one of the small result schemas understood
by the core Reader. A broken package is skipped at discovery and a failing
action is contained by the API adapter.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from deeptutor.core.entry_points import load_entry_point_group

logger = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "deeptutor.reading_extensions"
PROTOCOL_VERSION = "1"
RESULT_TYPES = frozenset({"card", "quiz", "feedback", "browser_speech"})


class ReadingAction(BaseModel):
    id: str
    label: str
    trigger: str = "toolbar"
    requires: list[str] = Field(default_factory=list)


class ReadingExtensionManifest(BaseModel):
    id: str
    version: str
    name: str
    protocol_version: str = PROTOCOL_VERSION
    actions: list[ReadingAction]
    result_types: list[str] = Field(default_factory=list)
    event_subscriptions: list[str] = Field(default_factory=list)


class ReadingContext(BaseModel):
    material_id: str
    locator: int = Field(ge=1)
    source_href: str = ""
    source_anchor: str = Field(default="", max_length=4096)
    locale: str = "en"
    age_band: str = ""
    selection: str = ""
    visible_text: str = ""
    unit_text: str


class ReadingExtensionResult(BaseModel):
    type: Literal["card", "quiz", "feedback", "browser_speech"]
    interaction_id: str = ""
    title: str = ""
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ReadingExtension(Protocol):
    manifest: ReadingExtensionManifest

    def run_action(
        self, action: str, context: ReadingContext
    ) -> ReadingExtensionResult | dict[str, Any]: ...

    def submit(
        self, interaction: dict[str, Any], submission: dict[str, Any]
    ) -> ReadingExtensionResult | dict[str, Any]: ...


def _coerce(name: str, loaded: Any) -> ReadingExtension | None:
    candidate = loaded() if isinstance(loaded, type) else loaded
    manifest = getattr(candidate, "manifest", None)
    try:
        parsed = (
            manifest
            if isinstance(manifest, ReadingExtensionManifest)
            else ReadingExtensionManifest.model_validate(manifest)
        )
    except Exception:
        logger.warning("Reading extension %r has an invalid manifest.", name, exc_info=True)
        return None
    if parsed.id != name or parsed.protocol_version != PROTOCOL_VERSION:
        logger.warning("Reading extension %r has an incompatible id or protocol.", name)
        return None
    if not parsed.result_types or not set(parsed.result_types).issubset(RESULT_TYPES):
        logger.warning("Reading extension %r declares unsupported result types.", name)
        return None
    if not callable(getattr(candidate, "run_action", None)):
        logger.warning("Reading extension %r has no run_action method.", name)
        return None
    candidate.manifest = parsed
    return candidate


class ReadingExtensionRegistry:
    def __init__(self, extensions: list[ReadingExtension] | None = None) -> None:
        rows = (
            extensions
            if extensions is not None
            else load_entry_point_group(ENTRY_POINT_GROUP, _coerce, log=logger)
        )
        self._extensions: dict[str, ReadingExtension] = {}
        for row in rows:
            self._extensions.setdefault(row.manifest.id, row)

    def all(self) -> list[ReadingExtension]:
        return sorted(self._extensions.values(), key=lambda row: row.manifest.id)

    def get(self, extension_id: str) -> ReadingExtension | None:
        return self._extensions.get(extension_id)


_registry: ReadingExtensionRegistry | None = None


def get_reading_extension_registry(*, refresh: bool = False) -> ReadingExtensionRegistry:
    global _registry
    if _registry is None or refresh:
        _registry = ReadingExtensionRegistry()
    return _registry


def dispatch_learning_event(event: dict[str, Any], *, allowed: set[str] | None = None) -> None:
    """Best-effort event fan-out; reward failures never affect quiz results."""
    kind = str(event.get("action") or "")
    for extension in get_reading_extension_registry().all():
        if allowed is not None and extension.manifest.id not in allowed:
            continue
        if kind not in extension.manifest.event_subscriptions:
            continue
        consume = getattr(extension, "on_learning_event", None)
        if not callable(consume):
            continue
        try:
            consume(dict(event))
        except Exception:
            logger.warning(
                "Reading extension %r failed to consume learning event.",
                extension.manifest.id,
                exc_info=True,
            )


__all__ = [
    "ENTRY_POINT_GROUP",
    "PROTOCOL_VERSION",
    "RESULT_TYPES",
    "ReadingAction",
    "ReadingContext",
    "ReadingExtensionManifest",
    "ReadingExtensionRegistry",
    "ReadingExtensionResult",
    "get_reading_extension_registry",
    "dispatch_learning_event",
]
