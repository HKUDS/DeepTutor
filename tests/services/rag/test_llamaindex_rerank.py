"""Optional cross-encoder reranking for LlamaIndex retrieval."""

from __future__ import annotations

from pathlib import Path

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
