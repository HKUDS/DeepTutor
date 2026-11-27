"""Resource selections preserve old access and narrow every runtime entry point."""

from pathlib import Path

from fastapi import HTTPException
import pytest

from deeptutor.core.errors import AccessError
from deeptutor.multi_user.knowledge_access import (
    current_kb_manager,
    list_visible_knowledge_bases,
    resolve_kb,
)
from deeptutor.services.skill.runtime import runtime_skills, skill_manifest
from deeptutor.services.skill.service import get_skill_service
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.knowledge import (
    knowledge_catalog,
    library_request,
    qualified_kb_id,
)
from deeptutor.services.workspace.resources import current_resources, resource_catalog
from deeptutor.tools.builtin import ReadSkillTool


def write_skill(root, name, text, *, always=False):
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\ndescription: {text}\nalways: {str(always).lower()}\n---\n{text}"
    )


@pytest.mark.asyncio
async def test_legacy_and_selected_skills_and_local_shadow(as_user):
    with as_user("alice"):
        write_skill(get_skill_service().root, "research", "account version", always=True)
        write_skill(get_skill_service().root, "other", "other version")
        service = ContentWorkspaceService()
        row = service.create_workspace("Research")
        with workspace_context(row["workspace_id"]):
            assert current_resources().skills is None
            assert "account version" in skill_manifest()
        write_skill(Path(row["path"]) / "skills", "research", "workspace version", always=True)
        service.update_workspace(row["workspace_id"], resources={"skills": ["research"]})
        with workspace_context(row["workspace_id"]):
            assert set(runtime_skills()) == {"research"}
            assert "workspace version" in skill_manifest()
            assert "account version" not in skill_manifest()
            assert not (await ReadSkillTool().execute(name="other")).success
            assert "workspace version" in (await ReadSkillTool().execute(name="research")).content
        service.update_workspace(row["workspace_id"], resources={"skills": []})
        with workspace_context(row["workspace_id"]):
            assert skill_manifest() == ""
            assert not (await ReadSkillTool().execute(name="research")).success
        with workspace_context():
            assert "account version" in skill_manifest()


def test_knowledge_origins_selection_and_grants(as_user):
    with as_user("alice"):
        current_kb_manager().register_connected_entry(
            "same", {"type": "obsidian", "vault_path": "/unused"}
        )
        service = ContentWorkspaceService()
        a = service.create_workspace("A")
        b = service.create_workspace("B")
        with workspace_context(a["workspace_id"]):
            current_kb_manager().register_connected_entry(
                "same", {"type": "obsidian", "vault_path": "/unused-a"}
            )
            legacy_root = resolve_kb("same").base_dir
        global_id = qualified_kb_id("same")
        local_id = qualified_kb_id("same", a["workspace_id"])
        assert {global_id, local_id} <= {r["id"] for r in knowledge_catalog()}
        service.update_workspace(b["workspace_id"], resources={"knowledge_bases": [local_id]})
        with workspace_context(b["workspace_id"]):
            assert [r["id"] for r in list_visible_knowledge_bases()] == [local_id]
            assert resolve_kb("same").base_dir == legacy_root
            assert resolve_kb(local_id).base_dir == legacy_root
            with pytest.raises(AccessError, match="not assigned"):
                resolve_kb(global_id)
            with pytest.raises(AccessError):
                resolve_kb("admin:kb:same")
        service.update_workspace(
            b["workspace_id"], resources={"knowledge_bases": [global_id, local_id]}
        )
        with workspace_context(b["workspace_id"]):
            with pytest.raises(AccessError):
                resolve_kb("same")
            assert resolve_kb(global_id).base_dir != resolve_kb(local_id).base_dir
        service.update_workspace(b["workspace_id"], resources={"knowledge_bases": []})
        with workspace_context(b["workspace_id"]):
            assert list_visible_knowledge_bases() == []
            with pytest.raises(AccessError):
                resolve_kb(local_id)
            token = library_request.set(True)
            try:
                assert len(list_visible_knowledge_bases()) == 2
                assert resolve_kb(local_id).base_dir == legacy_root
            finally:
                library_request.reset(token)
    with as_user("bob"):
        with pytest.raises(AccessError):
            resolve_kb(local_id)
        with pytest.raises(WorkspaceError):
            ContentWorkspaceService().create_workspace(
                "Theft", resources={"knowledge_bases": [local_id]}
            )


