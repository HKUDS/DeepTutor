"""Public request contracts and config validators for built-in capabilities."""

from __future__ import annotations

from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from deeptutor.agents.math_animator.request_config import (
    MathAnimatorRequestConfig,
    validate_math_animator_request_config,
)
from deeptutor.agents.research.request_config import (
    DeepResearchRequestConfig,
    validate_research_request_config,
)
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


class CourseStudyRequestConfig(EmptyConfig):
    pass


class ImmersiveWatchingRequestConfig(EmptyConfig):
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


CAPABILITY_CONFIG_VALIDATORS: dict[str, Callable[[dict[str, Any] | None], Any]] = {
    "chat": validate_chat_request_config,
    "deep_solve": validate_deep_solve_request_config,
    "deep_question": validate_deep_question_request_config,
    "deep_research": validate_research_request_config,
    "math_animator": validate_math_animator_request_config,
    "visualize": validate_visualize_request_config,
}

CAPABILITY_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "chat": ChatRequestConfig,
    "ask_questions": AskQuestionsRequestConfig,
    "deep_solve": DeepSolveRequestConfig,
    "deep_question": DeepQuestionRequestConfig,
    "deep_research": DeepResearchRequestConfig,
    "math_animator": MathAnimatorRequestConfig,
    "visualize": VisualizeRequestConfig,
    "mastery_path": MasteryPathRequestConfig,
    "immersive_reading": ImmersiveReadingRequestConfig,
    "course_study": CourseStudyRequestConfig,
    "immersive_watching": ImmersiveWatchingRequestConfig,
}


def _model_validator(
    model_type: type[BaseModel],
    capability_name: str,
) -> Callable[[dict[str, Any] | None], BaseModel]:
    def validate(raw_config: dict[str, Any] | None) -> BaseModel:
        return _validate_model(
            model_type,
            raw_config,
            label=capability_name.replace("_", " "),
        )

    return validate


# Every built-in has an explicit validator, including no-options capabilities.
for _capability_name, _model_type in CAPABILITY_CONFIG_MODELS.items():
    CAPABILITY_CONFIG_VALIDATORS.setdefault(
        _capability_name,
        _model_validator(_model_type, _capability_name),
    )

CAPABILITY_REQUEST_SCHEMAS: dict[str, dict[str, Any]] = {
    name: build_request_schema(model_type) for name, model_type in CAPABILITY_CONFIG_MODELS.items()
}


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
    "AskQuestionsRequestConfig",
    "ChatRequestConfig",
    "CourseStudyRequestConfig",
    "DeepQuestionRequestConfig",
    "DeepSolveRequestConfig",
    "ImmersiveReadingRequestConfig",
    "ImmersiveWatchingRequestConfig",
    "MasteryPathRequestConfig",
    "VisualizeRequestConfig",
    "build_request_schema",
    "get_capability_request_schema",
    "validate_capability_config",
    "validate_chat_request_config",
    "validate_deep_question_request_config",
    "validate_deep_solve_request_config",
    "validate_visualize_request_config",
]
