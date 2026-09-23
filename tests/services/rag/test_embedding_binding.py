from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from deeptutor.services.embedding.config import get_embedding_config
from deeptutor.services.rag import embedding_binding as binding
from deeptutor.services.rag.embedding_signature import signature_from_config
from deeptutor.services.rag.service import RAGService


@pytest.fixture
def catalog(monkeypatch):
    value = {
        "version": 1,
        "services": {
            "embedding": {
                "active_profile_id": "p",
                "active_model_id": "a",
                "profiles": [
                    {
                        "id": "p",
                        "name": "Provider",
                        "binding": "openai",
                        "api_key": "original-key",
                        "base_url": "https://example.test/v1/embeddings",
                        "models": [
                            {"id": "a", "model": "embed-a", "dimension": "2"},
                            {"id": "b", "model": "embed-b", "dimension": "3"},
                        ],
                    }
                ],
            }
        },
    }
    from deeptutor.services import config
    from deeptutor.services.config import provider_runtime

    monkeypatch.setattr(
        config, "get_model_catalog_service", lambda: SimpleNamespace(load=lambda: deepcopy(value))
    )
    monkeypatch.setattr(binding, "load_catalog", lambda: deepcopy(value))
    monkeypatch.setattr(
        provider_runtime,
        "_load_catalog",
        lambda supplied: supplied if supplied is not None else deepcopy(value),
    )
    return value


def selection(model="a"):
    return {"profile_id": "p", "model_id": model}


def write_entry(root, name="kb", model="a", **overrides):
    config = get_embedding_config(selection(model))
    entry = {
        "path": name,
        "rag_provider": "llamaindex",
        "status": "ready",
        **binding.binding_fields(selection(model), config),
        **overrides,
    }
    path = root / "kb_config.json"
    payload = json.loads(path.read_text()) if path.exists() else {"knowledge_bases": {}}
    payload["knowledge_bases"][name] = entry
    path.write_text(json.dumps(payload))
    (root / name / "raw").mkdir(parents=True, exist_ok=True)
    return entry


def read_entry(root, name="kb"):
    return json.loads((root / "kb_config.json").read_text())["knowledge_bases"][name]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "metadata", "binding"])
