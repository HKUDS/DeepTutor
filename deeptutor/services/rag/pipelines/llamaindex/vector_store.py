"""Vector-store backend selection for the LlamaIndex RAG pipeline.

This module is the single seam between DeepTutor's LlamaIndex pipeline and the
concrete vector store implementation. It exists so the rest of the pipeline
(ingestion, storage, retrieval) never has to know *how* vectors are stored.

Why it exists
-------------
LlamaIndex's built-in ``SimpleVectorStore`` keeps every embedding in a JSON
document and performs a pure-Python, O(N) brute-force scan on each query. On a
large knowledge base that is re-parsed and re-scanned per query, which pins a
CPU core and makes retrieval take minutes (issue #552).

This seam swaps in a FAISS index instead:

* New (and re-indexed) knowledge bases are persisted as a binary FAISS index
  (``IndexFlatIP``), loaded once and searched with vectorized BLAS.
* Legacy ``SimpleVectorStore`` knowledge bases stay fully readable, so upgrading
  never breaks an existing index. Re-indexing one rebuilds it as FAISS for the
  full speed-up.

FAISS is optional. When ``faiss`` / ``llama-index-vector-stores-faiss`` are not
importable, every path falls back to ``SimpleVectorStore`` so retrieval keeps
working (just without the speed-up).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, Optional

from fsspec.implementations.local import LocalFileSystem
from llama_index.core import StorageContext, load_index_from_storage
from llama_index.core.vector_stores.simple import DEFAULT_VECTOR_STORE, NAMESPACE_SEP
import numpy as np

logger = logging.getLogger(__name__)

BACKEND_FAISS = "faiss"
BACKEND_SIMPLE = "simple"

# The default vector store is always persisted under this filename, whether it
# holds a SimpleVectorStore JSON document or a binary FAISS index. The first
# byte disambiguates the two: "{" => JSON/simple, anything else => FAISS.
DEFAULT_VECTOR_STORE_FILENAME = f"{DEFAULT_VECTOR_STORE}{NAMESPACE_SEP}vector_store.json"

_COSINE_FAISS_CLS: Optional[type] = None


def _faiss_modules() -> tuple[Any, Any]:
    """Return ``(faiss, FaissVectorStore)`` or ``(None, None)`` when unavailable."""
    try:
        import faiss
        from llama_index.vector_stores.faiss import FaissVectorStore
    except Exception:  # pragma: no cover - exercised only without faiss installed
        return None, None
    return faiss, FaissVectorStore


def faiss_available() -> bool:
    """True when both the FAISS library and its LlamaIndex integration import."""
    faiss, faiss_store_cls = _faiss_modules()
    return faiss is not None and faiss_store_cls is not None


def _normalize(embedding: Any) -> list[float]:
    """L2-normalize an embedding so inner product equals cosine similarity."""
    vector = np.asarray(embedding, dtype="float32")
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm
    return vector.tolist()


def faiss_write_index(index: Any, persist_path: str) -> None:
    """Persist a FAISS index through a Python byte stream (Unicode-path safe).

    Stock ``faiss.write_index`` is a SWIG passthrough that hands the path
    straight to C++ ``fopen``. On Windows that is the *narrow* ANSI API, while
    SWIG encodes the Python string as UTF-8 — so any non-ASCII path (a Chinese
    knowledge-base name, or a ``C:\\Users\\张三`` home directory) fails to open
    and index rebuilds crash. Serializing to bytes in memory and letting Python
    write the file sidesteps this: CPython opens files via the wide ``_wfopen``
    API on Windows, so Unicode paths work. The byte payload is identical to
    ``write_index`` output, so indexes stay cross-readable with stock FAISS.
    """
    import faiss

    payload = faiss.serialize_index(index)
    with open(persist_path, "wb") as handle:
        handle.write(payload.tobytes())


def faiss_read_index(persist_path: str) -> Any:
    """Load a FAISS index written by :func:`faiss_write_index` (or stock FAISS).

    The on-disk format is identical either way, so this also reads indexes
    persisted by an older ``faiss.write_index`` call. Reading the bytes with
    Python ``open`` keeps the load path Unicode-safe on Windows, mirroring
    :func:`faiss_write_index`.
    """
    import faiss

    with open(persist_path, "rb") as handle:
        buffer = np.frombuffer(handle.read(), dtype="uint8")
    return faiss.deserialize_index(buffer)


def _cosine_faiss_cls() -> Optional[type]:
    """Return a memoized FaissVectorStore subclass that ranks by cosine.

    Stock ``FaissVectorStore`` normalizes neither on add nor on query, so an
    ``IndexFlatIP`` would rank by raw dot product. Normalizing both sides makes
    inner-product ranking identical to the cosine similarity SimpleVectorStore
    used, preserving retrieval behaviour after the backend swap.
    """
    global _COSINE_FAISS_CLS
    if _COSINE_FAISS_CLS is not None:
        return _COSINE_FAISS_CLS

    _, faiss_store_cls = _faiss_modules()
    if faiss_store_cls is None:
        return None

    class _CosineFaissVectorStore(faiss_store_cls):  # type: ignore[valid-type, misc]
        """FAISS store that L2-normalizes vectors for cosine ranking.

        It also overrides persistence to route through :func:`faiss_write_index`
        / :func:`faiss_read_index` instead of the stock path-based
        ``faiss.write_index`` / ``read_index``, which cannot handle non-ASCII
        paths on Windows. The two concerns are independent: cosine ranking
        shapes *what* is stored, the IO override shapes *how* it reaches disk.
        """

        def add(self, nodes: list[Any], **kwargs: Any) -> list[str]:
            for node in nodes:
                node.embedding = _normalize(node.get_embedding())
            return super().add(nodes, **kwargs)

        def query(self, query: Any, **kwargs: Any) -> Any:
            if getattr(query, "query_embedding", None) is not None:
                query.query_embedding = _normalize(query.query_embedding)
            return super().query(query, **kwargs)

        def persist(self, persist_path: str, fs: Any = None) -> None:
            if fs is not None and not isinstance(fs, LocalFileSystem):
                raise NotImplementedError("FAISS only supports local storage for now.")
            dirpath = os.path.dirname(persist_path)
            if dirpath:
                os.makedirs(dirpath, exist_ok=True)
            faiss_write_index(self._faiss_index, persist_path)

        @classmethod
        def from_persist_path(cls, persist_path: str, fs: Any = None) -> Any:
            if fs is not None and not isinstance(fs, LocalFileSystem):
                raise NotImplementedError("FAISS only supports local storage for now.")
            if not os.path.exists(persist_path):
                raise ValueError(f"No existing FAISS index found at {persist_path}.")
            return cls(faiss_index=faiss_read_index(persist_path))

    _COSINE_FAISS_CLS = _CosineFaissVectorStore
    return _COSINE_FAISS_CLS


def _uniform_dimension(embeddings: Iterable[Any]) -> Optional[int]:
    """Return the shared embedding dimension, or None if missing/ragged.

    Mixed dimensions (e.g. text + multimodal image vectors) cannot live in a
    single fixed-width FAISS index, so callers fall back to SimpleVectorStore.
    """
    dimension: Optional[int] = None
    for embedding in embeddings:
        if embedding is None:
            return None
        length = len(embedding)
        if dimension is None:
            dimension = length
        elif length != dimension:
            return None
    return dimension if dimension and dimension > 0 else None


def new_faiss_storage_context(dimension: int) -> Optional[StorageContext]:
    """Return a StorageContext whose default store is a fresh cosine FAISS index.

    Returns None when FAISS is unavailable or the dimension is invalid, so
    callers fall back to the default SimpleVectorStore StorageContext.
    """
    faiss, _ = _faiss_modules()
    cosine_cls = _cosine_faiss_cls()
    if faiss is None or cosine_cls is None or dimension <= 0:
        return None
    store = cosine_cls(faiss_index=faiss.IndexFlatIP(dimension))
    return StorageContext.from_defaults(vector_store=store)


def storage_context_for_nodes(nodes: list[Any]) -> Optional[StorageContext]:
    """Choose the write-time StorageContext for a set of embedded nodes.

    Returns a FAISS-backed context when every node shares one embedding
    dimension and FAISS is available; otherwise None (use the SimpleVectorStore
    default). ``None`` keeps multimodal / mixed-dimension and faiss-less installs
    on the original code path.
    """
    if not faiss_available():
        return None
    dimension = _uniform_dimension(getattr(node, "embedding", None) for node in nodes)
    if dimension is None:
        return None
    return new_faiss_storage_context(dimension)


def detect_backend(storage_dir: Path) -> str:
    """Detect a persisted index's vector backend from its default store file."""
    path = Path(storage_dir) / DEFAULT_VECTOR_STORE_FILENAME
    try:
        with open(path, "rb") as handle:
            head = handle.read(1)
    except OSError:
        return BACKEND_SIMPLE
    return BACKEND_SIMPLE if head[:1] == b"{" else BACKEND_FAISS


