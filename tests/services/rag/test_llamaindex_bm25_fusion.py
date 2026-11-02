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


def _exercise_nodes() -> list[TextNode]:
    return [
        TextNode(
            text="## Exercise 3.4.26 Reduce the order of y'' + y = 0.",
            id_="e3426",
        ),
        TextNode(
            text="## Exercise 3.5.15 Solve the exact equation (2x + y) dx + x dy = 0.",
            id_="e3515",
        ),
        TextNode(
            text="## Exercise 4.2.15 Find the general solution of y' = 2y.",
            id_="e4215",
        ),
    ]


def test_dotted_identifiers_are_indexed_as_whole_tokens() -> None:
    """A query for an exercise number must reach that exercise (#2331).

    The library default pattern (``\\b\\w\\w+\\b``) indexes ``3.4.26`` as
    ``26``, so every exercise containing ``26`` looks the same. The module
    pattern keeps the dotted identifier intact.
    """

    bm25_cls = retriever_module._import_bm25_retriever()
    if bm25_cls is None:
        pytest.skip("llama-index-retrievers-bm25 is not installed")

    retriever = bm25_cls.from_defaults(
        nodes=_exercise_nodes(),
        similarity_top_k=3,
        token_pattern=retriever_module.BM25_TOKEN_PATTERN,
    )

    hits = retriever.retrieve("3.4.26")

    assert hits and hits[0].node.node_id == "e3426"
    assert hits[0].score > 0


def test_identifier_and_topic_words_rank_the_matching_exercise_first() -> None:
    bm25_cls = retriever_module._import_bm25_retriever()
    if bm25_cls is None:
        pytest.skip("llama-index-retrievers-bm25 is not installed")

    retriever = bm25_cls.from_defaults(
        nodes=_exercise_nodes(),
        similarity_top_k=3,
        token_pattern=retriever_module.BM25_TOKEN_PATTERN,
    )

    hits = retriever.retrieve("exercise 3.5.15 exact equation")

    assert hits and hits[0].node.node_id == "e3515"


def test_persisted_sidecar_is_loaded_with_the_new_pattern(tmp_path) -> None:
    """The library does not persist ``token_pattern``; loading must restore it."""

    bm25_cls = retriever_module._import_bm25_retriever()
    if bm25_cls is None:
        pytest.skip("llama-index-retrievers-bm25 is not installed")

    built = bm25_cls.from_defaults(
        nodes=_exercise_nodes(),
        similarity_top_k=3,
        token_pattern=retriever_module.BM25_TOKEN_PATTERN,
    )
    persist_dir = tmp_path / retriever_module.BM25_PERSIST_DIRNAME
    persist_dir.mkdir()
    built.persist(str(persist_dir))

    loaded = retriever_module.build_bm25_retriever(object(), tmp_path, top_k=3)

    assert loaded is not None
    assert loaded.token_pattern == retriever_module.BM25_TOKEN_PATTERN
    hits = loaded.retrieve("3.4.26")
    assert hits and hits[0].node.node_id == "e3426"


def test_persisting_replaces_the_default_tokenizer_sidecar(tmp_path) -> None:
    """A sidecar built with the old pattern must not survive the rebuild."""

    bm25_cls = retriever_module._import_bm25_retriever()
    if bm25_cls is None:
        pytest.skip("llama-index-retrievers-bm25 is not installed")

    legacy = tmp_path / retriever_module.LEGACY_BM25_PERSIST_DIRNAME
    legacy.mkdir()
    (legacy / "retriever.json").write_text("{}", encoding="utf-8")

    class _Index:
        class _Docstore:
            docs = {node.node_id: node for node in _exercise_nodes()}

        docstore = _Docstore()

    assert retriever_module.persist_bm25_retriever(_Index(), tmp_path, top_k=3) is True
    assert not legacy.exists()
    assert (tmp_path / retriever_module.BM25_PERSIST_DIRNAME).exists()
