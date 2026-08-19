"""Book calls three pipelines it does not own. Pin those call shapes.

figure and interactive drive VisualizePipeline, animation drives
MathAnimatorPipeline, quiz drives QuestionPipeline. Every one is reached through
a lazy import inside a try/except, so a renamed or dropped parameter upstream
produces a GenerationFailure at compile time — a block that quietly fails for
every reader — rather than anything a type checker or an import would catch.

These assert the arguments book passes are still accepted. They deliberately
check signatures rather than calling the pipelines: the point is a cheap,
always-run tripwire, not an integration test.
"""

from __future__ import annotations

import inspect

import pytest


def _accepted(func) -> set[str]:
    sig = inspect.signature(func)
    return set(sig.parameters) - {"self"}


def _required(func) -> set[str]:
    sig = inspect.signature(func)
    return {
        name
        for name, p in sig.parameters.items()
        if name != "self"
        and p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    }


def _assert_call_is_valid(func, passed: set[str], label: str) -> None:
    accepted, required = _accepted(func), _required(func)
    assert passed <= accepted, f"{label}: book passes unknown args {passed - accepted}"
    assert required <= passed, f"{label}: book omits required args {required - passed}"


# ── visualize (figure, interactive) ─────────────────────────────────────


def test_visualize_pipeline_construction() -> None:
    from deeptutor.agents.visualize.pipeline import VisualizePipeline

    _assert_call_is_valid(
        VisualizePipeline.__init__,
        {"api_key", "base_url", "api_version", "language"},
        "VisualizePipeline()",
    )


def test_visualize_analysis_and_generation_calls() -> None:
    from deeptutor.agents.visualize.pipeline import VisualizePipeline

    _assert_call_is_valid(
        VisualizePipeline.run_analysis,
        {"user_input", "history_context", "render_mode"},
        "run_analysis",
    )
    _assert_call_is_valid(
        VisualizePipeline.run_code_generation,
        {"user_input", "history_context", "analysis"},
        "run_code_generation",
    )


# ── math_animator (animation) ───────────────────────────────────────────


def test_math_animator_request_config_fields() -> None:
    """A pydantic model — check declared fields, not the generated __init__."""
    pytest.importorskip("deeptutor.agents.math_animator.pipeline")
    from deeptutor.agents.math_animator.pipeline import MathAnimatorRequestConfig

    fields = set(MathAnimatorRequestConfig.model_fields)
    passed = {"output_mode", "quality", "style_hint"}
    assert passed <= fields, f"unknown fields {passed - fields}"


def test_math_animator_pipeline_construction() -> None:
    pytest.importorskip("deeptutor.agents.math_animator.pipeline")
    from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline

    _assert_call_is_valid(
        MathAnimatorPipeline.__init__,
        {"api_key", "base_url", "api_version", "language"},
        "MathAnimatorPipeline()",
    )


# ── shared prompt layer ─────────────────────────────────────────────────


def test_the_book_prompt_loader_contract() -> None:
    """Every block now goes through these two; keep their shape pinned."""
    from deeptutor.book.blocks._prompts import get_book_prompt, load_book_prompts

    assert len(_accepted(load_book_prompts)) >= 2
    assert len(_accepted(get_book_prompt)) >= 2
