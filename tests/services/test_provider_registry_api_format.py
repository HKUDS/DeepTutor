"""The API-format vocabulary layered over the provider registry."""

from deeptutor.services.provider_registry import (
    api_format_for_provider,
    api_format_from_legacy,
    effective_backend,
    find_by_name,
    wire_api_from_api_format,
)


def test_api_formats_follow_the_backend() -> None:
    assert find_by_name("custom").api_formats == (
        "auto",
        "openai_chat",
        "openai_responses",
        "anthropic",
    )
    assert find_by_name("openai").api_formats == ("auto", "openai_chat", "openai_responses")
    assert find_by_name("anthropic").api_formats == ("anthropic",)
    # Fixed by the backend: nothing for a profile to choose.
    assert find_by_name("azure_openai").api_formats == ()
    assert find_by_name("openai_codex").api_formats == ()
    assert find_by_name("codebuddy").api_formats == ()


def test_effective_backend_switches_only_for_anthropic_on_openai_compat() -> None:
    assert effective_backend(find_by_name("custom"), "anthropic") == "anthropic"
    assert effective_backend(find_by_name("custom"), "openai_responses") == "openai_compat"
    assert effective_backend(find_by_name("minimax"), "anthropic") == "anthropic"
    # OpenAI does not serve Anthropic Messages, so the stray value is clamped.
    assert effective_backend(find_by_name("openai"), "anthropic") == "openai_compat"
    assert effective_backend(find_by_name("anthropic"), "auto") == "anthropic"
    assert effective_backend(None, "anthropic") == "openai_compat"


def test_legacy_anthropic_entries_describe_their_replacement() -> None:
    assert find_by_name("custom_anthropic").legacy_of == ("custom", "anthropic")
    assert find_by_name("minimax_anthropic").legacy_of == ("minimax", "anthropic")
    assert find_by_name("custom").is_legacy is False
    minimax = find_by_name("minimax")
    assert minimax.default_api_base_for("anthropic") == "https://api.minimax.io/anthropic"
    assert minimax.default_api_base_for("auto") == "https://api.minimax.io/v1"
    assert minimax.default_api_base_for("openai_chat") == "https://api.minimax.io/v1"


def test_api_format_from_legacy_fields() -> None:
    assert api_format_from_legacy("custom", "responses") == "openai_responses"
    assert api_format_from_legacy("custom", "chat_completions") == "openai_chat"
    assert api_format_from_legacy("custom", "auto") == "auto"
    assert api_format_from_legacy("custom", None) == "auto"
    assert api_format_from_legacy("custom_anthropic", "responses") == "anthropic"
    assert api_format_from_legacy("anthropic", "auto") == "anthropic"
    assert api_format_from_legacy(None, "responses") == "openai_responses"


def test_wire_api_from_api_format() -> None:
    assert wire_api_from_api_format("openai_responses") == "responses"
    assert wire_api_from_api_format("openai_chat") == "chat_completions"
    assert wire_api_from_api_format("anthropic") == "auto"
    assert wire_api_from_api_format("auto") == "auto"
    assert wire_api_from_api_format("garbage") == "auto"


def test_api_format_for_provider_clamps_to_what_is_offered() -> None:
    assert api_format_for_provider("anthropic", "openai") == "auto"
    assert api_format_for_provider("openai_responses", "anthropic") == "anthropic"
    assert api_format_for_provider("openai_responses", "azure_openai") == "auto"
    assert api_format_for_provider("bogus", "custom") == "auto"
    assert api_format_for_provider("anthropic", "minimax") == "anthropic"
    assert api_format_for_provider("openai_responses", "custom") == "openai_responses"
    # Unknown provider: nothing to clamp against.
    assert api_format_for_provider("anthropic", "nonexistent") == "anthropic"