def load_index(storage_dir: Path) -> Any:
    """Load a persisted index for retrieval.

    FAISS-persisted versions load their binary index directly. Legacy
    SimpleVectorStore versions load unchanged and stay queryable; re-indexing
    such a knowledge base rebuilds it as FAISS for the full speed-up.
    """
    storage_dir = Path(storage_dir)

    if detect_backend(storage_dir) == BACKEND_FAISS:
        cosine_cls = _cosine_faiss_cls()
        if cosine_cls is None:
            raise RuntimeError(
                "This knowledge base was indexed with FAISS but the 'faiss-cpu' "
                "package is not installed. Install it (pip install faiss-cpu) or "
                "re-index the knowledge base to query it again."
            )
        vector_store = cosine_cls.from_persist_dir(str(storage_dir))
        context = StorageContext.from_defaults(
            persist_dir=str(storage_dir), vector_store=vector_store
        )
        return load_index_from_storage(context)

    context = StorageContext.from_defaults(persist_dir=str(storage_dir))
    return load_index_from_storage(context)


__all__ = [
    "BACKEND_FAISS",
    "BACKEND_SIMPLE",
    "DEFAULT_VECTOR_STORE_FILENAME",
    "detect_backend",
    "faiss_available",
    "faiss_read_index",
    "faiss_write_index",
    "load_index",
    "new_faiss_storage_context",
    "storage_context_for_nodes",
]
