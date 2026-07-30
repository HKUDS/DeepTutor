"""Regression tests for visualize.utils.extract_code_block."""

from __future__ import annotations

from deeptutor.agents.visualize.utils import extract_code_block


def test_extract_code_block_closing_fence_without_leading_newline() -> None:
    """Extract a closing fence attached to the final content line."""
    raw = "```mermaid\ngraph TD\n  A-->B```"
    assert extract_code_block(raw, "mermaid") == "graph TD\n  A-->B"
    assert extract_code_block(raw) == "graph TD\n  A-->B"


def test_extract_code_block_normal_fenced_block() -> None:
    """Extract a standard fenced block with its requested language."""
    raw = "```javascript\nconst x = 1;\n```"
    assert extract_code_block(raw, "javascript") == "const x = 1;"


def test_extract_code_block_language_miss_is_empty_for_or_fallback() -> None:
    """Return empty on a language miss so generic extraction can run."""
    cfg = '{"type": "bar", "data": {"labels": ["A"], "datasets": [{"data": [1]}]}}'
    raw = f"```json\n{cfg}\n```\nThanks."
    assert extract_code_block(raw, "javascript") == ""
    extracted = extract_code_block(raw, "javascript") or extract_code_block(raw)
    assert extracted == cfg

