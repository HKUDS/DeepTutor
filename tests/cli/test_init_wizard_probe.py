from __future__ import annotations

from types import SimpleNamespace


class _FakeClient:
    captured: list[dict] = []

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url: str, *, headers: dict, json: dict):
        self.captured.append({"url": url, "headers": headers, "json": json})
        return SimpleNamespace(status_code=200, text="")


def test_probe_llm_uses_max_completion_tokens_for_gpt5(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    ok, _elapsed_ms, error = init_wizard.probe_llm(
        base_url="https://example.test/v1",
        api_key="sk-test",
        binding="openai",
        model="gpt-5-mini",
    )

    assert ok is True
    assert error == ""
    body = _FakeClient.captured[0]["json"]
    assert body["max_completion_tokens"] == 1
    assert "max_tokens" not in body


def test_probe_llm_keeps_max_tokens_for_legacy_chat_models(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    init_wizard.probe_llm(
        base_url="https://example.test/v1",
        api_key="sk-test",
        binding="openai",
        model="gpt-3.5-turbo",
    )

    body = _FakeClient.captured[0]["json"]
    assert body["max_tokens"] == 1
    assert "max_completion_tokens" not in body


def test_probe_llm_keeps_anthropic_native_max_tokens(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    init_wizard.probe_llm(
        base_url="https://api.anthropic.test/v1",
        api_key="sk-test",
        binding="anthropic",
        model="claude-sonnet-4",
    )

    body = _FakeClient.captured[0]["json"]
    assert body["max_tokens"] == 1
    assert "max_completion_tokens" not in body
