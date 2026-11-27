"""Optional cross-encoder reranking for LlamaIndex retrieval."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import textwrap

from llama_index.core.schema import NodeWithScore, TextNode
import pytest

from deeptutor.services.rag.pipelines.llamaindex import rerank as rerank_module
from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module
from deeptutor.services.rag.pipelines.llamaindex.config import RetrievalConfig


@pytest.fixture(autouse=True)
def _clear_reranker_cache():
    rerank_module.clear_reranker_cache()
    yield
    rerank_module.clear_reranker_cache()


def _result(node_id: str, text: str, score: float = 0.5) -> NodeWithScore:
    return NodeWithScore(node=TextNode(text=text, id_=node_id), score=score)


def _install_fake_sentence_transformers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
) -> Path:
    pkg_dir = tmp_path / "fake_st"
    pkg_dir.mkdir()
    (pkg_dir / "sentence_transformers.py").write_text(textwrap.dedent(body), encoding="utf-8")
    repo_root = str(Path(rerank_module.__file__).resolve().parents[5])
    existing = os.environ.get("PYTHONPATH", "")
    pythonpath = os.pathsep.join(part for part in (str(pkg_dir), repo_root, existing) if part)
    monkeypatch.setenv("PYTHONPATH", pythonpath)
    monkeypatch.syspath_prepend(str(pkg_dir))
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)
    importlib.invalidate_caches()
    return pkg_dir


def test_cross_encoder_reranks_candidates_and_normalizes_scores() -> None:
    class _FakeModel:
        def predict(
            self,
            pairs: list[tuple[str, str]],
            *,
            activation_fct: object,
        ) -> list[float]:
            assert all(query == "probe" for query, _ in pairs)
            assert callable(activation_fct)
            return [-8.0, 8.0]

    candidates = [_result("weak", "weak candidate"), _result("strong", "strong candidate")]

    ranked = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=2,
        model_name="fake-reranker",
        loader=lambda _model: _FakeModel(),
    )

    assert [result.node_id for result in ranked] == ["strong", "weak"]
    assert ranked[0].score is not None and ranked[0].score > 0.99
    assert ranked[1].score is not None and ranked[1].score < 0.01


def test_reranker_load_failure_returns_first_stage_candidates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    candidates = [_result("first", "first"), _result("second", "second")]

    def _missing_dependency(_model: str):
        raise ImportError("sentence-transformers is not installed")

    with caplog.at_level("WARNING"):
        ranked = rerank_module.rerank_nodes(
            "probe",
            candidates,
            top_k=1,
            model_name="fake-reranker",
            loader=_missing_dependency,
        )

    assert [result.node_id for result in ranked] == ["first"]
    assert "sentence-transformers is not installed" in caplog.text


def test_reranker_scoring_failure_returns_first_stage_candidates(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _FailingModel:
        def predict(
            self,
            pairs: list[tuple[str, str]],
            *,
            activation_fct: object,
        ) -> list[float]:
            raise RuntimeError("scoring failed")

    candidates = [_result("first", "first"), _result("second", "second")]

    with caplog.at_level("WARNING"):
        ranked = rerank_module.rerank_nodes(
            "probe",
            candidates,
            top_k=1,
            model_name="fake-reranker",
            loader=lambda _model: _FailingModel(),
        )

    assert [result.node_id for result in ranked] == ["first"]
    assert "failed while scoring 2 candidates" in caplog.text


def test_retrieve_nodes_expands_candidates_only_when_reranker_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class _FakeRetriever:
        def retrieve(self, query: str) -> list[NodeWithScore]:
            captured["query"] = query
            return [
                _result("first", "first"),
                _result("second", "second"),
                _result("third", "third"),
            ]

    def _fake_build(_index, _storage_dir, *, top_k: int, config: RetrievalConfig):
        captured["candidate_top_k"] = top_k
        captured["config"] = config
        return _FakeRetriever()

    def _fail_if_called(*args: object, **kwargs: object):
        raise AssertionError("rerank_nodes must not run without a configured model")

    monkeypatch.setattr(retriever_module, "build_retriever", _fake_build)
    monkeypatch.setattr(retriever_module, "rerank_nodes", _fail_if_called)
    monkeypatch.setattr(
        retriever_module,
        "retrieval_config_from_settings",
        lambda: RetrievalConfig(profile="vector"),
    )

    unchanged = retriever_module.retrieve_nodes(object(), tmp_path, "probe", top_k=2)

    assert captured["candidate_top_k"] == 2
    assert [result.node_id for result in unchanged] == ["first", "second"]

    rerank_calls: list[dict[str, object]] = []

    def _fake_rerank(query, candidates, *, top_k, model_name):
        rerank_calls.append(
            {
                "query": query,
                "count": len(candidates),
                "top_k": top_k,
                "model_name": model_name,
            }
        )
        return candidates[:top_k]

    monkeypatch.setattr(retriever_module, "rerank_nodes", _fake_rerank)
    monkeypatch.setattr(
        retriever_module,
        "retrieval_config_from_settings",
        lambda: RetrievalConfig(profile="vector", reranker_model="fake-reranker", rerank_top_k=9),
    )

    reranked = retriever_module.retrieve_nodes(object(), tmp_path, "probe", top_k=2)

    assert captured["candidate_top_k"] == 9
    assert rerank_calls == [
        {
            "query": "probe",
            "count": 3,
            "top_k": 2,
            "model_name": "fake-reranker",
        }
    ]
    assert [result.node_id for result in reranked] == ["first", "second"]


def test_default_reranker_runs_in_isolated_worker_and_reuses_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid_log = tmp_path / "pids.txt"
    _install_fake_sentence_transformers(
        tmp_path,
        monkeypatch,
        f"""
        import os
        from pathlib import Path

        class CrossEncoder:
            def __init__(self, model_name: str) -> None:
                self.model_name = model_name
                print("noisy progress output on stdout", flush=True)

            def predict(self, pairs, *, activation_fct=None):
                with Path({str(pid_log)!r}).open("a", encoding="utf-8") as fh:
                    fh.write(f"{{os.getpid()}}\\n")
                scores = [-8.0, 8.0][: len(pairs)]
                return activation_fct(scores) if callable(activation_fct) else scores
        """,
    )
    candidates = [_result("weak", "weak candidate"), _result("strong", "strong candidate")]

    first = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=2,
        model_name="fake-reranker",
    )
    second = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=2,
        model_name="fake-reranker",
    )

    assert "sentence_transformers" not in sys.modules
    assert [item.node_id for item in first] == ["strong", "weak"]
    assert [item.node_id for item in second] == ["strong", "weak"]

    pids = [int(line) for line in pid_log.read_text(encoding="utf-8").splitlines()]
    assert len(pids) == 2
    assert pids[0] != os.getpid()
    assert pids[0] == pids[1]

    rerank_module.clear_reranker_cache()
    rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=2,
        model_name="fake-reranker",
    )
    pids_after_clear = [int(line) for line in pid_log.read_text(encoding="utf-8").splitlines()]
    assert len(pids_after_clear) == 3
    assert pids_after_clear[2] != pids[0]


def test_reranker_worker_crash_falls_back_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    crash_marker = tmp_path / "crash_once"
    crash_marker.write_text("1", encoding="utf-8")
    _install_fake_sentence_transformers(
        tmp_path,
        monkeypatch,
        f"""
        import os
        from pathlib import Path
        import sys

        class CrossEncoder:
            def __init__(self, model_name: str) -> None:
                self.model_name = model_name

            def predict(self, pairs, *, activation_fct=None):
                marker = Path({str(crash_marker)!r})
                if marker.exists():
                    marker.unlink()
                    sys.stderr.write("simulated native worker abort\\n")
                    sys.stderr.flush()
                    os._exit(134)
                return [-5.0, 5.0][: len(pairs)]
        """,
    )
    candidates = [_result("first", "first"), _result("second", "second")]

    with caplog.at_level("WARNING"):
        fallback = rerank_module.rerank_nodes(
            "probe",
            candidates,
            top_k=1,
            model_name="fake-reranker",
        )

    assert [item.node_id for item in fallback] == ["first"]
    assert "using embedding retrieval unchanged" in caplog.text

    recovered = rerank_module.rerank_nodes(
        "probe",
        candidates,
        top_k=1,
        model_name="fake-reranker",
    )
    assert [item.node_id for item in recovered] == ["second"]


def test_faiss_search_then_rerank_does_not_abort_process() -> None:
    for module_name in ("faiss", "sentence_transformers"):
        if importlib.util.find_spec(module_name) is None:
            pytest.skip(f"{module_name} is not installed")

    code = textwrap.dedent(
        """
        import sys
        import faiss
        import numpy as np
        from llama_index.core.schema import NodeWithScore, TextNode
        from deeptutor.services.rag.pipelines.llamaindex.rerank import (
            clear_reranker_cache,
            rerank_nodes,
        )

        idx = faiss.IndexFlatIP(8)
        idx.add(np.ones((2, 8), dtype="float32"))
        idx.search(np.ones((1, 8), dtype="float32"), 1)

        node = NodeWithScore(node=TextNode(text="hello", id_="n1"), score=0.5)
        ranked = rerank_nodes("hello", [node], top_k=1, model_name="local-offline-probe")
        clear_reranker_cache()
        assert len(ranked) == 1
        assert "torch" not in sys.modules
        assert "sentence_transformers" not in sys.modules
        print("OK")
        """
    )
    env = {
        **os.environ,
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
