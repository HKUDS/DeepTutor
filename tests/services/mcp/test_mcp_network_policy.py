"""MCP URL guard under Fake-IP proxies and the private-layer switch (#2789/#2889)."""

from __future__ import annotations

import socket

import pytest

from deeptutor.services import net_policy
from deeptutor.services.mcp.network import validate_mcp_url

FAKE_IP = "fd27:712::c600:116b"


@pytest.fixture(autouse=True)
def _isolated_policy(monkeypatch):
    for name in (
        net_policy.SYNTHETIC_RANGES_ENV,
        net_policy.PROTECTION_ENABLED_ENV,
        *net_policy.COMPATIBLE_ENV_NAMES,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(net_policy, "_settings", lambda: {})


def _stub_resolver(monkeypatch, answers: dict[str, str]) -> None:
    real = socket.getaddrinfo

    def fake(host, *args, **kwargs):  # noqa: ANN001 - mirrors the stdlib shape
        answer = answers.get(host)
        if answer is None:
            return real(host, *args, **kwargs)
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (answer, 0, 0, 0))]

    monkeypatch.setattr("deeptutor.services.mcp.network.socket.getaddrinfo", fake)


def test_fake_ip_answer_blocks_a_public_entry_by_default(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"gitmcp.io": FAKE_IP})

    ok, error = validate_mcp_url("https://gitmcp.io/docs", strict=True)

    assert ok is False
    assert "resolves to a disallowed address" in error
    assert FAKE_IP in error


def test_declared_range_makes_the_same_entry_installable(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"gitmcp.io": FAKE_IP})
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fd27:712::/32")

    assert validate_mcp_url("https://gitmcp.io/docs", strict=True) == (True, "")


def test_legacy_mcp_env_name_is_honoured(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"gitmcp.io": FAKE_IP})
    monkeypatch.setenv("DEEPTUTOR_MCP_FAKE_IP_RANGES", "fd27:712::/32")

    assert validate_mcp_url("https://gitmcp.io/docs", strict=True) == (True, "")


def test_ip_literal_url_gets_no_exemption(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fd27:712::/32")
    _stub_resolver(monkeypatch, {"fd27:712::1": "fd27:712::1"})

    ok, error = validate_mcp_url("https://[fd27:712::1]/mcp", strict=True)

    assert ok is False
    assert "disallowed address" in error


def test_metadata_answer_stays_blocked_with_a_declared_range(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"meta.example": "169.254.169.254"})
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "169.254.0.0/16")

    ok, error = validate_mcp_url("https://meta.example/mcp", strict=True)

    assert ok is False
    assert "disallowed address" in error


def test_one_private_answer_beside_a_synthetic_one_still_fails(monkeypatch) -> None:
    def fake(host, *args, **kwargs):  # noqa: ANN001
        assert host == "mixed.example"
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (FAKE_IP, 0, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0)),
        ]

    monkeypatch.setattr("deeptutor.services.mcp.network.socket.getaddrinfo", fake)
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fd27:712::/32")

    ok, error = validate_mcp_url("https://mixed.example/mcp", strict=True)

    assert ok is False
    assert "10.1.2.3" in error


def test_private_layer_switch_allows_a_lan_server_but_not_metadata(monkeypatch) -> None:
    _stub_resolver(
        monkeypatch,
        {"lan.example": "10.1.2.3", "meta.example": "169.254.169.254"},
    )
    monkeypatch.setenv(net_policy.PROTECTION_ENABLED_ENV, "0")

    assert validate_mcp_url("https://lan.example/mcp", strict=True) == (True, "")
    assert validate_mcp_url("https://meta.example/mcp", strict=True)[0] is False


def test_switch_does_not_relax_loopback(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"loop.example": "127.0.0.1"})
    monkeypatch.setenv(net_policy.PROTECTION_ENABLED_ENV, "0")

    assert validate_mcp_url("https://loop.example/mcp", strict=True)[0] is False


def test_permissive_posture_is_unchanged(monkeypatch) -> None:
    """Deployment-owned servers keep needing no declaration at all."""
    _stub_resolver(monkeypatch, {"lan.example": "192.168.1.9"})

    assert validate_mcp_url("https://lan.example/mcp", strict=False) == (True, "")


def test_permissive_posture_keeps_loopback_servers(monkeypatch) -> None:
    """A deployment's own server on localhost must stay reachable (#2789 scope).

    WeKnora and similar admin-configured integrations call this guard with the
    permissive posture; tightening it here would break LAN/loopback endpoints.
    """
    _stub_resolver(monkeypatch, {"localhost": "127.0.0.1"})

    assert validate_mcp_url("http://localhost:8080/mcp", strict=False) == (True, "")
