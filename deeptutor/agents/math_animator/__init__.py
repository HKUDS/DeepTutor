"""Math animator agents and pipeline."""

from importlib import import_module
from typing import Any

from .request_config import (
    MathAnimatorRequestConfig,
    validate_math_animator_request_config,
)

__all__ = [
    "MathAnimatorPipeline",
    "MathAnimatorRequestConfig",
    "validate_math_animator_request_config",
]


def __getattr__(name: str) -> Any:
    if name == "MathAnimatorPipeline":
        value = import_module(f"{__name__}.pipeline").MathAnimatorPipeline
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
