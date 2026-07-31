"""Tests for request-scoped LLM selection lifetime management."""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.multi_user.execution_source import get_execution_source
from deeptutor.services.llm.config import LLMConfig, get_scoped_llm_config
from deeptutor.services.model_selection import runtime


def test_nested_selection_resets_the_matching_execution_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.context.get_current_user",
        lambda: SimpleNamespace(id="u_test", is_admin=True),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_llm_config_for_selection",
        lambda selection: LLMConfig(
            model="test-model",
            api_key="test-key",
            base_url="https://example.test/v1",
            source=getattr(selection, "source", "platform"),
        ),
    )

    _outer_config, outer_token = runtime.activate_llm_selection(
        {"source": "platform", "profile_id": "platform-profile", "model_id": "model"}
    )
    _inner_config, inner_token = runtime.activate_llm_selection(
        {"source": "byok", "profile_id": "byok-profile", "generation": 2}
    )

    assert get_execution_source() is not None
    assert get_execution_source().source == "byok"
    assert get_scoped_llm_config() is not None
    assert get_scoped_llm_config().source == "byok"

    runtime.reset_llm_selection(inner_token)

    assert get_execution_source() is not None
    assert get_execution_source().source == "platform"
    assert get_scoped_llm_config() is not None
    assert get_scoped_llm_config().source == "platform"

    runtime.reset_llm_selection(outer_token)

    assert get_execution_source() is None
    assert get_scoped_llm_config() is None
