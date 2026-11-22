from types import SimpleNamespace

import pytest

from deeptutor.multi_user import knowledge_access
from deeptutor.services.workspace import knowledge, resources


@pytest.mark.parametrize("attached", [False, True])
def test_default_selection_is_ready_scoped_and_deterministic(monkeypatch, attached):
    from deeptutor.modules import catalog
    from deeptutor.services.workspace import context

    monkeypatch.setattr(catalog, "module_enabled", lambda _: True)
    monkeypatch.setattr(context, "current_workspace_id", lambda: "school")
    monkeypatch.setattr(
        resources,
        "current_resources",
        lambda: resources.WorkspaceResources(knowledge_bases=["other:kb"] if attached else None),
    )
    ids = [
        "workspace:school:kb:z",
        "workspace:school:kb:a",
        "workspace:school:kb:building",
        "account:kb:agent",
    ]
    monkeypatch.setattr(
        knowledge_access, "list_visible_knowledge_bases", lambda: [{"id": rid} for rid in ids]
    )
    monkeypatch.setattr(
        knowledge_access,
        "resolve_kb",
        lambda rid: SimpleNamespace(id=rid, name=rid.rsplit(":", 1)[1]),
    )

    class Manager:
        def get_info(self, name, **kwargs):
            return {
                "status": "initializing" if name == "building" else "ready",
                "is_default": name == "z",
                "metadata": {"type": "subagent" if name == "agent" else "local"},
            }

    monkeypatch.setattr(knowledge_access, "manager_for_resource", lambda _: Manager())
    expected = ids[:1] + ([ids[1]] if attached else [])
    assert knowledge.inherited_chat_knowledge_bases() == expected
