"""Partner channel URLs under Fake-IP proxies and the private-layer switch."""

from __future__ import annotations

import socket

import pytest

from deeptutor.partners.network import validate_url_target
from deeptutor.services import net_policy


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

    monkeypatch.setattr("deeptutor.partners.network.socket.getaddrinfo", fake)


def test_channel_media_behind_fake_ip_is_refused_by_default(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"cdn.example": "fd27:712::c600:116b"})

    ok, error = validate_url_target("https://cdn.example/a.png")

    assert ok is False
    assert "private/internal" in error


def test_declared_range_restores_the_download(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"cdn.example": "fd27:712::c600:116b"})
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fd27:712::/32")

    assert validate_url_target("https://cdn.example/a.png") == (True, "")


def test_loopback_host_stays_refused_with_a_declared_range(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "127.0.0.0/8")

    assert validate_url_target("http://127.0.0.1/a.png")[0] is False


def test_private_layer_switch_allows_lan_media_only(monkeypatch) -> None:
    _stub_resolver(
        monkeypatch,
        {"lan.example": "10.1.2.3", "meta.example": "169.254.169.254"},
    )
    monkeypatch.setenv(net_policy.PROTECTION_ENABLED_ENV, "0")

    assert validate_url_target("https://lan.example/a.png") == (True, "")
    assert validate_url_target("https://meta.example/a.png")[0] is False


def test_allow_loopback_still_works(monkeypatch) -> None:
    def fake(host, *args, **kwargs):  # noqa: ANN001
        assert host == "localhost"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("deeptutor.partners.network.socket.getaddrinfo", fake)

    assert validate_url_target("http://localhost/a.png", allow_loopback=True) == (True, "")
    assert validate_url_target("http://localhost/a.png")[0] is False
