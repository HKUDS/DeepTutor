"""Regression tests for VisionSolverAgent._extract_json."""

from __future__ import annotations

import json

import pytest

from deeptutor.agents.vision_solver.vision_solver_agent import VisionSolverAgent

_PAYLOAD = {"commands": [{"command": "A = (1, 2)"}]}


def test_extract_json_trailing_prose_after_object() -> None:
    raw = json.dumps(_PAYLOAD) + "\nHere is the result {done}."
    assert VisionSolverAgent._extract_json(raw) == _PAYLOAD


def test_extract_json_preface_before_object() -> None:
    raw = "Sure:\n" + json.dumps(_PAYLOAD) + "\n"
    assert VisionSolverAgent._extract_json(raw) == _PAYLOAD


def test_extract_json_fenced_block() -> None:
    raw = "```json\n" + json.dumps(_PAYLOAD) + "\n```"
    assert VisionSolverAgent._extract_json(raw) == _PAYLOAD


def test_extract_json_rejects_non_object() -> None:
    with pytest.raises(json.JSONDecodeError):
        VisionSolverAgent._extract_json("[1, 2, 3]")
