from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from deeptutor.services.path_service import PathService
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager
from deeptutor.services.workspace import ContentWorkspaceService, WorkspaceError


@pytest.fixture
def service(tmp_path, monkeypatch):
    from deeptutor.services.workspace import service as module

    paths = PathService(workspace_root=tmp_path / "runtime")
    paths.ensure_all_directories()
    monkeypatch.setattr(module, "get_path_service", lambda: paths)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS", raising=False)
    return ContentWorkspaceService()


def test_registered_identity_survives_rename_archive_and_global_switch(service, tmp_path):
    a = service.create_workspace("Algebra")
    b = service.create_workspace("Biology")
    root = Path(a["path"])
    (root / "notes.txt").write_text("algebra", encoding="utf-8")
    published = service.publish(service.binding_by_id(a["workspace_id"]), [{"path": "notes.txt"}])[
        0
    ]
    service.update_workspace(a["workspace_id"], name="Linear algebra", archived=True)
    service.set_workspace(b["path"])
    restored = ContentWorkspaceService().binding_by_id(a["workspace_id"])
    assert restored.root == root
    assert restored.display_name == "Linear algebra"
    assert (
        service.resolve_published_item(a["workspace_id"], published.workspace_item_id)[
            0
        ].read_text()
        == "algebra"
    )
    with pytest.raises(WorkspaceError, match="archived"):
        service.validate_chat_binding(a["workspace_id"])
    assert service.validate_chat_binding(a["workspace_id"], existing=True).root == root
    service.update_workspace(a["workspace_id"], archived=False)
    assert service.create_workspace("Same folder", str(root))["workspace_id"] == a["workspace_id"]


def test_unbound_sessions_share_general_root_but_keep_distinct_outputs(service):
    a = service.create_runtime_context(
        capability="chat", session_id="a/b", turn_id="one", workspace_id=""
    )
    b = service.create_runtime_context(
        capability="chat", session_id="a_b", turn_id="one", workspace_id=""
    )
    again = service.create_runtime_context(
        capability="chat", session_id="a/b", turn_id="two", workspace_id=""
    )
    assert a.root == again.root
    assert a.root == b.root
    assert a.output_dir != b.output_dir
    assert a.output_dir != again.output_dir
    assert a.workspace_id == service.general_binding().workspace_id
    Path(a.output_dir, "result.txt").write_text("private result", encoding="utf-8")
    binding = service.binding_by_id(a.workspace_id)
    item = service.publish(binding, [{"path": f"{a.logical_output_dir}/result.txt"}])[0]
    assert (
        service.resolve_published_item(a.workspace_id, item.workspace_item_id)[0].read_text()
        == "private result"
    )
    with pytest.raises(WorkspaceError):
        service.resolve(service.binding_by_id(b.workspace_id), "../result.txt")


def test_registry_serializes_concurrent_registration(service):
    with ThreadPoolExecutor(max_workers=6) as pool:
        bindings = list(pool.map(lambda i: service.create_workspace(str(i)), range(25)))
    assert len({row["workspace_id"] for row in bindings}) == 25
    fresh = ContentWorkspaceService()
    assert all(
        str(fresh.binding_by_id(row["workspace_id"]).root) == row["path"] for row in bindings
    )


def test_registry_is_owner_scoped_even_with_shared_storage(service, tmp_path):
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    row = service.create_workspace("Owner")
    token = set_current_user(
        CurrentUser("other", "Other", "admin", UserScope("admin", "other", tmp_path))
    )
    try:
        with pytest.raises(WorkspaceError):
            service.binding_by_id(row["workspace_id"])
        with pytest.raises(WorkspaceError):
            service.update_workspace(row["workspace_id"], name="Stolen")
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
async def test_admission_freezes_binding_and_resume_ignores_global_folder(
    service, tmp_path, monkeypatch
):
    store = SQLiteSessionStore(tmp_path / "sessions.sqlite3")
    runtime = TurnRuntimeManager(store)
    a = service.create_workspace("A")
    b = service.create_workspace("B")
    captured = []

    async def run(execution):
        captured.append(
            service.create_runtime_context(
                capability=execution.capability,
                session_id=execution.session_id,
                turn_id=execution.turn_id,
                workspace_id=execution.payload.get("_content_workspace_id"),
            )
        )
        await store.update_turn_status(execution.turn_id, "completed")

    monkeypatch.setattr(runtime, "_run_turn", run)
    session, turn = await runtime.start_turn(
        {
            "content": "first",
            "workspace_id": a["workspace_id"],
            "language": "en",
            "auto_route": False,
        }
    )
    service.set_workspace(b["path"])
    await runtime._executions[turn["id"]].task
    assert captured[-1].root == a["path"]
    saved = await store.get_session(session["id"])
    assert saved["preferences"]["workspace_id"] == a["workspace_id"]
    _, next_turn = await runtime.start_turn(
        {"session_id": session["id"], "content": "continue", "language": "en", "auto_route": False}
    )
    await runtime._executions[next_turn["id"]].task
    assert captured[-1].root == a["path"]
    with pytest.raises(RuntimeError, match="workspace changed"):
        await runtime.start_turn(
            {
                "session_id": session["id"],
                "content": "stale",
                "workspace_id": b["workspace_id"],
                "auto_route": False,
            }
        )
    private, private_turn = await runtime.start_turn(
        {"content": "private", "workspace_id": None, "language": "en", "auto_route": False}
    )
    await runtime._executions[private_turn["id"]].task
    assert captured[-1].root not in {a["path"], b["path"]}
    assert (await store.get_session(private["id"]))["preferences"]["workspace_id"] is None
    await runtime.close()


