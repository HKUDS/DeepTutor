"""Safe, schema-driven extensions for the shared Reading pane.

Extensions are Python entry points, never browser JavaScript. They receive a
server-verified context and return one of the small result schemas understood
by the core Reader. A broken package is skipped at discovery and a failing
action is contained by the API adapter.
"""

from __future__ import annotations

from hashlib import sha256
import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from deeptutor.core.entry_points import load_entry_point_group

logger = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "deeptutor.reading_extensions"
PROTOCOL_VERSION = "1"


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
    type: str
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


def _sentences(text: str, limit: int = 3) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    rows = [row.strip() for row in re.split(r"(?<=[.!?。！？])\s*", clean) if row.strip()]
    return rows[:limit] or ([clean[:240]] if clean else [])


class _DeclarativeExtension:
    def __init__(self, manifest: ReadingExtensionManifest) -> None:
        self.manifest = manifest

    def run_action(self, action: str, context: ReadingContext) -> ReadingExtensionResult:
        if action not in {item.id for item in self.manifest.actions}:
            raise ValueError(f"Unknown action {action!r}")
        source = context.selection or context.visible_text or context.unit_text
        rows = _sentences(source)
        if self.manifest.id == "read_aloud":
            return ReadingExtensionResult(
                type="browser_speech",
                title="Read aloud",
                payload={"text": source, "locale": context.locale},
            )
        if self.manifest.id == "guided_learn":
            return ReadingExtensionResult(
                type="card",
                title="Guided learning",
                payload={
                    "overview": rows[0] if rows else "",
                    "concepts": rows[:3],
                    "example": rows[1] if len(rows) > 1 else (rows[0] if rows else ""),
                    "reflection": "What detail in this passage best supports its main idea?",
                },
            )
        if self.manifest.id == "vocabulary":
            word = (context.selection.strip().split() or [""])[0][:80]
            return ReadingExtensionResult(
                type="card",
                title=word or "Vocabulary",
                message=(
                    "Select one word in the page to get a contextual clue."
                    if not word
                    else "Use the surrounding sentence as a clue before revealing a definition."
                ),
                payload={"word": word, "context": rows[0] if rows else ""},
            )
        if self.manifest.id == "translation":
            return ReadingExtensionResult(
                type="card",
                title="Translation",
                message="A translation provider is not configured for this extension.",
                payload={"source_text": source[:2000]},
            )
        if self.manifest.id == "quiz":
            questions = []
            choices = rows[:3]
            while len(choices) < 3:
                choices.append("Not stated in this passage")
            for index in range(3):
                rotated = choices[index:] + choices[:index]
                questions.append(
                    {
                        "id": f"q{index + 1}",
                        "prompt": "Which statement appears in the current passage?",
                        "choices": rotated,
                    }
                )
            interaction_id = sha256(
                f"{context.material_id}|{context.locator}|{source}".encode()
            ).hexdigest()[:24]
            return ReadingExtensionResult(
                type="quiz",
                interaction_id=interaction_id,
                title="Three-question check",
                payload={
                    "questions": questions,
                    "_answers": {f"q{index + 1}": 0 for index in range(3)},
                },
            )
        return ReadingExtensionResult(type="card", title=self.manifest.name)

    def submit(
        self, interaction: dict[str, Any], submission: dict[str, Any]
    ) -> ReadingExtensionResult:
        expected = interaction.get("private", {}).get("answers", {})
        answers = submission.get("answers") if isinstance(submission.get("answers"), dict) else {}
        score = sum(1 for key, value in expected.items() if answers.get(key) == value)
        return ReadingExtensionResult(
            type="feedback",
            interaction_id=str(interaction.get("interaction_id") or ""),
            title="Quiz result",
            message=f"{score}/{len(expected)}",
            payload={"score": score, "total": len(expected), "completed": True},
        )


def _builtin_extensions() -> list[ReadingExtension]:
    specs = [
        ("read_aloud", "Read aloud", "read", ["visible_text"], ["browser_speech"]),
        ("guided_learn", "Learn", "explain", ["visible_text"], ["card"]),
        ("vocabulary", "Vocabulary", "hint", ["selection"], ["card"]),
        ("translation", "Translate", "translate", ["visible_text"], ["card"]),
        ("quiz", "Test", "start", ["visible_text"], ["quiz", "feedback"]),
    ]
    return [
        _DeclarativeExtension(
            ReadingExtensionManifest(
                id=identifier,
                version="1.0.0",
                name=name,
                actions=[ReadingAction(id=action, label=name, requires=requires)],
                result_types=result_types,
            )
        )
        for identifier, name, action, requires, result_types in specs
    ]


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
    if not callable(getattr(candidate, "run_action", None)):
        logger.warning("Reading extension %r has no run_action method.", name)
        return None
    candidate.manifest = parsed
    return candidate


class ReadingExtensionRegistry:
    def __init__(self, extensions: list[ReadingExtension] | None = None) -> None:
        rows = extensions if extensions is not None else (
            _builtin_extensions()
            + load_entry_point_group(ENTRY_POINT_GROUP, _coerce, log=logger)
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
    "ReadingAction",
    "ReadingContext",
    "ReadingExtensionManifest",
    "ReadingExtensionRegistry",
    "ReadingExtensionResult",
    "get_reading_extension_registry",
    "dispatch_learning_event",
]
