from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from io import StringIO
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import httpx
import pytest

from deeptutor.services.memory import paths
from deeptutor.services.memory.evaluation import (
    AdapterResult,
    CaseInput,
    Evidence,
    ReaderResult,
    evaluate,
    load_cases,
    memory_snapshot,
    pack_evidence,
    score_answer,
)
from deeptutor.services.memory.store import MemoryStore
from deeptutor.services.path_service import PathService

FIXTURES = Path(__file__).parents[2] / "fixtures" / "memory_evaluation" / "cases.jsonl"


def _case():
    return json.loads(FIXTURES.read_text(encoding="utf-8").splitlines()[0])


def _load(tmp_path, data):
    path = tmp_path / "case.jsonl"
    path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    return load_cases(path)


def test_shipped_cases_and_temporal_filter():
    cases = load_cases(FIXTURES)
    assert len(cases) == 11
    temporal = cases[-1]
    assert [item.identifier for item in temporal.input.history] == ["h1"]
    assert temporal.answers == ("Python",)
    assert not hasattr(temporal.input, "answers")
    with pytest.raises(FrozenInstanceError):
        temporal.input.query = "mutated"


@pytest.mark.parametrize(
    "change",
    [
        {"question_time": "2026-01-01T00:00:00+00:00"},
        {"memory_as_of": "2027-01-01T00:00:00+00:00"},
        {"question_time": "2026-10-10T00:00:00"},
        {"evidence_ids": ["unknown"]},
        {"answer_aliases": "Python"},
        {"answer_aliases": [""]},
        {"l3_snapshot": {"../../outside": "bad"}},
        {"l3_snapshot": {"profile": 12}},
        {"answerable": "yes"},
        {"expected_answer": ""},
        {"case_id": ""},
        {"history": {}},
    ],
)
def test_invalid_cases_fail_with_line_number(tmp_path, change):
    data = _case()
    data.update(change)
    with pytest.raises(ValueError, match="case.jsonl:1:"):
        _load(tmp_path, data)


def test_unsorted_or_duplicate_history_rejected(tmp_path):
    data = _case()
    item = dict(data["history"][0])
    data["history"].append(item)
    with pytest.raises(ValueError, match="Duplicate history"):
        _load(tmp_path, data)
    item.update(id="h2", timestamp="2025-01-01T00:00:00+00:00")
    with pytest.raises(ValueError, match="chronological"):
        _load(tmp_path, data)


