from __future__ import annotations

import os
import stat
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

    _Client.calls = []
    _Client.poll_count = 0
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


def test_storage_is_private_and_isolated_by_owner_and_home(tmp_path, monkeypatch):
    from deeptutor.multi_user.models import CurrentUser, UserScope
    from deeptutor.multi_user.paths import user_context
    from deeptutor.services.github_copilot_storage import GitHubToken

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home-one"))
    admin_store = auth.get_github_copilot_storage()
    admin_token = GitHubToken("admin-token", 2_000_000_000_000, "admin")
    admin_store.save(admin_token)
    assert admin_store.load() == admin_token
    assert "data\\system\\user-secrets" in str(admin_store.root).replace("/", "\\")
    user = CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "alice"),
    )
    with user_context(user):
        alice_store = auth.get_github_copilot_storage()
        assert alice_store.load() is None
        alice_store.save(GitHubToken("alice-token", 2_000_000_000_000, "alice"))
        assert alice_store.load().access == "alice-token"
    assert admin_store.load() == admin_token
    assert admin_store.credentials_path != alice_store.credentials_path
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home-two"))
    other_home = auth.get_github_copilot_storage()
    assert other_home.credentials_path != admin_store.credentials_path
    assert other_home.load() is None
    if os.name != "nt":
        assert stat.S_IMODE(admin_store.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(admin_store.credentials_path.stat().st_mode) == 0o600


def test_storage_never_reads_external_tokens_or_sets_environment(tmp_path, monkeypatch):
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    external = ModuleType("oauth_cli_kit.storage")

    def forbidden(**kwargs):
        pytest.fail("External OS-user token storage must not be instantiated")

    external.FileTokenStorage = forbidden
    monkeypatch.setitem(sys.modules, "oauth_cli_kit.storage", external)
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    before = dict(os.environ)
    storage = auth.get_github_copilot_storage()
    assert isinstance(storage, GitHubCopilotStorage)
    assert storage.load() is None
    assert dict(os.environ) == before


def test_storage_rejects_invalid_credentials_and_unsafe_paths(tmp_path, monkeypatch):
    from deeptutor.services.codex_auth import storage as storage_helpers
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    store.root.mkdir(parents=True)
    store.credentials_path.write_text('{"access": "invalid"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="credentials are invalid"):
        store.load()
    monkeypatch.setattr(
        storage_helpers, "_is_reparse_point", lambda path: path == store.root.parent
    )
    with pytest.raises(RuntimeError, match="unsafe path"):
        store.load()


@pytest.mark.asyncio
async def test_model_discovery_preserves_endpoints_and_filters_unusable_rows(monkeypatch):
    rows = [
        {"id": "claude", "supported_endpoints": ["/responses"]},
        {"id": "gpt-5-chat", "supported_endpoints": ["/chat/completions"]},
        {"id": "both", "supported_endpoints": ["/responses", "/chat/completions"]},
        {"id": "legacy"},
        {"id": "empty", "supported_endpoints": []},
        {"id": "other", "supported_endpoints": ["/messages"]},
        {"id": "hidden", "model_picker_enabled": False},
        {"id": "disabled", "policy": {"state": "disabled"}},
        {"id": "bad", "supported_endpoints": "responses"},
    ]

    class ModelsClient(_Client):
        async def get(self, url, **kwargs):
            assert url == "https://tenant.example/models"
            return _Response({"data": rows})

    access = auth.CopilotAccess("short-token", 2_000_000_000, "https://tenant.example")
    monkeypatch.setattr(auth.httpx, "AsyncClient", ModelsClient)
    discovered = await auth.fetch_github_copilot_models(access)
    assert discovered == [
        auth.CopilotModel("claude", ("/responses",)),
        auth.CopilotModel("gpt-5-chat", ("/chat/completions",)),
        auth.CopilotModel("both", ("/responses", "/chat/completions")),
        auth.CopilotModel("legacy", None),
    ]

    async def exchange():
        return access

    monkeypatch.setattr(auth, "exchange_copilot_token", exchange)
    assert await auth.list_github_copilot_models() == [
        f"github-copilot/{row.id}" for row in discovered
    ]


@pytest.mark.asyncio
async def test_exchange_preserves_account_endpoint_and_uses_supplied_owner_token(monkeypatch):
    class ExchangeClient(_Client):
        async def get(self, url, **kwargs):
            assert kwargs["headers"]["Authorization"] == "token owner-github-token"
            return _Response(
                {
                    "token": "short-lived-token",
                    "expires_at": 2_000_000_000,
                    "endpoints": {"api": "https://enterprise.example/copilot"},
                }
            )

    monkeypatch.setattr(auth.httpx, "AsyncClient", ExchangeClient)
    monkeypatch.setattr(auth, "load_github_token", lambda: pytest.fail("must use captured owner"))
    assert await auth.exchange_copilot_token("owner-github-token") == auth.CopilotAccess(
        "short-lived-token", 2_000_000_000, "https://enterprise.example/copilot"
    )
