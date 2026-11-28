"""LlamaIndex ingestion helpers.

This module keeps DeepTutor's indexing path thin by delegating parsing
transformations and embedding to LlamaIndex's official IngestionPipeline.
"""

from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Callable

from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode

from . import vector_store
from .config import should_show_progress, vector_index_config_from_settings
from .embedding_adapter import current_embedding

_PUNKT_LOCK = threading.Lock()
_UNTIMED_PUNKT_CACHE: tuple[Any, Any] | None = None


def _disable_redos_timeout(pattern: Any) -> Any:
    """Return ``pattern`` with any ``nltk.redos.TimedPattern`` timeout disabled.

    NLTK 3.10.4 compiles Punkt's built-in patterns through ``nltk.redos``, which
    enforces a 5s ``regex`` timeout counted in whole-process CPU time across all
    threads. When chat turns stream concurrently in the same process, a single
    whole-document ``finditer`` scan can trip that limit with ``TimeoutError``.
    Disabling the timeout only on our private Punkt tokenizer's constant
    patterns avoids mutating process-global ``nltk.redos.DEFAULT_TIMEOUT`` and
    is a no-op on NLTK < 3.10.4.
    """
    try:
        from nltk import redos
    except ImportError:
        return pattern
    if isinstance(pattern, redos.TimedPattern):
        return redos.compile(pattern, timeout=None)
    return pattern


def _untimed_punkt_tokenizer() -> Any:
    """Return a thread-safe Punkt tokenizer derived from LlamaIndex's singleton
    whose built-in constant patterns do not inherit ``nltk.redos.DEFAULT_TIMEOUT``.
    """
    global _UNTIMED_PUNKT_CACHE

    from llama_index.core.utils import globals_helper

    base = globals_helper.punkt_tokenizer
    cached = _UNTIMED_PUNKT_CACHE
    if cached is not None and cached[0] is base:
        return cached[1]

    with _PUNKT_LOCK:
        cached = _UNTIMED_PUNKT_CACHE
        if cached is not None and cached[0] is base:
            return cached[1]

        try:
            from nltk import redos  # noqa: F401
            from nltk.tokenize import punkt
        except ImportError:
            _UNTIMED_PUNKT_CACHE = (base, base)
            return base

        base_lang_vars = getattr(base, "_lang_vars", None)
        base_token_cls = getattr(base, "_Token", None)
        if base_lang_vars is None or base_token_cls is None:
            _UNTIMED_PUNKT_CACHE = (base, base)
            return base

        base_lang_vars_cls = type(base_lang_vars)

        class _UntimedPunktLanguageVars(base_lang_vars_cls):
            __slots__ = ()
            re_boundary_realignment = _disable_redos_timeout(base_lang_vars.re_boundary_realignment)

        lang_vars = _UntimedPunktLanguageVars()
        # Eagerly populate both slotted patterns so concurrent indexing threads
        # never race on NLTK's lazy attribute initialization.
        lang_vars._re_period_context = _disable_redos_timeout(base_lang_vars.period_context_re())
        lang_vars._re_word_tokenizer = _disable_redos_timeout(base_lang_vars._word_tokenizer_re())

        untimed_non_punct = _disable_redos_timeout(getattr(punkt, "_re_non_punct", None))

        class _UntimedPunktToken(base_token_cls):
            __slots__ = ()
            _RE_ELLIPSIS = _disable_redos_timeout(base_token_cls._RE_ELLIPSIS)
            _RE_NUMERIC = _disable_redos_timeout(base_token_cls._RE_NUMERIC)
            _RE_INITIAL = _disable_redos_timeout(base_token_cls._RE_INITIAL)
            _RE_ALPHA = _disable_redos_timeout(base_token_cls._RE_ALPHA)

            if untimed_non_punct is not None:

                @property
                def is_non_punct(self) -> Any:
                    return untimed_non_punct.search(self.type)

        tokenizer = type(base)(lang_vars=lang_vars, token_cls=_UntimedPunktToken)
        tokenizer._params = base._params
        _UNTIMED_PUNKT_CACHE = (base, tokenizer)
        return tokenizer


