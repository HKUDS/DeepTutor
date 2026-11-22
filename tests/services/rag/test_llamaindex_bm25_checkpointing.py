"""BM25 sidecar lifecycle during a resumable (per-source) rebuild.

The sidecar is a retrieval accelerator rebuilt from the docstore on demand, so a
resumable rebuild must not rebuild it for every source checkpoint: that is a full
corpus pass per source (O(N^2) over the rebuild) and it dominated indexing time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _records(kb_dir: Path, names: list[str]) -> dict:
    from deeptutor.services.rag.pipelines.llamaindex import storage

    records = {}
    for name in names:
        path = kb_dir / "raw" / name
        records[name] = storage.EmbeddingSourceRecord(
            key=name,
            path=path,
            source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return records


@pytest.mark.asyncio
async def test_resumable_rebuild_writes_bm25_sidecar_once_after_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llama_index.core import Document, Settings
    from llama_index.core.embeddings import MockEmbedding

    from deeptutor.services.rag.pipelines.llamaindex import storage

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    names = ["first.txt", "second.txt"]
    documents = []
    for name in names:
        path = raw / name
        text = f"{name} explains Fourier transforms and sampling."
        path.write_text(text, encoding="utf-8")
        documents.append(Document(text=text, metadata={"file_path": str(path)}))

    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))

    calls: list[Path] = []

    def record_persist(index, storage_dir, *, top_k):
        calls.append(Path(storage_dir))
        return True

    monkeypatch.setattr(storage.retrievers, "persist_bm25_retriever", record_persist)

    storage_dir = kb_dir / "version-1"
    written = storage.create_resumable_index(
        documents,
        storage_dir,
        source_records=_records(kb_dir, names),
        signature=None,
        show_progress=False,
    )

    assert written == len(names)
    # Two per-source checkpoints ran, but the whole-corpus BM25 rebuild happens
    # exactly once, on the completed candidate, never on a `.checkpoint-*` dir.
    assert len(calls) == 1
    assert calls[0].parent == storage_dir
    assert calls[0].name.startswith(".bm25-sidecar-")
    assert not list(storage_dir.parent.glob(".*.checkpoint-*"))
    checkpoint = json.loads(
        (storage_dir / ".embedding-checkpoint.json").read_text(encoding="utf-8")
    )
    assert set(checkpoint["sources"]) == set(names)
    assert (storage_dir / "docstore.json").is_file()


@pytest.mark.asyncio
async def test_resumable_rebuild_persists_a_loadable_bm25_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("bm25s")
    pytest.importorskip("llama_index.retrievers.bm25")

    from llama_index.core import Document, Settings
    from llama_index.core.embeddings import MockEmbedding

    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    names = ["first.txt", "second.txt"]
    documents = []
    for name in names:
        path = raw / name
        text = f"{name} explains Fourier transforms and sampling."
        path.write_text(text, encoding="utf-8")
        documents.append(Document(text=text, metadata={"file_path": str(path)}))

    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))

    storage_dir = kb_dir / "version-1"
    storage.create_resumable_index(
        documents,
        storage_dir,
        source_records=_records(kb_dir, names),
        signature=None,
        show_progress=False,
    )

    # The sidecar only exists after the last checkpoint, and it is complete
    # enough for the query path to load it instead of rebuilding from docstore.
    assert (storage_dir / "bm25_retriever" / "corpus.jsonl").is_file()
    assert not list(storage_dir.parent.glob(".*.checkpoint-*"))
    index = storage.vector_store.load_index(storage_dir)
    retriever = retrievers.build_bm25_retriever(index, storage_dir, top_k=1)
    assert retriever is not None
    assert not list(storage_dir.parent.glob(".*.checkpoint-*"))


@pytest.mark.asyncio
async def test_intermediate_checkpoints_carry_no_bm25_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per-source checkpoints must stay cheap: no whole-corpus sidecar in them."""
    from llama_index.core import Document, Settings
    from llama_index.core.embeddings import MockEmbedding

    from deeptutor.services.rag.pipelines.llamaindex import storage

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    names = ["first.txt", "second.txt", "third.txt"]
    documents = []
    for name in names:
        path = raw / name
        text = f"{name} explains Fourier transforms and sampling."
        path.write_text(text, encoding="utf-8")
        documents.append(Document(text=text, metadata={"file_path": str(path)}))

    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))

    from deeptutor.services.rag.pipelines.llamaindex import retrievers

    sidecar_writes: list[Path] = []

    def record_sidecar(index, storage_dir, *, top_k):
        sidecar_writes.append(Path(storage_dir))
        return True

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", record_sidecar)

    storage_dir = kb_dir / "version-1"
    checkpoints: list[int] = []
    original_snapshot = storage._write_embedding_snapshot

    def snapshot_with_assertions(*args, **kwargs):
        candidate = kwargs.get("candidate") or args[1]
        result = original_snapshot(*args, **kwargs)
        assert not (Path(candidate) / "bm25_retriever").exists(), (
            "an intermediate checkpoint must not carry a whole-corpus BM25 sidecar"
        )
        checkpoints.append(len(checkpoints) + 1)
        return result

    monkeypatch.setattr(storage, "_write_embedding_snapshot", snapshot_with_assertions)

    storage.create_resumable_index(
        documents,
        storage_dir,
        source_records=_records(kb_dir, names),
        signature=None,
        show_progress=False,
    )

    # Checkpoint frequency is a policy choice (upstream PR #2837 batches them:
    # first source + batches), so the count is not necessarily one per source.
    # What must hold is that no checkpoint carries a whole-corpus sidecar.
    assert 1 <= len(checkpoints) <= len(names)
    assert len(sidecar_writes) == 1
    assert sidecar_writes[0].parent == storage_dir