@pytest.mark.parametrize("target_model", ["a", "b"])
async def test_lightrag_rebuild_persists_binding_after_meta_under_write_ownership(
    catalog, tmp_path, monkeypatch, failure, target_model
):
    from deeptutor.services.rag.pipelines.lightrag import engine, storage
    from deeptutor.services.rag.pipelines.lightrag import pipeline as pipeline_module
    from deeptutor.services.rag.pipelines.lightrag.indexing_policy import IndexingPolicyError
    from deeptutor.services.rag.pipelines.lightrag.write_lock import write_ownership

    monkeypatch.setattr(engine, "installed_version", lambda: "synthetic-test-version")
    write_entry(tmp_path, rag_provider="lightrag")
    old = tmp_path / "kb" / "version-1"
    old.mkdir()
    (old / "kv_store_doc_status.json").write_text('{"old":{"status":"processed"}}')
    storage.write_meta(old, embedding_config=get_embedding_config(selection("a")))
    old_meta = (old / "meta.json").read_bytes()
    service = RAGService(kb_base_dir=str(tmp_path))
    pipeline = pipeline_module.LightRagPipeline(str(tmp_path))
    service._pipelines["lightrag"] = pipeline
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)
    monkeypatch.setattr(
        pipeline_module,
        "freeze_default_snapshot",
        lambda: SimpleNamespace(embedding_config=get_embedding_config()),
    )

    async def finish_index(root, *_args, **_kwargs):
        (root / "kv_store_doc_status.json").write_text(
            json.dumps({"doc": {"status": "processed", "chunks_list": ["chunk"]}})
        )
        return pipeline_module.BatchOutcome(
            requested=1,
            accepted=1,
            processed=("doc",),
            indexing_policy={"policy": "legacy_unpinned"},
        )

    monkeypatch.setattr(pipeline, "_run_indexing", finish_index)
    original_persist = binding.persist_binding
    calls = []

    def persist(*args):
        root = storage.latest_published_root(tmp_path / "kb")
        assert root is not None
        assert (
            json.loads((root / "meta.json").read_text())["embedding_model"]
            == f"embed-{target_model}"
        )
        with pytest.raises(IndexingPolicyError, match="Another indexing operation"):
            with write_ownership(tmp_path / "kb"):
                pytest.fail("Binding publication must retain indexing ownership")
        calls.append(True)
        if failure == "binding":
            raise OSError("binding publication failed")
        original_persist(*args)

    monkeypatch.setattr(binding, "persist_binding", persist)
    if failure == "metadata":

        def fail_meta(*args, **kwargs):
            raise OSError("publication failed")

        monkeypatch.setattr(storage, "write_meta", fail_meta)
    if failure:
        with pytest.raises(OSError, match="publication failed"):
            await service.initialize("kb", ["doc"], embedding_selection=selection(target_model))
        assert calls == ([True] if failure == "binding" else [])
        assert read_entry(tmp_path)["embedding_selection"] == selection("a")
        assert storage.latest_published_root(tmp_path / "kb") == old
        assert (
            storage.published_root_for_embedding(
                tmp_path / "kb", read_entry(tmp_path)["embedding_signature"]
            )
            == old
        )
        assert not (tmp_path / "kb" / "version-2" / "meta.json").exists()
        assert (old / "meta.json").read_bytes() == old_meta
    else:
        assert await service.initialize("kb", ["doc"], embedding_selection=selection(target_model))
        assert calls == [True]
        assert read_entry(tmp_path)["embedding_selection"] == selection(target_model)
        assert storage.latest_published_root(tmp_path / "kb").name == "version-2"
    with write_ownership(tmp_path / "kb"):
        pass  # Ownership is released on success and failure.


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["initialize", "add_documents"])
async def test_lightrag_rejects_binding_changed_between_resolution_and_write_lock(
    catalog, tmp_path, monkeypatch, operation
):
    from contextlib import contextmanager

    from deeptutor.services.rag.pipelines.lightrag import write_lock
    from deeptutor.services.rag.pipelines.lightrag.pipeline import LightRagPipeline

    write_entry(tmp_path, rag_provider="lightrag")
    service = RAGService(kb_base_dir=str(tmp_path))
    pipeline = LightRagPipeline(str(tmp_path))
    service._pipelines["lightrag"] = pipeline
    original_lock = write_lock.write_ownership

    @contextmanager
    def changed_before_lock(kb_dir):
        # Another worker completed its rebuild after decorator resolution.
        binding.persist_binding(
            tmp_path, "kb", selection("b"), get_embedding_config(selection("b"))
        )
        with original_lock(kb_dir):
            yield

    async def unexpected(*args, **kwargs):
        pytest.fail("Stale binding must be rejected before any index write")

    monkeypatch.setattr(write_lock, "write_ownership", changed_before_lock)
    monkeypatch.setattr(pipeline, "_initialize_owned", unexpected)
    monkeypatch.setattr(pipeline, "_add_documents_owned", unexpected)
    with pytest.raises(ValueError, match="binding changed before indexing started"):
        await getattr(service, operation)("kb", ["doc"])
    assert read_entry(tmp_path)["embedding_selection"] == selection("b")


def test_default_change_and_key_rotation_do_not_invalidate_binding(catalog, tmp_path):
    entry = write_entry(tmp_path)
    catalog["services"]["embedding"]["active_model_id"] = "b"
    catalog["services"]["embedding"]["profiles"][0]["api_key"] = "rotated-key"
    state, config = binding.binding_status(entry)
    assert state == "ready"
    assert config.model == "embed-a"
    assert config.api_key == "rotated-key"
    assert "original-key" not in json.dumps(entry)


@pytest.mark.parametrize("missing_identity", [False, True])
def test_lightrag_reconciliation_checks_bound_index_not_global_default(
    catalog, tmp_path, monkeypatch, missing_identity
):
    from deeptutor.knowledge.manager import _reconcile_embedding_flags
    from deeptutor.services.rag.pipelines.lightrag import engine, storage

    monkeypatch.setattr(engine, "installed_version", lambda: "synthetic-test-version")
    entry = write_entry(tmp_path, rag_provider="lightrag")
    root = tmp_path / "kb" / "version-1"
    root.mkdir()
    (root / "kv_store_doc_status.json").write_text('{"doc":{"status":"processed"}}')
    storage.write_meta(root, embedding_config=get_embedding_config(selection("a")))
    workspace = root / engine.workspace_for(root)
    workspace.mkdir()
    (workspace / "kv_store_doc_status.json").write_text('{"doc":{"status":"processed"}}')
    if missing_identity:
        meta = json.loads((root / "meta.json").read_text())
        meta.pop("embedding_signature")
        (root / "meta.json").write_text(json.dumps(meta))
    catalog["services"]["embedding"]["active_model_id"] = "b"
    _reconcile_embedding_flags({"kb": entry}, tmp_path)
    assert bool(entry.get("embedding_mismatch")) is missing_identity
    assert entry["embedding_selection"] == selection("a")


