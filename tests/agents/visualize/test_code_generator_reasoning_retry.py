"""Visualize code generation retries once at low reasoning effort when starved (#2914)."""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.visualize.agents.code_generator_agent import CodeGeneratorAgent
from deeptutor.agents.visualize.models import VisualizationAnalysis
from deeptutor.services.llm.reasoning_params import RETRY_REASONING_EFFORT

_COMPLETE_HTML = (
    "<!DOCTYPE html>\n"
    '<html lang="en">\n'
    '<head><meta charset="UTF-8"><title>Demo</title></head>\n'
    '<body><div id="app">Ready</div><script>const ok = true;</script></body>\n'
    "</html>"
)
_COMPLETE_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60"><rect width="80" height="40"/></svg>'


def _analysis(render_type: str = "html") -> VisualizationAnalysis:
    return VisualizationAnalysis(
        render_type=render_type,  # type: ignore[arg-type]
        description="interactive diagram",
        data_description="",
        chart_type="interactive",
        visual_elements=["panel"],
        rationale="test",
    )


def _stub_call_llm(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    queue = list(replies)

    async def _call_llm(self: BaseAgent, **kwargs: Any) -> str:
        calls.append(kwargs)
        return queue.pop(0)

    monkeypatch.setattr(BaseAgent, "call_llm", _call_llm)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("render_type", "first_reply", "second_reply", "expected"),
    [
        ("html", "", f"```html\n{_COMPLETE_HTML}\n```", _COMPLETE_HTML),
        ("svg", "", f"```svg\n{_COMPLETE_SVG}\n```", _COMPLETE_SVG),
        (
            "html",
            "<think>Planning every control and SVG coordinate first.</think>",
            f"```html\n{_COMPLETE_HTML}\n```",
            _COMPLETE_HTML,
        ),
        (
            "html",
            "<think>Cut off mid-thought while mentioning <html> and </html>",
            f"```html\n{_COMPLETE_HTML}\n```",
            _COMPLETE_HTML,
        ),
        (
            "html",
            "```html\n<!DOCTYPE html>\n<html><body><script>if (startHour",
            f"```html\n{_COMPLETE_HTML}\n```",
            _COMPLETE_HTML,
        ),
    ],
    ids=[
        "empty-html-from-reasoning-starvation",
        "empty-svg-from-reasoning-starvation",
        "closed-think-only",
        "unclosed-think-mentioning-html-tags",
        "truncated-html-before-closing-tag",
    ],
)
async def test_code_generator_retries_once_with_low_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
    render_type: str,
    first_reply: str,
    second_reply: str,
    expected: str,
) -> None:
    calls = _stub_call_llm(monkeypatch, [first_reply, second_reply])

    result = await CodeGeneratorAgent().process(
        user_input="build an interactive chart",
        history_context="",
        analysis=_analysis(render_type),
    )

    assert result == expected
    assert [call.get("reasoning_effort") for call in calls] == [None, RETRY_REASONING_EFFORT]
    assert calls[0]["trace_meta"]["call_id"] != calls[1]["trace_meta"]["call_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        f"<think>Short plan.</think>\n```html\n{_COMPLETE_HTML}\n```",
        f"```html\n{_COMPLETE_HTML}",
        "```html\n<!DOCTYPE html>\n<html><body><pre>\n```js\nconst x = 1;\n```\n</pre></body></html>\n```",
    ],
    ids=[
        "think-prelude-then-complete-html",
        "complete-html-with-open-fence",
        "html-with-nested-fence-in-pre",
    ],
)
async def test_code_generator_does_not_retry_usable_first_response(
    monkeypatch: pytest.MonkeyPatch,
    reply: str,
) -> None:
    calls = _stub_call_llm(monkeypatch, [reply])

    result = await CodeGeneratorAgent().process(
        user_input="build an interactive chart",
        history_context="",
        analysis=_analysis("html"),
    )

    assert result.startswith("<!DOCTYPE html>") and result.endswith("</html>")
    assert [call.get("reasoning_effort") for call in calls] == [None]


@pytest.mark.asyncio
async def test_code_generator_stops_after_single_reasoning_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_call_llm(monkeypatch, ["", "<think>Still only thinking.</think>"])

    result = await CodeGeneratorAgent().process(
        user_input="build an interactive chart",
        history_context="",
        analysis=_analysis("html"),
    )

    assert result == ""
    assert [call.get("reasoning_effort") for call in calls] == [None, RETRY_REASONING_EFFORT]


@pytest.mark.asyncio
async def test_code_generator_keeps_non_empty_candidate_when_retry_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    truncated = "<!DOCTYPE html>\n<html><body><script>if (startHour"
    calls = _stub_call_llm(monkeypatch, [truncated, ""])

    result = await CodeGeneratorAgent().process(
        user_input="build an interactive chart",
        history_context="",
        analysis=_analysis("html"),
    )

    assert result == truncated
    assert [call.get("reasoning_effort") for call in calls] == [None, RETRY_REASONING_EFFORT]
