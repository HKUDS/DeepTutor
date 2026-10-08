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
