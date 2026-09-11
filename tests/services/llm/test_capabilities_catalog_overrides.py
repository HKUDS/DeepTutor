"""User-declared per-model capabilities layered over the static tables."""

from __future__ import annotations

import pytest

from deeptutor.services.llm.capabilities import (
    catalog_capability_override,
    effective_capabilities,
    get_capability,
    set_catalog_capability_overrides,
    supports_response_format,
    supports_tools,
    supports_vision,
)


@pytest.fixture(autouse=True)
def _clear_overrides():
    set_catalog_capability_overrides([])
    yield
    set_catalog_capability_overrides([])


def test_declared_capability_wins_over_static_tables() -> None:
    set_catalog_capability_overrides([("ollama", "llama3", {"tools": True, "vision": True})])

    assert supports_tools("ollama", "llama3") is True
    assert supports_vision("ollama", "llama3") is True
    # Untouched capabilities and other models keep the table answer.
    assert supports_response_format("ollama", "llama3") is True
    assert supports_tools("ollama", "mistral") is False


def test_declared_false_disables_a_table_true() -> None:
    set_catalog_capability_overrides([("openai", "gpt-4o", {"json_output": False})])

    assert supports_response_format("openai", "gpt-4o") is False
    assert get_capability("openai", "supports_response_format", "gpt-4o") is False


def test_lookup_is_by_model_when_the_runtime_uses_a_normalized_binding() -> None:
    # The catalog stores the vendor binding; the runtime asks under the
    # backend it normalized to (an Anthropic-format custom endpoint is asked
    # about as "anthropic").
    set_catalog_capability_overrides([("custom", "claude-relay", {"vision": False})])

    assert catalog_capability_override("anthropic", "claude-relay", "supports_vision") is False
    assert supports_vision("anthropic", "claude-relay") is False


def test_effective_capabilities_report_the_tables_not_the_overrides() -> None:
    set_catalog_capability_overrides([("ollama", "llama3", {"tools": True})])

    assert effective_capabilities("ollama", "llama3") == {
        "tools": False,
        "vision": False,
        "json_output": True,
    }


def test_only_known_boolean_entries_are_kept() -> None:
    set_catalog_capability_overrides(
        [
            ("openai", "gpt-4o", {"tools": "yes", "bogus": True}),
            ("openai", "", {"tools": True}),
        ]
    )

    assert catalog_capability_override("openai", "gpt-4o", "supports_tools") is None
    assert catalog_capability_override("openai", "", "supports_tools") is None
