"""Tests for Azure OpenAI endpoint normalization and client wiring."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.provider_core import azure_openai_provider as azure_mod
from deeptutor.services.llm.provider_core.azure_openai_provider import normalize_azure_base_url

V1_SURFACE = "https://res.openai.azure.com/openai/v1/"


@pytest.mark.parametrize(
    "api_base",
    [
        "https://res.openai.azure.com",
        "https://res.openai.azure.com/",
        "https://res.openai.azure.com/openai",
        "https://res.openai.azure.com/openai/",
        "https://res.openai.azure.com/openai/v1",
        "https://res.openai.azure.com/openai/v1/",
        "https://res.openai.azure.com/openai/v1/responses",
        "https://res.openai.azure.com/openai/deployments/gpt-4o",
        "https://res.openai.azure.com/openai/deployments/gpt-4o/chat/completions",
        "https://res.openai.azure.com/openai/deployments/my.dep-01/chat/completions?api-version=2024-10-21",
        "res.openai.azure.com/openai/deployments/gpt-4o",
        "  https://res.openai.azure.com/openai/deployments/gpt-4o  ",
    ],
)
def test_every_endpoint_spelling_collapses_to_one_surface(api_base: str) -> None:
    """Portal endpoints and hand-written bases must land on the same URL.

    Appending ``/openai/v1`` verbatim used to turn a classic deployment
    endpoint into ``.../deployments/gpt-4o/openai/v1/responses``, which Azure
    answers with ``404 Resource not found`` even though the settings probe —
    which builds classic URLs — succeeds against the same configuration.
    """
    assert normalize_azure_base_url(api_base) == V1_SURFACE


def test_reverse_proxy_prefix_survives_normalization() -> None:
    assert (
        normalize_azure_base_url("https://gw.corp/azure/openai/deployments/gpt-4o/chat/completions")
        == "https://gw.corp/azure/openai/v1/"
    )


def test_blank_base_is_left_untouched() -> None:
    assert normalize_azure_base_url("") == ""


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    class AsyncOpenAIStub:
        def __init__(self, **kwargs: Any) -> None:
            captured.append(kwargs)

    monkeypatch.setattr(azure_mod, "AsyncOpenAI", AsyncOpenAIStub)
    return captured


def test_client_gets_normalized_base_and_api_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture(monkeypatch)

    azure_mod.AzureOpenAIProvider(
        api_key="sk-test",
        api_base="https://res.openai.azure.com/openai/deployments/gpt-4o/chat/completions",
        default_model="gpt-4o",
    )

    kwargs = captured[0]
    assert kwargs["base_url"] == V1_SURFACE
    # Azure reserves ``Authorization: Bearer`` for Entra tokens; API keys are
    # authenticated through ``api-key``, which the SDK never sends on its own.
    assert kwargs["default_headers"]["api-key"] == "sk-test"


def test_extra_headers_override_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture(monkeypatch)

    azure_mod.AzureOpenAIProvider(
        api_key="sk-test",
        api_base="https://res.openai.azure.com",
        extra_headers={"api-key": "override", "x-custom": "1"},
    )

    headers = captured[0]["default_headers"]
    assert headers["api-key"] == "override"
    assert headers["x-custom"] == "1"


@pytest.mark.parametrize(
    ("api_version", "expected"),
    [
        ("preview", {"api-version": "preview"}),
        ("PREVIEW", {"api-version": "preview"}),
        # A dated version belongs to the classic surface and would be rejected
        # against ``/openai/v1``, so it must not be forwarded.
        ("2024-10-21", None),
        ("", None),
        (None, None),
    ],
)
def test_only_preview_api_version_reaches_the_v1_surface(
    monkeypatch: pytest.MonkeyPatch,
    api_version: str | None,
    expected: dict[str, str] | None,
) -> None:
    captured = _capture(monkeypatch)

    azure_mod.AzureOpenAIProvider(
        api_key="sk-test",
        api_base="https://res.openai.azure.com",
        api_version=api_version,
    )

    assert captured[0]["default_query"] == expected


@pytest.mark.parametrize(
    ("api_key", "api_base", "match"),
    [
        ("", "https://res.openai.azure.com", "api_key is required"),
        ("sk-test", "", "api_base is required"),
    ],
)
def test_missing_credentials_are_rejected(api_key: str, api_base: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        azure_mod.AzureOpenAIProvider(api_key=api_key, api_base=api_base)
