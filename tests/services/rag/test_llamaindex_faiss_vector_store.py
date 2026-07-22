"""Tests for the FAISS-backed vector store seam (issue #552).

These cover the behaviours plan B relies on: new indexes persist as FAISS,
legacy SimpleVectorStore indexes are rebuilt in-memory without re-embedding,
mixed-dimension/faiss-less installs fall back to SimpleVectorStore, and the
retrieval path loads + validates an index only once (cached).
"""

from __future__ import annotations

import os
from pathlib import Path

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import ImageNode, TextNode
import numpy as np
import pytest

from deeptutor.services.rag.pipelines.llamaindex import storage as storage_module
from deeptutor.services.rag.pipelines.llamaindex import vector_store

faiss = pytest.importorskip("faiss")
pytest.importorskip("llama_index.vector_stores.faiss")

_DIM = 8
_VECTORS = {
    "alpha": [1, 0, 0, 0, 0, 0, 0, 0],
    "beta": [0, 1, 0, 0, 0, 0, 0, 0],
    "gamma": [0.9, 0.1, 0, 0, 0, 0, 0, 0],
    "delta": [0, 0, 1, 0, 0, 0, 0, 0],
    # Query token chosen so it is not a substring of any node token (and vice
    # versa); leans slightly toward gamma so cosine ranks gamma above alpha.
    "probe": [0.8, 0.05, 0, 0, 0, 0, 0, 0],
}


