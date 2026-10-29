"""Public request contracts and config validators for built-in capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from importlib import import_module
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deeptutor.modules.catalog import contribution_enabled, manifests
from deeptutor.runtime.capability_catalog import EmptyConfig


class ChatRequestConfig(EmptyConfig):
    pass


class AskQuestionsRequestConfig(EmptyConfig):
    pass


class DeepSolveRequestConfig(EmptyConfig):
    pass


class MasteryPathRequestConfig(EmptyConfig):
    pass


class ImmersiveReadingRequestConfig(EmptyConfig):
    pass


class VideoLessonRequestConfig(EmptyConfig):
    pass


class DeepQuestionRequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["custom", "mimic"] = "custom"
    topic: str = ""
    num_questions: int = Field(default=1, ge=1, le=50)
    difficulty: str = ""
    # Allowed-types whitelist. Empty list means "any type — let the
    # planner pick per question". Frontend sends the user's multi-select.
    question_types: list[str] = Field(default_factory=list)
    # Optional per-type quantity targets. When non-empty, sum must equal
    # ``num_questions`` (frontend keeps them in sync). Empty dict means
    # "no per-type targets — distribute freely across allowed types".
    per_type_counts: dict[str, int] = Field(default_factory=dict)
    paper_path: str = ""
    max_questions: int = Field(default=10, ge=1, le=100)


class VisualizeRequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Visualizer ids are discovered at runtime, so this contract deliberately
    # validates the stable id grammar rather than freezing an enum into every
    # API client. Availability is checked against the per-user registry.
    render_mode: str = Field(default="auto", min_length=2, max_length=64)
    # Only meaningful when the routed render_type is manim_video / manim_image
    # (either chosen explicitly or selected by AnalysisAgent in auto mode).
    # Mirrors MathAnimatorRequestConfig defaults so the auto path stays
    # zero-config.
    quality: Literal["low", "medium", "high"] = "medium"
    style_hint: str = Field(default="", max_length=500)

    @field_validator("render_mode")
    @classmethod
    def _valid_render_mode(cls, value: str) -> str:
        import re

        normalized = value.strip().lower()
        if normalized != "auto" and not re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", normalized):
            raise ValueError("must be 'auto' or a valid visualizer id")
        return normalized


def _clean_public_config(raw_config: dict[str, Any] | None) -> dict[str, Any]:
    if raw_config is None:
        return {}
    if not isinstance(raw_config, dict):
        raise ValueError("Capability config must be an object.")
    return dict(raw_config)


def _validate_model(
    model_type: type[BaseModel],
    raw_config: dict[str, Any] | None,
    *,
    label: str,
) -> BaseModel:
    cleaned = _clean_public_config(raw_config)
    try:
        return model_type.model_validate(cleaned)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ValueError(f"Invalid {label} config: {details}") from exc


def validate_chat_request_config(raw_config: dict[str, Any] | None) -> ChatRequestConfig:
    return _validate_model(ChatRequestConfig, raw_config, label="chat")


def validate_deep_solve_request_config(
    raw_config: dict[str, Any] | None,
) -> DeepSolveRequestConfig:
    return _validate_model(DeepSolveRequestConfig, raw_config, label="deep solve")


def validate_deep_question_request_config(
    raw_config: dict[str, Any] | None,
) -> DeepQuestionRequestConfig:
    return _validate_model(DeepQuestionRequestConfig, raw_config, label="deep question")


def validate_visualize_request_config(
    raw_config: dict[str, Any] | None,
) -> VisualizeRequestConfig:
    return _validate_model(VisualizeRequestConfig, raw_config, label="visualize")


def build_request_schema(model_type: type[BaseModel]) -> dict[str, Any]:
    return model_type.model_json_schema(mode="validation")


class _Contracts(Mapping):
    def __init__(self, kind: str):
        self.kind = kind

    def __iter__(self):
        return iter(
            name
            for module in manifests().values()
            for name in module["capabilities"]
            if contribution_enabled("capabilities", name)
        )

    def __len__(self):
        return sum(1 for _ in self)

    def __getitem__(self, name):
        if not contribution_enabled("capabilities", name):
            raise KeyError(name)
        spec = next(
            (
                module["capabilities"][name]
                for module in manifests().values()
                if name in module["capabilities"]
            ),
            None,
        )
        if spec is None:
            raise KeyError(name)
        module, attribute = spec["config_model"].split(":")
        model = getattr(import_module(module), attribute)
        if self.kind == "models":
            return model
        if self.kind == "schemas":
            return build_request_schema(model)
        if "validator" in spec:
            reference, attribute = spec["validator"].split(":")
            return getattr(import_module(reference), attribute)
        return lambda raw: _validate_model(model, raw, label=name.replace("_", " "))


CAPABILITY_CONFIG_MODELS = _Contracts("models")
CAPABILITY_CONFIG_VALIDATORS = _Contracts("validators")
CAPABILITY_REQUEST_SCHEMAS = _Contracts("schemas")


def __getattr__(name: str):
    # Preserve imports used by SDK clients while leaving absent modules cold.
    for module in manifests().values():
        for spec in module["capabilities"].values():
            reference, attribute = spec["config_model"].split(":")
            if attribute == name and reference != __name__:
                return getattr(import_module(reference), attribute)
    raise AttributeError(name)


def validate_capability_config(
    capability: str, raw_config: dict[str, Any] | None
) -> dict[str, Any]:
    validator = CAPABILITY_CONFIG_VALIDATORS.get(capability)
    if validator is None:
        return _clean_public_config(raw_config)
    model = validator(raw_config)
    if isinstance(model, BaseModel):
        return model.model_dump(exclude_none=True)
    return _clean_public_config(raw_config)


def get_capability_request_schema(capability: str) -> dict[str, Any]:
    return dict(CAPABILITY_REQUEST_SCHEMAS.get(capability, {}))


__all__ = [
    "CAPABILITY_CONFIG_VALIDATORS",
    "CAPABILITY_CONFIG_MODELS",
    "CAPABILITY_REQUEST_SCHEMAS",
    "AudioOverviewRequestConfig",  # noqa: F822 - lazy compatibility export
    "AskQuestionsRequestConfig",
    "ChatRequestConfig",
    "DeepQuestionRequestConfig",
    "DeepSolveRequestConfig",
    "ImmersiveReadingRequestConfig",
    "MasteryPathRequestConfig",
    "VideoLessonRequestConfig",
    "VisualizeRequestConfig",
    "build_request_schema",
    "get_capability_request_schema",
    "validate_capability_config",
    "validate_chat_request_config",
    "validate_deep_question_request_config",
    "validate_deep_solve_request_config",
    "validate_visualize_request_config",
]
