"""The analysis agent must not crash when the LLM returns an illegal
visual_genre — it should degrade to "" and recover gracefully."""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.visualize.agents.analysis_agent import AnalysisAgent
from deeptutor.agents.visualize.models import VisualizationAnalysis


def _llm_reply(visual_genre: str) -> str:
    """A well-formed analysis JSON with a caller-controlled visual_genre."""
    return json.dumps(
        {
            "render_type": "svg",
            "description": "a diagram",
            "data_description": "",
            "chart_type": "",
            "visual_elements": ["box"],
            "rationale": "test",
            "visual_genre": visual_genre,
        }
    )


# Config-free prompt stubs — just enough for get_prompt() to return truthy values.
_FIXED_PROMPTS = {
    "system_fixed": "You are a visualization analyst.",
    "user_template_fixed": "Return JSON: {user_input} {history_context} {render_type}",
}

_AUTO_PROMPTS = {
    "system": "You are a visualization analyst.",
    "user_template": "Return JSON: {user_input} {history_context}",
}


def _install_agent_stubs(
    monkeypatch: pytest.MonkeyPatch,
    prompts: dict[str, str],
    llm_reply: str,
) -> dict[str, Any]:
    """Mock the three things ``AnalysisAgent`` needs for a local test run:

    1. ``get_agent_params`` — returns a dummy dict (avoids agents.yaml).
    2. ``self.prompts`` — pre-populated after ``__init__`` finishes.
    3. ``BaseAgent.call_llm`` — returns *llm_reply*, captures kwargs.
    """
    # (1) Avoid FileNotFoundError in BaseAgent.__init__
    monkeypatch.setattr(
        "deeptutor.agents.base_agent.get_agent_params",
        lambda _module_name: {},
    )

    # (2) After real __init__ runs, overwrite prompts with our stubs.
    real_init = AnalysisAgent.__init__

    def _patched_init(self: AnalysisAgent, **kwargs: Any) -> None:
        real_init(self, **kwargs)
        self.prompts = dict(prompts)

    monkeypatch.setattr(AnalysisAgent, "__init__", _patched_init)

    # (3) Replace the LLM call.
    captured: dict[str, Any] = {}

    async def _fake_call(self: BaseAgent, **kwargs: Any) -> str:
        captured.update(kwargs)
        return llm_reply

    monkeypatch.setattr(BaseAgent, "call_llm", _fake_call)
    return captured


# ── tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_visual_genre_falls_back_to_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent should return visual_genre="" instead of crashing."""
    _install_agent_stubs(monkeypatch, _FIXED_PROMPTS, _llm_reply("simulation"))

    result = await AnalysisAgent().process(
        user_input="explain how a CPU works",
        history_context="",
        render_mode="svg",
    )

    assert isinstance(result, VisualizationAnalysis)
    assert result.visual_genre == ""


@pytest.mark.asyncio
async def test_valid_visual_genre_passes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid values should not be touched by the fallback."""
    _install_agent_stubs(monkeypatch, _FIXED_PROMPTS, _llm_reply("interactive"))

    result = await AnalysisAgent().process(
        user_input="interactive demo of a pendulum",
        history_context="",
        render_mode="html",
    )

    assert result.visual_genre == "interactive"


@pytest.mark.asyncio
async def test_fixed_render_mode_preserves_render_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When visual_genre is illegal, fixed render_type is not affected."""
    _install_agent_stubs(monkeypatch, _FIXED_PROMPTS, _llm_reply("simulation"))

    result = await AnalysisAgent().process(
        user_input="draw a flowchart",
        history_context="",
        render_mode="svg",
    )

    assert result.render_type == "svg"


@pytest.mark.asyncio
async def test_auto_mode_survives_bad_genre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback works in auto mode (the default) too."""
    _install_agent_stubs(monkeypatch, _AUTO_PROMPTS, _llm_reply("simulation"))

    result = await AnalysisAgent().process(
        user_input="help me understand neural networks",
        history_context="",
    )

    assert isinstance(result, VisualizationAnalysis)
    assert result.visual_genre == ""
