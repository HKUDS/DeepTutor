"""Tests for LLM utility helpers."""

import pytest

from src.services.llm.utils import (
    build_auth_headers,
    build_chat_url,
    build_completion_url,
    clean_thinking_tags,
    collect_model_names,
    extract_response_content,
    is_local_llm_server,
    sanitize_url,
)


def test_sanitize_url_normalizes_local_host() -> None:
    """Local hostnames should be normalized and include /v1 when needed."""
    url = sanitize_url("localhost:11434")
    assert url == "http://localhost:11434/v1"


def test_build_chat_url_handles_provider_paths() -> None:
    """Provider-specific endpoints should resolve correctly."""
    assert build_chat_url("https://api.anthropic.com", binding="anthropic") == (
        "https://api.anthropic.com/messages"
    )
    assert build_chat_url("https://api.cohere.ai", binding="cohere") == (
        "https://api.cohere.ai/chat"
    )


def test_is_local_llm_server_private_ip(monkeypatch) -> None:
    """Private IPs are treated as local when the override is enabled."""
    monkeypatch.setenv("LLM_TREAT_PRIVATE_AS_LOCAL", "true")
    assert is_local_llm_server("http://10.0.0.5:1234") is True


def test_is_local_llm_server_cloud_domain() -> None:
    """Known cloud domains should never be treated as local."""
    assert is_local_llm_server("https://api.openai.com/v1") is False


def test_build_completion_url_appends_version() -> None:
    """Completion URLs should include api-version when provided."""
    url = build_completion_url("https://api.openai.com", api_version="2024-01-01")
    assert url.endswith("/completions?api-version=2024-01-01")


def test_build_completion_url_rejects_anthropic() -> None:
    """Anthropic bindings should raise when requesting /completions."""
    with pytest.raises(ValueError):
        build_completion_url("https://api.anthropic.com", binding="anthropic")


def test_clean_thinking_tags() -> None:
    """Thinking tags should be removed from model output."""
    assert clean_thinking_tags("Hello <think>ignore</think> World") == "Hello  World"


def test_extract_response_content() -> None:
    """Response content extraction should handle mapping payloads."""
    payload = {"content": [{"text": "Hello"}, {"text": "World"}]}
    assert extract_response_content(payload) == "HelloWorld"


def test_collect_model_names() -> None:
    """Model name collection should extract names from payload entries."""
    entries = ["m1", {"id": "m2"}, {"name": "m3"}, {"model": "m4"}]
    assert collect_model_names(entries) == ["m1", "m2", "m3", "m4"]


def test_build_auth_headers() -> None:
    """Auth headers should vary by provider binding."""
    assert build_auth_headers("key", binding="anthropic")["x-api-key"] == "key"
    assert build_auth_headers("key", binding="azure")["api-key"] == "key"
    assert build_auth_headers("key")["Authorization"] == "Bearer key"
