from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from deeptutor_cli.provider_cmd import _login_codebuddy


class FakeAuthFlow:
    auth_url = "https://codebuddy.example/login"

    def __await__(self):
        async def _wait():
            return SimpleNamespace(
                userinfo=SimpleNamespace(
                    user_id="u1",
                    user_name="karsa",
                    user_nickname="Karsa",
                )
            )

        return _wait().__await__()


@pytest.mark.asyncio
async def test_codebuddy_login_starts_auth_flow_when_not_logged_in(monkeypatch, capsys) -> None:
    opened: list[str] = []

    async def fake_query(**_kwargs):
        if False:
            yield None
        raise RuntimeError("Authentication required. Please use /login command")

    async def fake_authenticate(**kwargs):
        assert kwargs["timeout"] == 300.0
        return FakeAuthFlow()

    monkeypatch.setitem(
        sys.modules,
        "codebuddy_agent_sdk",
        SimpleNamespace(query=fake_query, authenticate=fake_authenticate),
    )
    monkeypatch.setattr("deeptutor_cli.provider_cmd.webbrowser.open", opened.append)

    await _login_codebuddy()

    output = capsys.readouterr().out
    assert "Starting CodeBuddy login flow" in output
    assert "https://codebuddy.example/login" in output
    assert "CodeBuddy auth validation succeeded for Karsa." in output
    assert opened == ["https://codebuddy.example/login"]
