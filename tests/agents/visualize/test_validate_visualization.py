"""Regression tests for visualize.utils.validate_visualization."""

from __future__ import annotations

from deeptutor.agents.visualize.utils import validate_visualization

_CFG = '{"type": "bar", "data": {"labels": ["A"], "datasets": [{"data": [1]}]}}'


def test_validate_chartjs_accepts_trailing_prose_after_json() -> None:
    """Accept a valid Chart.js object followed by model prose."""
    ok, err = validate_visualization(f"{_CFG}\nThanks!", "chartjs")
    assert ok is True
    assert err == ""


def test_validate_chartjs_accepts_clean_config() -> None:
    """Accept a complete strict-JSON Chart.js configuration."""
    ok, err = validate_visualization(_CFG, "chartjs")
    assert ok is True
    assert err == ""


def test_validate_chartjs_rejects_non_object_json() -> None:
    """Reject valid JSON values that are not Chart.js objects."""
    ok, err = validate_visualization("[1, 2, 3]", "chartjs")
    assert ok is False
    assert "JSON object" in err
