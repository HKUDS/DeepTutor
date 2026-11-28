from __future__ import annotations

from llama_index.core import Document
from llama_index.core.schema import TextNode


def test_documents_do_not_bypass_chunking_pipeline(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import ingestion

    captured: dict[str, object] = {}

    class FakePipeline:
        def run(self, *, documents, show_progress):
            captured["documents"] = list(documents)
            captured["show_progress"] = show_progress
            return [f"chunked:{type(item).__name__}" for item in documents]

    monkeypatch.setattr(ingestion, "build_ingestion_pipeline", lambda: FakePipeline())

    llama_document = Document(text="long document text")
    embedded_node = TextNode(text="already embedded", embedding=[0.1, 0.2])
    plain_node = TextNode(text="node without embedding")

    nodes = ingestion.documents_to_nodes(
        [llama_document, embedded_node, plain_node],
        show_progress=False,
    )

    assert captured["documents"] == [llama_document, plain_node]
    assert captured["show_progress"] is False
    assert nodes == ["chunked:Document", "chunked:TextNode", embedded_node]


def test_progress_disabled_when_stdout_is_not_a_tty(monkeypatch) -> None:
    """tqdm progress bars must be suppressed in headless/server contexts.

    When DeepTutor runs as a server, stdout is a pipe whose read end can
    close mid-indexing; a tqdm write then raises BrokenPipeError and kills
    document indexing. ``should_show_progress`` must return False for a
    non-interactive stream so no tqdm bar is ever created.
    """
    from deeptutor.services.rag.pipelines.llamaindex.config import should_show_progress

    class _NonTtyStream:
        def isatty(self) -> bool:
            return False

    monkeypatch.setattr("sys.stdout", _NonTtyStream())
    assert should_show_progress() is False

    class _TtyStream:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdout", _TtyStream())
    assert should_show_progress() is True


def test_documents_to_nodes_resolves_progress_at_call_time(monkeypatch) -> None:
    """The tqdm decision must be made per call, not frozen at import.

    ``show_progress: bool = should_show_progress()`` would evaluate once when the
    module is first imported, baking in whatever ``sys.stdout`` looked like then:
    a server started from a terminal would keep writing tqdm bars into a pipe
    that can close mid-indexing (the BrokenPipeError this guards against), and a
    piped CLI would never show progress again. Both directions are asserted so a
    regression to a default-argument call cannot pass under pytest's captured,
    non-tty stdout.
    """
    from deeptutor.services.rag.pipelines.llamaindex import ingestion

    captured: dict[str, object] = {}

    class FakePipeline:
        def run(self, *, documents, show_progress):
            captured["show_progress"] = show_progress
            return list(documents)

    monkeypatch.setattr(ingestion, "build_ingestion_pipeline", lambda: FakePipeline())

    class _Stream:
        def __init__(self, tty: bool) -> None:
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    monkeypatch.setattr("sys.stdout", _Stream(tty=False))
    ingestion.documents_to_nodes([Document(text="x")])
    assert captured["show_progress"] is False

    monkeypatch.setattr("sys.stdout", _Stream(tty=True))
    ingestion.documents_to_nodes([Document(text="x")])
    assert captured["show_progress"] is True


def test_sentence_splitter_ignores_nltk_redos_process_cpu_timeout(monkeypatch) -> None:
    """Issue #3030: NLTK 3.10.4's regex timeout must not abort large-document splitting.

    NLTK 3.10.4 routes Punkt's built-in patterns through ``nltk.redos``, whose
    ``regex`` timeout counts whole-process CPU time. Stock Punkt tokenization
    hits ``TimeoutError`` on a large single-block document when the timeout
    budget is tight; DeepTutor's splitter must succeed with identical chunks,
    without mutating global ``nltk.redos.DEFAULT_TIMEOUT``, and without loading
    ``corpora/stopwords`` through ``globals_helper.punkt_tokenizer``.
    """
    import pytest

    redos = pytest.importorskip("nltk.redos")
    from llama_index.core import Settings
    from llama_index.core.embeddings import MockEmbedding
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.node_parser.text.utils import split_by_sentence_tokenizer_internal
    from nltk.tokenize import PunktSentenceTokenizer

    from deeptutor.services.rag.pipelines.llamaindex import ingestion

    text = "Dr. Smith analyzed the 3.14 benchmark results carefully! Next sentence follows. " * 4000
    doc = Document(text=text)

    # Use stock PunktSentenceTokenizer directly (matching LlamaIndex's default
    # split_by_sentence_tokenizer) without triggering globals_helper's unrelated
    # stopwords disk load, which NLTK 3.10.4's pathsec rejects on group-writable
    # site-packages caches.
    stock_punkt = PunktSentenceTokenizer()
    stock_splitter = SentenceSplitter(
        chunk_size=512,
        chunk_overlap=50,
        chunking_tokenizer_fn=lambda s: split_by_sentence_tokenizer_internal(s, stock_punkt),
    )

    # Capture reference chunks from stock Punkt with no timeout limit.
    with monkeypatch.context() as ref_ctx:
        ref_ctx.setattr(redos, "DEFAULT_TIMEOUT", None)
        expected_texts = [node.text for node in stock_splitter.get_nodes_from_documents([doc])]

    tight_timeout = 0.005
    monkeypatch.setattr(redos, "DEFAULT_TIMEOUT", tight_timeout)
    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))
    monkeypatch.setattr(Settings, "chunk_size", 512)
    monkeypatch.setattr(Settings, "chunk_overlap", 50)
    monkeypatch.setattr(ingestion, "_UNTIMED_PUNKT_TOKENIZER", None)

    # Confirm the failure mode reproduces on stock PunktSentenceTokenizer.
    with pytest.raises(TimeoutError, match="time limit"):
        stock_splitter.get_nodes_from_documents([doc])

    # Confirm DeepTutor's splitter never touches globals_helper / stopwords disk cache.
    from llama_index.core import utils as llama_utils

    def _forbid_globals_helper(*_args, **_kwargs):
        raise AssertionError("build_sentence_splitter must not rely on globals_helper stopwords")

    monkeypatch.setattr(
        llama_utils.GlobalsHelper, "punkt_tokenizer", property(_forbid_globals_helper)
    )

    nodes = ingestion.documents_to_nodes([doc], show_progress=False)

    assert [node.text for node in nodes] == expected_texts
    assert redos.DEFAULT_TIMEOUT == tight_timeout


