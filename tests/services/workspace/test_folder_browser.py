import os
from pathlib import Path

import pytest

from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.workspace.folders import browse_folders
from deeptutor.services.workspace.models import WorkspaceError
from deeptutor.services.workspace.service import ContentWorkspaceService


@pytest.fixture
def browser(monkeypatch, tmp_path):
    root = tmp_path / "src"
    root.mkdir()
    monkeypatch.setenv("DEEPTUTOR_WORKSPACE_BROWSER_ROOTS", str(root))
    service = ContentWorkspaceService()
    # Even an admin who can register arbitrary folders must stay inside the
    # browser's explicitly configured roots.
    monkeypatch.setattr(service, "_assert_allowed_root", lambda root: None)
    return service, root


def test_navigate_existing_folders_without_creating_outputs(browser):
    service, root = browser
    (root / "oss").mkdir()
    (root / "中文项目").mkdir()
    (root / ".private").mkdir()
    (root / "file.txt").write_text("not a folder")
    listing = browse_folders(service)
    assert listing["path"] == str(root)
    assert listing["parent"] is None
    assert [entry["name"] for entry in listing["folders"]] == ["oss", "中文项目"]
    nested = browse_folders(service, str(root / "oss"))
    assert nested["parent"] == str(root)
    assert nested["folders"] == []
    assert not (root / "outputs").exists()
    assert not (root / "oss" / "outputs").exists()


def test_parent_traversal_and_absolute_escape_are_rejected(browser):
    service, root = browser
    for path in [str(root / ".."), str(root.parent), str(root) + "/../../outside"]:
        with pytest.raises(WorkspaceError, match="outside"):
            browse_folders(service, path)


def test_symlinks_cannot_escape_the_browsing_root(browser):
    service, root = browser
    outside = root.parent / "private"
    outside.mkdir()
    try:
        (root / "escape").symlink_to(outside, target_is_directory=True)
        (root / "self").symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this Windows host")
    assert browse_folders(service)["folders"] == []
    with pytest.raises(WorkspaceError, match="outside"):
        browse_folders(service, str(root / "escape"))


def test_missing_and_invalid_paths_fail_cleanly(browser):
    service, root = browser
    with pytest.raises(WorkspaceError, match="cannot be opened"):
        browse_folders(service, str(root / "missing"))
    with pytest.raises(WorkspaceError, match="invalid"):
        browse_folders(service, "\x00")


def test_roots_respect_existing_workspace_access_policy(browser, monkeypatch):
    service, _ = browser

    def deny(root: Path):
        raise WorkspaceError("denied")

    monkeypatch.setattr(service, "_assert_allowed_root", deny)
    with pytest.raises(WorkspaceError, match="No browsable"):
        browse_folders(service)


def test_multiple_roots_do_not_expand_a_normal_users_access(tmp_path, monkeypatch):
    allowed, private = tmp_path / "allowed", tmp_path / "private"
    allowed.mkdir()
    private.mkdir()
    monkeypatch.setenv(
        "DEEPTUTOR_WORKSPACE_BROWSER_ROOTS", os.pathsep.join(map(str, [allowed, private]))
    )
    service = ContentWorkspaceService()
    monkeypatch.setattr(service, "_allowed_roots", lambda: (allowed,))
    token = set_current_user(
        CurrentUser("learner", "learner", "user", UserScope("user", "learner", allowed))
    )
    try:
        assert browse_folders(service)["roots"] == [{"name": "allowed", "path": str(allowed)}]
        with pytest.raises(WorkspaceError, match="outside"):
            browse_folders(service, str(private))
    finally:
        reset_current_user(token)


def test_multiple_roots_are_navigable_without_parent_escape(browser, monkeypatch):
    service, first = browser
    second = first.parent / "other-projects"
    second.mkdir()
    monkeypatch.setenv(
        "DEEPTUTOR_WORKSPACE_BROWSER_ROOTS", os.pathsep.join(map(str, [first, second]))
    )
    listing = browse_folders(service, str(second))
    assert [row["path"] for row in listing["roots"]] == [str(first), str(second)]
    assert listing["parent"] is None