def _split_by_untimed_sentence_tokenizer() -> Callable[[str], list[str]]:
    """Mirror LlamaIndex's ``split_by_sentence_tokenizer`` without the process-CPU cap."""
    from llama_index.core.node_parser.text.utils import split_by_sentence_tokenizer_internal

    return lambda text: split_by_sentence_tokenizer_internal(text, _untimed_punkt_tokenizer())


def build_sentence_splitter(*, chunk_size: int, chunk_overlap: int) -> SentenceSplitter:
    """Create a ``SentenceSplitter`` immune to NLTK 3.10.4's process-CPU regex cap."""
    return SentenceSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunking_tokenizer_fn=_split_by_untimed_sentence_tokenizer(),
    )


def build_ingestion_pipeline() -> IngestionPipeline:
    """Create the default DeepTutor ingestion pipeline.

    The embedding step uses ``Settings.embed_model``, which is configured by
    ``embedding_adapter.configure_llamaindex_settings`` to call DeepTutor's
    configured embedding service rather than any local model.
    """

    return IngestionPipeline(
        transformations=[
            build_sentence_splitter(
                chunk_size=Settings.chunk_size,
                chunk_overlap=Settings.chunk_overlap,
            ),
            current_embedding(),
        ],
    )


def _has_precomputed_embedding(document: Any) -> bool:
    """Return True only for non-Document nodes that already carry a vector.

    LlamaIndex's ``Document`` class inherits from ``BaseNode``, so a naive
    ``isinstance(doc, BaseNode)`` check incorrectly classifies every Document
    as pre-embedded, bypassing the chunking pipeline entirely. This helper
    distinguishes genuinely pre-embedded nodes (e.g. ImageNode produced by
    multimodal loaders) from regular Documents that still need splitting and
    embedding. The embedding may be a list or a numpy array, so we check
    ``len(...) > 0`` rather than ``bool(...)`` (ambiguous for ndarrays).
    """
    if isinstance(document, Document):
        return False
    if not isinstance(document, BaseNode):
        return False
    embedding = getattr(document, "embedding", None)
    if embedding is None:
        return False
    try:
        return len(embedding) > 0
    except TypeError:
        return True


def documents_to_nodes(documents: list[Any], *, show_progress: bool | None = None) -> list[Any]:
    """Convert LlamaIndex documents into embedded nodes.

    Pre-embedded nodes, such as ImageNode instances produced by the document
    loader, pass through unchanged so they are not re-embedded as text.

    ``show_progress=None`` resolves the tqdm decision at call time. It must not
    be a default-argument call: Python evaluates those once at import, which
    would freeze whatever ``sys.stdout`` happened to be when the module first
    loaded.
    """
    if show_progress is None:
        show_progress = should_show_progress()
    text_documents = [
        document for document in documents if not _has_precomputed_embedding(document)
    ]
    preembedded_nodes = [document for document in documents if _has_precomputed_embedding(document)]

    nodes: list[Any] = []
    if text_documents:
        pipeline = build_ingestion_pipeline()
        nodes.extend(pipeline.run(documents=text_documents, show_progress=show_progress))
    nodes.extend(preembedded_nodes)
    return nodes


def create_index_from_documents(
    documents: list[Any], storage_dir: Path, *, show_progress: bool | None = None
) -> tuple[VectorStoreIndex, int]:
    """Create and persist a VectorStoreIndex from documents.

    Uses a FAISS-backed store when available and all node embeddings share one
    dimension; otherwise LlamaIndex's default SimpleVectorStore.
    """
    if show_progress is None:
        show_progress = should_show_progress()
    nodes = documents_to_nodes(documents, show_progress=show_progress)
    storage_context = vector_store.storage_context_for_nodes(
        nodes, vector_index_config_from_settings()
    )
    index = VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        show_progress=show_progress,
        embed_model=current_embedding(),
    )
    index.storage_context.persist(persist_dir=str(storage_dir))
    return index, len(documents)


def insert_documents_into_index(
    index: Any, documents: list[Any], *, show_progress: bool | None = None
) -> int:
    """Transform documents once, then insert nodes into an existing index."""
    nodes = documents_to_nodes(documents, show_progress=show_progress)
    index.insert_nodes(nodes)
    return len(documents)


__all__ = [
    "build_ingestion_pipeline",
    "build_sentence_splitter",
    "create_index_from_documents",
    "documents_to_nodes",
    "insert_documents_into_index",
]
