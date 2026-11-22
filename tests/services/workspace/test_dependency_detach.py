from __future__ import annotations

import pytest

from deeptutor.services.path_service import get_path_service
from deeptutor.services.session import get_sqlite_session_store
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.data_migration import _sessions
from deeptutor.services.workspace.dependencies import dependency_closure
from tests.services.workspace.test_data_scope import account as account


@pytest.mark.asyncio
async def test_cleared_knowledge_bases_are_not_resurrected_from_history(account):
    """An explicit empty selection is a detach, not a missing preference."""
    with workspace_context():
        store = get_sqlite_session_store()
        detached = await store.create_session("Detached")
        await store.update_session_preferences(detached["id"], {"knowledge_bases": []})
        await store.add_message(
            detached["id"],
            "user",
            "an old question",
            metadata={"request_snapshot": {"knowledgeBases": ["old-kb"]}},
        )
        legacy = await store.create_session("Legacy")
        await store.add_message(
            legacy["id"],
            "user",
            "a legacy question",
            metadata={"request_snapshot": {"knowledgeBases": ["legacy-kb"]}},
        )
        paths = get_path_service()
        rows = _sessions(paths)

        selected, _ = dependency_closure(paths, rows, ["chat"], session_ids={detached["id"]})
        assert "knowledge_bases" not in selected
        assert "parse_cache" not in selected

        # A session that never recorded the key still needs the historical
        # snapshot, otherwise old conversations lose their sources.
        selected, _ = dependency_closure(paths, rows, ["chat"], session_ids={legacy["id"]})
        assert {"knowledge_bases", "parse_cache"} <= selected
