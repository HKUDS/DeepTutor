"""BM25 must preserve identifiers and pass only lexical matches to hybrid fusion."""

from __future__ import annotations

from pathlib import Path

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from llama_index.core.storage.docstore import SimpleDocumentStore
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


@pytest.fixture
def identifier_index() -> VectorStoreIndex:
    if not retriever_module.bm25_available():
        pytest.skip("llama-index-retrievers-bm25 is not installed")
    nodes = [
        TextNode(text="Exercise 2.6.9: solve the equation.", id_="other-exercise"),
        TextNode(text="The variable y is unknown.", id_="other-variable"),
        TextNode(text="The variable x is unknown.", id_="variable"),
        TextNode(text="Exercise 2.6.8: solve the equation.", id_="exercise"),
    ]
    # Make the exact exercise a poor vector match so hybrid ranking must use BM25.
    for node in nodes:
        node.embedding = [-0.5 if node.node_id == "exercise" else 0.5] * 8
    return VectorStoreIndex(nodes, embed_model=MockEmbedding(embed_dim=8))


@pytest.mark.parametrize(("query", "expected_id"), [("2.6.8", "exercise"), ("x", "variable")])
def test_bm25_matches_dotted_identifiers_and_single_character_terms(
    tmp_path: Path, identifier_index: VectorStoreIndex, query: str, expected_id: str
) -> None:
    retriever = retriever_module.build_bm25_retriever(identifier_index, tmp_path, top_k=4)

    assert retriever is not None
    hits = retriever.retrieve(query)
    assert [hit.node.node_id for hit in hits if (hit.score or 0) > 0] == [expected_id]


@pytest.mark.parametrize("legacy", [False, True])
def test_persisted_bm25_keeps_corpus_and_query_tokenization_consistent(
    tmp_path: Path, identifier_index: VectorStoreIndex, legacy: bool
) -> None:
    if legacy:
        bm25_cls = retriever_module._import_bm25_retriever()
        old = bm25_cls.from_defaults(index=identifier_index, similarity_top_k=4)
        old.persist(str(tmp_path / retriever_module.BM25_PERSIST_DIRNAME))
    else:
        assert retriever_module.persist_bm25_retriever(identifier_index, tmp_path, top_k=4)

    retriever = retriever_module.build_bm25_retriever(identifier_index, tmp_path, top_k=2)

    assert retriever is not None
    assert len(retriever.retrieve("2.6.8")) == 2
    for query, expected_id in [("2.6.8", "exercise"), ("x", "variable")]:
        hits = retriever.retrieve(query)
        assert [hit.node.node_id for hit in hits if (hit.score or 0) > 0] == [expected_id]


def test_scoped_hybrid_retrieval_promotes_the_matching_identifier(
    identifier_index: VectorStoreIndex,
) -> None:
    for node in identifier_index.docstore.docs.values():
        node.metadata.update(document_key="textbook", page_status="searchable")
        identifier_index.docstore.add_documents([node], allow_update=True)

    hits = retriever_module.retrieve_scoped_nodes(identifier_index, "2.6.8", ["textbook"], top_k=4)

    assert hits[0].node.node_id == "exercise"


@pytest.mark.parametrize("without_adapter", [False, True])
def test_legacy_page_lookup_keeps_dotted_identifiers_and_short_terms(
    tmp_path: Path,
    identifier_index: VectorStoreIndex,
    monkeypatch: pytest.MonkeyPatch,
    without_adapter: bool,
) -> None:
    store = SimpleDocumentStore()
    store.add_documents(list(identifier_index.docstore.docs.values()))
    store.persist(str(tmp_path / "docstore.json"))
    if without_adapter:
        monkeypatch.setattr(retriever_module, "_import_bm25_retriever", lambda: None)

    for query, expected_id in [("2.6.8", "exercise"), ("x", "variable")]:
        hits = retriever_module.retrieve_legacy_pages(tmp_path, query)
        assert [hit.node.node_id for hit in hits if (hit.score or 0) > 0] == [expected_id]


@pytest.mark.parametrize("heading", ["习题2.6.8", "2.6.8解答", "§2.6.8"])
def test_bm25_matches_identifiers_adjacent_to_text(
    tmp_path: Path, identifier_index: VectorStoreIndex, heading: str
) -> None:
    node = identifier_index.docstore.get_node("exercise")
    node.text = heading
    identifier_index.docstore.add_documents([node], allow_update=True)

    retriever = retriever_module.build_bm25_retriever(identifier_index, tmp_path, top_k=4)

    assert retriever is not None
    assert [hit.node.node_id for hit in retriever.retrieve("2.6.8") if (hit.score or 0) > 0] == [
        "exercise"
    ]


def test_old_bm25_rebuild_is_reused_until_the_index_changes(
    tmp_path: Path, identifier_index: VectorStoreIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    bm25_cls = retriever_module._import_bm25_retriever()
    old = bm25_cls.from_defaults(index=identifier_index, similarity_top_k=4)
    old.persist(str(tmp_path / retriever_module.BM25_PERSIST_DIRNAME))
    original = bm25_cls.from_defaults
    builds = []

    def build(**kwargs):
        builds.append(kwargs["index"])
        return original(**kwargs)

    monkeypatch.setattr(bm25_cls, "from_defaults", build)
    for _ in range(2):
        retriever = retriever_module.build_bm25_retriever(identifier_index, tmp_path, top_k=4)
        assert retriever is not None
        assert retriever.retrieve("2.6.8")[0].node.node_id == "exercise"
    assert len(builds) == 1

    updated = VectorStoreIndex(
        [TextNode(text="Exercise 2.6.7", id_="updated")],
        embed_model=MockEmbedding(embed_dim=8),
    )
    retriever = retriever_module.build_bm25_retriever(updated, tmp_path, top_k=4)
    assert retriever is not None
    assert retriever.retrieve("2.6.7")[0].node.node_id == "updated"
    assert len(builds) == 2


def test_bm25_keeps_short_cjk_terms_and_existing_english_stopwords(
    tmp_path: Path, identifier_index: VectorStoreIndex
) -> None:
    node = identifier_index.docstore.get_node("exercise")
    node.text = "第3.4節 a"
    identifier_index.docstore.add_documents([node], allow_update=True)
    retriever = retriever_module.build_bm25_retriever(identifier_index, tmp_path, top_k=4)

    assert retriever is not None
    for query in ["§3.4", "第", "節"]:
        assert [hit.node.node_id for hit in retriever.retrieve(query) if (hit.score or 0) > 0] == [
            "exercise"
        ]
    assert all(not hit.score for hit in retriever.retrieve("a"))


def test_version_prefix_and_sentence_boundaries():
    import re

    assert re.findall(retriever_module.BM25_TOKEN_PATTERN, "v1.7.1 习题2.6.8 End.Next") == [
        "v1.7.1",
        "习题",
        "2.6.8",
        "End",
        "Next",
    ]