@pytest.mark.asyncio
async def test_resume_with_every_source_done_backfills_the_missing_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate killed between the last checkpoint and the sidecar write resumes.

    Every source is already checkpointed, so the rebuild loop does nothing; the
    sidecar write must still happen once, and the candidate must then pass the
    publish-time verification. This is the regression seam for the new order of
    operations (checkpoints first, sidecar last).
    """
    pytest.importorskip("bm25s")
    pytest.importorskip("llama_index.retrievers.bm25")
    import shutil

    from llama_index.core import Document, Settings
    from llama_index.core.embeddings import MockEmbedding

    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    names = ["first.txt", "second.txt"]
    documents = []
    for name in names:
        path = raw / name
        text = f"{name} explains Fourier transforms and sampling."
        path.write_text(text, encoding="utf-8")
        documents.append(Document(text=text, metadata={"file_path": str(path)}))

    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=4))
    source_records = _records(kb_dir, names)
    storage_dir = kb_dir / "version-1"

    storage.create_resumable_index(
        documents,
        storage_dir,
        source_records=source_records,
        signature=None,
        show_progress=False,
    )
    assert (storage_dir / "bm25_retriever").is_dir()

    # Simulate the crash window: all sources checkpointed, sidecar absent.
    shutil.rmtree(storage_dir / "bm25_retriever")
    assert not (storage_dir / "bm25_retriever").exists()

    writes: list[Path] = []
    original_persist = retrievers.persist_bm25_retriever

    def counting_persist(index, target, *, top_k):
        writes.append(Path(target))
        return original_persist(index, target, top_k=top_k)

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", counting_persist)

    storage.create_resumable_index(
        documents,
        storage_dir,
        source_records=source_records,
        signature=None,
        show_progress=False,
    )

    assert len(writes) == 1
    assert writes[0].parent == storage_dir
    assert (storage_dir / "bm25_retriever" / "corpus.jsonl").is_file()
    assert not list(storage_dir.glob(".bm25-sidecar-*"))
    assert not list(storage_dir.glob(".*.previous-*"))
    storage.verify_persisted_index(storage_dir)


def test_successful_sidecar_write_replaces_the_old_one_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    old = storage_dir / "bm25_retriever"
    old.mkdir()
    (old / "corpus.jsonl").write_text("stale", encoding="utf-8")

    def fake_persist(index, target, *, top_k):
        staged = Path(target) / "bm25_retriever"
        staged.mkdir(parents=True)
        (staged / "corpus.jsonl").write_text("fresh", encoding="utf-8")
        return True

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", fake_persist)

    assert storage._persist_bm25_sidecar(object(), storage_dir) is True
    assert (storage_dir / "bm25_retriever" / "corpus.jsonl").read_text(encoding="utf-8") == "fresh"
    assert not list(storage_dir.glob(".bm25-sidecar-*"))
    assert not list(storage_dir.glob(".*.previous-*"))


def test_failed_sidecar_write_drops_the_old_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    old = storage_dir / "bm25_retriever"
    old.mkdir()
    (old / "corpus.jsonl").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", lambda *args, **kwargs: False)

    assert storage._persist_bm25_sidecar(object(), storage_dir) is False
    # A failed write must not leave a stale sidecar behind: the query path
    # rebuilds from the docstore instead of silently using an older corpus.
    assert not (storage_dir / "bm25_retriever").exists()
    assert not list(storage_dir.glob(".bm25-sidecar-*"))


def _fake_persist_writer(payload: str = "fresh"):
    def fake_persist(index, target, *, top_k):
        staged = Path(target) / "bm25_retriever"
        staged.mkdir(parents=True)
        (staged / "corpus.jsonl").write_text(payload, encoding="utf-8")
        return True

    return fake_persist


def test_sidecar_build_failure_does_not_fail_the_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing/broken accelerator must degrade to vector-only, not fail indexing."""
    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    old = storage_dir / "bm25_retriever"
    old.mkdir()
    (old / "corpus.jsonl").write_text("stale", encoding="utf-8")

    def exploding_persist(index, target, *, top_k):
        raise OSError("WinError 206: filename or extension is too long")

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", exploding_persist)
    monkeypatch.setattr(retrievers, "bm25_available", lambda: True)

    assert storage._persist_bm25_sidecar(object(), storage_dir) is False
    assert not old.exists()
    assert not list(storage_dir.glob(".bm25-sidecar-*"))