def test_sentence_splitter_succeeds_under_concurrent_cpu_load(monkeypatch) -> None:
    """Concurrent busy threads must not trip NLTK's process-CPU regex timeout."""
    import hashlib
    import threading

    import pytest

    redos = pytest.importorskip("nltk.redos")
    from deeptutor.services.rag.pipelines.llamaindex import ingestion

    tight_timeout = 0.05
    monkeypatch.setattr(redos, "DEFAULT_TIMEOUT", tight_timeout)
    text = "Sentence one explains the algorithm. Sentence two verifies the bound! " * 3000
    doc = Document(text=text)

    stop = threading.Event()

    def burn_cpu() -> None:
        block = b"x" * (1 << 16)
        while not stop.is_set():
            hashlib.sha256(block).digest()

    workers = [threading.Thread(target=burn_cpu, daemon=True) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        splitter = ingestion.build_sentence_splitter(chunk_size=512, chunk_overlap=50)
        nodes = splitter.get_nodes_from_documents([doc])
    finally:
        stop.set()
        for worker in workers:
            worker.join(timeout=2)

    assert len(nodes) > 1
    assert redos.DEFAULT_TIMEOUT == tight_timeout


def test_disable_redos_timeout_is_noop_for_plain_regex() -> None:
    import re

    from deeptutor.services.rag.pipelines.llamaindex import ingestion

    plain = re.compile(r"\w+")
    assert ingestion._disable_redos_timeout(plain) is plain
