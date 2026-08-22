"""sanitize_invalid_ssl_env drops CA-bundle env vars that point nowhere.

Reproduces the chat crash where a conda env's SSL_CERT_FILE goes stale after
the env is cloned/moved without ca-certificates: httpx hands the path to
ssl.create_default_context, which raises FileNotFoundError mid client
``__init__`` and aborts the whole chat turn.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from deeptutor.services.llm import openai_http_client
from deeptutor.services.llm.openai_http_client import sanitize_invalid_ssl_env


@pytest.fixture(autouse=True)
def _reset_sanitizer_state(monkeypatch: pytest.MonkeyPatch) -> None:
    # The warning-dedup set is module-level and would leak between tests.
    monkeypatch.setattr(openai_http_client, "_sanitized_warned", set())
    for name, _kind in openai_http_client._SSL_CA_ENV_PATHS:
        monkeypatch.delenv(name, raising=False)


def test_stale_ssl_cert_file_is_popped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "/definitely/not/here/cacert.pem")
    removed = sanitize_invalid_ssl_env()
    assert "SSL_CERT_FILE" in removed
    assert "SSL_CERT_FILE" not in os.environ


def test_valid_ssl_cert_file_is_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    bundle = tmp_path / "cacert.pem"
    bundle.write_text("dummy")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    removed = sanitize_invalid_ssl_env()
    assert removed == []
    assert os.environ["SSL_CERT_FILE"] == str(bundle)


def test_stale_ssl_cert_dir_is_popped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_CERT_DIR", "/definitely/not/a/dir")
    removed = sanitize_invalid_ssl_env()
    assert "SSL_CERT_DIR" in removed


def test_valid_ssl_cert_dir_is_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    removed = sanitize_invalid_ssl_env()
    assert removed == []


def test_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "/missing/cacert.pem")
    assert sanitize_invalid_ssl_env() == ["SSL_CERT_FILE"]
    # Already popped on the first pass — the second finds nothing.
    assert sanitize_invalid_ssl_env() == []


def test_warning_deduped(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    missing_path = "/missing/private-user/cacert.pem"
    monkeypatch.setenv("SSL_CERT_FILE", missing_path)
    sanitize_invalid_ssl_env()
    monkeypatch.setenv("SSL_CERT_FILE", missing_path)
    sanitize_invalid_ssl_env()
    warns = [
        record
        for record in caplog.records
        if record.levelname == "WARNING" and record.name == openai_http_client.__name__
    ]
    assert len(warns) == 1
    assert missing_path not in caplog.text


def test_build_openai_client_survives_stale_ssl_cert_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chat client factory must not crash when SSL_CERT_FILE is stale."""
    from deeptutor.core.agentic.client import LLMClientConfig, build_openai_client

    monkeypatch.setenv("SSL_CERT_FILE", "/definitely/not/here/cacert.pem")
    config = LLMClientConfig(
        binding="custom",
        model="m",
        api_key="sk-test",
        base_url="https://example.test/v1",
    )
    client = build_openai_client(config)  # raised FileNotFoundError before the fix
    try:
        # The underlying httpx transport initialised successfully.
        assert getattr(client._client, "_transport", None) is not None
    finally:
        asyncio.run(client.close())