class _FakeEmbed(BaseEmbedding):
    """Deterministic embedding keyed by a substring of the text."""

    def _vec(self, text: str) -> list[float]:
        for key, vector in _VECTORS.items():
            if key in text:
                return [float(x) for x in vector]
        return [0.0] * _DIM

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vec(text)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._vec(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._vec(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._vec(text)


@pytest.fixture(autouse=True)
def _fake_embed_model() -> None:
    Settings.embed_model = _FakeEmbed()
    storage_module.clear_index_cache()
    yield
    storage_module.clear_index_cache()


def _nodes() -> list[TextNode]:
    nodes = []
    for key in ("alpha", "beta", "gamma", "delta"):
        node = TextNode(text=f"node {key}", id_=key)
        node.embedding = [float(x) for x in _VECTORS[key]]
        nodes.append(node)
    return nodes


def _persist_faiss_index(storage_dir: Path) -> None:
    context = vector_store.new_faiss_storage_context(_DIM)
    assert context is not None
    index = VectorStoreIndex(nodes=_nodes(), storage_context=context)
    context.persist(persist_dir=str(storage_dir))


def _persist_simple_index(storage_dir: Path) -> None:
    index = VectorStoreIndex(nodes=_nodes())  # default = SimpleVectorStore
    index.storage_context.persist(persist_dir=str(storage_dir))


def test_new_index_persists_faiss_and_ranks_by_cosine(tmp_path: Path) -> None:
    _persist_faiss_index(tmp_path)

    assert vector_store.detect_backend(tmp_path) == vector_store.BACKEND_FAISS
    # The default store file holds a binary FAISS index, not JSON.
    head = (tmp_path / vector_store.DEFAULT_VECTOR_STORE_FILENAME).read_bytes()[:1]
    assert head != b"{"

    index = vector_store.load_index(tmp_path)
    results = index.as_retriever(similarity_top_k=2).retrieve("probe")
    ids = [r.node.node_id for r in results]
    # The probe vector aligns most with gamma then alpha under cosine.
    assert ids == ["gamma", "alpha"]


def test_legacy_simple_index_stays_readable_without_mutation(tmp_path: Path) -> None:
    """An existing SimpleVectorStore KB keeps working after the FAISS upgrade."""
    _persist_simple_index(tmp_path)
    assert vector_store.detect_backend(tmp_path) == vector_store.BACKEND_SIMPLE

    index = vector_store.load_index(tmp_path)
    # Loaded as-is (not converted): the read path never rewrites the store.
    assert "Faiss" not in type(index.vector_store).__name__
    assert vector_store.detect_backend(tmp_path) == vector_store.BACKEND_SIMPLE

    results = index.as_retriever(similarity_top_k=2).retrieve("probe")
    assert [r.node.node_id for r in results] == ["gamma", "alpha"]


def test_mixed_dimension_nodes_fall_back_to_simple() -> None:
    text_node = TextNode(text="text", id_="t")
    text_node.embedding = [0.1] * _DIM
    other_node = TextNode(text="other", id_="o")
    other_node.embedding = [0.2] * (_DIM * 2)  # different dimension

    assert vector_store.storage_context_for_nodes([text_node, other_node]) is None


def _multimodal_nodes() -> list[object]:
    """A text + image node sharing one dimension (single multimodal embedding).

    DeepTutor embeds text and images with the *same* embedding client, so both
    modalities produce same-dimension vectors and (in a plain VectorStoreIndex)
    land in the ``default`` store together.
    """
    text_node = TextNode(text="node alpha", id_="text-1")
    text_node.embedding = [float(x) for x in _VECTORS["alpha"]]
    image_node = ImageNode(text="[Image] gamma.png", id_="image-1", image_path="/x/gamma.png")
    image_node.embedding = [float(x) for x in _VECTORS["gamma"]]
    return [text_node, image_node]


def test_multimodal_nodes_indexed_and_retrieved_via_faiss(tmp_path: Path) -> None:
    """Same-dimension text + image vectors are stored in (and served from) FAISS."""
    nodes = _multimodal_nodes()
    context = vector_store.storage_context_for_nodes(nodes)
    assert context is not None, "uniform-dimension multimodal nodes should use FAISS"

    VectorStoreIndex(nodes=nodes, storage_context=context)
    context.persist(persist_dir=str(tmp_path))
    assert vector_store.detect_backend(tmp_path) == vector_store.BACKEND_FAISS

    index = vector_store.load_index(tmp_path)
    results = index.as_retriever(similarity_top_k=2).retrieve("probe")
    returned = {r.node.node_id: type(r.node).__name__ for r in results}
    assert returned == {"text-1": "TextNode", "image-1": "ImageNode"}


def test_legacy_multimodal_simple_index_stays_readable(tmp_path: Path) -> None:
    """A legacy multimodal SimpleVectorStore (text + image in default) still serves both."""
    VectorStoreIndex(nodes=_multimodal_nodes()).storage_context.persist(persist_dir=str(tmp_path))
    assert vector_store.detect_backend(tmp_path) == vector_store.BACKEND_SIMPLE

    index = vector_store.load_index(tmp_path)
    results = index.as_retriever(similarity_top_k=2).retrieve("probe")
    assert {r.node.node_id for r in results} == {"text-1", "image-1"}


def test_uniform_dimension_nodes_select_faiss() -> None:
    nodes = _nodes()
    context = vector_store.storage_context_for_nodes(nodes)
    assert context is not None
    assert "Faiss" in type(context.vector_store).__name__


def test_detect_backend_distinguishes_json_and_binary(tmp_path: Path) -> None:
    simple_dir = tmp_path / "simple"
    simple_dir.mkdir()
    (simple_dir / vector_store.DEFAULT_VECTOR_STORE_FILENAME).write_text(
        '{"embedding_dict": {}}', encoding="utf-8"
    )
    assert vector_store.detect_backend(simple_dir) == vector_store.BACKEND_SIMPLE

    faiss_dir = tmp_path / "faiss"
    faiss_dir.mkdir()
    faiss.write_index(
        faiss.IndexFlatIP(_DIM), str(faiss_dir / vector_store.DEFAULT_VECTOR_STORE_FILENAME)
    )
    assert vector_store.detect_backend(faiss_dir) == vector_store.BACKEND_FAISS

    # Missing file => assume simple (and never crash).
    assert vector_store.detect_backend(tmp_path / "missing") == vector_store.BACKEND_SIMPLE


def test_retrieve_nodes_caches_index_and_invalidates_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _persist_faiss_index(tmp_path)

    load_calls: list[str] = []
    real_load = vector_store.load_index

    def _counting_load(storage_dir):
        load_calls.append(str(storage_dir))
        return real_load(storage_dir)

    monkeypatch.setattr(storage_module.vector_store, "load_index", _counting_load)

    first = storage_module.retrieve_nodes(tmp_path, "probe", top_k=2)
    second = storage_module.retrieve_nodes(tmp_path, "probe", top_k=2)
    assert first and second
    assert len(load_calls) == 1, "second query must reuse the cached index"

    # Touch the docstore so the freshness token changes -> cache invalidated.
    docstore = tmp_path / "docstore.json"
    future = docstore.stat().st_mtime_ns + 1_000_000_000
    os.utime(docstore, ns=(future, future))

    storage_module.retrieve_nodes(tmp_path, "probe", top_k=2)
    assert len(load_calls) == 2, "a changed store must trigger a reload"


def test_validation_skips_binary_faiss_files(tmp_path: Path) -> None:
    """A persisted FAISS index must not trip the SimpleVectorStore validator."""
    _persist_faiss_index(tmp_path)
    # Should not raise despite the binary default__vector_store.json file.
    storage_module.validate_storage_embeddings(tmp_path)


def test_reindex_supersedes_legacy_simple_version_with_faiss(tmp_path: Path) -> None:
    """Re-indexing a legacy KB writes a newer FAISS version that wins on read."""
    from deeptutor.services.rag.index_versioning import (
        EmbeddingSignature,
        resolve_storage_dir_for_read,
        write_version_meta,
    )

    kb_dir = tmp_path / "kb"
    sig = EmbeddingSignature(binding="b", model="m", dimension=_DIM, base_url="", api_version="")

    # version-1: the pre-upgrade SimpleVectorStore index.
    v1 = kb_dir / "version-1"
    v1.mkdir(parents=True)
    _persist_simple_index(v1)
    write_version_meta(kb_dir, sig, storage_dir=v1)

    # version-2: a re-index, persisted as FAISS (same embedding signature).
    v2 = kb_dir / "version-2"
    v2.mkdir()
    _persist_faiss_index(v2)
    write_version_meta(kb_dir, sig, storage_dir=v2)

    resolved = resolve_storage_dir_for_read(kb_dir, sig)
    assert resolved == v2
    assert vector_store.detect_backend(resolved) == vector_store.BACKEND_FAISS


def test_storage_create_index_persists_faiss_end_to_end(tmp_path: Path) -> None:
    """The production create path (ingestion -> storage) persists a FAISS index."""
    from llama_index.core import Document

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()

    count = storage_module.create_index([Document(text="node alpha", id_="d")], storage_dir)
    assert count == 1
    assert vector_store.detect_backend(storage_dir) == vector_store.BACKEND_FAISS
    assert storage_module.retrieve_nodes(storage_dir, "probe", top_k=1)


def test_faiss_persist_and_load_survive_non_ascii_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Persist + load must work on a non-ASCII path (Windows fopen bug).

    Only the *string-path* overload of ``faiss.write_index`` / ``read_index`` is
    affected: it passes the path to C++ ``fopen``, which on Windows uses the
    narrow ANSI API and cannot open non-ASCII paths (a Chinese KB name, a
    ``C:\\Users\\张三`` home) — so index rebuilds crash. The in-memory
    ``IOWriter`` overload that ``serialize_index`` uses is unaffected, which is
    exactly why our store routes through it. The guards below mirror that
    Windows semantics on any platform (fail only when handed a ``str`` path), so
    this test fails if anything regresses to a path-based call.
    """
    real_write, real_read = faiss.write_index, faiss.read_index

    def _guard_write(index: object, target: object, *args: object, **kwargs: object) -> object:
        if isinstance(target, str):
            raise RuntimeError("simulated Windows narrow-fopen failure on non-ASCII path")
        return real_write(index, target, *args, **kwargs)

    def _guard_read(source: object, *args: object, **kwargs: object) -> object:
        if isinstance(source, str):
            raise RuntimeError("simulated Windows narrow-fopen failure on non-ASCII path")
        return real_read(source, *args, **kwargs)

    monkeypatch.setattr(faiss, "write_index", _guard_write)
    monkeypatch.setattr(faiss, "read_index", _guard_read)

    # A Chinese KB-name segment plus a flat version dir, mirroring real layout.
    storage_dir = tmp_path / "数学课程" / "version-1"
    storage_dir.mkdir(parents=True)

    _persist_faiss_index(storage_dir)  # write path: would raise via write_index
    assert vector_store.detect_backend(storage_dir) == vector_store.BACKEND_FAISS

    index = vector_store.load_index(storage_dir)  # read path: would raise via read_index
    results = index.as_retriever(similarity_top_k=2).retrieve("probe")
    assert [r.node.node_id for r in results] == ["gamma", "alpha"]


def test_faiss_index_bytes_stay_cross_readable_with_stock_faiss(tmp_path: Path) -> None:
    """Our serialize-based IO and stock path-based IO share one on-disk format.

    Guarantees existing indexes (written by an older ``faiss.write_index``) stay
    loadable, and new ones written by us stay readable by stock FAISS tooling.
    """
    idx = faiss.IndexFlatIP(_DIM)
    idx.add(np.asarray([_VECTORS["alpha"], _VECTORS["beta"]], dtype="float32"))

    ours = tmp_path / "ours.faiss"
    vector_store.faiss_write_index(idx, str(ours))
    assert faiss.read_index(str(ours)).ntotal == 2  # stock reader reads our bytes

    stock = tmp_path / "stock.faiss"
    faiss.write_index(idx, str(stock))
    assert vector_store.faiss_read_index(str(stock)).ntotal == 2  # our reader reads stock bytes
