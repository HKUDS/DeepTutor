from __future__ import annotations

from pathlib import Path
import re

import yaml

PROMPT_DIR = Path(__file__).resolve().parents[2] / "deeptutor" / "co_writer" / "prompts"
SPAN_TOKEN_RE = re.compile(r"<span\b|</span>")


def _load_auto_mark_prompt(language: str) -> str:
    path = PROMPT_DIR / language / "edit_agent.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))["auto_mark_system"]


def test_auto_mark_examples_do_not_nest_annotations() -> None:
    for language in ("en", "zh"):
        prompt = _load_auto_mark_prompt(language)
        depth = 0
        for token in SPAN_TOKEN_RE.findall(prompt):
            depth += 1 if token == "<span" else -1
            assert depth <= 1, f"{language} auto-mark prompt nests annotation spans"
        assert depth == 0, f"{language} auto-mark prompt has unbalanced annotation spans"


def test_auto_mark_contract_forbids_nested_annotations() -> None:
    assert "Never place one annotation span inside another" in _load_auto_mark_prompt("en")
    assert "不要在一个标注标签内部再放置另一个标注标签" in _load_auto_mark_prompt("zh")