def test_empty_and_duplicate_cases_rejected(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("")
    with pytest.raises(ValueError, match="at least one"):
        load_cases(path)
    path.write_text((json.dumps(_case()) + "\n") * 2)
    with pytest.raises(ValueError, match="Duplicate case"):
        load_cases(path)


@pytest.mark.parametrize(
    "answer,expected,exact,f1",
    [
        ("Python!", ("Python",), True, 1.0),
        ("not Python", ("Python",), False, 2 / 3),
        (
            "The topic of conditional probability.",
            ("conditional probability", "The topic of conditional probability"),
            True,
            1.0,
        ),
        ("The topic of conditional probability.", ("conditional probability",), False, 4 / 7),
        ("UNKNOWN", ("UNKNOWN",), True, 1.0),
        ("-2", ("2",), False, 2 / 3),
        ("−2", ("-2",), True, 1.0),
        ("2=3", ("2<3",), False, 2 / 3),
    ],
)
def test_explicit_scoring_contract(answer, expected, exact, f1):
    actual = score_answer(answer, expected)
    assert actual[0] is exact
    assert actual[1] == pytest.approx(f1)


@pytest.mark.parametrize("answer", [None, "", "   "])
def test_missing_answers_are_not_abstention(answer):
    with pytest.raises(ValueError, match="no answer"):
        score_answer(answer, ("UNKNOWN",))


def test_budget_counts_complete_labeled_context():
    items = (Evidence("a", "x" * 40), Evidence("b", "ok"))
    text, ids = pack_evidence(items, 10, len)
    assert text == "[b] ok\n"
    assert ids == ["b"]
    with pytest.raises(ValueError, match="positive"):
        pack_evidence(items, 0, len)


def test_native_reader_isolated_and_scope_restored(tmp_path, monkeypatch):
    outside = PathService(workspace_root=tmp_path / "owner")
    seen = []
    original = MemoryStore.read_l3_concat

    def observe(store):
        seen.append(paths.memory_root())
        return original(store)

    monkeypatch.setattr(MemoryStore, "read_l3_concat", observe)
    with paths.memory_path_service_override(outside):
        owner_root = paths.memory_root()
        asyncio.run(MemoryStore().overwrite_doc("L3", "profile", "owner-private"))
        first = asyncio.run(memory_snapshot(CaseInput("q", (), (("profile", "learner-A"),))))
        second = asyncio.run(memory_snapshot(CaseInput("q", (), (("preferences", "learner-B"),))))
        assert first.evidence[0].text == "learner-A\n"
        assert second.evidence[0].text == "learner-B\n"
        assert not first.original_source_ids
        assert paths.memory_root() == owner_root
        assert MemoryStore().read_raw("L3", "profile") == "owner-private"
    assert seen[0] != seen[1]
    assert all(not root.exists() for root in seen)


def test_native_reader_error_restores_override(tmp_path, monkeypatch):
    outside = PathService(workspace_root=tmp_path / "owner")

    def fail(_):
        raise RuntimeError("read failed")

    monkeypatch.setattr(MemoryStore, "read_l3_concat", fail)
    with paths.memory_path_service_override(outside):
        before = paths.memory_root()
        with pytest.raises(RuntimeError, match="read failed"):
            asyncio.run(memory_snapshot(CaseInput("q", (), (("profile", "fixture"),))))
        assert paths.memory_root() == before


def test_no_reader_is_preflight_not_a_quality_score():
    report = asyncio.run(
        evaluate(load_cases(FIXTURES), count_tokens=len, tokenizer="test-chars", budget=1000)
    )
    assert not report["reader_executed"]
    assert all(
        s["scored"] == 0 and s["exact_match_scored"] is None for s in report["summary"].values()
    )
    assert not any(row["error"] for row in report["rows"])
    assert all(
        row["source_id_recall"] is None
        for row in report["rows"]
        if row["adapter"] == "native_l3_snapshot"
    )


def test_reader_failures_keep_evidence_and_denominators():
    cases = load_cases(FIXTURES)[:2]

    async def adapter(context):
        assert not hasattr(context, "answers")
        return AdapterResult((Evidence("h1", "Python"),), True)

    async def reader(context, query):
        if "Which language" in query:
            return ReaderResult("Python", {"input_tokens": 5})
        raise RuntimeError("reader unavailable")

    report = asyncio.run(
        evaluate(
            cases,
            count_tokens=len,
            tokenizer="test-chars",
            reader=reader,
            adapters={"test": adapter},
        )
    )
    summary = report["summary"]["test"]
    assert (summary["scored"], summary["failed"]) == (1, 1)
    assert summary["exact_match_scored"] == 1.0
    assert summary["exact_match_all_cases"] == 0.5
    assert report["rows"][1]["evidence_context"] == "[h1] Python\n"


def test_all_failed_reader_calls_have_null_scores():
    async def fail(context, query):
        raise RuntimeError("offline")

    report = asyncio.run(
        evaluate(load_cases(FIXTURES)[:1], count_tokens=len, tokenizer="test-chars", reader=fail)
    )
    assert all(
        s["failed"] == 1 and s["exact_match_all_cases"] is None for s in report["summary"].values()
    )


def test_all_unanswerable_cases_and_empty_memory_have_defined_scores(tmp_path):
    data = _case()
    data.update(
        answerable=False, expected_answer="", answer_aliases=[], evidence_ids=[], l3_snapshot={}
    )
    cases = _load(tmp_path, data)

    async def reader(context, query):
        return ReaderResult("UNKNOWN")

    report = asyncio.run(evaluate(cases, count_tokens=len, tokenizer="test-chars", reader=reader))
    assert all(s["exact_match_scored"] == 1.0 for s in report["summary"].values())
    assert all(row["source_id_recall"] is None for row in report["rows"])
    native = next(row for row in report["rows"] if row["adapter"] == "native_l3_snapshot")
    assert native["evidence_context"] == ""


def test_concurrent_native_reads_do_not_cross_scopes():
    async def read_both():
        return await asyncio.gather(
            memory_snapshot(CaseInput("q", (), (("profile", "only-A"),))),
            memory_snapshot(CaseInput("q", (), (("profile", "only-B"),))),
        )

    a, b = asyncio.run(read_both())
    assert a.evidence[0].text == "only-A\n"
    assert b.evidence[0].text == "only-B\n"


def test_cli_reports_missing_model_without_stop_iteration(tmp_path, monkeypatch, capsys):
    script = Path(__file__).parents[3] / "examples/memory_evaluation/run.py"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--cases",
            str(FIXTURES),
            "--output",
            str(tmp_path / "report.json"),
            "--model",
            "missing-model",
        ],
    )
    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"models": []}),
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(script), run_name="__main__")
    assert exc.value.code == 2
    assert "is not installed" in capsys.readouterr().err
    assert not (tmp_path / "report.json").exists()


def test_unanswerable_aliases_cannot_turn_hallucination_into_correct_answer(tmp_path):
    data = _case()
    data.update(answerable=False, expected_answer="", evidence_ids=[], answer_aliases=["Python"])
    with pytest.raises(ValueError, match="Unanswerable cases"):
        _load(tmp_path, data)


def test_oversized_native_response_is_explicitly_omitted():
    report = asyncio.run(
        evaluate(load_cases(FIXTURES)[:1], count_tokens=len, tokenizer="test-chars", budget=1)
    )
    row = next(row for row in report["rows"] if row["adapter"] == "native_l3_snapshot")
    assert row["offered_ids"] == row["omitted_ids"] == ["l3"]
    assert row["evidence_context"] == ""
    assert row["evidence_tokens"] == 0
    assert row["error"] is None


def test_invalid_reader_answer_keeps_reported_usage():
    async def reader(context, query):
        return ReaderResult("", {"input_tokens": 9, "output_tokens": 1})

    report = asyncio.run(
        evaluate(load_cases(FIXTURES)[:1], count_tokens=len, tokenizer="test-chars", reader=reader)
    )
    for row in report["rows"]:
        assert row["error"] is not None
        assert row["usage"] == {"input_tokens": 9, "output_tokens": 1}
        assert row["answer"] == ""
        assert row["exact_match"] is None
