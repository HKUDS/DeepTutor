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
    )
    assert callback.status_code == 200
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


def test_unknown_callback_returns_400_without_calling_invidious(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/video-learning/invidious/account/callback",
        params={"state": "forged", "token": _token()},
    )
    assert response.status_code == 400
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