@pytest.mark.parametrize("drift", [False, True])
def test_lightrag_detail_and_reconciliation_keep_recorded_bound_version(
    catalog, tmp_path, monkeypatch, drift
):
    from deeptutor.knowledge.manager import KnowledgeBaseManager, _reconcile_embedding_flags
    from deeptutor.services.rag.pipelines.lightrag import engine, storage

    monkeypatch.setattr(engine, "installed_version", lambda: "synthetic-test-version")
    entry = write_entry(tmp_path, rag_provider="lightrag")
    for number, model in [(1, "a"), (2, "b")]:
        root = tmp_path / "kb" / f"version-{number}"
        root.mkdir()
        (root / "kv_store_doc_status.json").write_text('{"doc":{"status":"processed"}}')
        storage.write_meta(
            root,
            embedding_config=get_embedding_config(selection(model)),
            indexing_policy={"policy": "pinned", "fingerprint": model * 64},
        )
        workspace = root / engine.workspace_for(root)
        workspace.mkdir()
        (workspace / "kv_store_doc_status.json").write_text('{"doc":{"status":"processed"}}')
    _reconcile_embedding_flags({"kb": entry}, tmp_path)
    assert not entry.get("embedding_mismatch")
    assert entry["embedding_selection"] == selection("a")
    manager = KnowledgeBaseManager(str(tmp_path))
    if drift:
        catalog["services"]["embedding"]["profiles"][0]["models"][0]["model"] = "changed-a"
    _reconcile_embedding_flags(manager.config["knowledge_bases"], tmp_path)
    metadata = manager.get_info("kb")["metadata"]
    assert metadata["indexed_embedding_model"] == "embed-a"
    assert metadata["current_embedding_model"] == ("changed-a" if drift else "embed-a")
    assert metadata["indexing_policy"]["fingerprint"] == "a" * 64
    assert metadata["indexed_version"] == "version-1"


def test_lightrag_append_uses_policy_of_actual_bound_index(catalog, tmp_path, monkeypatch):
    from deeptutor.services.embedding.config import embedding_config_scope
    from deeptutor.services.rag.pipelines.lightrag import engine, indexing_policy, storage
    from deeptutor.services.rag.pipelines.lightrag.pipeline import BatchOutcome, LightRagPipeline

    monkeypatch.setattr(engine, "installed_version", lambda: "synthetic-test-version")
    write_entry(tmp_path, rag_provider="lightrag")
    for number, model in [(1, "a"), (2, "b")]:
        root = tmp_path / "kb" / f"version-{number}"
        root.mkdir()
        workspace = root / engine.workspace_for(root)
        workspace.mkdir()
        (workspace / "kv_store_doc_status.json").write_text('{"doc":{"status":"processed"}}')
        storage.write_meta(
            root,
            embedding_config=get_embedding_config(selection(model)),
            indexing_policy={"policy": "pinned", "label": model},
        )
    newer = tmp_path / "kb" / "version-2" / "meta.json"
    before = newer.read_bytes()
    monkeypatch.setattr(
        indexing_policy,
        "snapshot_from_persisted",
        lambda policy: SimpleNamespace(
            vision_available=False,
            embedding_config=get_embedding_config(selection("a")),
            persisted_policy=lambda: policy,
        ),
    )
    pipeline = LightRagPipeline(str(tmp_path))
    monkeypatch.setattr(pipeline, "_ensure_available", lambda: None)

    async def index(root, files, progress, snapshot, *, embedding_config):
        assert root.name == "version-1"
        assert snapshot.persisted_policy()["label"] == "a"
        assert embedding_config.model == "embed-a"
        return BatchOutcome(
            requested=1,
            accepted=1,
            processed=("new.md",),
            indexing_policy=snapshot.persisted_policy(),
        )

    monkeypatch.setattr(pipeline, "_run_indexing", index)
    with embedding_config_scope(get_embedding_config(selection("a"))):
        assert asyncio.run(pipeline.add_documents("kb", ["new.md"]))
    assert newer.read_bytes() == before
    assert (
        json.loads((tmp_path / "kb" / "version-1" / "meta.json").read_text())["indexing_policy"][
            "label"
        ]
        == "a"
    )


