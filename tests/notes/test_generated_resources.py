from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from deeptutor.notes.resources import normalize_note_resources, saved_note_resources


@pytest.fixture
def workspace(monkeypatch):
    import deeptutor.services.workspace as module

    service = Mock()
    service.publish.return_value = [SimpleNamespace(url="/files/workspace-items/scoped/chart")]
    monkeypatch.setattr(module, "get_content_workspace_service", lambda: service)
    return service


def test_generated_images_use_bound_workspace_and_do_not_mutate_blocks(workspace):
    path = "outputs/chat/unified_test/turn/image.png"
    blocks = [
        {
            "id": "image",
            "props": {"url": path},
            "children": [{"id": "caption", "props": {"markdown": f"![chart]({path})"}}],
        }
    ]
    markdown, normalized = normalize_note_resources(
        f"![chart]({path})", blocks, workspace_id="bound"
    )
    assert markdown == "![chart](/files/workspace-items/scoped/chart)"
    assert normalized[0]["props"]["url"] == "/files/workspace-items/scoped/chart"
    assert normalized[0]["children"][0]["props"]["markdown"] == markdown
    assert blocks[0]["props"]["url"] == path
    workspace.binding_by_id.assert_called_once_with("bound")
    workspace.current_binding.assert_not_called()
    workspace.publish.assert_called_once()


def test_existing_links_and_code_are_not_published(workspace):
    markdown = "![web](https://example.com/chart.png)\n```md\n![example](outputs/a.png)\n```"
    assert normalize_note_resources(markdown)[0] == markdown
    workspace.publish.assert_not_called()


def test_invalid_workspace_path_is_not_converted_to_a_public_url(workspace):
    from deeptutor.services.workspace import WorkspaceError

    workspace.publish.side_effect = WorkspaceError("Path leaves workspace")
    with pytest.raises(WorkspaceError):
        normalize_note_resources("![image](outputs/../../private.png)", workspace_id="bound")


@pytest.mark.asyncio
async def test_legacy_paths_resolve_only_from_authorized_session_attachments(
    monkeypatch, workspace
):
    import deeptutor.services.session as module

    path = "outputs/chat/unified_test/turn/chart.png"
    store = SimpleNamespace(
        get_session_with_messages=AsyncMock(
            return_value={
                "messages": [
                    {
                        "attachments": [
                            {"relative_path": path, "url": "/files/workspace-items/owner/asset"},
                            {
                                "relative_path": "outputs/unrelated.png",
                                "url": "/files/workspace-items/owner/other",
                            },
                        ]
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(module, "get_session_store", lambda: store)
    published = await saved_note_resources(f"![chart]({path})")
    assert published == {path: "/files/workspace-items/owner/asset"}
    store.get_session_with_messages.assert_awaited_once_with("unified_test")
    assert normalize_note_resources(f"![chart]({path})", published=published)[0].endswith(
        "/owner/asset)"
    )
    workspace.publish.assert_not_called()
    store.get_session_with_messages.return_value = None
    assert await saved_note_resources(f"![chart]({path})") == {}


def test_review_ignores_default_formatting_but_detects_user_edits():
    from deeptutor.notes.proposals import same_block

    original = {"id": "a", "type": "paragraph", "props": {}, "content": "Original"}
    normalized = {
        **original,
        "props": {"textColor": "default", "backgroundColor": "default", "textAlignment": "left"},
        "children": [],
    }
    assert same_block(original, normalized)
    assert not same_block(original, {**normalized, "content": "Typed while generating"})
    assert not same_block(original, {**normalized, "props": {"textAlignment": "center"}})
