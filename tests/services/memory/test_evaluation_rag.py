from __future__ import annotations

import asyncio
import builtins
import importlib.metadata
import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest

from deeptutor.services.memory.evaluation import (
    CaseInput,
    EvalCase,
    HistoryItem,
    evaluate,
    load_cases,
)
from deeptutor.services.memory.evaluation_rag import (
    RawHistoryRAG,
    RetrievalConfig,
    local_sentence_transformer_adapters,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "memory_evaluation" / "cases.jsonl"


def context(*texts):
    return CaseInput(
        "question",
        tuple(HistoryItem(f"h{i}", "2026-01-01", text) for i, text in enumerate(texts)),
        (),
    )


def run(adapter, case):
    return asyncio.run(adapter(case))


def constant_embed(texts):
    return [[1.0, 0.0] for _ in texts]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"window_chars": 0},
        {"overlap_chars": -1},
        {"overlap_chars": 600},
        {"candidates": 0},
        {"top_k": 0},
        {"top_k": 129},
        {"top_k": True},
        {"window_chars": 4.5},
    ],
)
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        RetrievalConfig(**kwargs)


def test_overlapping_windows_keep_complete_coverage_and_event_provenance():
    case = context("abcdefghij")
    adapter = RawHistoryRAG(constant_embed, config=RetrievalConfig(6, 2, 10, 10))
    result = run(adapter, case)
    # Exact dense ties favor later windows; overlap is retained, not deleted.
    assert [(item.identifier, item.text) for item in result.evidence] == [
        ("raw:0:4:10", "2026-01-01 efghij"),
        ("raw:0:0:6", "2026-01-01 abcdef"),
    ]
    assert result.source_ids == {"raw:0:0:6": "h0", "raw:0:4:10": "h0"}
    assert result.metadata["window_count"] == 2
    assert case.history[0].text == "abcdefghij"


def test_dense_cosine_normalization_and_candidate_only_reranking():
    seen = []

    def embed(texts):
        vectors = {
            "2026-01-01 weak": [100, 100],
            "2026-01-01 best": [1, 0],
            "2026-01-01 opposite": [-1, 0],
            "question": [10, 0],
        }
        return [vectors[text] for text in texts]

    def rerank(query, texts):
        seen.append((query, list(texts)))
        return [0, 5]

    case = context("weak", "best", "opposite")
    config = RetrievalConfig(candidates=2, top_k=1)
    dense = run(RawHistoryRAG(embed, config=config), case)
    ranked = run(RawHistoryRAG(embed, rerank, config=config), case)
    assert dense.source_ids[dense.evidence[0].identifier] == "h1"
    assert ranked.source_ids[ranked.evidence[0].identifier] == "h0"
    assert seen == [("question", ["2026-01-01 best", "2026-01-01 weak"])]
    assert dense.metadata["reranker_executed"] is False
    assert ranked.metadata["reranker_executed"] is True
    assert ranked.metadata["dense_candidates"][0]["score"] == pytest.approx(1)


def test_reranker_ties_retain_dense_order_and_empty_history_skips_models():
    adapter = RawHistoryRAG(constant_embed, lambda query, texts: [0] * len(texts))
    result = run(adapter, context("old", "new"))
    assert [result.source_ids[item.identifier] for item in result.evidence] == ["h1", "h0"]
    adapter = RawHistoryRAG(
        lambda _: pytest.fail("empty history was embedded"),
        lambda *_: pytest.fail("empty history was reranked"),
    )
    result = run(adapter, context())
    assert not result.evidence
    assert result.metadata["reranker_executed"] is False


@pytest.mark.parametrize(
    "corpus,query",
    [
        ([], [[1]]),
        ([[1], [2]], [[1]]),
        ([[]], [[1]]),
        ([[0, 0]], [[1, 0]]),
        ([[float("nan")]], [[1]]),
        ([[float("inf")]], [[1]]),
        ([[1]], []),
        ([[1]], [[1], [1]]),
        ([[1, 0]], [[1]]),
        ([[1]], [[0]]),
    ],
)
def test_invalid_embeddings_fail_instead_of_producing_misleading_rankings(corpus, query):
    responses = iter([corpus, query])
    with pytest.raises(ValueError):
        run(RawHistoryRAG(lambda _: next(responses)), context("one"))


