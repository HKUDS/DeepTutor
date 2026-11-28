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


def test_storage_delete_removes_credentials_and_handles_missing(tmp_path) -> None:
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage, GitHubToken

    store = GitHubCopilotStorage(tmp_path)
    assert store.delete() is False
    store.save(GitHubToken("tok", 2_000_000_000_000, "octocat"))
    assert store.load() is not None
    assert store.delete() is True
    assert store.load() is None
    assert store.delete() is False


@pytest.mark.asyncio
async def test_web_auth_service_device_flow_lifecycle(tmp_path, monkeypatch) -> None:
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    service = auth.GitHubCopilotAuthService(store)
    evictions: list[str] = []
    monkeypatch.setattr(auth, "_evict_owner_providers", evictions.append)

    _Client.calls = []
    _Client.poll_count = 0
    monkeypatch.setattr(auth.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(auth.asyncio, "sleep", lambda _seconds: _immediate())

    initial = await service.status()
    assert initial["connection"] == "disconnected"
    assert initial["user_code"] is None

    started = await service.start_login()
    assert started["connection"] == "authorizing"
    assert started["operation_state"] == "waiting"
    assert started["user_code"] == "ABCD-1234"
    assert started["verification_uri"] == "https://github.com/login/device"
    assert "device-code" not in str(started)

    # Idempotent while waiting: does not request a second device code.
    again = await service.start_login()
    assert again["user_code"] == "ABCD-1234"
    device_code_posts = [c for c in _Client.calls if c[0] == "post" and c[1].endswith("/device/code")]
    assert len(device_code_posts) == 1

    # Wait for background polling task to finish.
    assert service._active_task is not None
    await service._active_task

    done = await service.status()
    assert done["connection"] == "connected"
    assert done["account_id"] == "octocat"
    assert done["user_code"] is None
    assert done["verification_uri"] is None
    assert store.load() is not None
    assert store.load().access == "github-token"
    assert evictions == [str(store.credentials_path)]

    logged_out = await service.logout()
    assert logged_out["connection"] == "disconnected"
    assert logged_out["account_id"] is None
    assert store.load() is None
    assert evictions == [str(store.credentials_path), str(store.credentials_path)]


@pytest.mark.asyncio
async def test_web_auth_service_cancel_prevents_stale_token_write(tmp_path, monkeypatch) -> None:
    import asyncio

    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    service = auth.GitHubCopilotAuthService(store)
    gate = asyncio.Event()

    class _SlowClient(_Client):
        async def post(self, url: str, **kwargs):
            if url.endswith("/device/code"):
                return _Response(
                    {
                        "device_code": "secret-device",
                        "user_code": "WXYZ-9999",
                        "verification_uri": "https://github.com/login/device",
                        "interval": 1,
                        "expires_in": 30,
                    }
                )
            await gate.wait()
            return _Response({"access_token": "stale-token"})

    monkeypatch.setattr(auth.httpx, "AsyncClient", _SlowClient)
    monkeypatch.setattr(auth.asyncio, "sleep", lambda _seconds: _immediate())

    started = await service.start_login()
    assert started["connection"] == "authorizing"
    cancelled = await service.cancel_login()
    gate.set()
    await asyncio.sleep(0)

    assert cancelled["connection"] == "disconnected"
    assert cancelled["operation_state"] == "cancelled"
    assert store.load() is None


@pytest.mark.asyncio
async def test_cross_worker_logout_and_cli_login_supersede_inflight_poll(
    tmp_path, monkeypatch
) -> None:
    import asyncio

    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage, GitHubToken

    store_a = GitHubCopilotStorage(tmp_path)
    store_b = GitHubCopilotStorage(tmp_path)
    worker_a = auth.GitHubCopilotAuthService(store_a)
    worker_b = auth.GitHubCopilotAuthService(store_b)
    gate = asyncio.Event()

    class _CrossWorkerClient(_Client):
        async def post(self, url: str, **kwargs):
            if url.endswith("/device/code"):
                return _Response(
                    {
                        "device_code": "worker-a-device",
                        "user_code": "WORK-1111",
                        "verification_uri": "https://github.com/login/device",
                        "interval": 1,
                        "expires_in": 30,
                    }
                )
            await gate.wait()
            return _Response({"access_token": "stale-worker-a-token"})

    monkeypatch.setattr(auth.httpx, "AsyncClient", _CrossWorkerClient)
    monkeypatch.setattr(auth.asyncio, "sleep", lambda _seconds: _immediate())

    started = await worker_a.start_login()
    assert started["user_code"] == "WORK-1111"
    # Worker B sees the shared waiting prompt across processes.
    seen_by_b = await worker_b.status()
    assert seen_by_b["connection"] == "authorizing"
    assert seen_by_b["user_code"] == "WORK-1111"

    # Worker B logs out even though no credentials file existed yet.
    await worker_b.logout()
    poll_task = worker_a._active_task
    gate.set()
    if poll_task is not None:
        await poll_task

    # Worker A's stale token MUST NOT be written to disk.
    assert store_a.load() is None
    assert (await worker_b.status())["connection"] == "disconnected"

    # Also verify CLI login during an active Web poll wins and cannot be overwritten.
    gate.clear()
    await worker_a.start_login()
    poll_task = worker_a._active_task
    store_b.save(GitHubToken("cli-fresh-token", 2_000_000_000_000, "cli-user"))
    gate.set()
    if poll_task is not None:
        await poll_task
    assert store_a.load().access == "cli-fresh-token"
    assert store_a.load().account_id == "cli-user"


def test_sequential_event_loops_never_leave_orphaned_waiting_state(tmp_path, monkeypatch) -> None:
    import asyncio

    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    service = auth.GitHubCopilotAuthService(store)

    class _HangingClient(_Client):
        async def post(self, url: str, **kwargs):
            if url.endswith("/device/code"):
                return _Response(
                    {
                        "device_code": "loop-device",
                        "user_code": "LOOP-2222",
                        "verification_uri": "https://github.com/login/device",
                        "interval": 60,
                        "expires_in": 300,
                    }
                )
            await asyncio.Event().wait()

    monkeypatch.setattr(auth.httpx, "AsyncClient", _HangingClient)

    async def start_in_loop_one():
        started = await service.start_login()
        assert started["operation_state"] == "waiting"

    asyncio.run(start_in_loop_one())

    # Loop 1 is now closed; loop 2 must detect the orphaned task and never return waiting.
    status_in_loop_two = asyncio.run(service.status())
    assert status_in_loop_two["operation_state"] != "waiting"
    assert status_in_loop_two["connection"] == "error"


@pytest.mark.asyncio
async def test_symlink_owner_root_cannot_bypass_service_cache(tmp_path, monkeypatch) -> None:
    if os.name == "nt":
        pytest.skip("POSIX symlink test")
    from deeptutor.multi_user.context import user_from_token_payload
    from deeptutor.multi_user.paths import user_context
    from deeptutor.services.github_copilot_storage import GitHubToken

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    admin_a = user_from_token_payload(SimpleNamespace(user_id="u_sym_a", username="a", role="admin"))
    admin_b = user_from_token_payload(SimpleNamespace(user_id="u_sym_b", username="b", role="admin"))

    with user_context(admin_a):
        store_a = auth.get_github_copilot_storage()
        store_a.save(GitHubToken("secret-a", 2_000_000_000_000, "owner-a"))
        assert (await auth.get_github_copilot_auth_service().status())["account_id"] == "owner-a"

    # Point admin_b's owner_root symlink at admin_a's secrets dir.
    secrets_root = tmp_path / "home" / "data" / "system" / "user-secrets"
    (secrets_root / "u_sym_b").symlink_to(secrets_root / "u_sym_a")

    with user_context(admin_b):
        status_b = await auth.get_github_copilot_auth_service().status()
        assert status_b["connection"] == "error"
        assert status_b["error_code"] == "credentials_invalid"
        assert status_b["account_id"] is None


@pytest.mark.asyncio
async def test_untrusted_verification_urls_and_redirects_are_blocked(
    tmp_path, monkeypatch
) -> None:
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    redirect_flags: list[bool] = []

    class _UntrustedClient(_Client):
        uri = "https://evil.example/phish"
        uri_complete = ""

        def __init__(self, **kwargs) -> None:
            redirect_flags.append(bool(kwargs.get("follow_redirects", True)))

        async def post(self, url: str, **kwargs):
            return _Response(
                {
                    "device_code": "dev",
                    "user_code": "EVIL-0000",
                    "verification_uri": self.uri,
                    "verification_uri_complete": self.uri_complete,
                    "interval": 1,
                    "expires_in": 30,
                }
            )

    monkeypatch.setattr(auth.httpx, "AsyncClient", _UntrustedClient)

    for uri, complete in [
        ("https://evil.example/phish", ""),
        ("https://user@github.com/login/device", ""),
        ("https://github.com/login/device", "https://evil.example/phish"),
    ]:
        _UntrustedClient.uri = uri
        _UntrustedClient.uri_complete = complete
        svc = auth.GitHubCopilotAuthService(GitHubCopilotStorage(tmp_path / f"case-{len(redirect_flags)}"))
        res = await svc.start_login()
        assert res["connection"] == "error"
        assert res["error_code"] == "auth_failed"
        assert res["verification_uri"] is None

    assert redirect_flags and all(flag is False for flag in redirect_flags)


@pytest.mark.asyncio
async def test_storage_oserror_maps_to_fixed_error_and_never_leaves_waiting(
    tmp_path, monkeypatch
) -> None:
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    service = auth.GitHubCopilotAuthService(store)

    def _boom(*_args, **_kwargs):
        raise OSError("/private/secret/disk-path: permission denied")

    monkeypatch.setattr(store, "read_snapshot", _boom)
    st = await service.status()
    assert st["connection"] == "error"
    assert st["error_code"] == "credentials_invalid"
    assert "/private/secret/disk-path" not in str(st)


@pytest.mark.asyncio
async def test_expired_stored_token_reports_error_not_connected(tmp_path) -> None:
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage, GitHubToken

    store = GitHubCopilotStorage(tmp_path)
    store.save(GitHubToken("old-tok", 1_000, "octocat"))
    status = await auth.GitHubCopilotAuthService(store).status()
    assert status["connection"] == "error"
    assert status["error_code"] == "expired"
    assert status["account_id"] == "octocat"


@pytest.mark.asyncio
async def test_copilot_provider_checks_credential_version_and_agentic_key_is_owner_scoped(
    tmp_path, monkeypatch
) -> None:
    import asyncio

    from deeptutor.multi_user.context import user_from_token_payload
    from deeptutor.multi_user.paths import user_context
    from deeptutor.runtime.agentic.client import LLMClientConfig, _client_cache_key
    from deeptutor.services.github_copilot_storage import GitHubToken
    from deeptutor.services.llm.provider_core.github_copilot_provider import GitHubCopilotProvider

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    admin_a = user_from_token_payload(SimpleNamespace(user_id="u_pool_a", username="a", role="admin"))
    admin_b = user_from_token_payload(SimpleNamespace(user_id="u_pool_b", username="b", role="admin"))
    loop = asyncio.get_running_loop()
    cfg = LLMClientConfig(
        api_key="",
        base_url="",
        binding="github_copilot",
        model="github-copilot/gpt-4.1",
    )

    with user_context(admin_a):
        key_a = _client_cache_key(cfg, loop, False)
    with user_context(admin_b):
        key_b = _client_cache_key(cfg, loop, False)
    assert key_a != key_b

    # Cached short-lived token must NOT be reused after logout bumps credential_version.
    store = auth.get_github_copilot_storage()
    store.save(GitHubToken("tok-1", 2_000_000_000_000, "octocat"))
    provider = GitHubCopilotProvider(configure_env=False)
    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.github_copilot_provider.exchange_copilot_token",
        lambda _gh: _async_return(auth.CopilotAccess("short-1", 9_999_999_999.0, "https://api.githubcopilot.com")),
    )
    monkeypatch.setattr(
        "deeptutor.services.llm.provider_core.github_copilot_provider.fetch_github_copilot_models",
        lambda _acc: _async_return([auth.CopilotModel("gpt-4.1", None)]),
    )
    await provider._ensure_api_key()
    assert provider.api_key == "short-1"

    # Simulate external/other-worker logout.
    store.clear_credentials()
    with pytest.raises(RuntimeError, match="not logged in"):
        await provider._ensure_api_key()


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_web_auth_service_handles_corrupt_credentials_gracefully(tmp_path) -> None:
    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    store.root.mkdir(parents=True)
    store.credentials_path.write_text('{"bad": true}', encoding="utf-8")
    service = auth.GitHubCopilotAuthService(store)

    status = await service.status()
    assert status["connection"] == "error"
    assert status["error_code"] == "credentials_invalid"

    # Logout clears the corrupt file and returns cleanly to disconnected.
    cleared = await service.logout()
    assert cleared["connection"] == "disconnected"
    assert cleared["error_code"] is None
    assert not store.credentials_path.exists()


