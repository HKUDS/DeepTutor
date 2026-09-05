from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import stat
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api.routers import video_learning
from deeptutor.multi_user import paths
from deeptutor.video_learning import invidious_account as account
from deeptutor.video_learning import invidious_account_client as account_client
from deeptutor.video_learning import invidious_account_storage as account_storage
from deeptutor.video_learning.service import TimedMediaError


@pytest.fixture
def system_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = (tmp_path / "data" / "system").resolve()
    monkeypatch.setattr(paths, "SYSTEM_ROOT", root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", (tmp_path / "data").resolve())
    monkeypatch.setattr(paths, "USERS_ROOT", (tmp_path / "data" / "users").resolve())
    return root


@pytest.fixture
def configured_instance(monkeypatch: pytest.MonkeyPatch) -> str:
    base = "https://invidious.example.test"
    monkeypatch.setattr(
        account,
        "load_video_learning_settings",
        lambda: {
            "version": 1,
            "default_provider": "youtube",
            "youtube": {"transcript_provider": "none"},
            "invidious": {"api_base_url": base, "public_base_url": ""},
        },
    )
    return base


def _token(scopes: list[str] | None = None) -> str:
    return json.dumps(
        {
            "session": "v1:test-session",
            "scopes": scopes or list(account.ACCOUNT_SCOPES),
            "signature": "test-signature",
        }
    )


def _state_from_authorize_url(url: str) -> str:
    callback_url = parse_qs(urlsplit(url).query)["callback_url"][0]
    return parse_qs(urlsplit(callback_url).query)["state"][0]


@pytest.fixture
def client(
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    app = FastAPI()
    app.include_router(video_learning.router, prefix="/api/video-learning")
    monkeypatch.setattr(video_learning, "current_owner_id", lambda: "u_ada")
    return TestClient(app)


def test_authorization_uses_minimal_scopes_and_one_time_state(
    system_root: Path,
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def preferences(*, api_base_url: str, token: dict[str, object]) -> dict[str, object]:
        assert api_base_url == configured_instance
        assert token["session"] == "v1:test-session"
        return {"locale": "en-US"}

    monkeypatch.setattr(account, "_request_preferences", preferences)

    url = account.begin_invidious_account_authorization(
        owner_id="u_ada", redirect_uri="https://app.example.test/callback"
    )
    query = parse_qs(urlsplit(url).query)
    state = _state_from_authorize_url(url)

    assert urlsplit(url).path == "/authorize_token"
    assert query["scopes"] == [",".join(account.ACCOUNT_SCOPES)]
    pending = account_storage.flow_path("u_ada", state)
    assert pending.is_file()
    assert stat.S_IMODE(pending.stat().st_mode) == 0o600

    status = asyncio.run(
        account.complete_invidious_account_authorization(
            owner_id="u_ada", state=state, token=_token()
        )
    )
    secret = (
        system_root
        / "user-secrets"
        / "u_ada"
        / "private"
        / "video-learning-invidious"
        / "account.json"
    )
    assert status["connected"] is True
    assert status["api_base_url"] == configured_instance
    assert "token" not in status
    assert "test-session" not in status
    assert "v1:test-session" in secret.read_text(encoding="utf-8")
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    for directory in (secret.parent, secret.parent.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_callback_cannot_be_replayed_or_used_by_another_owner(
    system_root: Path,
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def preferences(*, api_base_url: str, token: dict[str, object]) -> dict[str, object]:
        return {"locale": "en-US"}

    monkeypatch.setattr(account, "_request_preferences", preferences)
    url = account.begin_invidious_account_authorization(
        owner_id="u_ada", redirect_uri="https://app.example.test/callback"
    )
    state = _state_from_authorize_url(url)

    with pytest.raises(TimedMediaError):
        asyncio.run(
            account.complete_invidious_account_authorization(
                owner_id="u_bob", state=state, token=_token()
            )
        )

    # Looking under another owner's state directory must not consume the real
    # owner's pending callback.
    status = asyncio.run(
        account.complete_invidious_account_authorization(
            owner_id="u_ada", state=state, token=_token()
        )
    )
    assert status["connected"] is True
    with pytest.raises(TimedMediaError):
        asyncio.run(
            account.complete_invidious_account_authorization(
                owner_id="u_ada", state=state, token=_token()
            )
        )


def test_pending_callback_claim_is_atomic_across_workers(
    system_root: Path,
    configured_instance: str,
) -> None:
    url = account.begin_invidious_account_authorization(
        owner_id="u_ada", redirect_uri="https://app.example.test/callback"
    )
    state = _state_from_authorize_url(url)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(
            executor.map(
                lambda _: account_storage.consume_pending_flow("u_ada", state),
                range(2),
            )
        )

    assert sum(flow is not None for flow in claimed) == 1
    assert not account_storage.flow_path("u_ada", state).exists()


def test_expired_callback_is_rejected_and_never_writes_a_token(
    system_root: Path,
    configured_instance: str,
) -> None:
    url = account.begin_invidious_account_authorization(
        owner_id="u_ada", redirect_uri="https://app.example.test/callback"
    )
    state = _state_from_authorize_url(url)
    pending = account_storage.flow_path("u_ada", state)
    payload = account_storage.read_json(pending)
    payload["expires_at"] = 0
    account_storage.write_private_json(pending, payload)

    with pytest.raises(TimedMediaError):
        asyncio.run(
            account.complete_invidious_account_authorization(
                owner_id="u_ada", state=state, token=_token()
            )
        )
    assert not list(system_root.rglob("account.json"))


def test_token_missing_disconnect_scope_is_rejected(
    system_root: Path,
    configured_instance: str,
) -> None:
    url = account.begin_invidious_account_authorization(
        owner_id="u_ada", redirect_uri="https://app.example.test/callback"
    )
    state = _state_from_authorize_url(url)

    with pytest.raises(TimedMediaError, match="missing a required scope"):
        asyncio.run(
            account.complete_invidious_account_authorization(
                owner_id="u_ada", state=state, token=_token(["GET:preferences"])
            )
        )
    assert not list(system_root.rglob("account.json"))


def test_failed_preference_verification_never_writes_a_token(
    system_root: Path,
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = account_client.httpx.AsyncClient

    def refusing_client(**kwargs: object) -> object:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "invalid token"})

        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(account_client.httpx, "AsyncClient", refusing_client)
    url = account.begin_invidious_account_authorization(
        owner_id="u_ada", redirect_uri="https://app.example.test/callback"
    )
    state = _state_from_authorize_url(url)

    with pytest.raises(TimedMediaError, match="verification failed with HTTP 403"):
        asyncio.run(
            account.complete_invidious_account_authorization(
                owner_id="u_ada", state=state, token=_token()
            )
        )
    assert not list(system_root.rglob("account.json"))


def test_preference_network_failure_is_a_user_facing_error(
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    original_client = account_client.httpx.AsyncClient

    def offline_client(**kwargs: object) -> object:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline")

        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(account_client.httpx, "AsyncClient", offline_client)

    with pytest.raises(TimedMediaError, match="verification request failed"):
        asyncio.run(
            account._request_preferences(
                api_base_url=configured_instance, token=json.loads(_token())
            )
        )


def test_disconnect_revokes_upstream_and_removes_only_the_local_secret(
    system_root: Path,
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {"session": "v1:test-session", "signature": "test-signature"},
        },
    )
    account_storage.write_account(
        "u_bob",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {"session": "v1:bob-session", "signature": "bob-signature"},
        },
    )
    revoked: dict[str, object] = {}

    async def revoke(*, api_base_url: str, token: dict[str, object]) -> None:
        revoked["api_base_url"] = api_base_url
        revoked["session"] = token["session"]

    monkeypatch.setattr(account, "_revoke_token", revoke)

    status = asyncio.run(account.disconnect_invidious_account(owner_id="u_ada"))

    assert status == {"connected": False}
    assert revoked == {
        "api_base_url": configured_instance,
        "session": "v1:test-session",
    }
    assert "u_ada" not in (system_root / "user-secrets").iterdir()
    assert account.invidious_account_status("u_bob")["connected"] is True


def test_failed_upstream_disconnect_keeps_the_saved_connection_for_retry(
    system_root: Path,
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {"session": "v1:test-session", "signature": "test-signature"},
        },
    )

    original_client = account_client.httpx.AsyncClient

    def failing_client(**kwargs: object) -> object:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(account_client.httpx, "AsyncClient", failing_client)

    with pytest.raises(TimedMediaError, match="failed with HTTP 503"):
        asyncio.run(account.disconnect_invidious_account(owner_id="u_ada"))
    assert account.invidious_account_status("u_ada")["connected"] is True


def test_disconnect_network_failure_is_user_facing_and_keeps_connection(
    system_root: Path,
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {"session": "v1:test-session", "signature": "test-signature"},
        },
    )

    original_client = account_client.httpx.AsyncClient

    def offline_client(**kwargs: object) -> object:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(account_client.httpx, "AsyncClient", offline_client)

    with pytest.raises(TimedMediaError, match="disconnection request failed"):
        asyncio.run(account.disconnect_invidious_account(owner_id="u_ada"))
    assert account.invidious_account_status("u_ada")["connected"] is True


def test_public_url_override_is_the_only_remote_callback_origin(
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(account.PUBLIC_URL_ENV, "https://public.example.test")
    assert account.invidious_redirect_uri() == "https://public.example.test" + account.CALLBACK_PATH


def test_default_callback_never_trusts_request_host_headers(
    client: TestClient,
    system_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(account.PUBLIC_URL_ENV, raising=False)
    response = client.post(
        "/api/video-learning/invidious/account/authorize",
        headers={
            "host": "attacker.example.test",
            "x-forwarded-proto": "https",
            "x-forwarded-host": "forwarded-attacker.example.test",
        },
    )
    callback_url = parse_qs(urlsplit(response.json()["authorize_url"]).query)["callback_url"][0]
    assert callback_url.startswith(account.DEFAULT_PUBLIC_URL + account.CALLBACK_PATH)
    assert "attacker.example.test" not in callback_url


def test_invidious_requests_use_bearer_json_and_unregister_session(
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    token = json.loads(_token())
    requests: list[httpx.Request] = []
    original_client = account_client.httpx.AsyncClient

    def recording_client(**kwargs: object) -> object:
        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/api/v1/auth/preferences":
                return httpx.Response(200, json={"locale": "en-US"})
            return httpx.Response(204)

        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(account_client.httpx, "AsyncClient", recording_client)

    preferences = asyncio.run(
        account._request_preferences(api_base_url=configured_instance, token=token)
    )
    asyncio.run(account._revoke_token(api_base_url=configured_instance, token=token))

    assert preferences == {"locale": "en-US"}
    assert [request.method for request in requests] == ["GET", "POST"]
    assert [request.url.path for request in requests] == [
        "/api/v1/auth/preferences",
        "/api/v1/auth/tokens/unregister",
    ]
    expected_authorization = f"Bearer {account_client.bearer_token(token)}"
    assert all(request.headers["authorization"] == expected_authorization for request in requests)
    assert json.loads(requests[-1].content) == {"session": "v1:test-session"}


def test_status_rejects_expired_or_incomplete_stored_tokens(
    system_root: Path,
    configured_instance: str,
) -> None:
    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {"session": "v1:test-session", "signature": "sig"},
        },
    )
    assert account.invidious_account_status("u_ada")["connected"] is True

    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {"signature": "sig"},
        },
    )
    assert account.invidious_account_status("u_ada") == {"connected": False}


