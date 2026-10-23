"""Durable outcomes, interruption, cancellation and publication (#1612)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.knowledge.indexing_run import (
    IndexingBusyError,
    IndexingCancelled,
    IndexingRun,
    current_run,
    load_run,
    request_cancel,
    visible_run,
)
from deeptutor.services.rag.index_versioning import (
    EmbeddingSignature,
    list_kb_versions,
    resolve_storage_dir_for_rebuild,
    write_version_meta,
)


def test_retry_retains_source_identity_and_verified_parse_receipt(tmp_path):
    source = tmp_path / "raw" / "book.pdf"
    source.parent.mkdir()
    source.write_bytes(b"original textbook")
    with IndexingRun(tmp_path, [str(source)], task_id="first") as run:
        run.document(source, "parsed", parse_reused=True)
        run.finish("failed", error=TimeoutError("embedding timed out"))
    first = load_run(tmp_path)
    assert first["error_code"] == "timeout"
    assert first["documents"]["book.pdf"]["status"] == "unknown"
    with IndexingRun(tmp_path, [str(source)], task_id="retry") as run:
        assert run.data["previous_task_id"] == "first"
        assert (
            run.data["documents"]["book.pdf"]["source_hash"]
            == first["documents"]["book.pdf"]["source_hash"]
        )
        run.document(source, "completed", parse_reused=True)
        run.finish("completed", version="version-2")
    assert visible_run(tmp_path)["usable_version"] == "version-2"
    assert current_run() is None


def test_cancel_is_owned_by_task_and_preserves_newer_worker(tmp_path):
    with IndexingRun(tmp_path, [], task_id="one") as run:
        assert not request_cancel(tmp_path, "other")
        assert request_cancel(tmp_path, "one")
        with pytest.raises(IndexingCancelled):
            run.check()
        run.finish("cancelled")
    with IndexingRun(tmp_path, [], task_id="two") as run:
        run.check()
        assert not request_cancel(tmp_path, "one")
        run.finish("completed")


def test_live_owner_cannot_be_replaced_and_corrupt_journal_survives(tmp_path):
    with IndexingRun(tmp_path, [], task_id="one") as run:
        with pytest.raises(IndexingBusyError):
            with IndexingRun(tmp_path, [], task_id="two"):
                pass
        run.finish("completed")
    path = tmp_path / ".indexing-run.json"
    path.write_text("{broken")
    with pytest.raises(OSError):
        with IndexingRun(tmp_path, []):
            pass
    assert path.read_text() == "{broken"


def test_restart_projection_is_read_only_and_retains_completed_sources(tmp_path):
    with IndexingRun(tmp_path, [], task_id="crashed") as run:
        run.finish("completed")
    path = tmp_path / ".indexing-run.json"
    data = json.loads(path.read_text())
    data.update(
        state="running",
        pid=999999999,
        documents={"a.pdf": {"status": "completed"}, "b.pdf": {"status": "embedding"}},
    )
    path.write_text(json.dumps(data))
    original = path.read_bytes()
    result = visible_run(tmp_path)
    assert result["state"] == "interrupted"
    assert result["documents"]["a.pdf"]["status"] == "completed"
    assert result["documents"]["b.pdf"]["status"] == "unknown"
    assert path.read_bytes() == original


def test_changed_source_cannot_be_published(tmp_path):
    source = tmp_path / "raw" / "book.txt"
    source.parent.mkdir()
    source.write_text("before")
    with IndexingRun(tmp_path, [str(source)]) as run:
        run.document(source, "embedding")
        source.write_text("after")
        with pytest.raises(RuntimeError, match="Source changed"):
            run.verify_sources()
        run.finish("failed")


def test_incomplete_version_is_not_queryable_and_previous_version_survives(tmp_path):
    signature = EmbeddingSignature("openai", "model", 3, "https://example.test", "")
    old = resolve_storage_dir_for_rebuild(tmp_path, signature, publication_guard=True)
    (old / "docstore.json").write_text("{}")
    write_version_meta(tmp_path, signature, old)
    candidate = resolve_storage_dir_for_rebuild(tmp_path, signature, publication_guard=True)
    (candidate / "docstore.json").write_text("partial")
    from deeptutor.services.rag.index_probe import inspect_provider_index

    assert not inspect_provider_index("llamaindex", candidate).ready
    versions = list_kb_versions(tmp_path)
    assert next(row for row in versions if row["version"] == old.name)["ready"]
    assert not next(row for row in versions if row["version"] == candidate.name)["ready"]


def test_failure_details_redact_quoted_credentials(tmp_path):
    with IndexingRun(tmp_path, []) as run:
        run.finish("failed", error=RuntimeError('error {"api_key": "secret"} Bearer abc123'))
    detail = load_run(tmp_path)["error"]
    assert "secret" not in detail and "abc123" not in detail


def test_real_persisted_index_reloads_and_missing_vectors_fail(tmp_path, monkeypatch):
    from llama_index.core import Document, Settings, VectorStoreIndex
    from llama_index.core.embeddings import MockEmbedding

    from deeptutor.services.rag.pipelines.llamaindex import storage

    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))
    index = VectorStoreIndex.from_documents(
        [Document(text="A known source about Fourier transforms.")]
    )
    index.storage_context.persist(persist_dir=str(tmp_path))
    storage.verify_persisted_index(tmp_path)
    (tmp_path / "default__vector_store.json").unlink()
    with pytest.raises(Exception):
        storage.verify_persisted_index(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["local", "cloud"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_mineru_failure_publishes_remaining_documents_as_partial(
    tmp_path, monkeypatch, mode, cancelled
):
    """#1982: the real parser error crosses loading, persistence and the run journal."""
    from llama_index.core import Settings
    from llama_index.core.embeddings import MockEmbedding

    from deeptutor.services import parsing
    from deeptutor.services.parsing import service as parse_module
    from deeptutor.services.parsing.base import ReadinessReport
    from deeptutor.services.parsing.engines.mineru import backend
    from deeptutor.services.parsing.engines.mineru.config import MinerUConfig, MinerUError
    from deeptutor.services.parsing.engines.mineru.engine import MinerUParser
    from deeptutor.services.rag.pipelines.llamaindex import storage, vector_store
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline
    from deeptutor.services.rag.service import RAGService

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    bad, good = raw / "failed.docx", raw / "next.docx"
    bad.write_bytes(b"failed source")
    good.write_bytes(b"good source")
    parser = MinerUParser()
    monkeypatch.setattr(parser, "resolve_config", lambda: MinerUConfig(mode=mode))
    monkeypatch.setattr(parser, "is_ready", lambda config: ReadinessReport(True))
    monkeypatch.setattr(parse_module, "get_parser", lambda name: parser)
    service = parse_module.ParseService(cache_root=tmp_path / "parse_cache")
    monkeypatch.setattr(service, "active_engine", lambda: "mineru")
    monkeypatch.setattr(parsing, "get_parse_service", lambda: service)
    attempts = []

    def parse(source, workdir, **kwargs):
        attempts.append(source.name)
        if source == bad:
            if cancelled:
                assert request_cancel(kb_dir, current_run().task_id)
                raise MinerUError("Local MinerU parsing was cancelled", code="cancelled")
            raise MinerUError("1 task(s) failed: Timed out waiting for result", code="timeout")
        (workdir / "full.md").write_text("The next document explains Fourier transforms.")

    monkeypatch.setattr(backend, "parse_document_to_workdir", parse)
    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))
    pipeline = LlamaIndexPipeline(str(tmp_path), signature_provider=lambda: None)
    monkeypatch.setattr(pipeline, "_configure_settings", lambda: None)

    async def offline_connectivity():
        return None

    monkeypatch.setattr(pipeline, "_verify_embedding_connectivity", offline_connectivity)
    rag = RAGService(str(tmp_path), provider="llamaindex")
    rag._pipelines["llamaindex"] = pipeline
    if cancelled:
        with pytest.raises(IndexingCancelled):
            await rag._index("kb", [str(bad), str(good)], "initialize", {})
        assert attempts == [bad.name]
        assert load_run(kb_dir)["state"] == "cancelled"
        assert not load_run(kb_dir).get("usable_version")
        return
    assert await rag._index("kb", [str(bad), str(good)], "initialize", {})

    journal = load_run(kb_dir)
    assert attempts == [bad.name, good.name]
    assert journal["state"] == "partial"
    assert journal["documents"][bad.name]["status"] == "failed"
    assert "Timed out waiting" in journal["documents"][bad.name]["detail"]
    assert journal["documents"][good.name]["status"] == "completed"
    published = kb_dir / journal["usable_version"]
    storage.verify_persisted_index(published)
    reloaded = vector_store.load_index(published)
    assert any("Fourier" in node.text for node in reloaded.docstore.docs.values())

    # Retry must reuse the good parse even though its previous run was partial.
    assert await rag._index("kb", [str(bad), str(good)], "initialize", {})
    assert attempts == [bad.name, good.name, bad.name]
    assert load_run(kb_dir)["documents"][good.name]["parse_reused"] is True


