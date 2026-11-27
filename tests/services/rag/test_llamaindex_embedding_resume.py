from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from deeptutor.services.rag.index_versioning import EmbeddingSignature


def _signature() -> EmbeddingSignature:
    return EmbeddingSignature(
        binding="test",
        model="embedding-resume",
        dimension=4,
        base_url="https://embedding.test",
        api_version="",
    )


def _records(kb_dir: Path, names: list[str]) -> dict[str, object]:
    from deeptutor.services.rag.pipelines.llamaindex import storage

    records = {}
    for name in names:
        source = kb_dir / "raw" / name
        records[name] = storage.EmbeddingSourceRecord(
            key=name,
            path=source,
            source_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        )
    return records


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted_swap", [False, True])
async def test_rebuild_resumes_completed_documents_after_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted_swap: bool
) -> None:
    from llama_index.core import Settings
    from llama_index.core.embeddings import MockEmbedding

    from deeptutor.knowledge.indexing_run import IndexingRun, load_run
    from deeptutor.services.rag.pipelines.llamaindex import storage
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    first, second = raw / "first.txt", raw / "second.txt"
    first.write_text("The first source explains Fourier transforms.", encoding="utf-8")
    second.write_text("The second source explains sampling.", encoding="utf-8")

    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))
    monkeypatch.setattr(
        storage.retrievers, "persist_bm25_retriever", lambda *_args, **_kwargs: False
    )
    original_snapshot = storage._write_embedding_snapshot
    snapshots = 0

    def fail_second_snapshot(*args, **kwargs):
        nonlocal snapshots
        snapshots += 1
        if snapshots == 2:
            raise OSError("simulated power loss boundary")
        return original_snapshot(*args, **kwargs)

    def make_pipeline() -> LlamaIndexPipeline:
        pipeline = LlamaIndexPipeline(str(tmp_path), signature_provider=_signature)
        monkeypatch.setattr(pipeline, "_configure_settings", lambda: None)

        async def verify_embedding() -> None:
            return None

        monkeypatch.setattr(
            pipeline,
            "_verify_embedding_connectivity",
            verify_embedding,
        )
        return pipeline

    monkeypatch.setattr(storage, "_write_embedding_snapshot", fail_second_snapshot)
    with pytest.raises(OSError, match="simulated power loss"):
        async with IndexingRun(kb_dir, [str(first), str(second)], provider="llamaindex"):
            await make_pipeline().initialize("kb", [str(first), str(second)])

    failed_run = load_run(kb_dir)
    candidate = Path(failed_run["candidate_storage"])
    checkpoint = json.loads((candidate / ".embedding-checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["sources"]["first.txt"]["completed"] is True
    assert checkpoint["sources"]["second.txt"]["completed"] is False
    assert failed_run["documents"]["first.txt"]["status"] == "completed"
    assert failed_run["documents"]["first.txt"]["embedding_reused"] is False

    if interrupted_swap:
        candidate.rename(candidate.with_name(f".{candidate.name}.previous-crash"))

    monkeypatch.setattr(storage, "_write_embedding_snapshot", original_snapshot)
    embedded_sources: list[str] = []
    original_documents_to_nodes = storage.ingestion.documents_to_nodes

    def track_documents(documents, **kwargs):
        embedded_sources.extend(Path(document.metadata["file_path"]).name for document in documents)
        return original_documents_to_nodes(documents, **kwargs)

    monkeypatch.setattr(storage.ingestion, "documents_to_nodes", track_documents)
    async with IndexingRun(kb_dir, [str(first), str(second)], provider="llamaindex") as run:
        assert await make_pipeline().initialize("kb", [str(first), str(second)])
        assert run.data["candidate_storage"] == str(candidate)
        run.finish("completed", version=candidate.name)

    resumed_run = load_run(kb_dir)
    assert resumed_run["state"] == "completed"
    assert resumed_run["documents"]["first.txt"]["embedding_reused"] is True
    assert resumed_run["documents"]["second.txt"]["embedding_reused"] is False
    assert embedded_sources == [second.name]
    storage.verify_persisted_index(candidate)
    # Shape validation alone does not detect silently replacing the old index
    # with one containing only the remaining sources.
    restored = storage.vector_store.load_index(candidate)
    retained = {
        Path(node.metadata["file_path"]).name
        for node in restored.docstore.docs.values()
        if node.metadata.get("file_path")
    }
    assert retained == {first.name, second.name}
    retained_text = "\n".join(node.get_content() for node in restored.docstore.docs.values())
    assert "Fourier transforms" in retained_text
    assert "sampling" in retained_text
    assert checkpoint["signature"] == _signature().hash()


def test_resume_requires_exact_source_hashes_and_checkpoint(
    tmp_path: Path,
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import storage

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    source = raw / "book.txt"
    source.write_text("stable source", encoding="utf-8")
    candidate = kb_dir / "version-1"
    candidate.mkdir()
    (candidate / ".building.json").write_text('{"state":"building"}', encoding="utf-8")

    records = _records(kb_dir, ["book.txt"])
    previous = {
        "state": "interrupted",
        "action": "rebuild",
        "provider": "llamaindex",
        "usable_version": None,
        "candidate_storage": str(candidate),
    }
    assert (
        storage.resolve_resumable_rebuild_dir(
            kb_dir, _signature(), previous_run=previous, source_records=records
        )
        is None
    )

    manifest = {
        "schema": 1,
        "provider": "llamaindex",
        "action": "rebuild",
        "signature": _signature().hash(),
        "sources": {
            key: {
                "path": str(record.path),
                "source_hash": record.source_hash,
                "completed": True,
            }
            for key, record in records.items()
        },
    }
    (candidate / ".embedding-checkpoint.json").write_text(json.dumps(manifest), encoding="utf-8")
    resolved = storage.resolve_resumable_rebuild_dir(
        kb_dir,
        _signature(),
        previous_run=previous,
        source_records=records,
    )
    assert resolved == candidate
    interrupted = {**previous, "state": "interrupted"}
    assert (
        storage.resolve_resumable_rebuild_dir(
            kb_dir,
            _signature(),
            previous_run=interrupted,
            source_records=records,
        )
        == candidate
    )
    (candidate / "meta.json").write_text('{"state":"published"}', encoding="utf-8")
    assert (
        storage.resolve_resumable_rebuild_dir(
            kb_dir,
            _signature(),
            previous_run=interrupted,
            source_records=records,
        )
        is None
    )
    (candidate / "meta.json").unlink()

    source.write_text("changed source", encoding="utf-8")
    changed_records = _records(kb_dir, ["book.txt"])
    assert (
        storage.resolve_resumable_rebuild_dir(
            kb_dir,
            _signature(),
            previous_run=previous,
            source_records=changed_records,
        )
        is None
    )


@pytest.mark.asyncio
async def test_empty_rebuild_preserves_existing_published_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.index_versioning import (
        list_kb_versions,
        resolve_storage_dir_for_read,
        write_version_meta,
    )
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    published = kb_dir / "version-1"
    published.mkdir()
    (published / "docstore.json").write_text("{}", encoding="utf-8")
    write_version_meta(tmp_path / "kb", _signature(), published)

    class Loader:
        async def load(self, *_args, **_kwargs):
            return []

    pipeline = LlamaIndexPipeline(
        str(tmp_path),
        signature_provider=_signature,
        document_loader=Loader(),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(pipeline, "_configure_settings", lambda: None)

    async def verify_embedding() -> None:
        return None

    monkeypatch.setattr(pipeline, "_verify_embedding_connectivity", verify_embedding)
    assert await pipeline.initialize("kb", [str(kb_dir / "raw" / "empty.txt")]) is False
    assert resolve_storage_dir_for_read(kb_dir, _signature()) == published
    assert (
        next(row for row in list_kb_versions(kb_dir) if row["version"] == "version-1")["ready"]
        is True
    )