def test_deployed_session_roots_are_shared_with_existing_runner_but_hidden_from_discovery(
    service, tmp_path, monkeypatch
):
    deployment = tmp_path / "shared"
    deployment.mkdir()
    monkeypatch.setenv("DEEPTUTOR_WORKSPACE_ROOT", str(deployment))
    private = service.session_binding("one")
    named = service.create_workspace("Named")
    assert private.root.is_relative_to(deployment / "outputs")
    assert Path(named["path"]).is_relative_to(deployment / "outputs")
    (private.root / "private.txt").write_text("hidden", encoding="utf-8")
    visible = service.list_entries(service.current_binding(), ".", depth=5, limit=1000)
    assert not any(".deeptutor" in str(row) for row in visible)


@pytest.mark.asyncio
async def test_workspace_filter_precedes_pagination(service, tmp_path):
    store = SQLiteSessionStore(tmp_path / "filter.sqlite3")
    for index in range(15):
        session = await store.ensure_session(f"session-{index}")
        await store.update_session_preferences(
            session["id"],
            {
                "workspace_id": "a" if index % 2 else None,
            },
        )
    rows = await store.list_sessions(limit=3, offset=0, workspace_id="a")
    more = await store.list_sessions(limit=3, offset=3, workspace_id="a")
    recent = await store.list_sessions(limit=3, workspace_id="")
    assert len(rows) == len(more) == len(recent) == 3
    assert {row["id"] for row in rows}.isdisjoint(row["id"] for row in more)
    assert all(row["preferences"]["workspace_id"] == "a" for row in rows + more)
    assert all(row["preferences"]["workspace_id"] is None for row in recent)


@pytest.mark.asyncio
async def test_move_and_unbind_persist_and_running_turn_cannot_be_moved(
    service, tmp_path, monkeypatch
):
    from fastapi import HTTPException

    from deeptutor.api.routers import sessions as router

    store = SQLiteSessionStore(tmp_path / "moves.sqlite3")
    monkeypatch.setattr(router, "get_session_store", lambda: store)
    workspace = service.create_workspace("A")
    session = await store.ensure_session("moving")
    moved = await router.update_session_organization(
        session["id"], router.SessionOrganizationRequest(workspace_id=workspace["workspace_id"])
    )
    assert moved["session"]["preferences"]["workspace_id"] == workspace["workspace_id"]
    turn = await store.create_turn(session["id"], "chat")
    with pytest.raises(HTTPException) as error:
        await router.update_session_organization(
            session["id"], router.SessionOrganizationRequest(workspace_id=None)
        )
    assert error.value.status_code == 409
    await store.update_turn_status(turn["id"], "completed")
    moved = await router.update_session_organization(
        session["id"], router.SessionOrganizationRequest(workspace_id=None)
    )
    assert moved["session"]["preferences"]["workspace_id"] is None


def test_root_and_individual_migrations_preserve_files_ids_and_artifact_urls(service, tmp_path):
    workspace = service.create_workspace("Calculus")
    binding = service.binding_by_id(workspace["workspace_id"])
    (binding.root / "notes.txt").write_text("keep these notes", encoding="utf-8")
    item = service.publish(binding, [{"path": "notes.txt"}])[0]
    old_root = binding.root
    root = tmp_path / "new-root"
    with service.maintenance():
        result = service.migrate_root(str(root))
    assert result["root"] == str(root)
    binding = service.binding_by_id(workspace["workspace_id"])
    assert binding.root == root / workspace["workspace_id"]
    assert (binding.root / "notes.txt").read_text() == "keep these notes"
    assert (old_root / "notes.txt").read_text() == "keep these notes"
    assert (
        service.resolve_published_item(workspace["workspace_id"], item.workspace_item_id)[
            0
        ].read_text()
        == "keep these notes"
    )
    independent = tmp_path / "external-calculus"
    with service.maintenance():
        service.migrate_workspace(workspace["workspace_id"], str(independent))
    with service.maintenance():
        service.migrate_root(str(tmp_path / "third-root"))
    assert service.binding_by_id(workspace["workspace_id"]).root == independent
    assert service.general_binding().root.parent == tmp_path / "third-root"
    assert service.system_binding().root.parent == tmp_path / "third-root"