def test_deleted_or_edited_model_does_not_fall_back(catalog, tmp_path):
    entry = write_entry(tmp_path)
    catalog["services"]["embedding"]["profiles"][0]["models"][0]["model"] = "other-space"
    assert binding.binding_status(entry)[0] == "changed"
    catalog["services"]["embedding"]["profiles"][0]["models"].pop(0)
    assert binding.binding_status(entry)[0] == "missing"
    with pytest.raises(ValueError, match="deleted"):
        get_embedding_config(selection())


def test_legacy_binding_follows_index_not_new_default(catalog, tmp_path):
    entry = write_entry(tmp_path)
    entry.pop("embedding_selection")
    entry["embedding_mismatch"] = True
    entry["needs_reindex"] = True
    catalog["services"]["embedding"]["active_model_id"] = "b"
    entries = {"kb": entry}
    binding.reconcile_bindings(entries, tmp_path)
    assert entry["embedding_selection"] == selection()
    assert entry["embedding_status"] == "ready"
    assert not entry["needs_reindex"]


def test_legacy_placeholder_signature_can_migrate_without_reindex(catalog, tmp_path):
    entry = write_entry(tmp_path)
    entry.pop("embedding_selection")
    entry["embedding_signature"] = "legacy"
    catalog["services"]["embedding"]["active_model_id"] = "b"
    assert binding.migrate_binding(entry, tmp_path / "kb")
    assert entry["embedding_selection"] == selection("a")


@pytest.mark.parametrize("provider", ["graphrag", "lightrag"])
def test_graph_reads_keep_bound_version_and_ignore_unpublished_candidates(
    catalog, tmp_path, provider
):
    from deeptutor.services.embedding.config import embedding_config_scope

    config = get_embedding_config(selection("a"))

    def version(number, model, **extra):
        root = tmp_path / f"version-{number}"
        root.mkdir()
        meta = {
            "provider": provider,
            "signature": provider,
            "embedding_signature": signature_from_config(
                get_embedding_config(selection(model))
            ).hash(),
            **extra,
        }
        if provider == "graphrag":
            (root / "output").mkdir()
            (root / "output" / "entities.parquet").touch()
        else:
            meta = {
                "lightrag_adapter_schema": 2,
                "parser_bridge_schema": 1,
                "state": "published",
                **meta,
            }
            (root / "kv_store_doc_status.json").write_text(
                json.dumps({"doc": {"status": "processed"}})
            )
        (root / "meta.json").write_text(json.dumps(meta))
        return root

    old = version(1, "a")
    newer = version(2, "b")
    with embedding_config_scope(config):
        assert binding.bound_graph_storage_root(tmp_path, provider, newer) == old
        if provider == "lightrag":
            version(3, "a", state="building")
            assert binding.bound_graph_storage_root(tmp_path, provider, newer) == old
        (old / "meta.json").write_text(json.dumps({"provider": provider, "signature": provider}))
        assert binding.bound_graph_storage_root(tmp_path, provider, old) == old
        with pytest.raises(ValueError, match="No index version matches"):
            binding.bound_graph_storage_root(tmp_path, provider, newer)


@pytest.mark.asyncio
async def test_service_isolates_concurrent_kbs_and_preserves_failed_rebuild(catalog, tmp_path):
    write_entry(tmp_path, "a", "a")
    write_entry(tmp_path, "b", "b")
    reached = asyncio.Event()
    seen = []

    class Pipeline:
        async def search(self, query, kb_name, **kwargs):
            seen.append(get_embedding_config().model)
            if len(seen) == 2:
                reached.set()
            await reached.wait()
            return {"answer": get_embedding_config().model}

        async def initialize(self, **kwargs):
            assert get_embedding_config().model == "embed-b"
            raise RuntimeError("provider failed")

    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = Pipeline()
    results = await asyncio.gather(service.search("query", "a"), service.search("query", "b"))
    assert [row["answer"] for row in results] == ["embed-a", "embed-b"]
    with pytest.raises(RuntimeError, match="provider failed"):
        await service.initialize("a", ["source"], embedding_selection=selection("b"))
    assert read_entry(tmp_path, "a")["embedding_selection"] == selection("a")
    assert get_embedding_config().model == "embed-a"


