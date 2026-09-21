from pathlib import Path

import pytest

from deeptutor.multi_user.paths import get_current_path_service, local_admin_user, user_context
from deeptutor.partners.bus.events import InboundMessage
from deeptutor.partners.bus.queue import MessageBus
from deeptutor.services.partners.manager import PartnerConfig
from deeptutor.services.partners.runtime import PartnerRunner
from deeptutor.services.partners.workspace_binding import partner_content_context
from deeptutor.services.workspace import WorkspaceError, get_content_workspace_service
from deeptutor.services.workspace.context import current_workspace_id, workspace_context
from tests.services.partners.test_partner_workspace import _seed_admin_connected_kb


@pytest.mark.asyncio
async def test_shared_turn_reads_live_resources_and_preserves_private_memory(
    partners_root,
    fake_orchestrator,
    monkeypatch,
):
    from deeptutor.services.partners.interaction import get_partner_turn_context
    from deeptutor.services.partners.scope import partner_scope
    from deeptutor.tools.workspace import WorkspaceReadTool
    from tests.services.partners.scripts import finish

    with user_context(local_admin_user()):
        service = get_content_workspace_service()
        row = service.create_workspace("Research")
        other = service.create_workspace("Unrelated")
        workspace_id = row["workspace_id"]
        root = Path(row["path"])
        (root / "notes.txt").write_text("first version")
        with workspace_context(workspace_id):
            _seed_admin_connected_kb(get_current_path_service().workspace_root)
        skill = root / "skills" / "research"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            "---\nname: research\ndescription: Workspace skill\n---\nRead carefully."
        )

        runner = PartnerRunner(
            "ada", PartnerConfig(name="Ada", workspace_id=workspace_id), MessageBus()
        )
        seen = []

        async def handle(self, context):
            assert current_workspace_id() == workspace_id
            assert context.runtime.workspace.root == str(root)
            assert Path(context.runtime.workspace.output_dir).is_relative_to(root / "outputs")
            assert context.knowledge_bases == ["admin:kb:wiki"]
            assert "research" in context.skills_manifest
            assert get_partner_turn_context().own_memory.workspace_root == partner_scope("ada").root
            result = await WorkspaceReadTool().execute(path="notes.txt", _workspace_id=workspace_id)
            assert result.success
            seen.append(result.content)
            for event in finish("Done"):
                yield event

        monkeypatch.setattr(fake_orchestrator, "handle", handle)
        # A caller's different active workspace cannot redirect the Partner.
        with workspace_context(other["workspace_id"]):
            for text in ("first version", "updated live"):
                (root / "notes.txt").write_text(text)
                await runner.process_message(
                    InboundMessage(
                        channel="web", sender_id="42", chat_id="42", content="Read notes"
                    )
                )
                assert current_workspace_id() == other["workspace_id"]
        assert seen == ["first version", "updated live"]


def test_shared_workspace_filters_agents_and_honors_resource_selection(partners_root):
    with user_context(local_admin_user()):
        service = get_content_workspace_service()
        row = service.create_workspace("Research")
        config = PartnerConfig(name="Ada", workspace_id=row["workspace_id"])
        runner = PartnerRunner("ada", config, MessageBus())
        with partner_content_context("ada", config):
            _seed_admin_connected_kb(
                get_current_path_service().workspace_root, "other-agent", "subagent"
            )
            assert runner._list_kb_names() == []
            _seed_admin_connected_kb(get_current_path_service().workspace_root)
            assert runner._list_kb_names() == ["admin:kb:wiki"]
        service.update_workspace(
            row["workspace_id"], resources={"knowledge_bases": [], "skills": [], "mcp": []}
        )
        with partner_content_context("ada", config):
            assert runner._list_kb_names() == []
            assert runner._build_skills_manifest() == ""


def test_archived_workspace_fails_instead_of_falling_back(partners_root):
    with user_context(local_admin_user()):
        service = get_content_workspace_service()
        row = service.create_workspace("Research")
        config = PartnerConfig(name="Ada", workspace_id=row["workspace_id"])
        service.update_workspace(row["workspace_id"], archived=True)
        with pytest.raises(WorkspaceError, match="archived"):
            with partner_content_context("ada", config):
                pytest.fail("Archived workspaces must not execute")
        assert current_workspace_id() == ""


def test_deleted_owner_cannot_fall_back_to_admin(partners_root):
    config = PartnerConfig(name="Ada", owner_id="deleted-owner", workspace_id="ws_missing")
    with pytest.raises(WorkspaceError, match="owner is unavailable"):
        with partner_content_context("ada", config):
            pytest.fail("Missing owners must not execute")


def test_workspace_is_resolved_against_owner_not_message_sender(partners_root, monkeypatch):
    from deeptutor.multi_user.models import CurrentUser
    from deeptutor.multi_user.paths import scope_for_user
    from deeptutor.services.partners import workspace_binding
    from deeptutor.services.partners.workspace_binding import validate_partner_workspace

    owner = CurrentUser("owner", "Owner", "user", scope_for_user("owner", is_admin=False))
    sender = CurrentUser("sender", "Sender", "user", scope_for_user("sender", is_admin=False))
    with user_context(owner):
        row = get_content_workspace_service().create_workspace("Owner research")
    config = PartnerConfig(name="Ada", owner_id=owner.id, workspace_id=row["workspace_id"])
    monkeypatch.setattr(
        workspace_binding, "actor_for_account", lambda uid: owner if uid == owner.id else None
    )
    with user_context(sender):
        with pytest.raises(WorkspaceError):
            validate_partner_workspace(row["workspace_id"], sender.id)
        with partner_content_context("ada", config):
            assert current_workspace_id() == row["workspace_id"]
            assert get_current_path_service().scope.account_root == owner.scope.root
        assert get_current_path_service().workspace_root == sender.scope.root


def test_binding_follows_registry_move_without_copying_resources(partners_root):
    service = get_content_workspace_service()
    row = service.create_workspace("Research")
    root = Path(row["path"])
    (root / "notes.txt").write_text("persistent notes")
    config = PartnerConfig(name="Ada", workspace_id=row["workspace_id"])
    destination = root.parent / "moved-research"
    service.migrate_workspace(row["workspace_id"], str(destination))
    with partner_content_context("ada", config):
        binding = get_content_workspace_service().binding_by_id(config.workspace_id)
        assert binding.root == destination
        assert (binding.root / "notes.txt").read_text() == "persistent notes"
