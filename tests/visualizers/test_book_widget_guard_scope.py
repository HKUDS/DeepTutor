"""The HTML-widget guard must not run for non-HTML book figures."""

import asyncio

from deeptutor.agents.visualize.agents import code_generator_agent as mod
from deeptutor.agents.visualize.models import VisualizationAnalysis


def test_mermaid_book_figure_skips_html_widget_validation(monkeypatch):
    agent = mod.CodeGeneratorAgent()

    async def fake_call(**kwargs):
        outcome = kwargs.get("outcome")
        if outcome is not None:
            outcome.finish_reason = "stop"
            outcome.usage = {}
        return "graph TD\n  a-->b"

    monkeypatch.setattr(agent, "call_llm", fake_call)

    def boom(*args, **kwargs):
        raise AssertionError("html widget validation ran for a mermaid figure")

    monkeypatch.setattr(mod, "validate_book_widget_html", boom)
    analysis = VisualizationAnalysis(render_type="mermaid", description="mindmap")
    out = asyncio.run(
        agent.process(
            user_input="u",
            history_context="",
            analysis=analysis,
            book_block_id="blk_x",
        )
    )
    assert out.startswith("graph TD")


def test_html_book_figure_still_validated(monkeypatch):
    agent = mod.CodeGeneratorAgent()

    async def fake_call(**kwargs):
        outcome = kwargs.get("outcome")
        if outcome is not None:
            outcome.finish_reason = "stop"
            outcome.usage = {}
        return "<html><body>hi</body></html>"

    monkeypatch.setattr(agent, "call_llm", fake_call)
    calls = []

    def fake_validate(code):
        calls.append(code)
        return True, ""

    monkeypatch.setattr(mod, "validate_book_widget_html", fake_validate)
    analysis = VisualizationAnalysis(render_type="html", description="widget")
    asyncio.run(
        agent.process(
            user_input="u",
            history_context="",
            analysis=analysis,
            book_block_id="blk_x",
        )
    )
    assert len(calls) == 1
