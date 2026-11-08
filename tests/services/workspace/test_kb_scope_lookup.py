"""A dead workspace registration must not break KB scope lookup.

`workspace_id_for_kb_base_dir()` runs on every upload/sync/reindex to stamp the
destination scope onto the background task. It walks every registered
workspace, and a registration whose folder no longer exists raises on entry —
which used to abort the whole lookup (surfacing as a bogus
``404 Knowledge base '<kb>' not found`` on an otherwise healthy workspace).
"""

from __future__ import annotations

from pathlib import Path

from deeptutor.multi_user.paths import get_account_path_service
from deeptutor.services.path_service import get_path_service
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.knowledge import workspace_id_for_kb_base_dir
from tests.services.workspace.test_data_scope import account as account


def test_lookup_skips_a_registration_whose_folder_is_gone(account):
    stale = account.create_workspace("Leftover")
    Path(stale["path"]).rename(Path(stale["path"]).with_name("leftover-moved"))
    account.update_workspace(stale["workspace_id"], archived=True)

    target = account.create_workspace("Calculus")["workspace_id"]
    with workspace_context(target):
        kb_root = get_path_service().get_knowledge_bases_root()

    assert workspace_id_for_kb_base_dir(kb_root) == target


def test_account_knowledge_base_root_needs_no_workspace_scan(account):
    account.create_workspace("Leftover")

    with workspace_context(""):
        account_kb_root = get_account_path_service().get_knowledge_bases_root()

    assert workspace_id_for_kb_base_dir(account_kb_root) == ""


def test_lookup_returns_none_for_an_unowned_directory(account, tmp_path):
    account.create_workspace("Calculus")

    stray = tmp_path / "not-a-workspace-kb"
    stray.mkdir()

    assert workspace_id_for_kb_base_dir(stray) is None