@pytest.mark.asyncio
async def test_readiness_is_local_and_cancel_requires_writable_owned_task(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from deeptutor.api.routers import knowledge
    from deeptutor.services.embedding import config
    from deeptutor.services.parsing import base
    from deeptutor.services.parsing.engines import factory

    resource = SimpleNamespace(name="kb", base_dir=tmp_path)
    monkeypatch.setattr(knowledge, "resolve_kb", lambda name: resource)
    monkeypatch.setattr(
        factory,
        "get_parser",
        lambda name: SimpleNamespace(
            resolve_config=lambda: SimpleNamespace(mode="local", device="cpu"),
            is_ready=lambda config: base.ReadinessReport(
                False, "models_missing", "Download models explicitly."
            ),
            supported_formats=lambda: {".pdf"},
        ),
    )
    monkeypatch.setattr(config, "get_embedding_config", lambda: SimpleNamespace(model="known"))
    result = await knowledge.get_indexing_readiness("kb")
    assert not result["ready"] and result["reason"] == "models_missing"
    assert result["device"] == "cpu"
    assert not (tmp_path / "kb").exists()

    def reject(name):
        raise HTTPException(403, "read only")

    monkeypatch.setattr(knowledge, "_writable_kb", reject)
    with pytest.raises(HTTPException) as error:
        await knowledge.cancel_indexing_run("kb", "someone-else")
    assert error.value.status_code == 403


_READ_TEXT = Path.read_text


def _lock_reads(monkeypatch, path: Path, failures: int) -> list[Path]:
    """Deny the next *failures* reads of *path* like a Windows sharing lock."""
    from deeptutor.services import file_io

    attempts: list[Path] = []

    def read_text(self, *args, **kwargs):
        if self == path:
            attempts.append(self)
            if len(attempts) <= failures:
                raise PermissionError(13, "Permission denied", str(self))
        return _READ_TEXT(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(file_io.time, "sleep", lambda _seconds: None)
    return attempts


def test_transient_journal_lock_is_retried_and_persistent_lock_fails(tmp_path, monkeypatch):
    journal = tmp_path / ".indexing-run.json"
    cancel = tmp_path / ".indexing-cancel.json"
    with IndexingRun(tmp_path, [], task_id="one") as run:
        attempts = _lock_reads(monkeypatch, journal, failures=2)
        run.check()
        assert len(attempts) == 3

        assert request_cancel(tmp_path, "one")
        attempts = _lock_reads(monkeypatch, cancel, failures=1)
        with pytest.raises(IndexingCancelled):
            run.check()
        assert len(attempts) == 2

        _lock_reads(monkeypatch, journal, failures=100)
        with pytest.raises(OSError, match="unreadable"):
            load_run(tmp_path)
        monkeypatch.undo()
        run.finish("cancelled")
    assert load_run(tmp_path)["state"] == "cancelled"


def test_journal_is_read_as_utf8_regardless_of_locale(tmp_path, monkeypatch):
    source = tmp_path / "raw" / "ÁLGEBRA 数学.pdf"
    source.parent.mkdir()
    source.write_bytes(b"textbook")

    def read_text(self, encoding=None, errors=None, **kwargs):
        # Simulate a Windows cp1252 locale, the default when no encoding is given.
        return _READ_TEXT(self, encoding=encoding or "cp1252", errors=errors, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    with IndexingRun(tmp_path, [str(source)], task_id="one") as run:
        run.check()
        run.document(source, "parsed")
        run.finish("failed")
    assert list(visible_run(tmp_path)["documents"]) == ["ÁLGEBRA 数学.pdf"]
