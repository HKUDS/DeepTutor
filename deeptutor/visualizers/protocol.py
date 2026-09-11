"""Stable contracts shared by visualizer generators, validators and canvases."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable, Literal

from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import validator_for
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VISUALIZE_MODE_KEY = "_visualizer_mode"
VISUALIZATION_RESULT_KEY = "_visualizer_result"
REQUESTED_VISUALIZER_KEY = "_requested_visualizer"

_VISUALIZER_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
MAX_PAYLOAD_CHARS = 200_000
MAX_MANIFEST_SCHEMA_CHARS = 32_000


class VisualizerManifest(BaseModel):
    """Static, serializable description of one visualization type."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = Field(default="1.0.0", min_length=1, max_length=32)
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=1_000)
    author: str = Field(default="DeepTutor", min_length=1, max_length=120)
    subjects: list[str] = Field(default_factory=list, max_length=32)
    intents: list[str] = Field(default_factory=list, max_length=32)
    render_target: Literal["native", "iframe", "artifact"] = "native"
    native_renderer: str = Field(default="", max_length=80)
    renderer_entry: str = Field(default="", max_length=240)
    payload_format: str = Field(min_length=1, max_length=160)
    payload_kind: Literal["text", "json"] = "text"
    payload_schema: dict[str, Any] = Field(default_factory=dict)
    language_tag: str = Field(default="text", min_length=1, max_length=40)
    prompt: str = Field(min_length=1, max_length=12_000)
    agentic: bool = True
    core: bool = False
    default_installed: bool = True
    priority: int = 100

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        value = value.strip().lower()
        if not _VISUALIZER_ID_RE.fullmatch(value):
            raise ValueError("visualizer id must match [a-z][a-z0-9_.-]{1,63}")
        return value

    @field_validator("renderer_entry")
    @classmethod
    def _safe_renderer_entry(cls, value: str) -> str:
        value = value.strip().replace("\\", "/")
        if not value:
            return ""
        parts = value.split("/")
        if value.startswith("/") or ".." in parts:
            raise ValueError("renderer_entry must be a safe relative path")
        return value

    @model_validator(mode="after")
    def _renderer_contract(self) -> "VisualizerManifest":
        if self.render_target == "native" and not self.native_renderer:
            raise ValueError("native visualizers require native_renderer")
        if self.render_target == "iframe" and not self.renderer_entry:
            raise ValueError("iframe visualizers require renderer_entry")
        if len(json.dumps(self.payload_schema, ensure_ascii=False)) > MAX_MANIFEST_SCHEMA_CHARS:
            raise ValueError(f"payload_schema exceeds {MAX_MANIFEST_SCHEMA_CHARS} characters")
        if self.payload_schema:
            remote_ref = _find_remote_schema_ref(self.payload_schema)
            if remote_ref:
                raise ValueError(
                    f"payload_schema may only use local # references, found: {remote_ref}"
                )
            try:
                validator_for(self.payload_schema).check_schema(self.payload_schema)
            except SchemaError as exc:
                raise ValueError(f"payload_schema is invalid: {exc.message}") from exc
        return self


class RendererRef(BaseModel):
    id: str
    version: str
    target: Literal["native", "iframe", "artifact"]
    native_renderer: str = ""
    entry_url: str = ""


class VisualizationPayload(BaseModel):
    format: str
    data: Any


class VisualizationPresentation(BaseModel):
    title: str = ""
    description: str = ""
    alt_text: str = ""
    aspect_ratio: str = ""


class VisualizationInteraction(BaseModel):
    events: list[str] = Field(default_factory=list)


class VisualizationEnvelope(BaseModel):
    """Versioned result understood by the generic frontend canvas."""

    schema_version: str = "deeptutor.visualization/v1"
    render_type: str
    renderer: RendererRef
    payload: VisualizationPayload
    presentation: VisualizationPresentation = Field(default_factory=VisualizationPresentation)
    interaction: VisualizationInteraction = Field(default_factory=VisualizationInteraction)
    fallback: dict[str, Any] = Field(default_factory=dict)


PayloadValidator = Callable[[str], tuple[bool, Any, str]]


@dataclass(frozen=True)
class VisualizerPlugin:
    """Runtime wrapper around a manifest and its trusted validator."""

    manifest: VisualizerManifest
    origin: Literal["core", "bundled", "user"]
    root: str = ""
    validator: PayloadValidator | None = None

    def validate_payload(self, raw_payload: str) -> tuple[bool, Any, str]:
        raw = str(raw_payload or "").strip()
        if not raw:
            return False, None, "payload is empty"
        if len(raw) > MAX_PAYLOAD_CHARS:
            return False, None, f"payload exceeds {MAX_PAYLOAD_CHARS} characters"
        if self.validator is not None:
            return self.validator(raw)
        if self.manifest.payload_kind == "json":
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                return False, None, f"payload is not valid JSON: {exc}"
            if self.manifest.payload_schema:
                validator_type = validator_for(self.manifest.payload_schema)
                try:
                    validator_type(self.manifest.payload_schema).validate(data)
                except ValidationError as exc:
                    location = "$"
                    if exc.absolute_path:
                        location += "".join(
                            f"[{part}]" if isinstance(part, int) else f".{part}"
                            for part in exc.absolute_path
                        )
                    return (
                        False,
                        None,
                        f"payload schema violation at {location}: {exc.message}",
                    )
            return True, data, ""
        return True, raw, ""

    def serialize_payload(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        return json.dumps(data, ensure_ascii=False, indent=2)


def manifest_public_dict(
    plugin: VisualizerPlugin,
    *,
    installed: bool,
    enabled: bool,
) -> dict[str, Any]:
    result = plugin.manifest.model_dump()
    # Prompt rules are runtime implementation detail and can be very large.
    result.pop("prompt", None)
    result.update(
        {
            "origin": plugin.origin,
            "installed": installed,
            "enabled": enabled,
            "uninstallable": not plugin.manifest.core,
        }
    )
    return result


def _find_remote_schema_ref(value: Any) -> str:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"$ref", "$dynamicRef"} and isinstance(item, str):
                if not item.startswith("#"):
                    return item
            found = _find_remote_schema_ref(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_remote_schema_ref(item)
            if found:
                return found
    return ""


__all__ = [
    "MAX_PAYLOAD_CHARS",
    "MAX_MANIFEST_SCHEMA_CHARS",
    "REQUESTED_VISUALIZER_KEY",
    "VISUALIZATION_RESULT_KEY",
    "VISUALIZE_MODE_KEY",
    "RendererRef",
    "VisualizationEnvelope",
    "VisualizationInteraction",
    "VisualizationPayload",
    "VisualizationPresentation",
    "VisualizerManifest",
    "VisualizerPlugin",
    "manifest_public_dict",
]
