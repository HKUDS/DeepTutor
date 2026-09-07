from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from deeptutor.services import github_copilot_auth as auth


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _Client:
    calls: list[tuple[str, str, dict]] = []
    poll_count = 0

    def __init__(self, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url: str, **kwargs):
        self.calls.append(("post", url, kwargs))
        if url.endswith("/device/code"):
            return _Response(
                {
                    "device_code": "device-code",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 1,
                    "expires_in": 30,
                }
            )
        type(self).poll_count += 1
        if type(self).poll_count == 1:
            return _Response({"error": "authorization_pending"})
        return _Response({"access_token": "github-token"})

    async def get(self, url: str, **kwargs):
        self.calls.append(("get", url, kwargs))
        return _Response({"login": "octocat"})


@pytest.mark.asyncio
async def test_device_login_persists_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    saved: list[object] = []
    storage = SimpleNamespace(load=lambda: None, save=saved.append)
    models = ModuleType("oauth_cli_kit.models")
    models.OAuthToken = lambda **kwargs: SimpleNamespace(**kwargs)

    _Client.calls = []
    _Client.poll_count = 0
    monkeypatch.setitem(sys.modules, "oauth_cli_kit.models", models)
    monkeypatch.setattr(auth.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(auth, "get_github_copilot_storage", lambda: storage)
    monkeypatch.setattr(auth.asyncio, "sleep", lambda _seconds: _immediate())
    opened: list[str] = []
    monkeypatch.setattr(auth.webbrowser, "open", opened.append)

    output: list[str] = []
    token = await auth.login_github_copilot(print_fn=output.append)

    assert token.access == "github-token"
    assert token.account_id == "octocat"
    assert saved == [token]
    assert opened == ["https://github.com/login/device"]
    assert output == ["Open: https://github.com/login/device", "Code: ABCD-1234"]
    assert _Client.poll_count == 2


async def _immediate() -> None:
    return None
