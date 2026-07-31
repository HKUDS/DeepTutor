from __future__ import annotations

import json
import socket
import threading

import pytest

from deeptutor.multi_user import byok_policy


def test_policy_environment_only_forces_byok_off(tmp_path, monkeypatch):
    path = tmp_path / "byok_policy.v1.json"
    monkeypatch.setattr(byok_policy, "policy_path", lambda: path)
    path.write_text(json.dumps({"enabled": False}), encoding="utf-8")

    monkeypatch.delenv("DEEPTUTOR_BYOK_ENABLED", raising=False)
    assert byok_policy.load_policy()["enabled"] is False

    monkeypatch.setenv("DEEPTUTOR_BYOK_ENABLED", "true")
    assert byok_policy.load_policy()["enabled"] is False
    monkeypatch.setenv("DEEPTUTOR_BYOK_ENABLED", "not-a-bool")
    assert byok_policy.load_policy()["enabled"] is False

    path.write_text(json.dumps({"enabled": True}), encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_BYOK_ENABLED", "false")
    assert byok_policy.load_policy()["enabled"] is False


def test_endpoint_dns_timeout_does_not_change_global_socket_timeout(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def stalled_getaddrinfo(*_args, **_kwargs):
        started.set()
        release.wait()
        return []

    monkeypatch.setattr(byok_policy.socket, "getaddrinfo", stalled_getaddrinfo)
    monkeypatch.setattr(byok_policy, "DNS_RESOLUTION_TIMEOUT_SECONDS", 0.01)
    policy = byok_policy.normalize_policy(
        {"services": {"llm": {"allow_custom_endpoints": True}}}
    )
    initial_timeout = socket.getdefaulttimeout()
    try:
        with pytest.raises(ValueError, match="DNS resolution timed out"):
            byok_policy.validate_endpoint(
                "https://slow.example/v1",
                service="llm",
                binding="openai",
                policy=policy,
            )
    finally:
        release.set()

    assert started.wait(0.1)
    assert socket.getdefaulttimeout() == initial_timeout
