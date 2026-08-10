"""A user's own MCP servers: where they live, and what is refused.

Two invariants carry the whole self-service feature. The file must sit outside
every tree the exec sandbox mounts (otherwise another account's shell can edit
which credentials this account's server injects), and a user must not be able to
ask for a ``stdio`` server (a command run on the host as the app user).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.mcp.config import MCPServerConfig
from deeptutor.services.mcp.user_config import (
    MAX_SERVERS_PER_OWNER,
    UserMcpError,
    assert_name_available,
    delete_user_server,
    load_user_mcp_config,
    save_user_server,
    user_mcp_path,
)


@pytest.fixture
def system_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from deeptutor.multi_user import paths

    root = (tmp_path / "data" / "system").resolve()
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", (tmp_path / "data").resolve())
    monkeypatch.setattr(paths, "USERS_ROOT", (tmp_path / "data" / "users").resolve())
    return root


@pytest.fixture(autouse=True)
def _offline_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve test hostnames without touching the network.

    Only the lookup is stubbed — the address policy itself still runs, so a URL
    that must be blocked still is (``127.0.0.1`` resolves to loopback here).
    """
    import socket

    def _getaddrinfo(host: str, *args: object, **kwargs: object) -> list[tuple]:
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        addr = "127.0.0.1" if loopback else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))]

    monkeypatch.setattr("deeptutor.services.mcp.network.socket.getaddrinfo", _getaddrinfo)


def _remote(url: str = "https://mcp.example.com/mcp") -> MCPServerConfig:
    return MCPServerConfig(url=url)


def test_config_lives_outside_every_sandbox_mounted_tree(system_root: Path) -> None:
    path = user_mcp_path("u_ada")
    assert "system" in path.parts
    # docker-compose mounts ./data/user/workspace and ./data/users into the
    # runner; data/system is mounted for nobody.
    assert "users" not in path.parts
    assert path.parent.name == "user-mcp"


def test_stdio_is_refused_on_write(system_root: Path) -> None:
    with pytest.raises(UserMcpError) as excinfo:
        save_user_server("u_ada", "local", MCPServerConfig(command="/bin/sh"))
    assert excinfo.value.code == "mcp.stdio_not_allowed"


def test_stdio_in_a_hand_edited_file_is_dropped_and_reported(system_root: Path) -> None:
    """A refusal at the API is not enough: the file is also editable by hand."""
    path = user_mcp_path("u_ada")
    path.write_text(
        '{"servers": {"evil": {"command": "/bin/sh"}, "ok": {"url": "https://a.example/mcp"}}}',
        encoding="utf-8",
    )

    config, rejected = load_user_mcp_config("u_ada")
    assert set(config.servers) == {"ok"}
    assert [row.name for row in rejected] == ["evil"]


def test_reserved_tool_name_prefixes_are_refused(system_root: Path) -> None:
    """Tool names are namespaced ``mcp_<server>_<tool>``.

    A server called ``mcp_x`` could forge a name in the namespace the model
    reads, so the prefix is refused rather than sanitised.
    """
    for name in ("mcp_x", "cli_gimp"):
        with pytest.raises(UserMcpError) as excinfo:
            save_user_server("u_ada", name, _remote())
        assert excinfo.value.code == "mcp.name_reserved"


def test_a_url_pointing_back_at_the_deployment_is_refused(system_root: Path) -> None:
    """The request would be made by the app process, which holds every key."""
    with pytest.raises(UserMcpError) as excinfo:
        save_user_server("u_ada", "inward", _remote("http://127.0.0.1:8090/mcp"))
    assert excinfo.value.code == "mcp.blocked_url"


def test_saving_one_server_preserves_the_others(system_root: Path) -> None:
    save_user_server("u_ada", "first", _remote("https://a.example/mcp"))
    save_user_server("u_ada", "second", _remote("https://b.example/mcp"))

    config, _ = load_user_mcp_config("u_ada")
    assert set(config.servers) == {"first", "second"}


def test_fields_the_editor_does_not_model_survive_a_save(system_root: Path) -> None:
    """A whole-map write is how a hand-written tool blocklist gets wiped."""
    save_user_server(
        "u_ada",
        "kept",
        MCPServerConfig(url="https://a.example/mcp", disabled_tools=["noisy_tool"]),
    )
    save_user_server("u_ada", "other", _remote("https://b.example/mcp"))

    config, _ = load_user_mcp_config("u_ada")
    assert config.servers["kept"].disabled_tools == ["noisy_tool"]


def test_owners_are_isolated_from_each_other(system_root: Path) -> None:
    save_user_server("u_ada", "mine", _remote("https://a.example/mcp"))
    config, _ = load_user_mcp_config("u_bob")
    assert config.servers == {}


def test_two_owners_may_use_the_same_server_name(system_root: Path) -> None:
    """Normal, and must stay possible: names only have to be unique per owner."""
    save_user_server("u_ada", "notion", _remote("https://a.example/mcp"))
    save_user_server("u_bob", "notion", _remote("https://b.example/mcp"))

    assert load_user_mcp_config("u_ada")[0].servers["notion"].url == "https://a.example/mcp"
    assert load_user_mcp_config("u_bob")[0].servers["notion"].url == "https://b.example/mcp"


def test_a_name_colliding_with_a_deployment_server_is_refused() -> None:
    with pytest.raises(UserMcpError) as excinfo:
        assert_name_available("github", shared_names={"github"})
    assert excinfo.value.code == "mcp.name_reserved"


def test_the_per_owner_limit_is_enforced(system_root: Path) -> None:
    for index in range(MAX_SERVERS_PER_OWNER):
        save_user_server("u_ada", f"s{index}", _remote(f"https://s{index}.example/mcp"))
    with pytest.raises(UserMcpError) as excinfo:
        save_user_server("u_ada", "one-too-many", _remote("https://x.example/mcp"))
    assert excinfo.value.code == "mcp.too_many_servers"
    # Replacing an existing one is still allowed at the limit.
    save_user_server("u_ada", "s0", _remote("https://changed.example/mcp"))


def test_delete_removes_only_that_server(system_root: Path) -> None:
    save_user_server("u_ada", "first", _remote("https://a.example/mcp"))
    save_user_server("u_ada", "second", _remote("https://b.example/mcp"))

    delete_user_server("u_ada", "first")

    config, _ = load_user_mcp_config("u_ada")
    assert set(config.servers) == {"second"}


def test_an_unreadable_file_reads_as_empty_rather_than_crashing(system_root: Path) -> None:
    user_mcp_path("u_ada").write_text("{not json", encoding="utf-8")
    config, rejected = load_user_mcp_config("u_ada")
    assert config.servers == {}
    assert rejected == []
