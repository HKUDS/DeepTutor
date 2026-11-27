"""Validated request config for the math animator capability."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class MathAnimatorRequestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_mode: Literal["video", "image"] = "video"
    quality: Literal["low", "medium", "high"] = "medium"
    style_hint: str = Field(default="", max_length=500)
    enable_visual_review: bool = Field(
        default=False,
        description="Inspect rendered frames and repair visual issues. Adds model calls and render time.",
    )


def validate_math_animator_request_config(
    raw_config: dict[str, Any] | None,
) -> MathAnimatorRequestConfig:
    if raw_config is None:
        return MathAnimatorRequestConfig()
    if not isinstance(raw_config, dict):
        raise ValueError("Math animator config must be an object.")
    try:
        return MathAnimatorRequestConfig.model_validate(raw_config)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise ValueError(f"Invalid math animator config: {details}") from exc


__all__ = [
    "MathAnimatorRequestConfig",
    "validate_math_animator_request_config",
]