def test_disconnect_removes_an_expired_local_connection_without_upstream_call(
    system_root: Path,
    configured_instance: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import datetime, timezone

    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {
                "session": "v1:test-session",
                "signature": "sig",
                "expire": int(datetime.now(timezone.utc).timestamp()) - 1,
            },
        },
    )

    async def revoke(*, api_base_url: str, token: dict[str, object]) -> None:
        raise AssertionError("an expired token must not be sent upstream")

    monkeypatch.setattr(account, "_revoke_token", revoke)
    status = asyncio.run(account.disconnect_invidious_account(owner_id="u_ada"))
    assert status == {"connected": False}
    assert "u_ada" not in (system_root / "user-secrets").iterdir()


def test_router_authorize_callback_status_and_disconnect(
    client: TestClient,
    configured_instance: str,
    system_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(account.PUBLIC_URL_ENV, "https://app.example.test")
    response = client.post(
        "/api/video-learning/invidious/account/authorize",
        headers={
            "x-forwarded-proto": "https",
            "x-forwarded-host": "forwarded.example.test",
        },
    )

    assert response.status_code == 200
    url = response.json()["authorize_url"]
    state = _state_from_authorize_url(url)
    callback_url = parse_qs(urlsplit(url).query)["callback_url"][0]
    assert callback_url.startswith("https://app.example.test")

    async def complete(*, owner_id: str, state: str, token: str) -> dict[str, object]:
        assert owner_id == "u_ada"
        assert state
        assert "v1:test-session" in token
        return {"connected": True, "api_base_url": configured_instance}

    monkeypatch.setattr(
        video_learning.invidious_account, "complete_invidious_account_authorization", complete
    )
    callback = client.get(
        "/api/video-learning/invidious/account/callback",
        params={"state": state, "token": _token()},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/watching?account=connected"
    assert callback.headers["cache-control"] == "no-store"
    assert "v1:test-session" not in callback.text

    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "2026-09-02T00:00:00+00:00",
            "token": {"session": "v1:test-session", "signature": "test-signature"},
        },
    )
    status_response = client.get("/api/video-learning/invidious/account/status")
    assert status_response.status_code == 200
    assert status_response.json()["connected"] is True
    assert "v1:test-session" not in status_response.text

    disconnected: dict[str, object] = {}

    async def disconnect(*, owner_id: str) -> dict[str, object]:
        disconnected["owner_id"] = owner_id
        return {"connected": False}

    monkeypatch.setattr(
        video_learning.invidious_account, "disconnect_invidious_account", disconnect
    )
    disconnect_response = client.post("/api/video-learning/invidious/account/disconnect")
    assert disconnect_response.status_code == 200
    assert disconnect_response.json() == {"connected": False}
    assert disconnected == {"owner_id": "u_ada"}


