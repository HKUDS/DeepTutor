"""
Error Mapping - Map provider-specific errors to unified exceptions.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import logging
import math

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


def retry_after_seconds(
    exc: Exception,
    *,
    now: datetime | None = None,
) -> float | None:
    """Extract a numeric or HTTP-date Retry-After value from an exception."""
    value = getattr(exc, "retry_after", None)
    if value is None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        get_header = getattr(headers, "get", None)
        if callable(get_header):
            value = get_header("Retry-After")
            if value is None:
                value = get_header("retry-after")

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            seconds = float(normalized)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(normalized)
            except (TypeError, ValueError, OverflowError):
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            current_time = now or datetime.now(timezone.utc)
            if current_time.tzinfo is None:
                current_time = current_time.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - current_time).total_seconds())
    else:
        return None

    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _rate_limit_error(exc: Exception, provider: str | None) -> LLMRateLimitError:
    """Map rate-limit errors without discarding their server retry hint."""
    return LLMRateLimitError(
        str(exc),
        retry_after=retry_after_seconds(exc),
        provider=provider,
    )


_GLOBAL_RULES: list[MappingRule] = [
    MappingRule(
        classifier=_class_named("AuthenticationError", "AuthenticationStatusError"),
        factory=lambda exc, provider: LLMAuthenticationError(str(exc), provider=provider),
    ),
    MappingRule(
        classifier=_class_named("RateLimitError"),
        factory=_rate_limit_error,
    ),
    MappingRule(
        classifier=_message_contains("rate limit", "429", "quota"),
        factory=_rate_limit_error,
    ),
    MappingRule(
        classifier=_message_contains("context length", "maximum context"),
        factory=lambda exc, provider: ProviderContextWindowError(str(exc), provider=provider),
    ),
]


def map_error(exc: Exception, provider: str | None = None) -> LLMError:
    """Map provider-specific errors to unified internal exceptions.

    An exception that is already an ``LLMError`` is returned *itself*, not a
    replacement: re-running the rules would re-classify a precise error into a
    vaguer one (an ``LLMTimeoutError`` fell out as a bare ``LLMAPIError``), and
    callers such as the LightRAG adapter re-raise the terminal error and
    compare identity. Filling in ``provider`` when the raiser did not know it is
    therefore an in-place write on the caller's exception — deliberate, and the
    only field this function mutates.
    """
    if isinstance(exc, LLMError):
        if exc.provider is None:
            exc.provider = provider
        return exc

    # Heuristic check for status codes before rules
    status_code = getattr(exc, "status_code", None)
    if status_code == 401:
        return LLMAuthenticationError(str(exc), provider=provider)
    if status_code == 429:
        return _rate_limit_error(exc, provider)

    for rule in _GLOBAL_RULES:
        if rule.classifier(exc):
            return rule.factory(exc, provider)

    return LLMAPIError(str(exc), status_code=status_code, provider=provider)
