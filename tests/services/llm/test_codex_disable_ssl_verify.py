"""DISABLE_SSL_VERIFY coverage for the OpenAI Codex Responses provider.

The codex provider was previously hardcoded to ``verify=True`` on the first
attempt, with an auto-retry on ``CERTIFICATE_VERIFY_FAILED``. The flag now
short-circuits the first attempt while preserving the retry-on-cert-failure
fallback.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm import openai_http_client
from deeptutor.services.llm.provider_core import openai_codex_provider


@pytest.fixture(autouse=True)
def _clean_ssl_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISABLE_SSL_VERIFY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setattr(openai_http_client, "_warning_logged", False)


def _stub_token_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Token:
        access = "test-token"
        account_id = "test-account"

    async def _fake_load_token(self: Any) -> _Token:
        return _Token()

    monkeypatch.setattr(openai_codex_provider.OpenAICodexProvider, "_load_token", _fake_load_token)


@pytest.mark.asyncio
async def test_codex_first_attempt_verify_true_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_token_loader(monkeypatch)
    captured: list[dict[str, Any]] = []

    async def fake_request(*args: Any, **kwargs: Any) -> tuple[str, list[Any], str]:
        captured.append(kwargs)
        return ("ok", [], "stop")

    monkeypatch.setattr(openai_codex_provider, "_request_codex", fake_request)

    provider = openai_codex_provider.OpenAICodexProvider()
    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert captured[0]["verify"] is True


@pytest.mark.asyncio
async def test_codex_first_attempt_verify_false_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DISABLE_SSL_VERIFY", "1")
    _stub_token_loader(monkeypatch)
    captured: list[dict[str, Any]] = []

    async def fake_request(*args: Any, **kwargs: Any) -> tuple[str, list[Any], str]:
        captured.append(kwargs)
        return ("ok", [], "stop")

    monkeypatch.setattr(openai_codex_provider, "_request_codex", fake_request)

    provider = openai_codex_provider.OpenAICodexProvider()
    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert captured[0]["verify"] is False


@pytest.mark.asyncio
async def test_codex_retry_on_cert_failure_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CERTIFICATE_VERIFY_FAILED retry fallback is preserved."""
    _stub_token_loader(monkeypatch)
    captured: list[dict[str, Any]] = []
    call_count = {"n": 0}

    async def fake_request(*args: Any, **kwargs: Any) -> tuple[str, list[Any], str]:
        captured.append(kwargs)
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("[SSL: CERTIFICATE_VERIFY_FAILED] cert chain")
        return ("recovered", [], "stop")

    monkeypatch.setattr(openai_codex_provider, "_request_codex", fake_request)

    provider = openai_codex_provider.OpenAICodexProvider()
    result = await provider.chat(messages=[{"role": "user", "content": "hi"}])

    assert result.content == "recovered"
    assert len(captured) == 2
    assert captured[0]["verify"] is True
    assert captured[1]["verify"] is False
