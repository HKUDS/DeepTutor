"""Where installs and preferences live, and what that placement has to guarantee.

The layout is the security design, not an implementation detail: an app the
sandbox can rewrite is a persistence primitive, and a preference the sandbox can
rewrite is a way to switch on an app for the next turn. These tests pin the two
placements and the one path-building function that turns catalog data into a
filename.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.cli_apps.models import AppRuntime, InstallKind
from deeptutor.services.cli_apps.paths import (
    abi_stamp,
    app_dir,
    cli_apps_root,
    ensure_root,
    executable_path,
    state_path,
)
from deeptutor.services.cli_apps.state import (
    InstalledApp,
    disabled_apps,
    forget_install,
    load_installed,
    now_stamp,
    prefs_path,
    record_install,
    set_app_enabled,
)


def _app(app_id: str = "demo", **overrides: object) -> InstalledApp:
    base: dict[str, object] = {
        "id": app_id,
        "entry_point": f"cli-anything-{app_id}",
        "runtime": AppRuntime.PYTHON,
        "kind": InstallKind.PINNED_HARNESS,
        "target": "git+https://example.invalid/repo.git@abc#subdirectory=x",
        "pin": "abc",
        "abi": abi_stamp(),
        "installed_at": now_stamp(),
    }
    base.update(overrides)
    return InstalledApp(**base)  # type: ignore[arg-type]


# ── placement ─────────────────────────────────────────────────────────────


def test_installs_live_outside_every_writable_sandbox_mount(cli_app_roots: Path) -> None:
    """``data/cli-apps`` is a third location on purpose.

    The runner mounts the two workspace roots **writable** — an executable in
    either could be replaced by a command that escaped the sandbox, and would
    then run in every later turn of every account.
    """
    root = cli_apps_root()

    assert root == cli_app_roots / "cli-apps"
    assert not root.is_relative_to(cli_app_roots / "users")
    assert not root.is_relative_to(cli_app_roots / "user" / "workspace")
    # And not under data/system either: the runner has to *read* this one.
    assert not root.is_relative_to(cli_app_roots / "system")


def test_preferences_live_where_the_sandbox_cannot_reach_them(cli_app_roots: Path) -> None:
    """Enabling an app for the next turn must not be reachable from inside one."""
    path = prefs_path("u_ada")

    assert path.is_relative_to(cli_app_roots / "system")
    assert not path.is_relative_to(cli_apps_root())


@pytest.mark.parametrize("owner", ["../escape", "a/b", "", ".hidden"])
def test_a_preferences_file_cannot_be_addressed_outside_its_directory(owner: str) -> None:
    with pytest.raises(ValueError, match="owner id"):
        prefs_path(owner)


def test_the_tree_is_created_owner_only(cli_app_roots: Path) -> None:
    root = ensure_root()
    assert root.is_dir()
    assert (root / "apps").is_dir()
    assert oct(root.stat().st_mode)[-3:] == "700"


@pytest.mark.parametrize("entry_point", ["../../../bin/sh", "sub/dir", "", "."])
def test_an_executable_path_cannot_escape_the_app_directory(entry_point: str) -> None:
    """``entry_point`` is catalog data, and this is the function that makes it a path."""
    with pytest.raises(ValueError, match="entry point"):
        executable_path("demo", AppRuntime.PYTHON, entry_point)


def test_an_executable_resolves_inside_its_own_app_directory() -> None:
    path = executable_path("demo", AppRuntime.PYTHON, "cli-anything-demo")
    assert path.is_relative_to(app_dir("demo"))
    assert path.name == "cli-anything-demo"


def test_each_app_gets_its_own_environment() -> None:
    """One venv per app, so two apps with incompatible pins both work."""
    assert app_dir("a") != app_dir("b")
    assert executable_path("a", AppRuntime.PYTHON, "x").parent != (
        executable_path("b", AppRuntime.PYTHON, "x").parent
    )


def test_node_and_python_apps_do_not_share_a_bin_directory() -> None:
    assert executable_path("a", AppRuntime.NODE, "x") != executable_path(
        "a", AppRuntime.PYTHON, "x"
    )


# ── deployment state ──────────────────────────────────────────────────────


def test_an_install_round_trips() -> None:
    record_install(_app("blender"))
    loaded = load_installed()

    assert list(loaded) == ["blender"]
    assert loaded["blender"].entry_point == "cli-anything-blender"
    assert loaded["blender"].runtime is AppRuntime.PYTHON


def test_recording_the_same_app_replaces_rather_than_duplicates() -> None:
    record_install(_app("blender", version="1"))
    record_install(_app("blender", version="2"))

    loaded = load_installed()
    assert list(loaded) == ["blender"]
    assert loaded["blender"].version == "2"


def test_forgetting_an_app_leaves_the_others() -> None:
    record_install(_app("a"))
    record_install(_app("b"))
    forget_install("a")

    assert list(load_installed()) == ["b"]


def test_forgetting_an_unknown_app_is_a_no_op() -> None:
    record_install(_app("a"))
    forget_install("nope")
    assert list(load_installed()) == ["a"]


def test_torn_state_reads_as_nothing_installed_rather_than_raising() -> None:
    """Unreadable state has to degrade — a raise here would break every turn."""
    ensure_root()
    state_path().write_text("{ truncated", encoding="utf-8")
    assert load_installed() == {}


def test_a_state_row_naming_an_unsafe_id_is_dropped() -> None:
    """The file is on disk and could be hand-edited; ids become directory names."""
    ensure_root()
    state_path().write_text(
        '{"apps": [{"id": "../escape", "entry_point": "sh", "runtime": "python", '
        '"kind": "pip"}, {"id": "ok", "entry_point": "ok", "runtime": "python", '
        '"kind": "pip"}]}',
        encoding="utf-8",
    )
    assert list(load_installed()) == ["ok"]


def test_the_state_write_leaves_no_temporary_file_behind() -> None:
    record_install(_app("a"))
    assert not list(state_path().parent.glob("*.tmp"))


# ── per-account preference ────────────────────────────────────────────────


def test_an_app_is_enabled_until_the_account_says_otherwise() -> None:
    """Opt-out, so a newly installed app is usable without every user revisiting
    a settings page."""
    assert disabled_apps("u_ada") == set()


def test_disabling_then_enabling_round_trips() -> None:
    set_app_enabled("u_ada", "blender", False)
    assert disabled_apps("u_ada") == {"blender"}

    set_app_enabled("u_ada", "blender", True)
    assert disabled_apps("u_ada") == set()


def test_one_accounts_preference_does_not_touch_anothers() -> None:
    set_app_enabled("u_ada", "blender", False)
    assert disabled_apps("u_bob") == set()
