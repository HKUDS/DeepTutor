"""Tests for the DeepTutor error hierarchy."""

from __future__ import annotations

from deeptutor.core.errors import (
    ConfigurationError,
    DeepTutorError,
    EnvironmentConfigError,
    LLMContextError,
    LLMServiceError,
    ServiceError,
    ValidationError,
)


def test_hierarchy() -> None:
    """All custom errors must inherit from DeepTutorError."""
    for cls in (
        ConfigurationError,
        ValidationError,
        ServiceError,
        LLMServiceError,
        LLMContextError,
        EnvironmentConfigError,
    ):
        err = cls("test")
        assert isinstance(err, DeepTutorError), f"{cls.__name__} should extend DeepTutorError"
        assert isinstance(err, Exception)


def test_str_without_details() -> None:
    """__str__ with no details just returns the message."""
    err = DeepTutorError("something went wrong")
    assert str(err) == "something went wrong"


def test_str_with_details() -> None:
    """__str__ with details appends them in parentheses."""
    err = DeepTutorError("failed", details={"code": 42})
    result = str(err)
    assert "failed" in result
    assert "code" in result
    assert "42" in result


def test_details_dictionary_is_stored() -> None:
    """The details dict is accessible on the error instance."""
    err = DeepTutorError("oops", details={"model": "gpt-4", "tokens": 8000})
    assert err.details["model"] == "gpt-4"
    assert err.details["tokens"] == 8000


def test_details_defaults_to_empty_dict() -> None:
    """When no details are provided, defaults to an empty dict."""
    err = DeepTutorError("oops")
    assert err.details == {}


def test_llm_context_error_carries_message() -> None:
    """LLMContextError (deepest subclass) still carries the message."""
    err = LLMContextError("context window exceeded", details={"max": 128000})
    assert err.message == "context window exceeded"
    assert err.details["max"] == 128000
    assert isinstance(err, LLMServiceError)
    assert isinstance(err, ServiceError)


def test_error_is_catchable_as_base_exception() -> None:
    """All custom errors can be caught via DeepTutorError."""
    try:
        raise ConfigurationError("bad config")
    except DeepTutorError as e:
        assert str(e) == "bad config"


def test_environment_config_error_chain() -> None:
    """EnvironmentConfigError is a ConfigurationError."""
    err = EnvironmentConfigError("missing env")
    assert isinstance(err, ConfigurationError)
    assert isinstance(err, DeepTutorError)


def test_validation_error_carries_details() -> None:
    """ValidationError specific details storage."""
    err = ValidationError("invalid val", details={"field": "age", "reason": "too low"})
    assert err.details["field"] == "age"
    assert err.details["reason"] == "too low"

