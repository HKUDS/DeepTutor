"""One-KB moves retain bytes, assignments, and saved qualified references."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import BackgroundTasks, UploadFile
import pytest

from deeptutor.multi_user.knowledge_access import (
    current_kb_manager,
    list_visible_knowledge_bases,
    resolve_kb,
)
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.kb_move import move_kb, preview_kb_move
from deeptutor.services.workspace.knowledge import qualified_kb_id


def _make_kb(name: str, marker: bytes) -> None:
    manager = current_kb_manager()
    folder = manager.base_dir / name
    (folder / "raw").mkdir(parents=True)
    (folder / "raw" / "source.pdf").write_bytes(marker)
    (folder / "version-1" / "index").parent.mkdir()
    (folder / "version-1" / "index").write_bytes(b"index:" + marker)
    manager.config = manager._load_config()
    manager.config.setdefault("knowledge_bases", {})[name] = {
        "path": name,
        "rag_provider": "llamaindex",
        "status": "ready",
        "description": "an atlas",
    }
    manager._save_config()


def test_move_one_kb_into_nonempty_workspace_preserves_bytes_and_references(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source-pixels")
        source_manager = current_kb_manager()
        source_manager.config = source_manager._load_config()
        source_manager.config["defaults"] = {"default_kb": "atlas"}
        source_manager._save_config()
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")
        destination_id = destination["workspace_id"]
        with workspace_context(destination_id):
            _make_kb("existing", b"keep-me")
        old_id = qualified_kb_id("atlas")
        new_id = qualified_kb_id("atlas", destination_id)
        consumer = service.create_workspace("Consumer", resources={"knowledge_bases": [old_id]})

        plan = preview_kb_move(old_id, destination_id)
        assert plan["blockers"] == []
        assert plan["files"] == 2
        assert [row["display_name"] for row in plan["assignments"]] == ["Consumer"]

        result = move_kb(old_id, destination_id)
        assert result["target_id"] == new_id
        with workspace_context(destination_id):
            manager = current_kb_manager()
            assert set(manager.list_knowledge_bases()) == {"atlas", "existing"}
            assert manager._load_config()["defaults"]["default_kb"] == "atlas"
            assert (
                manager.base_dir / "atlas" / "raw" / "source.pdf"
            ).read_bytes() == b"source-pixels"
            assert (
                manager.base_dir / "atlas" / "version-1" / "index"
            ).read_bytes() == b"index:source-pixels"
            assert (manager.base_dir / "existing" / "raw" / "source.pdf").read_bytes() == b"keep-me"
        assert "atlas" not in current_kb_manager().list_knowledge_bases()
        assert current_kb_manager()._load_config()["defaults"]["default_kb"] is None
        assert resolve_kb(old_id).id == new_id
        assert resolve_kb("user:kb:atlas").id == new_id
        assert resolve_kb("atlas").id == new_id
        moved_in_account = next(
            row for row in list_visible_knowledge_bases() if row["id"] == new_id
        )
        assert moved_in_account["provenance_label"] == "Research"
        with workspace_context(consumer["workspace_id"]):
            assert [row["id"] for row in list_visible_knowledge_bases()] == [new_id]
            assert resolve_kb(old_id).base_dir == resolve_kb(new_id).base_dir
        selected = next(
            row for row in service._catalog() if row["workspace_id"] == consumer["workspace_id"]
        )
        assert selected["resources"]["knowledge_bases"] == [new_id]


def test_move_reports_name_conflict_without_touching_either_catalog(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        with workspace_context(destination):
            _make_kb("atlas", b"destination")
        source_id = qualified_kb_id("atlas")
        assert "already contains" in preview_kb_move(source_id, destination)["blockers"][0]
        with pytest.raises(WorkspaceError, match="already contains"):
            move_kb(source_id, destination)
        assert (
            current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
        ).read_bytes() == b"source"
        with workspace_context(destination):
            assert (
                current_kb_manager().base_dir / "atlas" / "raw" / "source.pdf"
            ).read_bytes() == b"destination"


def test_failed_publish_restores_source_destination_and_assignment(as_user, monkeypatch):
    from deeptutor.services.workspace import kb_move

    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        destination = service.create_workspace("Research")["workspace_id"]
        old_id = qualified_kb_id("atlas")
        consumer = service.create_workspace("Consumer", resources={"knowledge_bases": [old_id]})
        source_config = current_kb_manager().config_file
        original = kb_move.atomic_write_json
        failed = False

        def fail_once(path, payload):
            nonlocal failed
            if path == source_config and not failed:
                failed = True
                raise OSError("injected write failure")
            original(path, payload)

        monkeypatch.setattr(kb_move, "atomic_write_json", fail_once)
        with pytest.raises(OSError, match="injected"):
            move_kb(old_id, destination)
        assert "atlas" in json.loads(source_config.read_text())["knowledge_bases"]
        assert (source_config.parent / "atlas" / "raw" / "source.pdf").read_bytes() == b"source"
        with workspace_context(destination):
            assert "atlas" not in current_kb_manager().list_knowledge_bases()
            assert not (current_kb_manager().base_dir / "atlas").exists()
        row = next(
            row for row in service._catalog() if row["workspace_id"] == consumer["workspace_id"]
        )
        assert row["resources"]["knowledge_bases"] == [old_id]
        assert resolve_kb(old_id).base_dir == source_config.parent


def test_legacy_account_selection_redirect_is_private_to_owner(as_user):
    from fastapi import HTTPException

    with as_user("alice"):
        _make_kb("atlas", b"source")
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        move_kb(qualified_kb_id("atlas"), destination)
        assert resolve_kb("user:kb:atlas").id == qualified_kb_id("atlas", destination)
    with as_user("bob"):
        with pytest.raises(HTTPException):
            resolve_kb("user:kb:atlas")


def test_saved_general_chat_legacy_selection_is_rewritten_on_move(as_user):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        service.general_binding()
        general_id = service._builtin_id("general")
        # Older chat catalogs stored role-prefixed IDs before the qualified
        # account/workspace resource scheme existed.
        with service._catalog_connection() as conn:
            record = conn.execute(
                "SELECT payload FROM workspaces WHERE id = ?", (general_id,)
            ).fetchone()
            row = json.loads(record[0])
            row["resources"] = {"knowledge_bases": ["user:kb:atlas"]}
            conn.execute(
                "UPDATE workspaces SET payload = ? WHERE id = ?",
                (json.dumps(row), general_id),
            )
        destination = service.create_workspace("Research")["workspace_id"]
        plan = preview_kb_move(qualified_kb_id("atlas"), destination)
        assert any(item["workspace_id"] == general_id for item in plan["assignments"])
        move_kb(qualified_kb_id("atlas"), destination)
        target_id = qualified_kb_id("atlas", destination)
        with workspace_context():
            assert resolve_kb("user:kb:atlas").id == target_id
            assert [item["id"] for item in list_visible_knowledge_bases()] == [target_id]
        general = next(row for row in service._catalog() if row["workspace_id"] == general_id)
        assert general["resources"]["knowledge_bases"] == [target_id]


def test_legacy_admin_selection_redirects_only_in_admin_account(as_user):
    with as_user("operator", role="admin"):
        _make_kb("atlas", b"source")
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        move_kb(qualified_kb_id("atlas"), destination)
        assert resolve_kb("admin:kb:atlas").id == qualified_kb_id("atlas", destination)


def test_owner_can_move_kb_excluded_from_general_chat_selection(as_user):
    with as_user("alice"):
        _make_kb("selected", b"other")
        _make_kb("atlas", b"source")
        service = ContentWorkspaceService()
        service.update_workspace(
            service._builtin_id("general"),
            resources={"knowledge_bases": [qualified_kb_id("selected")]},
        )
        destination = service.create_workspace("Research")["workspace_id"]
        assert preview_kb_move(qualified_kb_id("atlas"), destination)["blockers"] == []
        move_kb(qualified_kb_id("atlas"), destination)
        with workspace_context(destination):
            assert "atlas" in current_kb_manager().list_knowledge_bases()


def test_moved_away_name_cannot_be_registered_by_connected_providers(as_user, tmp_path):
    with as_user("alice"):
        _make_kb("atlas", b"source")
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        move_kb(qualified_kb_id("atlas"), destination)
        manager = current_kb_manager()
        attempts = [
            lambda: manager.register_connected_entry("atlas", {"type": "obsidian"}),
            lambda: manager.register_obsidian_vault("atlas", str(tmp_path)),
            lambda: manager.register_linked_kb("atlas", str(tmp_path), "llamaindex"),
            lambda: manager.register_lightrag_server_kb("atlas", "http://localhost:9621"),
            lambda: manager.register_marginnote4_kb("atlas"),
            lambda: manager.register_ima_kb("atlas", "", "", "remote-id"),
            lambda: manager.register_weknora_kb("atlas", "http://localhost", "key", "remote-id"),
            lambda: manager.register_subagent_connection("atlas", "local"),
        ]
        for attempt in attempts:
            with pytest.raises(ValueError, match="reserved by an earlier move"):
                attempt()
        assert "atlas" not in manager._load_config()["knowledge_bases"]

        second_destination = ContentWorkspaceService().create_workspace("Archive")["workspace_id"]
        move_kb(qualified_kb_id("atlas", destination), second_destination)
        with workspace_context(destination):
            with pytest.raises(ValueError, match="reserved by an earlier move"):
                current_kb_manager().register_connected_entry("atlas", {"type": "obsidian"})
        assert resolve_kb("user:kb:atlas").id == qualified_kb_id("atlas", second_destination)


def test_marginnote_move_is_blocked_before_synced_database_is_lost(as_user):
    from deeptutor.capabilities.marginnote4.store import default_db_path

    with as_user("alice"):
        current_kb_manager().register_connected_entry("notes", {"type": "marginnote4"})
        database = default_db_path("notes")
        database.parent.mkdir(parents=True, exist_ok=True)
        database.write_bytes(b"synced-notes")
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        source_id = qualified_kb_id("notes")
        assert "MarginNote 4" in preview_kb_move(source_id, destination)["blockers"][0]
        with pytest.raises(WorkspaceError, match="MarginNote 4"):
            move_kb(source_id, destination)
        assert database.read_bytes() == b"synced-notes"
        assert "notes" in current_kb_manager().list_knowledge_bases()
        with workspace_context(destination):
            assert "notes" not in current_kb_manager().list_knowledge_bases()


def test_moved_llamaindex_retrieval_keeps_citations_and_images(as_user, monkeypatch):
    from llama_index.core import Settings, VectorStoreIndex
    from llama_index.core.embeddings import MockEmbedding
    from llama_index.core.schema import ImageNode, TextNode

    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.rag.pipelines.llamaindex import storage
    from deeptutor.services.rag.pipelines.llamaindex.pipeline import LlamaIndexPipeline

    monkeypatch.setattr(Settings, "_embed_model", MockEmbedding(embed_dim=8))
    with as_user("alice"):
        _make_kb("atlas", b"source text")
        source_root = current_kb_manager().base_dir / "atlas"
        source_file = source_root / "raw" / "source.pdf"
        cache_image = get_path_service().get_parse_cache_root() / "aa" / "image.png"
        cache_image.parent.mkdir(parents=True)
        cache_image.write_bytes(b"image bytes")
        text_node = TextNode(
            text="source alpha",
            id_="text-1",
            metadata={"file_name": "source.pdf", "file_path": str(source_file)},
            embedding=[0.5] * 8,
        )
        image_node = ImageNode(
            text="[Image] source.pdf",
            id_="image-1",
            image_path=str(cache_image),
            metadata={"file_name": "source.pdf", "file_path": str(source_file)},
            embedding=[0.5] * 8,
        )
        index = VectorStoreIndex(nodes=[text_node, image_node])
        index.storage_context.persist(persist_dir=str(source_root / "version-1"))
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]

        move_kb(qualified_kb_id("atlas"), destination)
        assert not source_root.exists()
        cache_image.unlink()

        with workspace_context(destination):
            target_root = current_kb_manager().base_dir / "atlas"
            nodes = storage.retrieve_nodes(target_root / "version-1", "alpha", top_k=2)
            assert {node.node.node_id for node in nodes} == {"text-1", "image-1"}
            result = LlamaIndexPipeline._nodes_to_result(None, "alpha", nodes)
            assert {source["source"] for source in result["sources"]} == {
                str(target_root / "raw" / "source.pdf")
            }
            assert Path(result["sources"][0]["source"]).is_file()
            moved_image = next(node.node for node in nodes if node.node.node_id == "image-1")
            assert Path(moved_image.image_path).is_file()
            assert Path(moved_image.image_path).read_bytes() == b"image bytes"
            assert Path(moved_image.image_path).is_relative_to(target_root)


@pytest.mark.asyncio
async def test_moved_lightrag_search_opens_published_native_workspace(as_user, monkeypatch):
    from deeptutor.services.rag.pipelines.lightrag import engine, pipeline, storage

    with as_user("alice"):
        _make_kb("atlas", b"source")
        source_root = current_kb_manager().base_dir / "atlas"
        source_version = source_root / "version-1"
        source_workspace = engine.workspace_for(source_version)
        native_store = source_version / source_workspace
        native_store.mkdir()
        (native_store / "kv_store_doc_status.json").write_text(
            json.dumps({"doc": {"status": "processed", "chunks_list": ["chunk"]}})
        )
        (native_store / "kv_store_text_chunks.json").write_text(
            json.dumps({"chunk": {"content": "grounded passage"}})
        )
        (source_version / "meta.json").write_text(
            json.dumps(
                {
                    "version": "version-1",
                    "signature": "lightrag",
                    "provider": "lightrag",
                    "state": "published",
                    "lightrag_adapter_schema": 2,
                    "parser_bridge_schema": 1,
                    "workspace": source_workspace,
                }
            )
        )
        manager = current_kb_manager()
        manager.config = manager._load_config()
        manager.config["knowledge_bases"]["atlas"]["rag_provider"] = "lightrag"
        manager._save_config()
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        move_kb(qualified_kb_id("atlas"), destination)

        with workspace_context(destination):
            target_root = current_kb_manager().base_dir / "atlas"
            target_version = target_root / "version-1"
            assert not source_root.exists()
            assert engine.workspace_for(target_version) == source_workspace
            assert storage.latest_published_root(target_root) == target_version

            async def in_worker(job):
                return await job(None)

            async def no_op(*_args, **_kwargs):
                return None

            async def fake_query(rag, *_args):
                payload = json.loads(
                    (rag.working_dir / rag.workspace / "kv_store_text_chunks.json").read_text()
                )
                return payload["chunk"]["content"], [{"file_path": "source.pdf"}]

            def fake_build_rag(working_dir, **_kwargs):
                return SimpleNamespace(
                    working_dir=Path(working_dir),
                    workspace=engine.workspace_for(working_dir),
                )

            monkeypatch.setattr(pipeline, "run_in_worker_loop", in_worker)
            monkeypatch.setattr(engine, "build_rag", fake_build_rag)
            monkeypatch.setattr(engine, "initialize", no_op)
            monkeypatch.setattr(engine, "finalize", no_op)
            monkeypatch.setattr(engine, "query_with_sources", fake_query)
            monkeypatch.setattr(storage, "require_compatible_embedding", lambda *_args: None)
            monkeypatch.setattr(
                "deeptutor.services.rag.pipelines.lightrag.roles.resolve_query_roles",
                lambda: {},
            )
            monkeypatch.setattr(
                "deeptutor.services.embedding.get_embedding_config", lambda: object()
            )
            rag_pipeline = pipeline.LightRagPipeline(kb_base_dir=str(target_root.parent))
            monkeypatch.setattr(rag_pipeline, "_ensure_available", lambda: None)
            result = await rag_pipeline.search("alpha", "atlas")
            assert result["content"] == "grounded passage"
            assert result["sources"] == [{"file_path": "source.pdf"}]


@pytest.mark.asyncio
async def test_create_destination_overrides_library_scope(as_user, monkeypatch):
    from deeptutor.services import config

    monkeypatch.setattr(config, "load_config_with_main", lambda *_args: {})
    from deeptutor.api.routers import knowledge
    from deeptutor.services.workspace.knowledge import library_request

    with as_user("alice"):
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        seen = []

        async def fake_create(*_args):
            seen.append(knowledge._current_kb_base_dir())
            return {"name": "new"}

        monkeypatch.setattr(knowledge, "_create_knowledge_base_owned", fake_create)
        token = library_request.set(True)
        try:
            result = await knowledge.create_knowledge_base(
                BackgroundTasks(),
                name="new",
                files=[],
                rag_provider="llamaindex",
                pageindex_mode="",
                search_mode="",
                rel_paths=[],
                indexing_llm="",
                embedding_model="",
                storage_workspace_id=destination,
            )
        finally:
            library_request.reset(token)
        with workspace_context(destination):
            assert seen == [current_kb_manager().base_dir]
        assert result["id"] == qualified_kb_id("new", destination)


@pytest.mark.asyncio
async def test_uploaded_create_background_task_keeps_destination_scope(as_user, monkeypatch):
    from deeptutor.services import config

    monkeypatch.setattr(config, "load_config_with_main", lambda *_args: {})
    from deeptutor.api.routers import knowledge
    from deeptutor.knowledge.initializer import KnowledgeBaseInitializer
    from deeptutor.services.config import get_kb_config_service
    from deeptutor.services.workspace.knowledge import library_request

    with as_user("alice"):
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        account_root = current_kb_manager().base_dir
        seen = []

        async def fake_process(self):
            seen.append(knowledge._current_kb_base_dir())
            get_kb_config_service().set_kb_config(self.kb_name, {"indexed_in_scope": True})

        monkeypatch.setattr(KnowledgeBaseInitializer, "process_documents", fake_process)
        monkeypatch.setattr(knowledge, "_assert_provider_ready", lambda *_args: None)
        background = BackgroundTasks()
        token = library_request.set(True)
        try:
            result = await knowledge.create_knowledge_base(
                background,
                name="atlas",
                files=[UploadFile(file=BytesIO(b"grounded text"), filename="source.txt")],
                rag_provider="llamaindex",
                pageindex_mode="",
                search_mode="",
                rel_paths=[],
                indexing_llm="",
                embedding_model="",
                storage_workspace_id=destination,
            )
        finally:
            library_request.reset(token)

        with workspace_context(destination):
            target_root = current_kb_manager().base_dir
            assert (
                current_kb_manager()._load_config()["knowledge_bases"]["atlas"]["status"]
                == "processing"
            )
        assert "atlas" not in current_kb_manager()._load_config()["knowledge_bases"]
        assert result["task_id"]

        # Execute Starlette's real callback after the route's scope has gone.
        await background()

        assert seen == [target_root]
        with workspace_context(destination):
            entry = current_kb_manager()._load_config()["knowledge_bases"]["atlas"]
            assert entry["status"] == "ready"
            assert entry["indexed_in_scope"] is True
            assert (target_root / "atlas" / "raw" / "source.txt").read_bytes() == b"grounded text"
        assert "atlas" not in current_kb_manager()._load_config()["knowledge_bases"]
        assert not (account_root / "atlas").exists()


@pytest.mark.asyncio
async def test_upload_to_moved_kb_background_task_uses_its_storage_scope(as_user, monkeypatch):
    from deeptutor.services import config

    monkeypatch.setattr(config, "load_config_with_main", lambda *_args: {})
    from deeptutor.api.routers import knowledge
    from deeptutor.services.config import get_kb_config_service
    from deeptutor.services.workspace.knowledge import library_request

    with as_user("alice"):
        _make_kb("atlas", b"original")
        destination = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        move_kb(qualified_kb_id("atlas"), destination)
        account_root = current_kb_manager().base_dir
        seen = []

        class FakeAdder:
            def __init__(self, **_kwargs):
                pass

            def add_documents(self, paths, **_kwargs):
                return paths

            async def process_new_documents(self, paths):
                return SimpleNamespace(processed_count=len(paths), has_failures=False)

            def update_metadata(self, _count):
                seen.append(knowledge._current_kb_base_dir())
                get_kb_config_service().set_kb_config("atlas", {"uploaded_in_scope": True})

        monkeypatch.setattr(knowledge, "DocumentAdder", FakeAdder)
        monkeypatch.setattr(knowledge, "_assert_provider_ready", lambda *_args: None)
        monkeypatch.setattr(knowledge, "_freeze_append_indexing", lambda *_args: None)
        background = BackgroundTasks()
        token = library_request.set(True)
        try:
            result = await knowledge.upload_files(
                qualified_kb_id("atlas", destination),
                background,
                files=[UploadFile(file=BytesIO(b"second source"), filename="new.txt")],
                rag_provider=None,
                rel_paths=[],
                dest_subdir=None,
                image_analysis=None,
            )
        finally:
            library_request.reset(token)
        assert result["task_id"]
        await background()

        with workspace_context(destination):
            target_root = current_kb_manager().base_dir
            assert seen == [target_root]
            assert (
                current_kb_manager()._load_config()["knowledge_bases"]["atlas"]["uploaded_in_scope"]
                is True
            )
            assert (target_root / "atlas" / "raw" / "new.txt").read_bytes() == b"second source"
        assert "atlas" not in current_kb_manager()._load_config()["knowledge_bases"]
        assert not (account_root / "atlas").exists()
