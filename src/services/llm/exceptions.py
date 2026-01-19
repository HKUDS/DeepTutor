# -*- coding: utf-8 -*-
"""
LLM Service Exceptions
======================

Custom exception classes for the LLM service.
Provides a consistent exception hierarchy for better error handling.
Maintains parity with upstream dev branch.
"""

from typing import Any, Dict, Optional


class LLMError(Exception):
    """Base exception for all LLM-related errors."""

    def __init__(
        self, message: str, details: Optional[Dict[str, Any]] = None, provider: Optional[str] = None
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.provider = provider

    def __str__(self) -> str:
        provider_prefix = f"[{self.provider}] " if self.provider else ""
        if self.details:
            return f"{provider_prefix}{self.message} (details: {self.details})"
        return f"{provider_prefix}{self.message}"


class LLMConfigError(LLMError):
    """Raised when there's an error in LLM configuration."""

    pass


class LLMProviderError(LLMError):
    """Raised when there's an error with the LLM provider."""

    pass


class LLMAPIError(LLMError):
    """
    Raised when an API call to an LLM provider fails.
    Standardizes status_code and provider name.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        provider: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details, provider)
        self.status_code = status_code

    def __str__(self) -> str:
        parts = []
        if self.provider:
            parts.append(f"[{self.provider}]")
        if self.status_code:
            parts.append(f"HTTP {self.status_code}")
        parts.append(self.message)
        return " ".join(parts)


class LLMTimeoutError(LLMAPIError):
    """Raised when an API call times out."""

    def __init__(
        self,
        message: str = "Request timed out",
        timeout: Optional[float] = None,
        provider: Optional[str] = None,
    ):
        super().__init__(message, status_code=408, provider=provider)
        self.timeout = timeout


class LLMRateLimitError(LLMAPIError):
    """Raised when rate limited by the API."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: Optional[float] = None,
        provider: Optional[str] = None,
    ):
        super().__init__(message, status_code=429, provider=provider)
        self.retry_after = retry_after


class LLMAuthenticationError(LLMAPIError):
    """Raised when authentication fails (invalid API key, etc.)."""

    def __init__(
        self,
        message: str = "Authentication failed",
        provider: Optional[str] = None,
    ):
        super().__init__(message, status_code=401, provider=provider)


class LLMModelNotFoundError(LLMAPIError):
    """Raised when the requested model is not found."""

    def __init__(
        self,
        message: str = "Model not found",
        model: Optional[str] = None,
        provider: Optional[str] = None,
    ):
        super().__init__(message, status_code=404, provider=provider)
        self.model = model


class LLMParseError(LLMError):
    """Raised when parsing LLM output fails."""

    def __init__(
        self,
        message: str = "Failed to parse LLM output",
        provider: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, details=details, provider=provider)


# Multi-provider specific aliases for mapping rules
class ProviderQuotaExceededError(LLMRateLimitError):
    pass


class ProviderContextWindowError(LLMAPIError):
    pass


__all__ = [
    "LLMError",
    "LLMConfigError",
    "LLMProviderError",
    "LLMAPIError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMAuthenticationError",
    "LLMModelNotFoundError",
    "LLMParseError",
    "ProviderQuotaExceededError",
    "ProviderContextWindowError",
]
