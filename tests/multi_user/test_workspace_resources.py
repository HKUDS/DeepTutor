"""Resource selections preserve old access and narrow every runtime entry point."""

from pathlib import Path

from fastapi import HTTPException
import pytest

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
            with pytest.raises(HTTPException, match="403"):
                resolve_kb(global_id)
            with pytest.raises(HTTPException):
                resolve_kb("admin:kb:same")
        service.update_workspace(
            b["workspace_id"], resources={"knowledge_bases": [global_id, local_id]}
        )
        with workspace_context(b["workspace_id"]):
            with pytest.raises(HTTPException):
                resolve_kb("same")
            assert resolve_kb(global_id).base_dir != resolve_kb(local_id).base_dir
        service.update_workspace(b["workspace_id"], resources={"knowledge_bases": []})
        with workspace_context(b["workspace_id"]):
            assert list_visible_knowledge_bases() == []
            with pytest.raises(HTTPException):
                resolve_kb(local_id)
            token = library_request.set(True)
            try:
                assert len(list_visible_knowledge_bases()) == 2
                assert resolve_kb(local_id).base_dir == legacy_root
            finally:
                library_request.reset(token)
    with as_user("bob"):
        with pytest.raises(HTTPException):
            resolve_kb(local_id)
        with pytest.raises(WorkspaceError):
            ContentWorkspaceService().create_workspace(
                "Theft", resources={"knowledge_bases": [local_id]}
            )


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
            with pytest.raises(HTTPException):
                resolve_kb(source)
            with learning_source_access([source]):
                assert resolve_kb(source).name == "notes"
                assert current_workspace_id() == target
                with pytest.raises(HTTPException):
                    resolve_kb(source, require_write=True)
            with pytest.raises(HTTPException):
                resolve_kb(source)
    with as_user("bob"), learning_source_access([f"workspace:{target}:kb:notes"]):
        with pytest.raises(HTTPException):
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
