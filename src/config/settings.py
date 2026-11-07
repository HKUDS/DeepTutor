"""
Configuration Settings for DeepTutor

Environment Variables:
    LLM_RETRY__MAX_RETRIES: Maximum retry attempts for LLM calls (default: 3)
    LLM_RETRY__BASE_DELAY: Base delay between retries in seconds (default: 1.0)
    LLM_RETRY__EXPONENTIAL_BACKOFF: Whether to use exponential backoff (default: True)

Examples:
    export LLM_RETRY__MAX_RETRIES=5
    export LLM_RETRY__BASE_DELAY=2.0
    export LLM_RETRY__EXPONENTIAL_BACKOFF=false
"""

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMRetryConfig(BaseModel):
    max_retries: int = Field(default=8, description="Maximum retry attempts for LLM calls")
    base_delay: float = Field(default=5.0, description="Base delay between retries in seconds")
    exponential_backoff: bool = Field(
        default=True, description="Whether to use exponential backoff"
    )


class Settings(BaseSettings):
    # LLM retry configuration
    retry: LLMRetryConfig = Field(default_factory=LLMRetryConfig)

    # Deprecated: use retry instead
    @property
    def llm_retry(self):
        import warnings

        warnings.warn(
            "settings.llm_retry is deprecated, use settings.retry instead",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.retry

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_nested_delimiter="__",
    )


# Global settings instance
settings = Settings()
