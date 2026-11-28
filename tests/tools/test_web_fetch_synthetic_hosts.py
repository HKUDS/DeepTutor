"""web_fetch's SSRF gate under Fake-IP proxies and the private-layer switch."""

from __future__ import annotations

import socket

import pytest

from deeptutor.services import net_policy
from deeptutor.tools.web_fetch import _is_disallowed_host


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

    monkeypatch.setattr("deeptutor.tools.web_fetch.socket.getaddrinfo", fake)


def test_public_page_behind_clash_fake_ip_is_refused_by_default(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"www.mof.gov.cn": "198.18.0.20"})

    assert _is_disallowed_host("www.mof.gov.cn") is True


def test_declared_range_restores_the_fetch(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"www.mof.gov.cn": "198.18.0.20"})
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "198.18.0.0/15")

    assert _is_disallowed_host("www.mof.gov.cn") is False


def test_ip_literal_gets_no_exemption(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "198.18.0.0/15")

    assert _is_disallowed_host("198.18.0.20") is True


def test_loopback_literal_stays_refused_even_with_a_declared_range(monkeypatch) -> None:
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "127.0.0.0/8")

    assert _is_disallowed_host("127.0.0.1") is True
    assert _is_disallowed_host("localhost") is True


def test_metadata_answer_stays_refused_with_a_declared_range(monkeypatch) -> None:
    _stub_resolver(monkeypatch, {"meta.example": "169.254.169.254"})
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "169.254.0.0/16")

    assert _is_disallowed_host("meta.example") is True


def test_mixed_answers_keep_the_gate_closed(monkeypatch) -> None:
    def fake(host, *args, **kwargs):  # noqa: ANN001
        assert host == "mixed.example"
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fd27:712::1", 0, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0)),
        ]

    monkeypatch.setattr("deeptutor.tools.web_fetch.socket.getaddrinfo", fake)
    monkeypatch.setenv(net_policy.SYNTHETIC_RANGES_ENV, "fd27:712::/32")

    assert _is_disallowed_host("mixed.example") is True


def test_private_layer_switch_allows_intranet_pages_only(monkeypatch) -> None:
    _stub_resolver(
        monkeypatch,
        {"intranet.example": "10.1.2.3", "meta.example": "169.254.169.254"},
    )
    monkeypatch.setenv(net_policy.PROTECTION_ENABLED_ENV, "0")

    assert _is_disallowed_host("intranet.example") is False
    assert _is_disallowed_host("meta.example") is True
    assert _is_disallowed_host("localhost") is True