@pytest.mark.asyncio
async def test_cli_login_superseded_by_web_logout_does_not_overwrite(tmp_path, monkeypatch) -> None:
    import asyncio

    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    web_service = auth.GitHubCopilotAuthService(store)
    polling = asyncio.Event()
    gate = asyncio.Event()

    class _CliClient(_Client):
        async def post(self, url: str, **kwargs):
            if url.endswith("/device/code"):
                return _Response(
                    {
                        "device_code": "cli-dev",
                        "user_code": "CLI-1234",
                        "verification_uri": "https://github.com/login/device",
                        "interval": 1,
                        "expires_in": 30,
                    }
                )
            polling.set()
            await gate.wait()
            return _Response({"access_token": "stale-cli-token"})

    monkeypatch.setattr(auth.httpx, "AsyncClient", _CliClient)
    monkeypatch.setattr(auth, "get_github_copilot_storage", lambda: store)
    monkeypatch.setattr(auth.asyncio, "sleep", lambda _seconds: _immediate())
    monkeypatch.setattr(auth.webbrowser, "open", lambda _url: True)

    cli_task = asyncio.create_task(auth.login_github_copilot(print_fn=lambda _msg: None))
    await polling.wait()
    # Web logout happens while CLI is waiting on GitHub authorization.
    await web_service.logout()
    gate.set()

    with pytest.raises(RuntimeError, match="cancelled or superseded"):
        await cli_task
    assert store.load() is None


