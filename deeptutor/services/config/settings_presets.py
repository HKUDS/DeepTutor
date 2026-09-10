"""Value-free named Settings presets.

A preset describes a reviewable starting point. It carries stable identifiers
and draft payloads only: no credentials, deployment endpoints, provider
profiles, or write side effects. Staging one deliberately uses the ordinary
Settings draft, so the user still sees and applies every change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SETTINGS_PRESETS_SCHEMA_VERSION = "deeptutor.settings-presets/v1"

_DOCUMENT_PARSING_EXTENSION = "document_parsing"
_ENABLED_TOOLS_EXTENSION = "enabled_tools"


@dataclass(frozen=True, slots=True)
class SettingsPreset:
    """One static preset and the draft payload it can stage."""

    id: str
    label: str
    description: str
    resource_cost: str
    credentials: tuple[str, ...]
    prerequisites: tuple[str, ...]
    unlocked_features: tuple[str, ...]
    parser_engine: str
    tools: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        """Return the wire shape without the implementation-only write payload."""

        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "parser": self.parser_engine,
            "resource_cost": self.resource_cost,
            "credentials": list(self.credentials),
            "prerequisites": list(self.prerequisites),
            "unlocked_features": list(self.unlocked_features),
        }

    def draft_extensions(self) -> dict[str, dict[str, Any]]:
        """Return payload shapes accepted by the existing draft apply flow."""

        return {
            _DOCUMENT_PARSING_EXTENSION: {"engine": self.parser_engine},
            _ENABLED_TOOLS_EXTENSION: {"enabled_tools": list(self.tools)},
        }


_PRESETS: tuple[SettingsPreset, ...] = (
    SettingsPreset(
        id="basic_text",
        label="settings.presets.basic_text.name",
        description="settings.presets.basic_text.description",
        resource_cost="low",
        credentials=("llm",),
        prerequisites=("llm_profile",),
        unlocked_features=("core_chat", "reasoning"),
        parser_engine="text_only",
        tools=("brainstorm", "reason"),
    ),
    SettingsPreset(
        id="local_multimodal",
        label="settings.presets.local_multimodal.name",
        description="settings.presets.local_multimodal.description",
        resource_cost="medium",
        credentials=("llm", "imagegen", "videogen"),
        prerequisites=("llm_profile", "markdown_parser", "media_profiles"),
        unlocked_features=("document_parsing", "image_generation", "video_generation"),
        parser_engine="markitdown",
        tools=("brainstorm", "reason", "imagegen", "videogen"),
    ),
    SettingsPreset(
        id="university_study",
        label="settings.presets.university_study.name",
        description="settings.presets.university_study.description",
        resource_cost="medium",
        credentials=("llm",),
        prerequisites=("llm_profile", "markdown_parser", "search_profile"),
        unlocked_features=("document_parsing", "web_search", "paper_search", "reasoning"),
        parser_engine="markitdown",
        tools=("brainstorm", "web_search", "paper_search", "reason"),
    ),
    SettingsPreset(
        id="full_generation",
        label="settings.presets.full_generation.name",
        description="settings.presets.full_generation.description",
        resource_cost="high",
        credentials=("llm", "imagegen", "videogen"),
        prerequisites=("llm_profile", "markdown_parser", "media_profiles", "search_profile"),
        unlocked_features=(
            "document_parsing",
            "web_search",
            "paper_search",
            "image_generation",
            "video_generation",
        ),
        parser_engine="markitdown",
        tools=(
            "brainstorm",
            "web_search",
            "paper_search",
            "reason",
            "imagegen",
            "videogen",
        ),
    ),
)

_PRESETS_BY_ID = {preset.id: preset for preset in _PRESETS}


def list_settings_presets() -> list[dict[str, Any]]:
    """Return the stable, review-only preset catalog."""

    return [preset.public_dict() for preset in _PRESETS]


def get_settings_preset(preset_id: str) -> SettingsPreset | None:
    return _PRESETS_BY_ID.get(preset_id)


__all__ = [
    "SETTINGS_PRESETS_SCHEMA_VERSION",
    "SettingsPreset",
    "get_settings_preset",
    "list_settings_presets",
]
