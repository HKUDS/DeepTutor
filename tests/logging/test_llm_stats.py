import pytest

from deeptutor.logging.stats.llm_stats import MODEL_PRICING, get_pricing
from deeptutor.runtime.agentic.usage import UsageTracker


@pytest.mark.parametrize(
    ("model", "pricing_key"),
    [
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("gpt-4", "gpt-4"),
        ("openai/gpt-4o-mini", "gpt-4o-mini"),
        ("gpt-4o-mini-2024-07-18", "gpt-4o-mini"),
    ],
)
def test_get_pricing_prefers_the_most_specific_model(model: str, pricing_key: str) -> None:
    assert get_pricing(model) == MODEL_PRICING[pricing_key]


def test_get_pricing_falls_back_for_an_unknown_model() -> None:
    assert get_pricing("unknown-model") == MODEL_PRICING["gpt-4o-mini"]


def test_usage_tracker_uses_gpt_4o_mini_pricing() -> None:
    tracker = UsageTracker(model="gpt-4o-mini")
    tracker.add_from_response(
        {"prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000}
    )

    assert tracker.summary()["total_cost_usd"] == pytest.approx(0.00075)