def test_mixed_corpus_dimensions_rejected():
    with pytest.raises(ValueError, match="equal dimensions"):
        run(
            RawHistoryRAG(lambda texts: [[1], [1, 0]] if len(texts) == 2 else [[1]]),
            context("a", "b"),
        )


@pytest.mark.parametrize("scores", [[], [1, 2], [float("nan")], [float("inf")]])
def test_invalid_reranker_scores_rejected(scores):
    with pytest.raises(ValueError, match="one finite score"):
        run(RawHistoryRAG(constant_embed, lambda *_: scores), context("one"))


def test_future_history_is_never_indexed_and_cases_do_not_share_an_index():
    seen = []

    def embed(texts):
        seen.extend(texts)
        return constant_embed(texts)

    adapter = RawHistoryRAG(embed)
    temporal = load_cases(FIXTURES)[-1]
    run(adapter, temporal.input)
    assert seen[:-1] == [f"{item.timestamp} {item.text}" for item in temporal.input.history]
    assert seen[-1] == temporal.input.query
    assert not hasattr(temporal.input, "answers")
    seen.clear()
    result = run(adapter, context("different case"))
    assert seen == ["2026-01-01 different case", "question"]
    assert len(result.source_ids) == 1


def test_budgeted_recall_projects_chunks_to_unique_sources_and_retains_failures():
    case = EvalCase(
        "test",
        "coverage",
        context("abcdefghij", "klmnopqrst"),
        ("answer",),
        frozenset({"h0", "h1"}),
    )
    adapter = RawHistoryRAG(constant_embed, config=RetrievalConfig(6, 2, 10, 10))
    result = run(adapter, case.input)
    first = result.evidence[0]
    budget = len(f"[{first.identifier}] {first.text}\n") * 2
    report = asyncio.run(
        evaluate(
            (case,),
            count_tokens=len,
            tokenizer="characters",
            budget=budget,
            adapters={"rag": adapter},
        )
    )
    row = report["rows"][0]
    assert len(row["selected_ids"]) == 2
    assert row["selected_source_ids"] == ["h1"]
    assert row["source_id_recall"] == 0.5  # Two windows of one event do not count twice.
    assert row["evidence_tokens"] <= budget
    assert row["exact_match"] is None
    assert not report["reader_executed"]
    assert row["adapter_metadata"]["window_count"] == 4
    broken = RawHistoryRAG(lambda _: [[0]])
    report = asyncio.run(
        evaluate((case,), count_tokens=len, tokenizer="characters", adapters={"rag": broken})
    )
    assert report["summary"]["rag"]["failed"] == 1
    assert "ValueError" in report["rows"][0]["error"]


@pytest.fixture
def fake_models(monkeypatch):
    calls = []

    class Array:
        def __init__(self, values):
            self.values = values

        def reshape(self, _):
            return self

        def tolist(self):
            return self.values

    class Embedder:
        max_seq_length = 256

        def __init__(self, name, **kwargs):
            calls.append(("embed", name, kwargs))

        @staticmethod
        def tokenizer(text, **kwargs):
            assert kwargs == {"truncation": False}
            return {"input_ids": text.split()}

        def encode(self, texts, **kwargs):
            return Array(constant_embed(texts))

    class Cross:
        def __init__(self, name, **kwargs):
            calls.append(("cross", name, kwargs))

        @staticmethod
        def tokenizer(query, text, **kwargs):
            assert kwargs == {"truncation": False}
            return {"input_ids": (query + " " + text).split()}

        def predict(self, pairs, **kwargs):
            return Array([1] * len(pairs))

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=Embedder, CrossEncoder=Cross),
    )
    monkeypatch.setattr(
        importlib.metadata,
        "version",
        lambda name: "5.1.2" if name == "sentence-transformers" else "test-version",
    )
    return calls


def make_models(**kwargs):
    return local_sentence_transformer_adapters(
        RetrievalConfig(),
        embedding_model="embed",
        embedding_revision="a" * 40,
        reranker_model="rerank",
        reranker_revision="b" * 40,
        **kwargs,
    )