def test_credential_version_embedded_in_credentials_and_corrupt_state_raises(tmp_path) -> None:
    import json

    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage, GitHubToken

    store = GitHubCopilotStorage(tmp_path)
    store.save(GitHubToken("tok-1", 2_000_000_000_000, "u1"))
    _, ver1 = store.load_with_version()
    assert ver1 == 1

    # Simulate a crash where credentials.v1.json got version 2 while auth-state.v1.json stayed at 1.
    stale_state = store.state_path.read_text(encoding="utf-8")
    store.save(GitHubToken("tok-2", 2_000_000_000_000, "u2"))
    store.state_path.write_text(stale_state, encoding="utf-8")
    token, ver2 = store.load_with_version()
    assert token is not None and token.account_id == "u2"
    assert ver2 == 2

    # Corrupt auth-state.v1.json must raise rather than silently returning version 0.
    store.state_path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(RuntimeError, match="auth state is invalid"):
        store.load_with_version()
    # Confirm raw credentials JSON carries credential_version.
    raw = json.loads(store.credentials_path.read_text(encoding="utf-8"))
    assert raw["credential_version"] == 2


@pytest.mark.asyncio
async def test_cancelled_start_login_during_publish_cleans_up_waiting_state(
    tmp_path, monkeypatch
) -> None:
    import asyncio
    import threading

    from deeptutor.services.github_copilot_storage import GitHubCopilotStorage

    store = GitHubCopilotStorage(tmp_path)
    service = auth.GitHubCopilotAuthService(store)
    entered = threading.Event()
    release = threading.Event()
    real_publish = store.publish_device_prompt

    def slow_publish(**kwargs):
        entered.set()
        release.wait(timeout=2.0)
        return real_publish(**kwargs)

    monkeypatch.setattr(store, "publish_device_prompt", slow_publish)
    monkeypatch.setattr(auth.httpx, "AsyncClient", _Client)

    start_task = asyncio.create_task(service.start_login())
    for _ in range(100):
        if entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert entered.is_set()

    start_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await start_task
    release.set()

    # Wait briefly for orphan cleanup thread to settle after publish completes.
    for _ in range(50):
        st = await service.status()
        if st["operation_state"] != "waiting":
            break
        await asyncio.sleep(0.02)
    assert (await service.status())["operation_state"] != "waiting"


def test_copilot_auth_response_model_enforces_strict_types_and_waiting_invariants() -> None:
    from pydantic import ValidationError

    from deeptutor.api.routers.settings import GitHubCopilotAuthStatusResponse

    with pytest.raises(ValidationError):
        GitHubCopilotAuthStatusResponse.model_validate(
            {
                "connection": "disconnected",
                "expires_at": "42",
            }
        )
    with pytest.raises(ValidationError):
        GitHubCopilotAuthStatusResponse.model_validate(
            {
                "connection": "disconnected",
                "operation_state": "waiting",
            }
        )
    with pytest.raises(ValidationError):
        GitHubCopilotAuthStatusResponse.model_validate(
            {
                "connection": "disconnected",
                "device_code": "must-never-appear",
            }
        )
