"""Safe, schema-driven extensions for the shared Reading pane.

Extensions are Python entry points, never browser JavaScript. They receive a
server-verified context and return one of the small result schemas understood
by the core Reader. A broken package is skipped at discovery and a failing
action is contained by the API adapter.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from deeptutor.core.entry_points import load_entry_point_group

logger = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "deeptutor.reading_extensions"
PROTOCOL_VERSION = "1"
RESULT_TYPES = frozenset({"card", "quiz", "feedback", "browser_speech"})
_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"


class ReadingAction(BaseModel):
    id: str = Field(pattern=_ID_PATTERN)
    label: str = Field(min_length=1, max_length=80)
    trigger: Literal["toolbar"] = "toolbar"
    requires: list[Literal["selection", "visible_text"]] = Field(default_factory=list)


class ReadingExtensionManifest(BaseModel):
    id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=80)
    protocol_version: Literal["1"] = PROTOCOL_VERSION
    actions: list[ReadingAction] = Field(min_length=1, max_length=12)
    result_types: list[Literal["card", "quiz", "feedback", "browser_speech"]] = Field(min_length=1)
    event_subscriptions: list[str] = Field(default_factory=list)


class ReadingContext(BaseModel):
    material_id: str
    locator: int = Field(ge=1)
    source_href: str = Field(default="", max_length=2048)
    source_anchor: str = Field(default="", max_length=4096)
    locale: str = Field(default="en", max_length=32)
    age_band: str = Field(default="", max_length=32)
    selection: str = Field(default="", max_length=10_000)
    visible_text: str = Field(max_length=60_000)
    unit_text: str = Field(default="", max_length=60_000)


class ReadingExtensionResult(BaseModel):
    type: Literal["card", "quiz", "feedback", "browser_speech"]
    interaction_id: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=160)
    message: str = Field(default="", max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_payload(self) -> "ReadingExtensionResult":
        if len(json.dumps(self.payload, ensure_ascii=False, default=str)) > 64_000:
            raise ValueError("Reading extension result payload exceeds 64 KB.")
        if self.type == "browser_speech":
            text = self.payload.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 60_000:
                raise ValueError("browser_speech requires non-empty text up to 60,000 chars.")
        if self.type == "quiz":
            questions = self.payload.get("questions")
            if not isinstance(questions, list) or not 1 <= len(questions) <= 20:
                raise ValueError("quiz requires between 1 and 20 questions.")
            for row in questions:
                if not isinstance(row, dict):
                    raise ValueError("Each quiz question must be an object.")
                if not isinstance(row.get("prompt"), str):
                    raise ValueError("Each quiz question requires a prompt.")
                choices = row.get("choices")
                if not isinstance(choices, list) or not 2 <= len(choices) <= 8:
                    raise ValueError("Each quiz question requires 2 to 8 choices.")
                if not all(isinstance(choice, str) for choice in choices):
                    raise ValueError("Quiz choices must be strings.")
        return self


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
    try:
        manifest = ReadingExtensionManifest.model_validate(getattr(candidate, "manifest", None))
    except Exception:
        logger.warning("Reading extension %r has an invalid manifest.", name, exc_info=True)
        return None
    if manifest.id != name:
        logger.warning("Reading extension %r declares a different id.", name)
        return None
    if not callable(getattr(candidate, "run_action", None)):
        logger.warning("Reading extension %r has no run_action method.", name)
        return None
    candidate.manifest = manifest
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
