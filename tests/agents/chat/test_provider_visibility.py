"""Provider-failure copy and the prompt templates it formats (#2693 P0)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deeptutor.agents.loop.provider_visibility import (
    DEFAULT_FALLBACKS_AVAILABLE,
    DEFAULT_RETRY,
    DEFAULT_SERVER_ERROR,
    DEFAULT_UNAVAILABLE,
    annotate_provider_failure,
    failure_message,
    provider_label,
    retry_notice,
    unavailable_message,
)
from deeptutor.services.llm.exceptions import LLMAPIError

PROMPTS = Path(__file__).resolve().parents[3] / "deeptutor" / "agents" / "chat" / "prompts"


def _translate(pack: dict[str, str]):
    """Mimic the pipeline's ``_t``: look up, then ``str.format`` with kwargs."""

    def translate(key: str, default: str = "", **kwargs):
        value = pack.get(key.rsplit(".", 1)[-1], default)
        if kwargs:
            try:
                return value.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return value
        return value

    return translate


class _Pipeline:
    def __init__(self, binding: str = "", model: str = "", base_url: str = "") -> None:
        self.binding = binding
        self.model = model
        self.base_url = base_url


def test_provider_label_is_best_effort() -> None:
    assert provider_label(_Pipeline("deepseek", "deepseek-chat")) == ("deepseek", "deepseek-chat")
    assert provider_label(_Pipeline()) == ("unknown", "")


def test_provider_label_names_the_endpoint_host() -> None:
    # "openai" alone cannot tell an operator which gateway refused the request.
    assert provider_label(_Pipeline("openai", "gpt-test", "http://127.0.0.1:9/v1")) == (
        "openai (127.0.0.1:9)",
        "gpt-test",
    )
    assert provider_label(_Pipeline("openai", "gpt-test", "")) == ("openai", "gpt-test")


def test_unavailable_message_without_fallbacks_matches_the_default() -> None:
    message = unavailable_message(
        _translate({}),
        provider="deepseek",
        model="deepseek-chat",
        attempts=3,
        fallbacks=0,
    )

    assert message == DEFAULT_UNAVAILABLE
    assert "switch" not in message.lower()


def test_unavailable_message_names_the_alternative_count() -> None:
    message = unavailable_message(
        _translate({}),
        provider="deepseek",
        model="deepseek-chat",
        attempts=2,
        fallbacks=2,
    )

    assert message.startswith(DEFAULT_UNAVAILABLE)
    assert DEFAULT_FALLBACKS_AVAILABLE.format(count=2) in message
    # P0 must not imply the switch already happened.
    assert "automatically" in message


def test_retry_notice_carries_attempt_numbers() -> None:
    notice = retry_notice(
        _translate({}), provider="deepseek", model="deepseek-chat", attempt=1, total=3
    )

    assert notice == DEFAULT_RETRY


@pytest.mark.parametrize("language", ["zh", "en"])
def test_chat_prompt_templates_format_with_the_arguments_the_loop_passes(
    language: str,
) -> None:
    """A template/code mismatch would surface as literal ``{provider}`` in the UI."""
    pack = yaml.safe_load((PROMPTS / language / "agentic_chat.yaml").read_text(encoding="utf-8"))[
        "notices"
    ]

    retry = retry_notice(
        _translate(pack), provider="deepseek", model="deepseek-chat", attempt=1, total=3
    )
    unavailable = unavailable_message(
        _translate(pack),
        provider="deepseek",
        model="deepseek-chat",
        attempts=3,
        fallbacks=2,
    )

    for text in (retry, unavailable):
        assert "{" not in text and "}" not in text
        assert "deepseek" in text
    assert "3" in retry
    assert "2" in unavailable


class _StatusError(Exception):
    """Stands in for ``openai.InternalServerError``: a status, not a transport."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code


def test_server_error_copy_names_the_provider_and_the_alternative() -> None:
    exc = LLMAPIError("raw", status_code=502, provider="openai")

    message = failure_message(
        _translate({}),
        exc,
        provider="openai (127.0.0.1:9)",
        model="gpt-test",
        fallbacks=1,
    )

    assert message.startswith(DEFAULT_SERVER_ERROR.format(provider="openai (127.0.0.1:9)"))
    assert DEFAULT_FALLBACKS_AVAILABLE.format(count=1) in message


def test_annotation_preserves_classification_and_replaces_the_raw_text() -> None:
    raw = _StatusError(502)

    typed = annotate_provider_failure(
        raw,
        _translate({}),
        provider="openai (127.0.0.1:9)",
        model="gpt-test",
        fallbacks=1,
    )

    # A raw SDK error becomes a typed one so downstream retry/error handling keeps
    # working, and the message is readable instead of "Error code: 502".
    assert isinstance(typed, LLMAPIError)
    assert typed.status_code == 502
    assert "Error code: 502" not in str(typed)
    assert "server-side error" in str(typed)


def test_annotation_leaves_non_provider_errors_alone() -> None:
    raw = ValueError("not a provider problem")

    assert (
        annotate_provider_failure(raw, _translate({}), provider="openai", model="m", fallbacks=0)
        is raw
    )
