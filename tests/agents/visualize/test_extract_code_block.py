"""Regression tests for visualize.utils.extract_code_block."""

from __future__ import annotations

from deeptutor.agents.visualize.utils import extract_code_block


def test_extract_code_block_closing_fence_without_leading_newline() -> None:
    raw = "```mermaid\ngraph TD\n  A-->B```"
    assert extract_code_block(raw, "mermaid") == "graph TD\n  A-->B"
    assert extract_code_block(raw) == "graph TD\n  A-->B"


def test_extract_code_block_normal_fenced_block() -> None:
    raw = "```javascript\nconst x = 1;\n```"
    assert extract_code_block(raw, "javascript") == "const x = 1;"
