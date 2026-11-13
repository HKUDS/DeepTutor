"""xAI Grok provider registration and capability tests."""

from deeptutor.services.llm.capabilities import (
    supports_response_format,
    supports_tools,
    supports_vision,
)
from deeptutor.services.provider_registry import find_by_model, find_by_name


def test_xai_provider_spec() -> None:
    spec = find_by_name("xai")

    assert spec is not None
    assert spec.env_key == "XAI_API_KEY"
    assert spec.display_name == "xAI (Grok)"
    assert spec.default_api_base == "https://api.x.ai/v1"
    assert spec.model_id_families == ("grok",)


def test_xai_aliases() -> None:
    assert find_by_name("grok") is find_by_name("xai")
    assert find_by_name("x_ai") is find_by_name("xai")


def test_grok_model_ids_resolve_to_xai() -> None:
    xai = find_by_name("xai")
    for model in ("grok", "grok-3", "grok-4.5-latest", "grok-4.7"):
        assert find_by_model(model) is xai


def test_xai_capabilities() -> None:
    assert supports_tools("xai", "grok-4.5-latest") is True
    assert supports_response_format("xai", "grok-4.5-latest") is True
    assert supports_vision("xai", "grok-4.5-latest") is True