def test_sidecar_debris_from_a_crashed_publish_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    stale_staging = storage_dir / ".bm25-sidecar-crashed"
    (stale_staging / "bm25_retriever").mkdir(parents=True)
    stale_backup = storage_dir / ".bm25_retriever.previous-crashed"
    stale_backup.mkdir()

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", _fake_persist_writer("fresh"))

    assert storage._persist_bm25_sidecar(object(), storage_dir) is True
    assert (storage_dir / "bm25_retriever" / "corpus.jsonl").read_text(encoding="utf-8") == "fresh"
    assert not list(storage_dir.glob(".bm25-sidecar-*"))
    assert not list(storage_dir.glob(".bm25_retriever.previous-*"))


def test_unmovable_stale_sidecar_is_dropped_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the old sidecar cannot be moved aside, publish the new one anyway."""
    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    old = storage_dir / "bm25_retriever"
    old.mkdir()
    (old / "corpus.jsonl").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", _fake_persist_writer("fresh"))

    original_replace = Path.replace

    def locked_replace(self, target_path, *args, **kwargs):
        target_str = str(target_path)
        if self.name == "bm25_retriever" and ".previous-" in target_str:
            raise OSError("file is locked")
        return original_replace(self, target_path, *args, **kwargs)

    monkeypatch.setattr(Path, "replace", locked_replace)

    assert storage._persist_bm25_sidecar(object(), storage_dir) is True
    assert (storage_dir / "bm25_retriever" / "corpus.jsonl").read_text(encoding="utf-8") == "fresh"


def test_staged_sidecar_is_fsynced_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    monkeypatch.setattr(retrievers, "persist_bm25_retriever", _fake_persist_writer("fresh"))

    synced: list[Path] = []
    monkeypatch.setattr(storage, "_sync_checkpoint_tree", lambda root: synced.append(Path(root)))

    assert storage._persist_bm25_sidecar(object(), storage_dir) is True
    assert len(synced) == 1
    assert synced[0].name == "bm25_retriever"


def test_sidecar_setup_failure_is_non_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A staging-directory OSError (e.g. Windows MAX_PATH) must not fail the rebuild."""
    import tempfile as tempfile_module

    from deeptutor.services.rag.pipelines.llamaindex import storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    old = storage_dir / "bm25_retriever"
    old.mkdir()
    (old / "corpus.jsonl").write_text("stale", encoding="utf-8")

    def exploding_mkdtemp(*args, **kwargs):
        raise OSError("WinError 206: filename or extension is too long")

    monkeypatch.setattr(tempfile_module, "mkdtemp", exploding_mkdtemp)

    assert storage._persist_bm25_sidecar(object(), storage_dir) is False
    assert not old.exists()


def test_failed_publish_drops_the_old_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed swap must never restore a stale sidecar (it would leak missed sources)."""
    from deeptutor.services.rag.pipelines.llamaindex import retrievers, storage

    storage_dir = tmp_path / "version-1"
    storage_dir.mkdir()
    old = storage_dir / "bm25_retriever"
    old.mkdir()
    (old / "corpus.jsonl").write_text("stale", encoding="utf-8")

    monkeypatch.setattr(retrievers, "persist_bm25_retriever", _fake_persist_writer("fresh"))

    original_replace = Path.replace

    def fail_staged_swap(self, target_path, *args, **kwargs):
        if self.parent.name.startswith(".bm25-sidecar-"):
            raise OSError("sharing violation")
        return original_replace(self, target_path, *args, **kwargs)

    monkeypatch.setattr(Path, "replace", fail_staged_swap)

    assert storage._persist_bm25_sidecar(object(), storage_dir) is False
    assert not (storage_dir / "bm25_retriever").exists()
    assert not list(storage_dir.glob(".bm25_retriever.previous-*"))
