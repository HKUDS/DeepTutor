"""Model-intrinsic request overrides survive a generic binding (issue #938).

Kimi-branded models lock ``temperature`` server-side and answer HTTP 400
``invalid temperature: only 1 is allowed for this model`` to any explicit
value. The ``moonshot`` spec has dropped the parameter for them since before
v1.5.5 — but the override was resolved from the *configured binding*, so it
only fired for someone who had picked ``binding="moonshot"``. #938 picked
``binding="openai"`` and pointed it at Moonshot, which is what most users do
with an OpenAI-compatible endpoint, and kept getting the 400.

The route is not what enforces the limit, so the route is not what should
decide. These tests pin that, and pin the two things that must keep working:
an explicit binding still wins, and the tunable ``moonshot-v1-*`` series
(which carries no "kimi" in its name) keeps the caller's temperature.
"""

from __future__ import annotations

import pytest

from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider
from deeptutor.services.provider_registry import find_by_model, find_by_name, model_overrides_for

_MOONSHOT_BASE = "https://api.moonshot.cn/v1"


def _payload(binding: str | None, model: str) -> dict:
    """Build the request exactly as a chat round would."""
    spec = find_by_name(binding)
    provider = OpenAICompatProvider(
        api_key="test-key",
        api_base=_MOONSHOT_BASE,
        default_model=model,
        spec=spec,
        provider_name=binding,
    )
    return provider._build_kwargs(
        messages=[{"role": "user", "content": "hi"}],
        tools=None,
        model=model,
        max_tokens=256,
        temperature=0.7,
        reasoning_effort=None,
        tool_choice=None,
    )


@pytest.mark.parametrize("binding", ["openai", "moonshot", "azure", "no-such-provider"])
def test_kimi_never_carries_an_explicit_temperature(binding: str) -> None:
    """The reporter's scenario, plus every other route to the same model."""
    assert "temperature" not in _payload(binding, "kimi-k3")


@pytest.mark.parametrize("model", ["moonshot-v1-32k", "moonshot-v1-8k-vision"])
def test_tunable_moonshot_series_keeps_the_callers_temperature(model: str) -> None:
    """These accept temperature; dropping it would silently change sampling."""
    assert _payload("moonshot", model)["temperature"] == pytest.approx(0.7)


@pytest.mark.parametrize("model", ["gpt-4o", "claude-sonnet-5", "deepseek-chat"])
def test_unrelated_models_are_untouched(model: str) -> None:
    assert _payload("openai", model)["temperature"] == pytest.approx(0.7)


def test_configured_binding_wins_over_the_vendor_fallback() -> None:
    """An explicit binding is the user's statement about the route; the
    vendor lookup is only consulted when it says nothing about this model."""
    moonshot = find_by_name("moonshot")
    assert model_overrides_for("kimi-k3", moonshot) == {"temperature": None}
    # Same answer with no binding at all — resolved from the model itself.
    assert model_overrides_for("kimi-k3", None) == {"temperature": None}


def test_a_model_with_no_intrinsic_override_resolves_to_nothing() -> None:
    assert model_overrides_for("gpt-4o", find_by_name("openai")) == {}
    assert model_overrides_for("", find_by_name("moonshot")) == {}
    assert model_overrides_for(None, None) == {}


def test_vendor_prefixed_routing_still_finds_the_model() -> None:
    """Routers advertise Moonshot models as ``moonshotai/kimi-...``; the
    upstream API enforces the same limit whichever name reaches it."""
    assert model_overrides_for("moonshotai/kimi-k2", find_by_name("openai")) == {
        "temperature": None
    }


def test_bare_k3_is_exact_and_does_not_capture_unrelated_short_ids() -> None:
    moonshot = find_by_name("moonshot")
    assert model_overrides_for("k3", moonshot) == {"temperature": None}
    assert model_overrides_for("sk3", moonshot) == {}
    assert model_overrides_for("k30", moonshot) == {}
    assert find_by_model("k3") is moonshot
    assert find_by_model("sk3") is None