def test_unknown_callback_redirects_without_calling_invidious(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/video-learning/invidious/account/callback",
        params={"state": "forged", "token": _token()},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/watching?account=authorization_expired"
    assert "forged" not in response.text
    assert "v1:test-session" not in response.text


def test_router_start_returns_400_when_invidious_is_not_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        account,
        "load_video_learning_settings",
        lambda: {
            "version": 1,
            "default_provider": "youtube",
            "youtube": {"transcript_provider": "none"},
            "invidious": {"api_base_url": "", "public_base_url": ""},
        },
    )
    response = client.post("/api/video-learning/invidious/account/authorize")
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Configure the Invidious API base URL before connecting an account."
    )


def test_authorization_uses_public_origin_and_preserves_private_transport(system_root, monkeypatch):
    monkeypatch.setattr(
        account,
        "load_video_learning_settings",
        lambda: {
            "invidious": {
                "api_base_url": "http://127.0.0.1:3000",
                "public_base_url": "http://100.101.207.44:3000",
            }
        },
    )
    url = account.begin_invidious_account_authorization(
        owner_id="u_ada", redirect_uri="http://100.101.207.44:3782/callback"
    )
    assert url.startswith("http://100.101.207.44:3000/authorize_token?")
    flow = account_storage.consume_pending_flow("u_ada", _state_from_authorize_url(url))
    assert flow.api_base_url == "http://127.0.0.1:3000"