@pytest.mark.asyncio
async def test_missing_binding_returns_actionable_search_error(catalog, tmp_path):
    write_entry(tmp_path)
    catalog["services"]["embedding"]["profiles"][0]["models"].pop(0)
    result = await RAGService(kb_base_dir=str(tmp_path)).search("question", "kb")
    assert result["error_type"] == "embedding_binding_unavailable"
    assert "deleted" in result["answer"]


@pytest.mark.asyncio
async def test_unidentified_legacy_graph_index_keeps_its_existing_runtime(catalog, tmp_path):
    from deeptutor.services.embedding.config import scoped_embedding_config

    write_entry(
        tmp_path,
        rag_provider="graphrag",
        embedding_selection=None,
        embedding_signature=None,
        embedding_model=None,
        embedding_dim=None,
    )
    version = tmp_path / "kb" / "version-1"
    version.mkdir()
    (version / "meta.json").write_text(
        json.dumps({"provider": "graphrag", "signature": "graphrag"})
    )
    (version / "settings.yaml").write_text("# legacy model configuration")

    class Pipeline:
        async def search(self, **kwargs):
            assert scoped_embedding_config() is None
            return {"answer": "legacy result"}

        async def add_documents(self, **kwargs):
            assert scoped_embedding_config() is None
            return True

    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["graphrag"] = Pipeline()
    assert (await service.search("question", "kb"))["answer"] == "legacy result"
    assert await service.add_documents("kb", ["source"])
    assert not read_entry(tmp_path).get("embedding_selection")


@pytest.mark.asyncio
async def test_real_llamaindex_create_search_append_and_rebuild_use_bound_model(
    catalog, tmp_path, monkeypatch
):
    from llama_index.core import Document

    from deeptutor.services.embedding import client as clients
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline
    from deeptutor.services.rag.pipelines.llamaindex.storage import clear_index_cache

    calls = []

    class Client:
        def __init__(self, config):
            self.config = config

        async def embed(self, texts, **kwargs):
            calls.append((self.config.model, self.config.api_key, kwargs.get("input_type")))
            if callback := kwargs.get("progress_callback"):
                callback(1, 1)
            return [[1.0] + [0.0] * (self.config.dim - 1) for _ in texts]

    class Loader:
        async def load(self, files, **kwargs):
            await asyncio.sleep(0)
            return [Document(text=f"Useful study material from {path}") for path in files]

    monkeypatch.setattr(clients, "EmbeddingClient", Client)
    clients.reset_embedding_client()
    clear_index_cache()

    write_entry(tmp_path)
    service = RAGService(kb_base_dir=str(tmp_path))
    service._pipelines["llamaindex"] = LlamaIndexPipeline(str(tmp_path), document_loader=Loader())
    assert await service.initialize("kb", ["first"])
    original = read_entry(tmp_path)["embedding_signature"]
    catalog["services"]["embedding"]["active_model_id"] = "b"
    catalog["services"]["embedding"]["profiles"][0]["api_key"] = "new-key"
    calls.clear()
    result = await service.search("study", "kb")
    assert result.get("error_type") is None
    assert result["sources"]
    assert await service.add_documents("kb", ["second"])
    assert calls and all(model == "embed-a" and key == "new-key" for model, key, _ in calls)
    assert read_entry(tmp_path)["embedding_signature"] == original
    assert await service.initialize("kb", ["first", "second"], embedding_selection=selection("b"))
    assert read_entry(tmp_path)["embedding_selection"] == selection("b")
    assert len(list((tmp_path / "kb").glob("version-*"))) == 2
    assert (await service.search("study", "kb"))["sources"]
    clients.reset_embedding_client()
    clear_index_cache()


@pytest.mark.asyncio
async def test_reindex_admits_explicit_model_without_changing_old_binding(
    catalog, tmp_path, monkeypatch
):
    from fastapi import BackgroundTasks

    from deeptutor.api.routers import knowledge
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    write_entry(tmp_path)
    (tmp_path / "kb" / "raw" / "note.txt").write_text("study material")
    monkeypatch.setattr(knowledge, "kb_manager", KnowledgeBaseManager(str(tmp_path)))
    tasks = BackgroundTasks()
    result = await knowledge.reindex_knowledge_base(
        "kb", tasks, indexing_llm="", embedding_model=json.dumps(selection("b"))
    )
    assert not result["noop"]
    assert tasks.tasks[0].kwargs["embedding_selection"] == selection("b")
    assert tasks.tasks[0].kwargs["embedding_config"].model == "embed-b"
    assert read_entry(tmp_path)["embedding_selection"] == selection("a")
    assert catalog["services"]["embedding"]["active_model_id"] == "a"


