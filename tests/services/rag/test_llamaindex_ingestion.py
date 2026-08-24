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
