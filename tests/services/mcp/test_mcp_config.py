"""MCP config: transport auto-detection, tool filtering, SSRF URL guard, wrapped names."""

from __future__ import annotations

import pytest

from deeptutor.services.mcp.config import MCPConfig, MCPServerConfig
from deeptutor.services.mcp.manager import wrapped_tool_name
from deeptutor.services.mcp.network import validate_mcp_url


def test_resolved_type_stdio() -> None:
    cfg = MCPServerConfig(command="npx", args=["server"])
    assert cfg.resolved_type() == "stdio"


def test_resolved_type_sse_vs_http() -> None:
    assert MCPServerConfig(url="https://x.com/sse").resolved_type() == "sse"
    assert MCPServerConfig(url="https://x.com/mcp").resolved_type() == "streamableHttp"


def test_resolved_type_explicit_wins() -> None:
    cfg = MCPServerConfig(type="streamableHttp", url="https://x.com/sse")
    assert cfg.resolved_type() == "streamableHttp"


def test_resolved_type_none_when_empty() -> None:
    assert MCPServerConfig().resolved_type() is None


def test_tool_allowed_wildcard() -> None:
    cfg = MCPServerConfig(command="x", enabled_tools=["*"])
    assert cfg.tool_allowed("anything", "mcp_s_anything")


def test_tool_allowed_explicit_raw_and_wrapped() -> None:
    cfg = MCPServerConfig(command="x", enabled_tools=["search", "mcp_s_create"])
    assert cfg.tool_allowed("search", "mcp_s_search")
    assert cfg.tool_allowed("create", "mcp_s_create")
    assert not cfg.tool_allowed("delete", "mcp_s_delete")


def test_invalid_server_name_rejected() -> None:
    with pytest.raises(ValueError):
        MCPConfig(servers={"bad name!": MCPServerConfig(command="x")})


def test_connection_signature_changes_with_config() -> None:
    a = MCPServerConfig(command="x", args=["1"])
    b = MCPServerConfig(command="x", args=["2"])
    assert a.connection_signature() != b.connection_signature()
    assert (
        a.connection_signature() == MCPServerConfig(command="x", args=["1"]).connection_signature()
    )


def test_server_config_strips_string_fields() -> None:
    cfg = MCPServerConfig(command="  npx  ", url="  https://example.com/mcp  ", cwd="  /tmp  ")
    assert cfg.command == "npx"
    assert cfg.url == "https://example.com/mcp"
    assert cfg.cwd == "/tmp"


def test_tool_timeout_bounds_are_enforced() -> None:
    with pytest.raises(ValueError):
        MCPServerConfig(command="x", tool_timeout=0)
    with pytest.raises(ValueError):
        MCPServerConfig(command="x", tool_timeout=601)


def test_wrapped_tool_name_sanitizes() -> None:
    assert wrapped_tool_name("gh", "search") == "mcp_gh_search"
    assert wrapped_tool_name("my server", "do.thing") == "mcp_my_server_do_thing"


def test_ssrf_blocks_metadata_address() -> None:
    ok, error = validate_mcp_url("http://169.254.169.254/latest/meta-data")
    assert not ok
    assert "169.254" in error or "link-local" in error.lower()


def test_ssrf_rejects_non_http_scheme() -> None:
    ok, _ = validate_mcp_url("file:///etc/passwd")
    assert not ok


def test_ssrf_allows_public_host() -> None:
    # loopback / LAN is allowed under the current trust posture; a public
    # DNS name should validate (network permitting). We assert the guard
    # does not reject on scheme/parse for a well-formed https URL.
    ok, error = validate_mcp_url("https://localhost/mcp")
    # localhost resolves to loopback which is allowed (not in blocklist)
    assert ok or "resolve" in error.lower()


def _resolve_to(monkeypatch: pytest.MonkeyPatch, *addresses: str) -> None:
    import socket

    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, 0),
            )
            for address in addresses
        ]

    monkeypatch.setattr("deeptutor.services.mcp.network.socket.getaddrinfo", fake_getaddrinfo)


def test_strict_blocks_fake_ip_answer_without_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPTUTOR_MCP_FAKE_IP_RANGES", raising=False)
    _resolve_to(monkeypatch, "fd27:712::c600:116b")
    ok, error = validate_mcp_url("https://gitmcp.io/docs", strict=True)
    assert not ok
    assert "fd27:712::c600:116b" in error


def test_strict_allows_hostname_in_declared_fake_ip_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_MCP_FAKE_IP_RANGES", "198.18.0.0/15, fd27:712::/32")
    _resolve_to(monkeypatch, "198.18.0.42", "fd27:712::c600:116b")
    assert validate_mcp_url("https://gitmcp.io/docs", strict=True) == (True, "")


def test_fake_ip_range_does_not_exempt_other_private_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPTUTOR_MCP_FAKE_IP_RANGES", "fd27:712::/32")
    _resolve_to(monkeypatch, "fd27:712::c600:116b", "10.0.0.5")
    ok, error = validate_mcp_url("https://gitmcp.io/docs", strict=True)
    assert not ok
    assert "10.0.0.5" in error


def test_fake_ip_range_does_not_exempt_ip_literals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_MCP_FAKE_IP_RANGES", "fd27:712::/32")
    _resolve_to(monkeypatch, "fd27:712::c600:116b")
    ok, _ = validate_mcp_url("https://[fd27:712::c600:116b]/mcp", strict=True)
    assert not ok


@pytest.mark.parametrize(
    ("declared", "address"),
    [
        ("127.0.0.0/8", "127.0.0.1"),
        ("::/0", "::1"),
        ("::/0", "::ffff:127.0.0.1"),
        ("169.254.0.0/16", "169.254.169.254"),
        ("fc00::/7", "fd00:ec2::254"),
    ],
)
def test_fake_ip_range_never_exempts_loopback_or_metadata(
    monkeypatch: pytest.MonkeyPatch, declared: str, address: str
) -> None:
    monkeypatch.setenv("DEEPTUTOR_MCP_FAKE_IP_RANGES", declared)
    _resolve_to(monkeypatch, address)
    ok, _ = validate_mcp_url("https://gitmcp.io/docs", strict=True)
    assert not ok


def test_invalid_fake_ip_entries_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPTUTOR_MCP_FAKE_IP_RANGES", "not-a-range, fd27:712::/32")
    _resolve_to(monkeypatch, "fd27:712::c600:116b")
    assert validate_mcp_url("https://gitmcp.io/docs", strict=True) == (True, "")