@pytest.mark.asyncio
async def test_empty_kb_can_replace_deleted_model_without_starting_indexing(
    catalog, tmp_path, monkeypatch
):
    from fastapi import BackgroundTasks

    from deeptutor.api.routers import knowledge
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    write_entry(tmp_path)
    catalog["services"]["embedding"]["profiles"][0]["models"].pop(0)
    catalog["services"]["embedding"]["active_model_id"] = "b"
    monkeypatch.setattr(knowledge, "kb_manager", KnowledgeBaseManager(str(tmp_path)))
    tasks = BackgroundTasks()
    result = await knowledge.reindex_knowledge_base(
        "kb", tasks, indexing_llm="", embedding_model=json.dumps(selection("b"))
    )
    assert result["noop"] and not tasks.tasks
    assert binding.binding_status(read_entry(tmp_path))[0] == "ready"
    assert read_entry(tmp_path)["embedding_selection"] == selection("b")


@pytest.mark.asyncio
async def test_old_full_config_updates_preserve_binding(catalog, tmp_path, monkeypatch):
    from fastapi import HTTPException

    from deeptutor.api.routers import knowledge
    from deeptutor.services import config
    from deeptutor.services.config.knowledge_base_config import KnowledgeBaseConfigService

    write_entry(tmp_path)
    service = KnowledgeBaseConfigService(tmp_path / "kb_config.json")
    monkeypatch.setattr(config, "get_kb_config_service", lambda: service)
    payload = {**service.get_kb_config("kb"), "search_mode": "local"}
    assert (await knowledge.update_kb_config("kb", payload))["status"] == "success"
    assert read_entry(tmp_path)["embedding_selection"] == selection("a")
    with pytest.raises(HTTPException) as exc:
        await knowledge.update_kb_config("kb", {**payload, "embedding_selection": selection("b")})
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_usage_includes_legacy_bindings_without_mutating_them(catalog, tmp_path, monkeypatch):
    from deeptutor.api.routers import knowledge
    from deeptutor.knowledge.manager import KnowledgeBaseManager
    from deeptutor.multi_user import paths
    from deeptutor.services import workspace
    from deeptutor.services.path_service import PathService

    write_entry(tmp_path)
    manager = KnowledgeBaseManager(str(tmp_path))
    monkeypatch.setattr(knowledge, "kb_manager", manager)
    monkeypatch.setattr(paths, "get_account_path_service", lambda: PathService(tmp_path))
    monkeypatch.setattr(
        workspace,
        "get_content_workspace_service",
        lambda: SimpleNamespace(
            list_workspaces=lambda: [
                {"workspace_id": "system", "kind": "system", "status": "ready"},
                {"workspace_id": "session", "kind": "session", "status": "ready"},
                {"workspace_id": "missing", "kind": "workspace", "status": "missing"},
            ]
        ),
    )
    payload = json.loads((tmp_path / "kb_config.json").read_text())
    payload["knowledge_bases"]["kb"].pop("embedding_selection")
    (tmp_path / "kb_config.json").write_text(json.dumps(payload))
    before = (tmp_path / "kb_config.json").read_bytes()
    result = await knowledge.get_embedding_usage()
    assert result["knowledge_bases"] == [{"name": "kb", "workspace_name": "", **selection()}]
    assert (tmp_path / "kb_config.json").read_bytes() == before


@pytest.mark.parametrize("explicit", [False, True])
def test_create_binds_selected_or_default_model_and_preserves_global_default(
    catalog, tmp_path, monkeypatch, explicit
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from deeptutor.api.routers import knowledge
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    monkeypatch.setattr(knowledge, "kb_manager", KnowledgeBaseManager(str(tmp_path)))
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    data = {"name": "new", "rag_provider": "llamaindex"}
    if explicit:
        data["embedding_model"] = json.dumps(selection("b"))
    with TestClient(app) as client:
        response = client.post("/api/knowledge-bases", data=data)
    assert response.status_code == 200, response.text
    assert read_entry(tmp_path, "new")["embedding_selection"] == selection("b" if explicit else "a")
    assert catalog["services"]["embedding"]["active_model_id"] == "a"
