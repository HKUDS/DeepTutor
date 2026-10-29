"""Storage operations for the LlamaIndex RAG pipeline."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from llama_index.core import VectorStoreIndex

from deeptutor.services.embedding.validation import validate_embedding_batch
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.rag.index_versioning import (
    EmbeddingSignature,
    resolve_storage_dir_for_read,
    resolve_storage_dir_for_rebuild,
)

from . import ingestion, retrievers, vector_store
from .config import should_show_progress, vector_index_config_from_settings


@dataclass(frozen=True)
class AddStoragePlan:
    existing_storage: Path | None
    storage_dir: Path


@dataclass(frozen=True)
class EmbeddingSourceRecord:
    key: str
    path: Path
    source_hash: str


@dataclass(frozen=True)
class ResumeCandidate:
    storage_dir: Path
    completed_keys: frozenset[str]
    index: Any


def _storage_path_from_version_entry(entry: dict[str, Any]) -> Path | None:
    storage_path = entry.get("storage_path")
    if storage_path:
        return Path(str(storage_path))

    version_path = entry.get("version_path")
    if not version_path:
        return None

    path = Path(str(version_path))
    layout = str(entry.get("layout") or "")
    if layout == "nested_legacy":
        return path / "llamaindex_storage"
    return path


def cleanup_failed_version_dir(storage_dir: Path) -> bool:
    """Remove an empty flat version dir created by a failed indexing attempt."""
    if not storage_dir.is_dir() or not storage_dir.name.startswith("version-"):
        return False
    storage_empty = not any(child for child in storage_dir.iterdir() if child.name != "meta.json")
    meta_path = storage_dir / "meta.json"
    if storage_empty and not meta_path.exists():
        shutil.rmtree(storage_dir, ignore_errors=True)
        return True
    return False


def _read_embedding_checkpoint(storage_dir: Path) -> dict[str, Any] | None:
    path = storage_dir / ".embedding-checkpoint.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != 1
        or payload.get("provider") != "llamaindex"
        or payload.get("action") != "rebuild"
        or not isinstance(payload.get("sources"), dict)
    ):
        return None
    return payload


def _is_unpublished_building_dir(storage_dir: Path) -> bool:
    if storage_dir.name.startswith(".") or not storage_dir.name.startswith("version-"):
        return False
    if (storage_dir / "meta.json").exists():
        return False
    try:
        building = json.loads((storage_dir / ".building.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(building, dict) and building.get("state") == "building"


def resolve_resumable_rebuild_dir(
    kb_dir: Path,
    signature: EmbeddingSignature | None,
    *,
    previous_run: dict[str, Any] | None,
    source_records: dict[str, EmbeddingSourceRecord],
) -> Path | None:
    """Return an interrupted candidate only when every source still matches."""
    if not previous_run or previous_run.get("provider") != "llamaindex":
        return None
    if previous_run.get("action") != "rebuild" or previous_run.get("state") not in {
        "interrupted",
        "failed",
        "cancelled",
    }:
        return None
    if previous_run.get("usable_version"):
        return None

    candidate_value = previous_run.get("candidate_storage")
    if not isinstance(candidate_value, str) or not candidate_value:
        return None
    candidate = Path(candidate_value)
    try:
        candidate.resolve().relative_to(kb_dir.resolve())
    except (OSError, ValueError):
        return None
    if (
        candidate.parent.resolve() != kb_dir.resolve()
        or not candidate.name.startswith("version-")
        or (candidate / "meta.json").exists()
    ):
        return None
    # A crash can occur after moving the candidate aside but before publishing
    # its replacement. Restore that checkpoint before testing its build marker.
    _recover_candidate_swap(candidate)
    if not _is_unpublished_building_dir(candidate):
        return None

    payload = _read_embedding_checkpoint(candidate)
    if payload is None:
        return None
    expected_signature = signature.hash() if signature is not None else None
    if payload.get("signature") != expected_signature:
        return None
    sources = payload["sources"]
    if set(sources) != set(source_records):
        return None
    for key, record in source_records.items():
        row = sources.get(key)
        if not isinstance(row, dict) or row.get("source_hash") != record.source_hash:
            return None
    return candidate


def resolve_add_storage_plan(kb_dir: Path, signature: EmbeddingSignature | None) -> AddStoragePlan:
    """Choose existing/new storage dirs for incremental adds."""
    existing = resolve_storage_dir_for_read(kb_dir, signature)
    return AddStoragePlan(
        existing_storage=existing,
        storage_dir=resolve_storage_dir_for_rebuild(kb_dir, signature, publication_guard=True),
    )


def _group_documents_by_source(
    documents: list[Any], source_records: dict[str, EmbeddingSourceRecord]
) -> dict[str, list[Any]] | None:
    path_to_key = {str(record.path.resolve()): key for key, record in source_records.items()}
    grouped: dict[str, list[Any]] = {}
    for document in documents:
        metadata = getattr(document, "metadata", None)
        source_value = metadata.get("file_path") if isinstance(metadata, dict) else None
        if not isinstance(source_value, str):
            return None
        try:
            source_path = str(Path(source_value).resolve())
        except OSError:
            return None
        key = path_to_key.get(source_path)
        if key is None:
            return None
        grouped.setdefault(key, []).append(document)
    return grouped


def _resume_candidate(
    storage_dir: Path, source_records: dict[str, EmbeddingSourceRecord]
) -> ResumeCandidate | None:
    if not _is_unpublished_building_dir(storage_dir):
        return None
    payload = _read_embedding_checkpoint(storage_dir)
    if payload is None:
        return None
    if set(payload["sources"]) != set(source_records):
        return None
    completed_keys: set[str] = set()
    for key, row in payload["sources"].items():
        if not isinstance(row, dict) or row.get("source_hash") != source_records[key].source_hash:
            return None
        if row.get("completed") is True:
            completed_keys.add(key)
    if not completed_keys:
        return None

    try:
        index = vector_store.load_index(storage_dir)
        _validate_persisted_embeddings(index, storage_dir)
    except Exception:
        return None
    indexed_paths = {
        str(Path(getattr(node, "metadata", {}).get("file_path", "")).resolve())
        for node in getattr(index, "docstore", {}).docs.values()
        if isinstance(getattr(node, "metadata", None), dict) and node.metadata.get("file_path")
    }
    for key in completed_keys:
        if str(source_records[key].path.resolve()) not in indexed_paths:
            return None
    return ResumeCandidate(
        storage_dir=storage_dir, completed_keys=frozenset(completed_keys), index=index
    )


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        # Directory replacement still publishes a complete tree; fsync is a
        # durability hint on filesystems that reject it for arbitrary files.
        pass


def _sync_checkpoint_tree(root: Path) -> None:
    try:
        for path in root.rglob("*"):
            if path.is_file():
                with path.open("rb") as handle:
                    os.fsync(handle.fileno())
        _fsync_directory(root)
    except OSError:
        # Directory replacement still publishes a complete tree; fsync is a
        # durability hint on filesystems that reject it for arbitrary files.
        pass


def _recover_candidate_swap(candidate: Path) -> None:
    backup_prefix = f".{candidate.name}.previous-"
    backups = sorted(
        (path for path in candidate.parent.glob(backup_prefix + "*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime_ns,
    )
    if candidate.exists():
        for backup in backups:
            shutil.rmtree(backup, ignore_errors=True)
        return
    if backups:
        backups[-1].replace(candidate)


def _swap_candidate_snapshot(candidate: Path, snapshot: Path) -> None:
    _recover_candidate_swap(candidate)
    backup = candidate.parent / f".{candidate.name}.previous-{uuid4().hex}"
    if candidate.exists():
        candidate.replace(backup)
        _fsync_directory(candidate.parent)
    try:
        snapshot.replace(candidate)
        _fsync_directory(candidate.parent)
    except BaseException:
        if not candidate.exists() and backup.exists():
            backup.replace(candidate)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        for stale in candidate.parent.glob(f".{candidate.name}.checkpoint-*"):
            shutil.rmtree(stale, ignore_errors=True)


def _write_embedding_snapshot(
    index: Any,
    candidate: Path,
    *,
    source_records: dict[str, EmbeddingSourceRecord],
    completed_keys: set[str],
    document_group: list[Any],
    signature: EmbeddingSignature | None,
) -> None:
    snapshot = Path(tempfile.mkdtemp(prefix=f".{candidate.name}.checkpoint-", dir=candidate.parent))
    try:
        index.storage_context.persist(persist_dir=str(snapshot))
        retrievers.persist_bm25_retriever(index, snapshot, top_k=20)
        atomic_write_json(snapshot / ".building.json", {"state": "building"})
        existing_catalog = candidate / "source_pages.json"
        if existing_catalog.is_file():
            shutil.copy2(existing_catalog, snapshot / existing_catalog.name)
        from deeptutor.services.rag.source_pages import persist_page_catalog

        persist_page_catalog(document_group, snapshot)
        atomic_write_json(
            snapshot / ".embedding-checkpoint.json",
            {
                "schema": 1,
                "provider": "llamaindex",
                "action": "rebuild",
                "signature": signature.hash() if signature is not None else None,
                "sources": {
                    key: {
                        "path": str(record.path),
                        "source_hash": record.source_hash,
                        "completed": key in completed_keys,
                    }
                    for key, record in source_records.items()
                },
            },
        )
        _sync_checkpoint_tree(snapshot)
        _swap_candidate_snapshot(candidate, snapshot)
    finally:
        if snapshot.exists():
            shutil.rmtree(snapshot, ignore_errors=True)


def create_resumable_index(
    documents: list[Any],
    storage_dir: Path,
    *,
    source_records: dict[str, EmbeddingSourceRecord],
    signature: EmbeddingSignature | None,
    show_progress: bool | None = None,
    checkpoint_callback: Callable[[Path, bool], None] | None = None,
) -> int:
    """Build a rebuild candidate one source at a time and snapshot each source."""
    if show_progress is None:
        show_progress = should_show_progress()
    if (storage_dir / "meta.json").exists():
        raise ValueError(f"Refusing to modify published index: {storage_dir}")
    grouped = _group_documents_by_source(documents, source_records)
    if grouped is None:
        return create_index(documents, storage_dir, show_progress=show_progress)

    _recover_candidate_swap(storage_dir)
    resume = _resume_candidate(storage_dir, source_records)
    index: Any = resume.index if resume else None
    completed_keys = set(resume.completed_keys if resume else set())
    if resume is not None and checkpoint_callback is not None:
        for key in sorted(completed_keys):
            checkpoint_callback(source_records[key].path, True)

    for key, document_group in grouped.items():
        if key in completed_keys:
            continue
        nodes = ingestion.documents_to_nodes(document_group, show_progress=show_progress)
        if index is None:
            storage_context = vector_store.storage_context_for_nodes(
                nodes, vector_index_config_from_settings()
            )
            index = VectorStoreIndex(
                nodes=nodes,
                storage_context=storage_context,
                show_progress=show_progress,
                embed_model=ingestion.current_embedding(),
            )
        else:
            index.insert_nodes(nodes)
        completed_keys.add(key)
        _write_embedding_snapshot(
            index,
            storage_dir,
            source_records=source_records,
            completed_keys=completed_keys,
            document_group=document_group,
            signature=signature,
        )
        if checkpoint_callback is not None:
            checkpoint_callback(source_records[key].path, False)
    return len(documents)


def create_index(
    documents: list[Any], storage_dir: Path, *, show_progress: bool | None = None
) -> int:
    index, count = ingestion.create_index_from_documents(
        documents, storage_dir, show_progress=show_progress
    )
    retrievers.persist_bm25_retriever(index, storage_dir, top_k=20)
    from deeptutor.services.rag.source_pages import persist_page_catalog

    persist_page_catalog(documents, storage_dir)
    return count


def insert_documents(existing_storage: Path, storage_dir: Path, documents: list[Any]) -> int:
    index = vector_store.load_index(existing_storage)
    _validate_persisted_embeddings(index, existing_storage)
    if hasattr(index, "insert_nodes"):
        count = ingestion.insert_documents_into_index(index, documents)
    else:
        # Some tests use a tiny fake index that only implements insert().
        for document in documents:
            index.insert(document)
        count = len(documents)
    index.storage_context.persist(persist_dir=str(storage_dir))
    retrievers.persist_bm25_retriever(index, storage_dir, top_k=20)
    from deeptutor.services.rag.source_pages import persist_page_catalog

    if existing_storage != storage_dir and (existing_storage / "source_pages.json").is_file():
        shutil.copy2(existing_storage / "source_pages.json", storage_dir / "source_pages.json")
    persist_page_catalog(documents, storage_dir)
    return count


def _persisted_vector_fault(exc: ValueError) -> str:
    """Return the concrete fault from a shared-validator error message."""
    _, _, tail = str(exc).partition("): ")
    fault = tail.split(". ", 1)[0].rstrip(".")
    return fault or "unusable embedding data"


def _validate_embedding_dict(embedding_dict: Any, *, label: str) -> None:
    if not isinstance(embedding_dict, dict) or not embedding_dict:
        return

    try:
        validate_embedding_batch(
            list(embedding_dict.values()),
            expected_count=len(embedding_dict),
            binding="llamaindex",
            model=f"persisted-index:{label}",
        )
    except ValueError as exc:
        # The shared validator blames the embedding provider; persisted
        # vectors are local data, so restate the fault neutrally.
        raise ValueError(
            f"stored vector in {label} failed validation: {_persisted_vector_fault(exc)}"
        ) from exc


def _iter_index_embedding_dicts(index: Any):
    """Yield embedding dictionaries exposed by loaded LlamaIndex vector stores."""
    seen: set[int] = set()

    def _yield_store(label: str, vector_store: Any):
        if vector_store is None:
            return
        store_id = id(vector_store)
        if store_id in seen:
            return
        seen.add(store_id)
        data = getattr(vector_store, "data", None)
        embedding_dict = getattr(data, "embedding_dict", None)
        if isinstance(embedding_dict, dict):
            yield label, embedding_dict

    yield from _yield_store("default", getattr(index, "vector_store", None))

    storage_context = getattr(index, "storage_context", None)
    vector_stores = getattr(storage_context, "vector_stores", None)
    if isinstance(vector_stores, dict):
        for namespace, vector_store in vector_stores.items():
            yield from _yield_store(str(namespace), vector_store)


def _embedding_dict_from_payload(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("embedding_dict"), dict):
        return payload["embedding_dict"]
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("embedding_dict"), dict):
        return data["embedding_dict"]
    return None


def _iter_file_embedding_dicts(storage_dir: Path):
    """Yield embedding dictionaries from persisted SimpleVectorStore JSON files.

    Binary FAISS indexes share the ``*vector_store.json`` filename but are not
    JSON, so they are skipped (their vectors are validated at index build time).
    """
    for path in sorted(storage_dir.glob("*vector_store.json")):
        try:
            with open(path, "rb") as probe:
                if probe.read(1)[:1] != b"{":
                    continue  # binary FAISS index, not a JSON vector store
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            continue
        embedding_dict = _embedding_dict_from_payload(payload)
        if isinstance(embedding_dict, dict):
            yield path.name, embedding_dict


def _validate_persisted_embeddings(index: Any, storage_dir: Path | None = None) -> None:
    """Fail early when a persisted vector store contains unusable vectors."""
    try:
        for label, embedding_dict in _iter_index_embedding_dicts(index):
            _validate_embedding_dict(embedding_dict, label=label)
        if storage_dir is not None:
            for label, embedding_dict in _iter_file_embedding_dicts(storage_dir):
                _validate_embedding_dict(embedding_dict, label=label)
    except ValueError as exc:
        raise ValueError(
            "RAG index contains invalid embedding vectors. Rebuild it with "
            "the knowledge base's 'Re-index' action (Index versions → "
            "Re-index) using the current embedding provider/model; "
            "re-uploading documents reuses the damaged store and cannot "
            f"repair it. Details: {exc}"
        ) from exc


def validate_storage_embeddings(storage_dir: Path) -> None:
    """Validate persisted vector-store files without running a retrieval."""
    _validate_persisted_embeddings(None, storage_dir)


# Loaded indexes are cached per storage dir so repeated queries never re-read or
# re-validate the (potentially large) persisted store. Entries are keyed by a
# freshness token derived from the store files' mtimes, so a re-index or
# incremental insert naturally invalidates the stale entry.
@dataclass
class _CachedIndex:
    index: Any
    last_used: float


_INDEX_CACHE: "OrderedDict[tuple[str, tuple[int, ...]], _CachedIndex]" = OrderedDict()
_INDEX_CACHE_LOCK = threading.Lock()
_INDEX_CACHE_MAXSIZE = 2
_INDEX_CACHE_IDLE_SECONDS = 10 * 60


def _prune_index_cache_locked(now: float) -> None:
    stale = [
        key
        for key, entry in _INDEX_CACHE.items()
        if now - entry.last_used >= _INDEX_CACHE_IDLE_SECONDS
    ]
    for key in stale:
        _INDEX_CACHE.pop(key, None)


def _freshness_token(storage_dir: Path) -> tuple[int, ...]:
    token: list[int] = []
    for name in ("docstore.json", vector_store.DEFAULT_VECTOR_STORE_FILENAME):
        try:
            token.append((storage_dir / name).stat().st_mtime_ns)
        except OSError:
            token.append(0)
    return tuple(token)


def _load_validated_index(storage_dir: Path) -> Any:
    """Load an index once and validate its embeddings (cache-miss path)."""
    index = vector_store.load_index(storage_dir)
    _validate_persisted_embeddings(index, storage_dir)
    return index


def _cached_index(storage_dir: Path) -> Any:
    key = (str(storage_dir.resolve()), _freshness_token(storage_dir))
    from deeptutor.services.embedding.config import scoped_embedding_config

    config = scoped_embedding_config()
    if config is not None:
        # Include credentials too: rotating a key must not reuse a client with
        # the old key. Only a digest is retained in the in-memory cache key.
        identity = hashlib.sha256(json.dumps(asdict(config), sort_keys=True).encode()).hexdigest()
        key = (*key, identity)
    now = time.monotonic()
    with _INDEX_CACHE_LOCK:
        _prune_index_cache_locked(now)
        entry = _INDEX_CACHE.get(key)
        if entry is not None:
            entry.last_used = now
            _INDEX_CACHE.move_to_end(key)
            return entry.index

    # Load outside the lock so a slow first load of one KB does not block other
    # KBs' queries. A concurrent duplicate load is harmless (idempotent).
    index = _load_validated_index(storage_dir)
    with _INDEX_CACHE_LOCK:
        # Drop any superseded entry for the same storage dir (older token).
        for stale in [existing for existing in _INDEX_CACHE if existing[0] == key[0]]:
            _INDEX_CACHE.pop(stale, None)
        _INDEX_CACHE[key] = _CachedIndex(index=index, last_used=time.monotonic())
        _INDEX_CACHE.move_to_end(key)
        while len(_INDEX_CACHE) > _INDEX_CACHE_MAXSIZE:
            _INDEX_CACHE.popitem(last=False)
    return index


def clear_index_cache() -> None:
    """Drop all cached indexes (used by tests and after destructive edits)."""
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE.clear()


def prune_index_cache() -> int:
    """Drop indexes idle past the single-user warm window."""
    with _INDEX_CACHE_LOCK:
        before = len(_INDEX_CACHE)
        _prune_index_cache_locked(time.monotonic())
        return before - len(_INDEX_CACHE)


def retrieve_nodes(
    storage_dir: Path, query: str, *, top_k: int = 5, document_keys: list[str] | None = None
) -> list[Any]:
    index = _cached_index(Path(storage_dir))
    if document_keys is None:
        return retrievers.retrieve_nodes(index, Path(storage_dir), query, top_k=top_k)
    return retrievers.retrieve_scoped_nodes(index, query, document_keys, top_k=top_k)


def delete_kb_dir(kb_dir: Path) -> bool:
    if kb_dir.exists():
        shutil.rmtree(kb_dir)
        return True
    return False


def verify_persisted_index(storage_dir: Path) -> None:
    index = vector_store.load_index(storage_dir)
    _validate_persisted_embeddings(index, storage_dir)
    if not index.docstore.docs:
        raise ValueError("Persisted index contains no retrievable nodes.")
    if not getattr(index, "index_struct", None):
        raise ValueError("Persisted index has no index structure.")
    vectors = [values for _, values in _iter_index_embedding_dicts(index) if values]
    if vectors:
        sample = next(iter(vectors[0].values()))
    else:
        client = getattr(index.vector_store, "client", None)
        if client is None or not getattr(client, "ntotal", 0):
            raise ValueError("Persisted index contains no embedding vectors.")
        sample = client.reconstruct(0).tolist()
    from llama_index.core.schema import QueryBundle

    if not index.as_retriever(similarity_top_k=1).retrieve(
        QueryBundle(query_str="", embedding=sample)
    ):
        raise ValueError("Persisted index failed a retrieval probe with a stored vector.")
