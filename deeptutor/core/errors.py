"""
Base exception classes for consistent error handling across the application.
Provides a standardized way to distinguish between bugs, recoverable errors,
and configuration issues.
"""

from typing import Any, Dict, Optional


class DeepTutorError(Exception):
    """Base class for all application errors in DeepTutor."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ConfigurationError(DeepTutorError):
    """Raised when there's a configuration-related error."""

    pass


class ValidationError(DeepTutorError):
    """Raised when input validation fails."""

    pass


class ServiceError(DeepTutorError):
    """Base class for service layer errors."""

    pass


class LLMServiceError(ServiceError):
    """Base class for LLM service-related errors."""

    pass


class LLMContextError(LLMServiceError):
    """Raised when prompt exceeds model context window."""

    pass


class EnvironmentConfigError(ConfigurationError):
    """Raised when there's an environment-related configuration error."""

    pass


class SetupRequiredError(ConfigurationError):
    """The runtime home has not been initialized yet.

    Importing a module must never raise this: it is raised lazily, at the point
    where a code path actually needs ``data/user/settings/main.yaml``. The
    message is actionable (it names the command that fixes it) because the
    failure mode it replaces was a bare ``FileNotFoundError`` during import.
    """

    def __init__(self, config_file: str = "main.yaml", settings_dir: str = ""):
        location = f" under {settings_dir}" if settings_dir else ""
        super().__init__(
            "This DeepTutor installation is not initialized: "
            f"{config_file} is missing{location}. "
            "Run `deeptutor init` (or complete setup in the Web UI) before using "
            "this feature."
        )
        self.config_file = config_file
        self.settings_dir = settings_dir


class AccessError(DeepTutorError):
    """Transport-independent access failure, translated by HTTP adapters."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
