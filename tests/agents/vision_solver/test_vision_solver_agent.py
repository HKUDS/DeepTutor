"""Regression tests for the geogebra image-analysis agent.

Covers the two defects fixed together:

* ``_call_vision_llm`` passed a nonexistent ``verbose=`` kwarg to
  ``stream_llm``, so *every* image analysis raised ``TypeError`` before any
  model call — the tool was completely broken.
* ``_extract_json`` could not handle the output shapes reasoning VL models
  actually produce (``<think>`` preambles, prose appended after the object),
  so even a successful model call frequently ended in a parse failure.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.agents.vision_solver.vision_solver_agent import VisionSolverAgent


class TestExtractJson:
    @pytest.mark.parametrize(
        "response",
        [
            # Plain object.
            '{"commands": [{"command": "A = (1, 2)"}]}',
            # Markdown-fenced block with prose around it.
            "Here is the analysis:\n```json\n"
            '{"commands": [{"command": "Polygon(A,B,C)"}]}\n```\nThat is all.',
            # Reasoning-model preamble followed by a fenced block.
            "<thinking>Let me look at the figure.</thinking>\n<response>\n```json\n"
            '{"commands": [{"command": "A=(0,0)"}, {"command": "B=(4,0)"}]}\n```\n'
            "</response>",
            # Reasoning-model preamble followed by bare tail JSON.
            "<thinking>This is a parabola.</thinking>\n<response>\n"
            '{"commands": [{"command": "f(x)=x^2"}]}\n</response>',
            # Prose appended after the JSON object.
            'I analyzed it:\n{"commands": [{"command": "Circle((0,0),3)"}]} '
            "and that is the answer.",
            # Inline comments (the original parser tolerated them).
            '{\n// highlight the vertex\n"commands": [{"command": "A = (-3, 0)"}]\n}',
            # Block comments.
            '{\n/* highlight */\n"commands": [{"command": "A = (-3, 0)"}]\n}',
            # Trailing commas — the last-resort path.
            '```json\n{"commands": [{"command": "Line(A,B)",},]}\n```',
        ],
    )
    def test_extracts_commands(self, response: str) -> None:
        data = VisionSolverAgent._extract_json(response)
        assert isinstance(data, dict)
        assert data["commands"]

    def test_prefers_last_fenced_block(self) -> None:
        response = (
            '```json\n{"commands": [{"command": "A = (1, 1)"}]}\n```\n'
            "Wait, the correct figure is:\n```json\n"
            '{"commands": [{"command": "B = (2, 2)"}]}\n```'
        )
        data = VisionSolverAgent._extract_json(response)
        assert data["commands"][0]["command"] == "B = (2, 2)"

    def test_rejects_output_without_json_object(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            VisionSolverAgent._extract_json("I cannot see any figure in this image.")


class TestCallVisionLlmKwargs:
    """Regression: ``_call_vision_llm`` must not pass ``verbose=`` to stream_llm."""

    def test_stream_llm_receives_no_verbose_kwarg(self) -> None:
        agent = VisionSolverAgent.__new__(VisionSolverAgent)
        agent.vision_model = None
        agent.get_model = lambda: "main-model"  # type: ignore[method-assign]

        captured: dict[str, Any] = {}

        async def fake_stream_llm(**kwargs: Any):
            captured.update(kwargs)
            if False:  # pragma: no cover — makes this an async generator
                yield ""

        agent.stream_llm = fake_stream_llm  # type: ignore[method-assign]

        async def run() -> None:
            await agent._call_vision_llm(
                "analyze",
                "data:image/png;base64,AAAA",
            )

        asyncio.run(run())

        # The crash: stream_llm() has no ``verbose`` parameter, so passing it
        # raised TypeError before any model call. Guard against regression.
        assert "verbose" not in captured
        # The multimodal message shape must still be built and routed.
        assert captured["model"] == "main-model"
        content = captured["messages"][0]["content"]
        assert any(part.get("type") == "image_url" for part in content)