@pytest.mark.parametrize("by_name", [False, True])
@pytest.mark.asyncio
async def test_kb_delete_checks_workspace_access_on_cold_manager_lookup(
    as_user, monkeypatch, by_name
):
    from deeptutor.api.routers import knowledge
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    with as_user("alice"):
        workspace_id = ContentWorkspaceService().create_workspace(
            "Restricted", resources={"knowledge_bases": []}
        )["workspace_id"]
        with workspace_context(workspace_id):
            manager = current_kb_manager()
            assert manager.register_connected_entry(
                "notes", {"type": "obsidian", "vault_path": "/unused"}
            )
            uncached = KnowledgeBaseManager(manager.base_dir)
            managers = iter((uncached, manager))
            monkeypatch.setattr(knowledge, "current_kb_manager", lambda: next(managers, manager))

            with pytest.raises(AccessError):
                if by_name:
                    await knowledge.delete_knowledge_base_by_name(
                        knowledge.DeleteKnowledgeBaseRequest(name="notes")
                    )
                else:
                    await knowledge.delete_knowledge_base("notes")

            assert manager.get_kb_entry("notes") is not None


@pytest.mark.asyncio
async def test_library_delete_only_removes_the_qualified_workspace_kb(as_user):
    from deeptutor.api.routers import knowledge

    with as_user("alice"), workspace_context():
        account_manager = current_kb_manager()
        pointer = {"type": "obsidian", "vault_path": "/unused"}
        assert account_manager.register_connected_entry("notes", pointer)
        workspace_id = ContentWorkspaceService().create_workspace("Research")["workspace_id"]
        with workspace_context(workspace_id):
            workspace_manager = current_kb_manager()
            assert workspace_manager.register_connected_entry("notes", pointer)

        token = library_request.set(True)
        try:
            payload = knowledge.DeleteKnowledgeBaseRequest(
                name=qualified_kb_id("notes", workspace_id)
            )
            await knowledge.delete_knowledge_base_by_name(payload)
        finally:
            library_request.reset(token)

        assert account_manager.get_kb_entry("notes") is not None
        assert workspace_manager.get_kb_entry("notes") is None


@pytest.mark.asyncio
async def test_cancelled_kb_delete_holds_workspace_activity(as_user, monkeypatch):
    import asyncio
    from threading import Event

    from deeptutor.api.routers import knowledge
    from deeptutor.knowledge.manager import KnowledgeBaseManager
    from deeptutor.services.workspace.activity import WorkspaceActivityMiddleware, acquire_activity

    entered, release, finished = Event(), Event(), Event()
    delete = KnowledgeBaseManager._delete_knowledge_base

    def slow_delete(manager, *args, **kwargs):
        entered.set()
        try:
            assert release.wait(5)
            return delete(manager, *args, **kwargs)
        finally:
            finished.set()

    async def endpoint(_scope, _receive, _send):
        await knowledge.delete_knowledge_base("notes")

    with as_user("alice"), workspace_context():
        manager = current_kb_manager()
        assert manager.register_connected_entry(
            "notes", {"type": "obsidian", "vault_path": "/unused"}
        )
        monkeypatch.setattr(KnowledgeBaseManager, "_delete_knowledge_base", slow_delete)
        state = {"workspace_activity": acquire_activity()}
        middleware = WorkspaceActivityMiddleware(endpoint)
        request = asyncio.create_task(middleware({"state": state}, None, None))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
            assert not finished.is_set()
            with pytest.raises(WorkspaceError, match="busy"):
                acquire_activity(exclusive=True).close()
        finally:
            release.set()
            assert await asyncio.to_thread(finished.wait, 3)

        assert manager.get_kb_entry("notes") is None


def test_inherited_workspace_keeps_account_subagents_without_sharing_kbs(as_user):
    with as_user("alice"):
        account_manager = current_kb_manager()
        account_manager.register_connected_entry(
            "notes", {"type": "obsidian", "vault_path": "/unused"}
        )
        account_manager.register_subagent_connection("my-agent", "codex")

        workspace = ContentWorkspaceService().create_workspace("Research")
        with workspace_context(workspace["workspace_id"]):
            assert [item["id"] for item in list_visible_knowledge_bases()] == [
                "account:kb:my-agent"
            ]
            assert resolve_kb("account:kb:my-agent").name == "my-agent"

        ContentWorkspaceService().update_workspace(
            workspace["workspace_id"], resources={"knowledge_bases": []}
        )
        with workspace_context(workspace["workspace_id"]):
            assert list_visible_knowledge_bases() == []
            with pytest.raises(AccessError):
                resolve_kb("account:kb:my-agent")


