"""BM25 hits that match no query term must not reach hybrid fusion."""

from __future__ import annotations

from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
import pytest

from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module

_TEXTS = (
    "The median is robust to outliers.",
    "A box plot shows the quartiles of a variable.",
    "The correlation coefficient measures linear association.",
)


def _nodes() -> list[TextNode]:
    return [TextNode(text=text, id_=f"n{i}") for i, text in enumerate(_TEXTS)]


def test_unmatched_hits_are_dropped_and_matched_ones_kept() -> None:
    class _Inner:
        def retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
            nodes = _nodes()
            return [
                NodeWithScore(node=nodes[0], score=1.7),
                NodeWithScore(node=nodes[1], score=0.0),
                NodeWithScore(node=nodes[2], score=None),
            ]

    hits = retriever_module._MatchedOnlyRetriever(_Inner()).retrieve(QueryBundle("median"))

    assert [hit.node.node_id for hit in hits] == ["n0"]


def test_a_query_with_no_shared_term_adds_nothing_from_bm25() -> None:
    bm25_cls = retriever_module._import_bm25_retriever()
    if bm25_cls is None:
        pytest.skip("llama-index-retrievers-bm25 is not installed")
    bm25 = bm25_cls.from_defaults(nodes=_nodes(), similarity_top_k=2)

    # The whitespace tokenizer keeps a Japanese query as one unknown token, yet
    # BM25 still returns top-k nodes, all at score 0.
    raw = bm25.retrieve("中央値と平均の違い")
    assert raw and all(not hit.score for hit in raw)

    filtered = retriever_module._MatchedOnlyRetriever(bm25)
    assert filtered.retrieve("中央値と平均の違い") == []
    assert [hit.node.node_id for hit in filtered.retrieve("median outliers")] == ["n0"]
