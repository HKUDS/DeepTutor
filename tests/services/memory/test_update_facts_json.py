"""Regression: memory update fact JSON tolerates trailing brace prose."""

from __future__ import annotations

from deeptutor.services.memory.consolidator.modes import update as update_mode


def test_parse_facts_tolerates_trailing_brace_prose() -> None:
    raw = '{"facts":[{"text":"hello","section":"Notes","refs":["a:b"]}]} trailing {note}'
    facts = update_mode._parse_facts(raw)
    assert len(facts) == 1
    assert facts[0].text == "hello"
    assert facts[0].section == "Notes"