def test_explicit_learning_sources_allow_reads_without_changing_workspace_or_write_access(as_user):
    from deeptutor.services.workspace.context import current_workspace_id
    from deeptutor.services.workspace.knowledge import learning_source_access

    with as_user("alice"):
        current_kb_manager().register_connected_entry(
            "notes", {"type": "obsidian", "vault_path": "/unused"}
        )
        source = qualified_kb_id("notes")
        service = ContentWorkspaceService()
        target = service.create_workspace("New books", resources={"knowledge_bases": []})[
            "workspace_id"
        ]
        with workspace_context(target):
            with pytest.raises(AccessError):
                resolve_kb(source)
            with learning_source_access([source]):
                assert resolve_kb(source).name == "notes"
                assert current_workspace_id() == target
                with pytest.raises(AccessError):
                    resolve_kb(source, require_write=True)
            with pytest.raises(AccessError):
                resolve_kb(source)
    with as_user("bob"), learning_source_access([f"workspace:{target}:kb:notes"]):
        with pytest.raises(AccessError):
            resolve_kb(f"workspace:{target}:kb:notes")


def test_selection_persistence_missing_and_default(as_user):
    with as_user("alice"):
        service = ContentWorkspaceService()
        write_skill(get_skill_service().root, "one", "one")
        row = service.create_workspace("A", resources={"skills": ["one"], "mcp": []})
        service.update_workspace(row["workspace_id"], name="Renamed")
        with workspace_context(row["workspace_id"]):
            assert current_resources().skills == ["one"]
            assert current_resources().mcp == []
        get_skill_service().delete("one")
        service.update_workspace(row["workspace_id"], resources=row["resources"])
        with workspace_context(row["workspace_id"]):
            assert runtime_skills() == {}
        with pytest.raises(WorkspaceError):
            service.create_workspace("Invalid", resources={"skills": ["unknown"]})
        general = service.general_binding()
        service.update_workspace(general.workspace_id, resources={"skills": []})
        with workspace_context():
            assert skill_manifest() == ""
        assert isinstance(resource_catalog()["mcp"], list)


@pytest.mark.asyncio
async def test_resource_api_roundtrip(as_user):
    from deeptutor.api.routers.workspace import (
        CreateWorkspacePayload,
        UpdateWorkspacePayload,
        create_workspace,
        update_registered_workspace,
        workspace_resource_catalog,
    )

    with as_user("alice"):
        result = await create_workspace(
            CreateWorkspacePayload(
                name="Selected", resources={"skills": [], "mcp": [], "knowledge_bases": []}
            )
        )
        assert result["workspace"]["resources"] == {"skills": [], "mcp": [], "knowledge_bases": []}
        changed = await update_registered_workspace(
            result["workspace"]["workspace_id"], UpdateWorkspacePayload(resources={"skills": None})
        )
        assert changed["workspace"]["resources"]["skills"] is None
        assert set(await workspace_resource_catalog()) == {"skills", "mcp", "knowledge_bases"}


def test_migration_reports_workspaces_that_reference_the_source(as_user):
    from deeptutor.services.workspace.resources import knowledge_migration_blockers, resource_usage

    with as_user("alice"):
        current_kb_manager().register_connected_entry(
            "math", {"type": "obsidian", "vault_path": "/unused"}
        )
        service = ContentWorkspaceService()
        row = service.create_workspace(
            "Consumer", resources={"knowledge_bases": ["account:kb:math"]}
        )
        assert "Consumer" in knowledge_migration_blockers("")[0]
        assert row["workspace_id"] in {
            r["workspace_id"] for r in resource_usage("knowledge_bases", "account:kb:math")
        }
        service.update_workspace(row["workspace_id"], resources={"knowledge_bases": []})
        assert knowledge_migration_blockers("") == []


@pytest.mark.asyncio
async def test_delete_kb_file_in_workspace(as_user):
    from deeptutor.api.routers.knowledge import delete_kb_file
    from deeptutor.services.workspace import ContentWorkspaceService
    from deeptutor.services.workspace.context import workspace_context

    with as_user("alice"):
        service = ContentWorkspaceService()
        ws = service.create_workspace("Chemistry")
        ws_id = ws["workspace_id"]
        kb_name = "初中化学"

        with workspace_context(ws_id):
            mgr = current_kb_manager()
            kb_dir = mgr.base_dir / kb_name
            kb_dir.mkdir(parents=True, exist_ok=True)
            mgr.config.setdefault("knowledge_bases", {})[kb_name] = {
                "rag_provider": "llamaindex",
                "status": "ready",
            }
            mgr._save_config()
            raw_dir = kb_dir / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            doc_file = raw_dir / "chapter1.pdf"
            doc_file.write_text("chemical equations")

        assert doc_file.exists()
        qualified_ref = f"workspace:{ws_id}:kb:{kb_name}"
        result = await delete_kb_file(qualified_ref, "chapter1.pdf")
        assert result["status"] == "ok"
        assert not doc_file.exists()
