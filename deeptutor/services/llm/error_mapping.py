"""
Error Mapping - Map provider-specific errors to unified exceptions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging

# Import unified exceptions from exceptions.py
from .exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    ProviderContextWindowError,
)

logger = logging.getLogger(__name__)


ErrorClassifier = Callable[[Exception], bool]


@dataclass(frozen=True)
class MappingRule:
    classifier: ErrorClassifier
    factory: Callable[[Exception, str | None], LLMError]


def _instance_of(*types: type[BaseException]) -> ErrorClassifier:
    return lambda exc: isinstance(exc, types)


def _message_contains(*needles: str) -> ErrorClassifier:
    def _classifier(exc: Exception) -> bool:
        msg = str(exc).lower()
        return any(needle in msg for needle in needles)

    return _classifier


def _class_named(*names: str) -> ErrorClassifier:
    """Match optional SDK exceptions without importing the SDK at startup."""
    expected = set(names)

    def _classifier(exc: Exception) -> bool:
        return any(cls.__name__ in expected for cls in type(exc).__mro__)

    return _classifier


_GLOBAL_RULES: list[MappingRule] = [
    MappingRule(
        classifier=_class_named("AuthenticationError", "AuthenticationStatusError"),
        factory=lambda exc, provider: LLMAuthenticationError(str(exc), provider=provider),
    ),
    MappingRule(
        classifier=_class_named("RateLimitError"),
        factory=lambda exc, provider: LLMRateLimitError(str(exc), provider=provider),
    ),
    MappingRule(
        classifier=_message_contains("rate limit", "429", "quota"),
        factory=lambda exc, provider: LLMRateLimitError(str(exc), provider=provider),
    ),
    MappingRule(
        classifier=_message_contains("context length", "maximum context"),
        factory=lambda exc, provider: ProviderContextWindowError(str(exc), provider=provider),
    ),
]


def map_error(exc: Exception, provider: str | None = None) -> LLMError:
    """Map provider-specific errors to unified internal exceptions."""
    # Heuristic check for status codes before rules
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return LLMAuthenticationError(str(exc), provider=provider)
    if status_code == 429:
        return LLMRateLimitError(str(exc), provider=provider)

    for rule in _GLOBAL_RULES:
        if rule.classifier(exc):
            return rule.factory(exc, provider)

    return LLMAPIError(str(exc), status_code=status_code, provider=provider)