@pytest.mark.asyncio
async def test_catalog_is_owner_scoped_and_search_is_anonymous(
    system_root, configured_instance, monkeypatch
):
    calls = []

    async def catalog(**kwargs):
        calls.append(kwargs)
        return [
            {
                "videoId": "aircAruvnKk",
                "title": "Neural networks",
                "videoThumbnails": [{"url": "https://untrusted.test/tracking"}],
            }
        ]

    monkeypatch.setattr(account_client, "request_catalog", catalog)
    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": list(account.ACCOUNT_SCOPES),
            "connected_at": "now",
            "token": json.loads(_token()),
        },
    )
    await account.browse_invidious(owner_id="u_ada", kind="feed")
    assert calls[-1]["token"]["session"] == "v1:test-session"
    with pytest.raises(TimedMediaError, match="Reconnect"):
        await account.browse_invidious(owner_id="u_other", kind="feed")
    result = await account.browse_invidious(owner_id="u_ada", kind="search", query="neural")
    assert calls[-1]["token"] is None
    assert result["videos"][0]["videoThumbnails"][0]["url"].startswith("https://i.ytimg.com/")
    assert "token" not in result
    with pytest.raises(TimedMediaError, match="Invalid playlist"):
        await account.browse_invidious(
            owner_id="u_ada", kind="playlist", playlist_id="../preferences"
        )


