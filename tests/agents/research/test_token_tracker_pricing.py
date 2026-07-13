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