def test_failed_migration_preserves_source_and_binding(service, tmp_path, monkeypatch):
    from deeptutor.services.workspace import migration

    workspace = service.create_workspace("Keep")
    source = Path(workspace["path"])
    (source / "notes.txt").write_text("original")
    original_manifest = migration._manifest
    calls = 0

    def corrupted_manifest(path):
        nonlocal calls
        calls += 1
        result = original_manifest(path)
        if calls == 2:
            result["notes.txt"] = ("file", "corrupted")
        return result

    monkeypatch.setattr(migration, "_manifest", corrupted_manifest)
    destination = tmp_path / "failed-move"
    with pytest.raises(WorkspaceError, match="changed"):
        with service.maintenance():
            service.migrate_workspace(workspace["workspace_id"], str(destination))
    assert service.binding_by_id(workspace["workspace_id"]).root == source
    assert (source / "notes.txt").read_text() == "original"
    assert not destination.exists()
    service.assert_available()


def test_migration_blocks_new_runtime_contexts(service):
    service.list_workspaces()
    with service.maintenance():
        with pytest.raises(WorkspaceError, match="migrated"):
            service.create_runtime_context(
                capability="chat", session_id="a", turn_id="one", workspace_id=""
            )
        with pytest.raises(WorkspaceError, match="migrated"):
            service.create_workspace("Not now")
    assert service.session_binding("a").workspace_id == service.general_binding().workspace_id


def test_system_workspace_snapshot_is_allowlisted_and_skills_are_retained(service):
    import json

    settings = service._settings_file().parent
    settings.mkdir(parents=True, exist_ok=True)
    source = {
        "services": {
            "llm": {
                "active_model_id": "m1",
                "profiles": [
                    {
                        "id": "p1",
                        "name": "Provider",
                        "binding": "openai",
                        "api_key": "SECRET-API-KEY",
                        "base_url": "https://user:SECRET-PASSWORD@example.com/path/SECRET-PATH?token=SECRET-QUERY",
                        "headers": {"Authorization": "SECRET-HEADER"},
                        "models": [
                            {"id": "m1", "model": "gpt-test", "extra": {"secret": "SECRET-EXTRA"}}
                        ],
                    }
                ],
            }
        },
        "private": "SECRET-TOP",
    }
    (settings / "model_catalog.json").write_text(json.dumps(source))
    (settings / "mcp.json").write_text(
        json.dumps(
            {
                "servers": {
                    "docs": {
                        "url": "https://user:SECRET-MCP@example.org/mcp?key=SECRET-MCP-QUERY",
                        "headers": {"Authorization": "SECRET-MCP-HEADER"},
                        "env": {"KEY": "SECRET-ENV"},
                        "args": ["SECRET-ARG"],
                    }
                }
            }
        )
    )
    legacy_skill = service._default_root() / "skills" / "my-skill"
    legacy_skill.mkdir(parents=True)
    (legacy_skill / "SKILL.md").write_text("# A reusable skill")
    system = service.system_binding()
    snapshot = service.refresh_system_snapshot()
    encoded = json.dumps(snapshot)
    assert "SECRET-" not in encoded
    assert "gpt-test" in encoded and "https://example.com" in encoded
    assert "docs" in encoded
    assert (system.root / "skills" / "my-skill" / "SKILL.md").read_text() == "# A reusable skill"
    assert json.loads((settings / "model_catalog.json").read_text()) == source
    with pytest.raises(WorkspaceError):
        service.validate_chat_binding(system.workspace_id)
    with pytest.raises(WorkspaceError):
        service.update_workspace(system.workspace_id, archived=True)


def test_skill_service_follows_system_workspace_migration(service, tmp_path):
    from deeptutor.services.skill.service import get_skill_service

    old_service = get_skill_service()
    skill = old_service.root / "workspace-test"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: workspace-test\ndescription: test\n---\nA skill")
    system = service.system_binding()
    destination = tmp_path / "moved-system"
    with service.maintenance():
        service.migrate_workspace(system.workspace_id, str(destination))
    current = get_skill_service()
    assert current.root == destination / "skills"
    assert current is not old_service
    assert current.get_detail("workspace-test").name == "workspace-test"
    assert (skill / "SKILL.md").is_file()