def test_old_account_requires_read_permission_upgrade(system_root, configured_instance):
    account_storage.write_account(
        "u_ada",
        {
            "version": 1,
            "api_base_url": configured_instance,
            "scopes": ["GET:preferences", "POST:tokens/unregister"],
            "connected_at": "now",
            "token": json.loads(_token()),
        },
    )
    assert account.invidious_account_status("u_ada") == {
        "connected": False,
        "needs_reauthorization": True,
    }


def test_catalog_rejects_invalid_pagination(client):
    assert client.get("/api/video-learning/invidious/browse/search?page=0").status_code == 422


@pytest.mark.asyncio
async def test_catalog_transport_maps_offline_and_revoked_tokens(monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, *args, **kwargs):
            return httpx.Response(401)

    monkeypatch.setattr(account_client.httpx, "AsyncClient", lambda **kwargs: FakeClient())
    with pytest.raises(TimedMediaError, match="Reconnect"):
        await account_client.request_catalog(
            api_base_url="https://invidious.test",
            path="/api/v1/auth/feed",
            params={},
            token=json.loads(_token()),
        )


@pytest.mark.asyncio
async def test_unauthenticated_callback_clears_credentials_from_destination():
    from starlette.requests import Request
    from starlette.responses import Response

    from deeptutor.api.main import selective_access_log

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/video-learning/invidious/account/callback",
            "query_string": b"token=secret&state=secret",
            "headers": [],
            "scheme": "http",
            "server": ("localhost", 8001),
        }
    )

    async def denied(_request):
        return Response(status_code=401)

    response = await selective_access_log(request, denied)
    assert response.status_code == 303
    assert response.headers["location"] == "/watching?account=authorization_login_required"
    assert "secret" not in str(dict(response.headers))


@pytest.mark.parametrize("encoded", [False, True])
def test_real_invidious_callback_encoding(
    client, system_root, configured_instance, monkeypatch, encoded
):
    from urllib.parse import quote_plus

    # Native Invidious encodes JSON before HTTP::Params encodes the query again.
    raw = json.loads(_token())
    raw["session"] = "v1:literal+percent%2B"
    serialized = json.dumps(raw)

    async def preferences(*, api_base_url, token):
        assert token == raw
        return {}

    monkeypatch.setattr(account, "_request_preferences", preferences)
    started = client.post("/api/video-learning/invidious/account/authorize").json()
    state = _state_from_authorize_url(started["authorize_url"])
    callback = client.get(
        "/api/video-learning/invidious/account/callback",
        params={
            "state": state,
            "token": quote_plus(serialized) if encoded else serialized,
        },
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"] == "/watching?account=connected"
    assert account_storage.read_account("u_ada")["token"] == raw
    assert client.get("/api/video-learning/invidious/account/status").json()["connected"]
    repeated = client.get(
        "/api/video-learning/invidious/account/callback",
        params={"state": state, "token": serialized},
        follow_redirects=False,
    )
    assert repeated.headers["location"] == "/watching?account=authorization_expired"


def test_token_decoding_is_bounded_and_does_not_decode_literal_json():
    from urllib.parse import quote_plus

    raw = _token()
    with pytest.raises(TimedMediaError, match="invalid account token"):
        account._parse_token(quote_plus(quote_plus(raw)))


@pytest.mark.parametrize(
    ("error", "has_token", "code"),
    [
        (
            TimedMediaError("Invidious account callback is unknown, expired, or already used."),
            True,
            "authorization_expired",
        ),
        (
            TimedMediaError("Invidious account token is missing a required scope."),
            True,
            "authorization_scopes",
        ),
        (
            TimedMediaError("Invidious account verification failed with HTTP 403."),
            True,
            "authorization_token_rejected",
        ),
        (
            TimedMediaError("Invidious account verification request failed."),
            True,
            "authorization_unavailable",
        ),
        (RuntimeError("secret token should not be shown"), True, "authorization_failed"),
        (RuntimeError("anything"), False, "authorization_cancelled"),
    ],
)
def test_callback_failures_have_safe_actionable_codes(error, has_token, code):
    assert account.authorization_failure_code(error, has_token=has_token) == code
