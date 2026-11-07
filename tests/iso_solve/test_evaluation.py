"""
Comprehensive tests for the iso_solve benchmark evaluation pipeline.

Covers:
  - LLM capabilities (response_format, binding, model overrides) with OpenRouter scenarios
  - BaseAgent.call_llm() binding propagation and response_format handling
  - BenchmarkRunner: direct mode, pipeline mode, error handling
  - Answer extractor: normal, edge cases, LLM failure fallback
  - Answer judge: correct, incorrect, ambiguous, fallback
  - BenchmarkReport: aggregation, breakdowns, accuracy
  - BenchmarkAdapter: request building, extract/judge fallbacks
  - Pipeline call: solver integration

Run:
    pytest tests/iso_solve/test_evaluation.py -v
"""

from __future__ import annotations

import argparse
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from benchmark.iso_solve.core.types import BenchmarkReport, EvalResult, Problem

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_problem(**overrides: Any) -> Problem:
    defaults = dict(
        id="p001",
        question="What is 2+2?",
        ground_truth="4",
        benchmark="test",
        system_prompt="You are a math tutor.",
        metadata={"level": "easy", "subject": "Algebra"},
    )
    defaults.update(overrides)
    return Problem(**defaults)


def _make_result(correct: bool = True, error: str | None = None, **kw: Any) -> EvalResult:
    prob = kw.pop("problem", _make_problem())
    return EvalResult(
        problem=prob,
        model_output=kw.get("model_output", "The answer is 4"),
        extracted_answer=kw.get("extracted_answer", "4"),
        correct=correct,
        score=1.0 if correct else 0.0,
        elapsed_sec=kw.get("elapsed_sec", 1.5),
        judge_reasoning=kw.get("judge_reasoning", "CORRECT"),
        error=error,
    )


# ===================================================================
# 1. LLM Capabilities — OpenRouter / proxy model scenarios
# ===================================================================

class TestCapabilitiesOpenRouter:
    """Verify response_format and system_in_messages work correctly
    for Claude/Anthropic models routed through OpenRouter (binding=openai)."""

    def test_openrouter_claude_supports_response_format(self) -> None:
        from src.services.llm.capabilities import supports_response_format

        assert supports_response_format("openai", "anthropic/claude-sonnet-4.5") is True

    def test_openrouter_claude_system_in_messages(self) -> None:
        from src.services.llm.capabilities import system_in_messages

        assert system_in_messages("openai", "anthropic/claude-sonnet-4.5") is True

    def test_openrouter_claude_short_name(self) -> None:
        from src.services.llm.capabilities import supports_response_format

        assert supports_response_format("openai", "claude-3-5-sonnet-20241022") is True

    def test_native_anthropic_no_response_format(self) -> None:
        from src.services.llm.capabilities import supports_response_format

        assert supports_response_format("anthropic", "claude-sonnet-4.5") is False
        assert supports_response_format("claude", "claude-3-5-sonnet") is False

    def test_native_anthropic_system_not_in_messages(self) -> None:
        from src.services.llm.capabilities import system_in_messages

        assert system_in_messages("anthropic", "claude-sonnet-4.5") is False

    def test_deepseek_via_openai_no_response_format(self) -> None:
        from src.services.llm.capabilities import supports_response_format

        assert supports_response_format("openai", "deepseek-reasoner") is False
        assert supports_response_format("openai", "deepseek-chat") is False

    def test_openrouter_binding_supports_response_format(self) -> None:
        from src.services.llm.capabilities import supports_response_format

        assert supports_response_format("openrouter", "anthropic/claude-sonnet-4.5") is True

    def test_reasoning_model_forced_temperature(self) -> None:
        from src.services.llm.capabilities import get_effective_temperature

        assert get_effective_temperature("openai", "gpt-5-mini", 0.5) == 1.0
        assert get_effective_temperature("openai", "o3-mini", 0.0) == 1.0
        assert get_effective_temperature("openai", "gpt-4o", 0.4) == 0.4

    def test_thinking_tags_deepseek(self) -> None:
        from src.services.llm.capabilities import has_thinking_tags

        assert has_thinking_tags("openai", "deepseek-reasoner") is True
        assert has_thinking_tags("openai", "qwq-32b") is True
        assert has_thinking_tags("openai", "anthropic/claude-sonnet-4.5") is False

    def test_token_limit_kwargs_newer_models(self) -> None:
        from src.services.llm.config import get_token_limit_kwargs

        assert get_token_limit_kwargs("gpt-4o", 4096) == {"max_completion_tokens": 4096}
        assert get_token_limit_kwargs("o3-mini", 8192) == {"max_completion_tokens": 8192}
        assert get_token_limit_kwargs("gpt-5-mini", 4096) == {"max_completion_tokens": 4096}

    def test_token_limit_kwargs_anthropic_model(self) -> None:
        from src.services.llm.config import get_token_limit_kwargs

        assert get_token_limit_kwargs("anthropic/claude-sonnet-4.5", 4096) == {"max_tokens": 4096}
        assert get_token_limit_kwargs("claude-3-5-sonnet", 8192) == {"max_tokens": 8192}