def test_optional_model_factory_pins_revisions_avoids_credentials_and_reports_versions(fake_models):
    adapters, info = make_models()
    assert set(adapters) == {"raw_dense", "raw_dense_reranked"}
    assert info["library_versions"]["torch"] == "test-version"
    for kind, name, kwargs in fake_models:
        assert kwargs["revision"] == ("a" if kind == "embed" else "b") * 40
        assert kwargs["token"] is False
        assert kwargs["trust_remote_code"] is False
        assert kwargs["model_kwargs"] == {"use_safetensors": True}
        assert kwargs["device"] == "cpu"
    result = run(adapters["raw_dense_reranked"], context("short text"))
    assert result.metadata["reranker_executed"] is True


def test_model_inputs_are_rejected_instead_of_silently_truncated(fake_models):
    adapters, _ = make_models()
    with pytest.raises(ValueError, match="Embedding input exceeds"):
        adapters["raw_dense"].embed(["word " * 257])
    long_query = CaseInput("word " * 257, context("short").history, ())
    with pytest.raises(ValueError, match="Embedding input exceeds"):
        run(adapters["raw_dense"], long_query)
    # Exercise the paired-input guard independently of the embedding guard.
    adapter = adapters["raw_dense_reranked"]
    with pytest.raises(ValueError, match="Reranker input exceeds"):
        adapter.rerank("word " * 256, ["word " * 257])


def test_invalid_revision_rejected_before_optional_sdk_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ValueError, match="immutable"):
        local_sentence_transformer_adapters(
            RetrievalConfig(),
            embedding_model="e",
            embedding_revision="main",
            reranker_model="r",
            reranker_revision="b" * 40,
        )


def test_older_optional_sdk_fails_with_upgrade_message(fake_models, monkeypatch):
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "3.0.0")
    with pytest.raises(ImportError, match="sentence-transformers>=5.1.2,<6"):
        make_models()
    assert not fake_models


def test_default_cli_needs_no_optional_model_sdk(tmp_path, monkeypatch):
    import tiktoken

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"sentence_transformers", "transformers", "torch"}:
            pytest.fail(f"Default preflight imported {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(
        tiktoken, "get_encoding", lambda _: SimpleNamespace(encode=lambda text, **_: list(text))
    )
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["run.py", "--cases", str(FIXTURES), "--output", str(output)])
    runpy.run_path("examples/memory_evaluation/run.py", run_name="__main__")
    report = json.loads(output.read_text())
    assert set(report["summary"]) == {"raw_recent", "lexical_top2", "native_l3_snapshot"}
    assert not report["reader_executed"]


def test_opt_in_cli_adds_both_baselines_and_records_model_configuration(
    tmp_path, monkeypatch, fake_models
):
    import tiktoken

    monkeypatch.setattr(
        tiktoken, "get_encoding", lambda _: SimpleNamespace(encode=lambda text, **_: list(text))
    )
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--cases",
            str(FIXTURES),
            "--output",
            str(output),
            "--raw-rag",
            "--retrieval-candidates",
            "3",
            "--retrieval-top-k",
            "2",
        ],
    )
    runpy.run_path("examples/memory_evaluation/run.py", run_name="__main__")
    report = json.loads(output.read_text())
    assert {"raw_dense", "raw_dense_reranked"} <= set(report["summary"])
    assert not any(row["error"] for row in report["rows"])
    row = next(row for row in report["rows"] if row["adapter"] == "raw_dense_reranked")
    assert row["adapter_metadata"]["candidate_limit"] == 3
    assert row["adapter_metadata"]["top_k"] == 2
    assert report["retrieval_models"]["device"] == "cpu"
    assert all(summary["exact_match_scored"] is None for summary in report["summary"].values())


@pytest.mark.parametrize(
    "extra,message",
    [
        (["--embedding-model", "custom"], "explicit full commit"),
        (["--embedding-revision", "main"], "immutable"),
        (["--retrieval-top-k", "0"], "1 <= top_k"),
        ([], "optional rag-rerank"),
    ],
)
def test_cli_setup_errors_are_actionable_without_model_downloads(
    tmp_path, monkeypatch, capsys, extra, message
):
    import tiktoken

    monkeypatch.setattr(
        tiktoken, "get_encoding", lambda _: SimpleNamespace(encode=lambda text, **_: list(text))
    )
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "--cases",
            str(FIXTURES),
            "--output",
            str(tmp_path / "report.json"),
            "--raw-rag",
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as error:
        runpy.run_path("examples/memory_evaluation/run.py", run_name="__main__")
    assert error.value.code == 2
    assert message in capsys.readouterr().err
