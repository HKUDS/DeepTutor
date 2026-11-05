"""Pricing table regression tests for research token tracking."""

from deeptutor.agents.research.utils.token_tracker import get_model_pricing


def test_deepseek_v4_pricing_entries() -> None:
    assert get_model_pricing("deepseek-v4-flash") == {
        "input": 0.00014,
        "output": 0.00028,
    }
    assert get_model_pricing("deepseek-v4-pro") == {
        "input": 0.000435,
        "output": 0.00087,
    }


def test_dated_and_prefixed_mini_models_use_mini_pricing() -> None:
    mini = {"input": 0.00015, "output": 0.0006}
    assert get_model_pricing("gpt-4o-mini-2024-07-18") == mini
    assert get_model_pricing("openai/gpt-4o-mini") == mini


def test_dated_full_model_keeps_full_pricing() -> None:
    assert get_model_pricing("gpt-4o-2024-08-06") == {"input": 0.0025, "output": 0.010}
    assert get_model_pricing("gpt-4-turbo-2024-04-09") == {"input": 0.01, "output": 0.03}
