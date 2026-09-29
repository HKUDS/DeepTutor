"""Tests for `deeptutor kb eval`."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from deeptutor.services.rag.eval import EvalReport, QueryEvaluation, evaluate_hits
from deeptutor_cli.main import app

runner = CliRunner()

GOLD = "alpha beta gamma delta epsilon zeta"


@pytest.fixture
def eval_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A one-case KB, a one-case QA set, and a stubbed evaluator."""
    import deeptutor.services.rag.eval as eval_module
    import deeptutor.services.rag.provider_binding as binding_module
    from deeptutor_cli import kb as kb_module

    set_path = tmp_path / "set.jsonl"
    base_dir = tmp_path / "kbs"
    base_dir.mkdir()
    set_path.write_text(
        json.dumps({"query": "what is alpha?", "gold": [GOLD]}) + "\n", encoding="utf-8"
    )

    manager = SimpleNamespace(base_dir=base_dir, list_knowledge_bases=lambda: ["kb1"])
    monkeypatch.setattr(kb_module, "_get_kb_manager", lambda: manager)
    monkeypatch.setattr(binding_module, "resolve_bound_provider", lambda *_args: "llamaindex")

    calls: list[dict[str, Any]] = []

    class _FakeEvaluator:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            self.kwargs = kwargs

        async def evaluate(self, dataset, *, progress=None):
            k = self.kwargs["k"]
            case = dataset.cases[0]
            item = QueryEvaluation(
                case_id=case.id,
                query=case.query,
                k=k,
                gold_count=1,
                hits=({0},),
                metrics=evaluate_hits(case.id, ({0},), 1, k),
                provider=self.kwargs.get("provider", ""),
            )
            if progress is not None:
                progress(1, len(dataset.cases), item)
            return EvalReport(
                dataset_name=dataset.name,
                kb_name=self.kwargs["kb_name"],
                provider=self.kwargs.get("provider", ""),
                k=k,
                mode=self.kwargs.get("mode"),
                policy=self.kwargs["policy"],
                evaluations=(item,),
                duration_seconds=0.01,
            )

    monkeypatch.setattr(eval_module, "RetrievalEvaluator", _FakeEvaluator)

    return SimpleNamespace(set_path=set_path, base_dir=base_dir, calls=calls)


def test_eval_reports_metrics_for_a_scored_case(eval_env: SimpleNamespace) -> None:
    result = runner.invoke(app, ["kb", "eval", "kb1", "--dataset", str(eval_env.set_path)])

    assert result.exit_code == 0, result.output
    assert "recall@5" in result.output
    assert "kb: kb1" in result.output
    assert len(eval_env.calls) == 1
    call = eval_env.calls[0]
    assert call["kb_name"] == "kb1"
    assert call["kb_base_dir"] == str(eval_env.base_dir)
    assert call["k"] == 5
    assert call["mode"] is None
    assert call["query_limit"] is None


def test_eval_forwards_cutoff_mode_and_limit(eval_env: SimpleNamespace) -> None:
    result = runner.invoke(
        app,
        [
            "kb",
            "eval",
            "kb1",
            "--dataset",
            str(eval_env.set_path),
            "--top-k",
            "3",
            "--mode",
            "hybrid",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "recall@3" in result.output
    call = eval_env.calls[0]
    assert call["k"] == 3
    assert call["mode"] == "hybrid"
    assert call["query_limit"] == 1


def test_eval_json_output_carries_the_metrics_block(eval_env: SimpleNamespace) -> None:
    result = runner.invoke(
        app,
        ["kb", "eval", "kb1", "--dataset", str(eval_env.set_path), "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    assert "metrics" in result.output
    assert "recall@5" in result.output


def test_eval_save_writes_a_parseable_report(eval_env: SimpleNamespace, tmp_path: Path) -> None:
    target = tmp_path / "reports" / "baseline.json"

    result = runner.invoke(
        app,
        ["kb", "eval", "kb1", "--dataset", str(eval_env.set_path), "--save", str(target)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["kb"] == "kb1"
    assert payload["metrics"]["recall@5"] == 1.0


def test_eval_rejects_an_unknown_knowledge_base(eval_env: SimpleNamespace) -> None:
    result = runner.invoke(app, ["kb", "eval", "missing", "--dataset", str(eval_env.set_path)])

    assert result.exit_code == 1
    assert "not found" in result.output


def test_eval_reports_a_missing_dataset(eval_env: SimpleNamespace) -> None:
    result = runner.invoke(
        app, ["kb", "eval", "kb1", "--dataset", str(eval_env.base_dir / "absent.jsonl")]
    )

    assert result.exit_code == 1
    assert "Evaluation set not found" in result.output


def test_eval_reports_an_invalid_dataset(eval_env: SimpleNamespace, tmp_path: Path) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"query": "q"}\n', encoding="utf-8")

    result = runner.invoke(app, ["kb", "eval", "kb1", "--dataset", str(broken)])

    assert result.exit_code == 1
    assert "case #1" in result.output


def test_eval_rejects_a_reasoning_as_retrieval_engine(
    eval_env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    import deeptutor.services.rag.provider_binding as binding_module

    monkeypatch.setattr(binding_module, "resolve_bound_provider", lambda *_args: "pageindex")

    result = runner.invoke(app, ["kb", "eval", "kb1", "--dataset", str(eval_env.set_path)])

    assert result.exit_code == 1
    assert "PageIndex" in result.output
    assert eval_env.calls == []


def test_eval_rejects_an_impossible_match_ratio(eval_env: SimpleNamespace) -> None:
    result = runner.invoke(
        app, ["kb", "eval", "kb1", "--dataset", str(eval_env.set_path), "--min-ratio", "1.5"]
    )

    assert result.exit_code == 1
    assert "min_ratio must be in (0, 1]" in result.output