# ===================================================================
# 2. BaseAgent — binding propagation and response_format
# ===================================================================

class TestBaseAgentCallLLM:
    """Test that BaseAgent.call_llm() correctly propagates binding
    and handles response_format for various provider configurations."""

    @pytest.mark.asyncio
    async def test_call_llm_passes_binding_to_factory(self) -> None:
        from src.agents.base_agent import BaseAgent

        class _TestAgent(BaseAgent):
            async def process(self, *args: Any, **kwargs: Any) -> Any:
                return None

        with patch("src.agents.base_agent.get_llm_config") as mock_cfg, \
             patch("src.agents.base_agent.llm_complete", new_callable=AsyncMock) as mock_llm:
            mock_cfg.return_value = MagicMock(
                api_key="test-key", base_url="https://openrouter.ai/api/v1",
                model="anthropic/claude-sonnet-4.5", binding="openai",
                api_version=None,
            )
            mock_llm.return_value = "test response"

            agent = _TestAgent(
                module_name="solve", agent_name="test_agent",
                api_key="key", base_url="https://openrouter.ai/api/v1",
                model="anthropic/claude-sonnet-4.5",
            )

            await agent.call_llm(
                user_prompt="hello", system_prompt="you are helpful",
            )

            call_kwargs = mock_llm.call_args
            assert call_kwargs.kwargs.get("binding") == "openai"

    @pytest.mark.asyncio
    async def test_call_llm_includes_response_format_for_openrouter_claude(self) -> None:
        from src.agents.base_agent import BaseAgent

        class _TestAgent(BaseAgent):
            async def process(self, *args: Any, **kwargs: Any) -> Any:
                return None

        with patch("src.agents.base_agent.get_llm_config") as mock_cfg, \
             patch("src.agents.base_agent.llm_complete", new_callable=AsyncMock) as mock_llm:
            mock_cfg.return_value = MagicMock(
                api_key="key", base_url="https://openrouter.ai/api/v1",
                model="anthropic/claude-sonnet-4.5", binding="openai",
                api_version=None,
            )
            mock_llm.return_value = '{"analysis": "test", "steps": []}'

            agent = _TestAgent(
                module_name="solve", agent_name="test_agent",
                api_key="key", base_url="https://openrouter.ai/api/v1",
                model="anthropic/claude-sonnet-4.5",
            )

            await agent.call_llm(
                user_prompt="plan this",
                system_prompt="you are a planner",
                response_format={"type": "json_object"},
            )

            call_kwargs = mock_llm.call_args
            assert "response_format" in call_kwargs.kwargs
            assert call_kwargs.kwargs["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_call_llm_skips_response_format_for_native_anthropic(self) -> None:
        from src.agents.base_agent import BaseAgent

        class _TestAgent(BaseAgent):
            async def process(self, *args: Any, **kwargs: Any) -> Any:
                return None

        with patch("src.agents.base_agent.get_llm_config") as mock_cfg, \
             patch("src.agents.base_agent.llm_complete", new_callable=AsyncMock) as mock_llm:
            mock_cfg.return_value = MagicMock(
                api_key="key", base_url="https://api.anthropic.com/v1",
                model="claude-sonnet-4.5", binding="anthropic",
                api_version=None,
            )
            mock_llm.return_value = '{"result": "ok"}'

            agent = _TestAgent(
                module_name="solve", agent_name="test_agent",
                api_key="key", base_url="https://api.anthropic.com/v1",
                model="claude-sonnet-4.5", binding="anthropic",
            )

            await agent.call_llm(
                user_prompt="plan this",
                system_prompt="you are a planner",
                response_format={"type": "json_object"},
            )

            call_kwargs = mock_llm.call_args
            assert "response_format" not in call_kwargs.kwargs


# ===================================================================
# 3. Answer Extractor
# ===================================================================

class TestExtractor:
    """extractor.py uses `from src.services.llm import complete` inside the
    function body, so we must mock at the source: ``src.services.llm.complete``."""

    _PATCH = "src.services.llm.complete"

    @pytest.mark.asyncio
    async def test_extract_clean_answer(self) -> None:
        from benchmark.iso_solve.core.extractor import extract_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "42"
            ans = await extract_answer("What is 6*7?", "Let me think... 6*7 = 42.")
            assert ans == "42"

    @pytest.mark.asyncio
    async def test_extract_strips_answer_prefix(self) -> None:
        from benchmark.iso_solve.core.extractor import extract_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "Answer: 42"
            ans = await extract_answer("Q", "output")
            assert ans == "42"

    @pytest.mark.asyncio
    async def test_extract_multiline_takes_first(self) -> None:
        from benchmark.iso_solve.core.extractor import extract_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "42\nI'm confident about this."
            ans = await extract_answer("Q", "output")
            assert ans == "42"

    @pytest.mark.asyncio
    async def test_extract_none_response(self) -> None:
        from benchmark.iso_solve.core.extractor import extract_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "NONE"
            ans = await extract_answer("Q", "I don't know")
            assert ans is None

    @pytest.mark.asyncio
    async def test_extract_empty_response(self) -> None:
        from benchmark.iso_solve.core.extractor import extract_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "   "
            ans = await extract_answer("Q", "output")
            assert ans is None

    @pytest.mark.asyncio
    async def test_extract_llm_failure_returns_none(self) -> None:
        from benchmark.iso_solve.core.extractor import extract_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("API timeout")
            ans = await extract_answer("Q", "output")
            assert ans is None

    @pytest.mark.asyncio
    async def test_extract_truncates_long_output(self) -> None:
        from benchmark.iso_solve.core.extractor import extract_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "42"
            long_output = "x" * 100_000
            await extract_answer("Q", long_output, max_tokens=256)
            prompt_arg = mock.call_args.kwargs["prompt"]
            assert "...(truncated)" in prompt_arg


# ===================================================================
# 4. Answer Judge
# ===================================================================

class TestJudge:
    """judge.py uses `from src.services.llm import complete` inside the
    function body, so we must mock at the source."""

    _PATCH = "src.services.llm.complete"

    @pytest.mark.asyncio
    async def test_judge_correct(self) -> None:
        from benchmark.iso_solve.core.judge import judge_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "CORRECT"
            correct, reasoning = await judge_answer("Q", "4", "4")
            assert correct is True
            assert "CORRECT" in reasoning

    @pytest.mark.asyncio
    async def test_judge_incorrect(self) -> None:
        from benchmark.iso_solve.core.judge import judge_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "INCORRECT"
            correct, reasoning = await judge_answer("Q", "5", "4")
            assert correct is False

    @pytest.mark.asyncio
    async def test_judge_ambiguous_falls_back_to_string_match(self) -> None:
        from benchmark.iso_solve.core.judge import judge_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "I think it might be right?"
            correct, reasoning = await judge_answer("Q", "4", "4")
            assert correct is True
            assert "Ambiguous" in reasoning

    @pytest.mark.asyncio
    async def test_judge_ambiguous_no_match(self) -> None:
        from benchmark.iso_solve.core.judge import judge_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "Hmm, unsure"
            correct, reasoning = await judge_answer("Q", "5", "4")
            assert correct is False

    @pytest.mark.asyncio
    async def test_judge_none_predicted(self) -> None:
        from benchmark.iso_solve.core.judge import judge_answer

        correct, reasoning = await judge_answer("Q", None, "4")
        assert correct is False
        assert "No extracted answer" in reasoning

    @pytest.mark.asyncio
    async def test_judge_llm_failure_falls_back(self) -> None:
        from benchmark.iso_solve.core.judge import judge_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.side_effect = RuntimeError("API error")
            correct, reasoning = await judge_answer("Q", "4", "4")
            assert correct is True
            assert "Judge failed" in reasoning

    @pytest.mark.asyncio
    async def test_judge_with_hint(self) -> None:
        from benchmark.iso_solve.core.judge import judge_answer

        with patch(self._PATCH, new_callable=AsyncMock) as mock:
            mock.return_value = "CORRECT"
            await judge_answer("Q", "4", "4", judge_hint="Compare numerically.")
            prompt = mock.call_args.kwargs["prompt"]
            assert "Compare numerically" in prompt


# ===================================================================
# 5. BenchmarkReport — aggregation, breakdowns, accuracy
# ===================================================================

class TestBenchmarkReport:
    def test_empty_report(self) -> None:
        r = BenchmarkReport("test", "direct", "model", "20260101")
        assert r.total == 0
        assert r.accuracy == 0.0
        assert r.accuracy_pct == 0.0
        assert r.confidence_interval == 0.0

    def test_add_correct_result(self) -> None:
        r = BenchmarkReport("test", "direct", "model", "20260101")
        r.add(_make_result(correct=True), ["level", "subject"])
        assert r.total == 1
        assert r.correct == 1
        assert r.accuracy_pct == 100.0

    def test_add_incorrect_result(self) -> None:
        r = BenchmarkReport("test", "direct", "model", "20260101")
        r.add(_make_result(correct=False), [])
        assert r.total == 1
        assert r.correct == 0
        assert r.accuracy_pct == 0.0

    def test_add_error_result_not_counted_as_correct(self) -> None:
        r = BenchmarkReport("test", "direct", "model", "20260101")
        r.add(_make_result(correct=False, error="timeout"), [])
        assert r.total == 1
        assert r.errors == 1
        assert r.correct == 0

    def test_breakdowns_by_metadata(self) -> None:
        r = BenchmarkReport("test", "direct", "model", "20260101")
        r.add(_make_result(correct=True), ["level", "subject"])
        r.add(
            _make_result(
                correct=False,
                problem=_make_problem(metadata={"level": "hard", "subject": "Geometry"}),
            ),
            ["level", "subject"],
        )

        assert "by_level" in r.breakdowns
        assert r.breakdowns["by_level"]["easy"]["total"] == 1
        assert r.breakdowns["by_level"]["easy"]["correct"] == 1
        assert r.breakdowns["by_level"]["hard"]["total"] == 1
        assert r.breakdowns["by_level"]["hard"]["correct"] == 0

        assert "by_subject" in r.breakdowns
        assert r.breakdowns["by_subject"]["Algebra"]["correct"] == 1
        assert r.breakdowns["by_subject"]["Geometry"]["correct"] == 0

    def test_mixed_results_accuracy(self) -> None:
        r = BenchmarkReport("test", "direct", "model", "20260101")
        for i in range(10):
            r.add(_make_result(correct=(i < 7)), [])
        assert r.total == 10
        assert r.correct == 7
        assert r.accuracy_pct == 70.0

    def test_summary_lines(self) -> None:
        r = BenchmarkReport("test", "direct", "model-x", "20260101")
        r.add(_make_result(correct=True), ["level"])
        lines = r.summary_lines()
        text = "\n".join(lines)
        assert "model-x" in text
        assert "direct" in text
        assert "100.0%" in text

    def test_to_dict_structure(self) -> None:
        r = BenchmarkReport("test", "pipeline", "model", "20260101")
        r.add(_make_result(correct=True), ["level"])
        d = r.to_dict()
        assert d["benchmark"] == "test"
        assert d["mode"] == "pipeline"
        assert d["overall"]["total"] == 1
        assert d["overall"]["correct"] == 1
        assert len(d["results"]) == 1
        assert d["results"][0]["correct"] is True

    def test_confidence_interval(self) -> None:
        r = BenchmarkReport("test", "direct", "model", "20260101")
        for i in range(100):
            r.add(_make_result(correct=(i < 70)), [])
        ci = r.confidence_interval
        assert ci > 0
        assert ci < 20


# ===================================================================
# 6. BenchmarkAdapter — request building and fallbacks
# ===================================================================

class TestBenchmarkAdapter:
    def _make_adapter(self) -> Any:
        from benchmark.iso_solve.eval.base import BenchmarkAdapter

        class _Stub(BenchmarkAdapter):
            name = "stub"
            def load_dataset(self, *a: Any, **kw: Any) -> list: return []
            def filter_problems(self, problems: list, *a: Any, **kw: Any) -> list: return problems

        return _Stub()

    def test_default_build_direct_request(self) -> None:
        adapter = self._make_adapter()
        prob = _make_problem()
        req = adapter.build_direct_request(prob)
        assert "messages" in req
        assert req["messages"][0]["role"] == "system"
        assert req["messages"][1]["role"] == "user"

    def test_default_build_pipeline_request(self) -> None:
        adapter = self._make_adapter()
        prob = _make_problem()
        req = adapter.build_pipeline_request(prob)
        assert req["prompt"] == prob.question
        assert req["image_url"] is None

    def test_extract_fallback(self) -> None:
        adapter = self._make_adapter()
        assert adapter.extract_fallback("  42  ") == "42"
        assert adapter.extract_fallback("") is None
        assert adapter.extract_fallback("   ") is None

    def test_judge_fallback_exact_match(self) -> None:
        adapter = self._make_adapter()
        prob = _make_problem(ground_truth="Paris")
        assert adapter.judge_fallback(prob, "Paris")[0] is True
        assert adapter.judge_fallback(prob, "paris")[0] is True
        assert adapter.judge_fallback(prob, "London")[0] is False
        assert adapter.judge_fallback(prob, None)[0] is False


# ===================================================================
# 7. BenchmarkRunner — direct mode (mocked LLM)
# ===================================================================

def _make_stub_adapter(problems: list[Problem] | None = None) -> Any:
    from benchmark.iso_solve.eval.base import BenchmarkAdapter

    class _StubAdapter(BenchmarkAdapter):
        name = "stub"
        breakdown_keys = ["level"]

        def load_dataset(self, bench_cfg: dict, args: Any) -> list[Problem]:
            if problems is not None:
                return list(problems)
            return [
                _make_problem(id="p1", question="2+2?", ground_truth="4"),
                _make_problem(id="p2", question="3+3?", ground_truth="6"),
            ]

        def filter_problems(self, probs: list, bench_cfg: dict, args: Any) -> list:
            return probs

    return _StubAdapter()


class TestRunnerDirectMode:

    @pytest.mark.asyncio
    async def test_direct_mode_full_run(self, tmp_path: Any) -> None:
        from benchmark.iso_solve.core.runner import BenchmarkRunner

        mock_extractor = AsyncMock(side_effect=["4", "7"])
        mock_judge = AsyncMock(side_effect=[(True, "CORRECT"), (False, "INCORRECT")])
        runner = BenchmarkRunner(_make_stub_adapter(), mock_extractor, mock_judge)

        args = argparse.Namespace(
            mode="direct", dry_run=False, output=str(tmp_path),
            benchmark="stub", config="", limit=None, seed=42,
        )
        cfg = {
            "evaluation": {"llm_extract": True, "llm_judge": True},
            "output_dir": str(tmp_path),
            "stub": {
                "llm": {"model": "test-model", "temperature": 0.0, "max_tokens": 128},
                "concurrency": 2,
            },
        }

        with patch("src.services.llm.config.get_llm_config") as mock_llm_cfg, \
             patch.object(BenchmarkRunner, "_direct_call",
                          new_callable=AsyncMock) as mock_call:
            mock_llm_cfg.return_value = MagicMock(
                model="test-model", api_key="k", base_url="https://example.com/v1",
            )
            mock_call.side_effect = ["The answer is 4", "The answer is 7"]

            report = await runner.run(args, cfg)

        assert report.total == 2
        assert report.correct == 1
        assert report.errors == 0
        assert report.accuracy_pct == 50.0

    @pytest.mark.asyncio
    async def test_direct_mode_dry_run(self, tmp_path: Any) -> None:
        from benchmark.iso_solve.core.runner import BenchmarkRunner

        runner = BenchmarkRunner(_make_stub_adapter(), AsyncMock(), AsyncMock())
        args = argparse.Namespace(
            mode="direct", dry_run=True, output=str(tmp_path),
            benchmark="stub", config="", limit=None, seed=42,
        )
        cfg = {
            "output_dir": str(tmp_path),
            "stub": {"llm": {"model": "m"}, "concurrency": 1},
        }

        with patch("src.services.llm.config.get_llm_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(model="m", api_key="k", base_url="u")
            report = await runner.run(args, cfg)

        assert report.total == 0

    @pytest.mark.asyncio
    async def test_direct_mode_llm_error_captured(self, tmp_path: Any) -> None:
        """Problem 1 errors from _direct_call → extractor/judge are NOT called
        for it. Only problem 2 goes through extractor + judge."""
        from benchmark.iso_solve.core.runner import BenchmarkRunner

        mock_extractor = AsyncMock(return_value="6")
        mock_judge = AsyncMock(return_value=(True, "CORRECT"))
        runner = BenchmarkRunner(_make_stub_adapter(), mock_extractor, mock_judge)

        args = argparse.Namespace(
            mode="direct", dry_run=False, output=str(tmp_path),
            benchmark="stub", config="", limit=None, seed=42,
        )
        cfg = {
            "evaluation": {"llm_extract": True, "llm_judge": True},
            "output_dir": str(tmp_path),
            "stub": {"llm": {"model": "m", "temperature": 0, "max_tokens": 128}, "concurrency": 2},
        }

        with patch("src.services.llm.config.get_llm_config") as mock_llm_cfg, \
             patch.object(BenchmarkRunner, "_direct_call",
                          new_callable=AsyncMock) as mock_call:
            mock_llm_cfg.return_value = MagicMock(model="m", api_key="k", base_url="u")
            mock_call.side_effect = [RuntimeError("API 500"), "The answer is 6"]

            report = await runner.run(args, cfg)

        assert report.total == 2
        assert report.errors == 1
        assert report.correct == 1


# ===================================================================
# 8. BenchmarkRunner — pipeline mode (mocked solver)
# ===================================================================

class TestRunnerPipelineMode:

    @pytest.mark.asyncio
    async def test_pipeline_mode_calls_solver(self, tmp_path: Any) -> None:
        from benchmark.iso_solve.core.runner import BenchmarkRunner
        from benchmark.iso_solve.eval.base import BenchmarkAdapter

        class _StubAdapter(BenchmarkAdapter):
            name = "stub"
            skip_extract = True
            breakdown_keys = []

            def load_dataset(self, *a: Any, **kw: Any) -> list[Problem]:
                return [_make_problem(id="p1", question="Q1", ground_truth="A1")]

            def filter_problems(self, problems: list, *a: Any, **kw: Any) -> list:
                return problems

        mock_judge = AsyncMock(return_value=(True, "CORRECT"))
        runner = BenchmarkRunner(_StubAdapter(), AsyncMock(), mock_judge)

        args = argparse.Namespace(
            mode="pipeline", dry_run=False, output=str(tmp_path),
            benchmark="stub", config="", limit=None, seed=42,
        )
        cfg = {
            "evaluation": {"llm_extract": False, "llm_judge": True},
            "output_dir": str(tmp_path),
            "stub": {
                "llm": {"model": "m", "temperature": 0, "max_tokens": 128},
                "pipeline": {
                    "model": "test-model",
                    "tools": ["code_execute", "reason"],
                    "language": "en",
                    "concurrency": 1,
                },
            },
        }

        with patch("src.services.llm.config.get_llm_config") as mock_llm_cfg, \
             patch("benchmark.iso_solve.core.runner.run_solver_pipeline",
                   new_callable=AsyncMock) as mock_pipeline:
            mock_llm_cfg.return_value = MagicMock(model="m", api_key="k", base_url="u")
            mock_pipeline.return_value = {"final_answer": "A1"}

            report = await runner.run(args, cfg)

        assert report.total == 1
        assert report.correct == 1
        mock_pipeline.assert_called_once()
        call_kwargs = mock_pipeline.call_args.kwargs
        assert call_kwargs["language"] == "en"
        assert "code_execute" in call_kwargs["tools"]


# ===================================================================
# 9. Pipeline integration — run_solver_pipeline
# ===================================================================

class TestRunSolverPipeline:
    """pipeline.py uses lazy imports: `from src.agents.solve import MainSolver`
    and `from src.agents.solve.tools import ToolRegistry`. Mock at source."""

    @pytest.mark.asyncio
    async def test_pipeline_creates_solver_and_calls_solve(self) -> None:
        from benchmark.iso_solve.core.pipeline import run_solver_pipeline

        mock_solver = MagicMock()
        mock_solver.ainit = AsyncMock()
        mock_solver.solve = AsyncMock(return_value={
            "final_answer": "42",
            "output_md": "## Solution\n42",
        })

        with patch("src.agents.solve.MainSolver",
                   return_value=mock_solver) as mock_cls:
            result = await run_solver_pipeline(
                question="What is 6*7?",
                workspace="/tmp/test",
                language="en",
                tools=["code_execute", "reason"],
                model="test-model",
                max_tokens=4096,
                temperature=0.5,
            )

        assert result["final_answer"] == "42"
        mock_solver.ainit.assert_called_once()
        mock_solver.solve.assert_called_once_with("What is 6*7?", image_url=None)

        init_kwargs = mock_cls.call_args.kwargs
        assert init_kwargs["model"] == "test-model"
        assert init_kwargs["language"] == "en"
        assert init_kwargs["disable_memory"] is True
        assert init_kwargs["max_tokens"] == 4096
        assert init_kwargs["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_pipeline_with_image_url(self) -> None:
        from benchmark.iso_solve.core.pipeline import run_solver_pipeline

        mock_solver = MagicMock()
        mock_solver.ainit = AsyncMock()
        mock_solver.solve = AsyncMock(return_value={"final_answer": "cat"})

        with patch("src.agents.solve.MainSolver",
                   return_value=mock_solver):
            result = await run_solver_pipeline(
                question="What is in this image?",
                workspace="/tmp/test",
                image_url="https://example.com/image.jpg",
            )

        assert result["final_answer"] == "cat"
        mock_solver.solve.assert_called_once_with(
            "What is in this image?", image_url="https://example.com/image.jpg",
        )

    @pytest.mark.asyncio
    async def test_pipeline_default_tools(self) -> None:
        from benchmark.iso_solve.core.pipeline import build_tool_registry

        with patch("src.agents.solve.tools.ToolRegistry") as mock_tr:
            mock_tr.create_default.return_value = MagicMock()
            build_tool_registry(None, "en")
            mock_tr.create_default.assert_called_once_with(language="en")

    @pytest.mark.asyncio
    async def test_pipeline_custom_tools(self) -> None:
        from benchmark.iso_solve.core.pipeline import build_tool_registry

        with patch("src.agents.solve.tools.ToolRegistry") as mock_tr:
            mock_tr.create_from_names.return_value = MagicMock()
            build_tool_registry(["code_execute", "reason"], "en")
            mock_tr.create_from_names.assert_called_once_with(
                ["code_execute", "reason"], language="en",
            )


# ===================================================================
# 10. JSON parsing robustness (planner output parsing)
# ===================================================================

class TestPlannerParsing:

    def test_parse_pure_json(self) -> None:
        from src.agents.solve.utils.json_utils import extract_json_from_text

        data = extract_json_from_text('{"analysis": "test", "steps": [{"id": "S1", "goal": "do it"}]}')
        assert data is not None
        assert data["analysis"] == "test"
        assert len(data["steps"]) == 1

    def test_parse_json_in_markdown_block(self) -> None:
        from src.agents.solve.utils.json_utils import extract_json_from_text

        text = 'Here is the plan:\n```json\n{"analysis": "x", "steps": []}\n```'
        data = extract_json_from_text(text)
        assert data is not None
        assert data["analysis"] == "x"

    def test_parse_json_with_surrounding_text(self) -> None:
        from src.agents.solve.utils.json_utils import extract_json_from_text

        text = 'Let me plan this.\n{"analysis": "ok", "steps": [{"id": "S1", "goal": "step 1"}]}\nDone.'
        data = extract_json_from_text(text)
        assert data is not None
        assert data["steps"][0]["goal"] == "step 1"

    def test_parse_empty_returns_none(self) -> None:
        from src.agents.solve.utils.json_utils import extract_json_from_text

        assert extract_json_from_text("") is None
        assert extract_json_from_text("no json here") is None

    def test_planner_fallback_on_bad_json(self) -> None:
        from src.agents.solve.agents.planner_agent import PlannerAgent

        with patch("src.agents.base_agent.get_llm_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                api_key="k", base_url="u", model="m", binding="openai", api_version=None,
            )
            agent = PlannerAgent(api_key="k", base_url="u", model="m")

        plan = agent._parse_plan("This is not JSON at all.", None)
        assert len(plan.steps) == 1
        assert plan.steps[0].id == "S1"
        assert "Failed to parse plan" in plan.analysis

    def test_planner_parses_valid_plan(self) -> None:
        from src.agents.solve.agents.planner_agent import PlannerAgent

        with patch("src.agents.base_agent.get_llm_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                api_key="k", base_url="u", model="m", binding="openai", api_version=None,
            )
            agent = PlannerAgent(api_key="k", base_url="u", model="m")

        response = json.dumps({
            "analysis": "Multi-step problem",
            "steps": [
                {"id": "S1", "goal": "Identify the data"},
                {"id": "S2", "goal": "Calculate the answer"},
                {"id": "S3", "goal": "Verify the result"},
            ],
        })
        plan = agent._parse_plan(response, None)
        assert len(plan.steps) == 3
        assert plan.analysis == "Multi-step problem"
        assert plan.steps[0].goal == "Identify the data"
        assert plan.steps[2].id == "S3"


# ===================================================================
# 11. Solver agent decision parsing
# ===================================================================

class TestSolverAgentParsing:

    def _get_agent(self) -> Any:
        from src.agents.solve.agents.solver_agent import SolverAgent

        with patch("src.agents.base_agent.get_llm_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(
                api_key="k", base_url="u", model="m", binding="openai", api_version=None,
            )
            return SolverAgent(api_key="k", base_url="u", model="m")

    def test_parse_valid_decision(self) -> None:
        agent = self._get_agent()
        resp = json.dumps({
            "thought": "I need to calculate",
            "action": "code_execute",
            "action_input": "print(2+2)",
            "self_note": "Will compute arithmetic",
        })
        d = agent._parse_decision(resp)
        assert d["action"] == "code_execute"
        assert d["action_input"] == "print(2+2)"

    def test_parse_done_action(self) -> None:
        agent = self._get_agent()
        resp = json.dumps({
            "thought": "Found the answer",
            "action": "done",
            "action_input": "The answer is 42",
            "self_note": "Confirmed",
        })
        d = agent._parse_decision(resp)
        assert d["action"] == "done"

    def test_parse_invalid_json_defaults_to_done(self) -> None:
        agent = self._get_agent()
        d = agent._parse_decision("This is not JSON")
        assert d["action"] == "done"
        assert "Failed to parse" in d["thought"]

    def test_parse_unknown_action_defaults_to_done(self) -> None:
        agent = self._get_agent()
        resp = json.dumps({
            "thought": "hmm",
            "action": "unknown_tool",
            "action_input": "",
            "self_note": "",
        })
        d = agent._parse_decision(resp)
        assert d["action"] == "done"


# ===================================================================
# 12. End-to-end: skip_extract adapter flow
# ===================================================================

class TestSkipExtractFlow:

    @pytest.mark.asyncio
    async def test_skip_extract_uses_full_output(self, tmp_path: Any) -> None:
        from benchmark.iso_solve.core.runner import BenchmarkRunner
        from benchmark.iso_solve.eval.base import BenchmarkAdapter

        class _SkipExtractAdapter(BenchmarkAdapter):
            name = "skip_test"
            skip_extract = True
            breakdown_keys = []

            def load_dataset(self, *a: Any, **kw: Any) -> list[Problem]:
                return [_make_problem(id="p1", ground_truth="42")]

            def filter_problems(self, problems: list, *a: Any, **kw: Any) -> list:
                return problems

        mock_extractor = AsyncMock()
        mock_judge = AsyncMock(return_value=(True, "CORRECT"))
        runner = BenchmarkRunner(_SkipExtractAdapter(), mock_extractor, mock_judge)

        args = argparse.Namespace(
            mode="direct", dry_run=False, output=str(tmp_path),
            benchmark="skip_test", config="", limit=None, seed=42,
        )
        cfg = {
            "evaluation": {"llm_extract": True, "llm_judge": True},
            "output_dir": str(tmp_path),
            "skip_test": {"llm": {"model": "m"}, "concurrency": 1},
        }

        with patch("src.services.llm.config.get_llm_config") as mock_cfg, \
             patch.object(BenchmarkRunner, "_direct_call",
                          new_callable=AsyncMock) as mock_call:
            mock_cfg.return_value = MagicMock(model="m", api_key="k", base_url="u")
            mock_call.return_value = "Full detailed answer: 42"

            report = await runner.run(args, cfg)

        mock_extractor.assert_not_called()
        judge_call = mock_judge.call_args
        assert judge_call.kwargs["predicted"] == "Full detailed answer: 42"


# ===================================================================
# 13. Output saving and file structure
# ===================================================================

class TestOutputSaving:
    def test_save_result_creates_files(self, tmp_path: Any) -> None:
        from benchmark.iso_solve.core.runner import BenchmarkRunner

        runner = BenchmarkRunner(_make_stub_adapter(), AsyncMock(), AsyncMock())
        result = _make_result(correct=True)
        runner._save_result(tmp_path, 0, result)

        assert (tmp_path / "outputs" / "0000" / "output.md").exists()
        assert (tmp_path / "outputs" / "0000" / "meta.json").exists()

        with open(tmp_path / "outputs" / "0000" / "meta.json") as f:
            meta = json.load(f)
        assert meta["correct"] is True
        assert meta["id"] == "p001"
        assert meta["extracted_answer"] == "4"
