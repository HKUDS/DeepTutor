"""The settings picker must use the same owner-private discovery as the CLI."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from deeptutor.api.routers import settings
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.multi_user.paths import user_context
from deeptutor.services import github_copilot_auth as auth
from deeptutor.services.github_copilot_storage import GitHubToken
from deeptutor.services.llm import cloud_provider, local_provider
from deeptutor.services.partners.scope import PARTNER_USER_PREFIX

ENDPOINT = "/api/settings/fetch-models"
LOGIN_COMMAND = "deeptutor provider login github-copilot"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "home"))
    app = FastAPI()
    app.include_router(settings.router, prefix="/api/settings")
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def copilot_http(monkeypatch):
    """Only the HTTP transport is faked; storage, exchange and filtering are real."""
    state = SimpleNamespace(
        calls=[],
        rows=[
            {"id": "claude-live", "supported_endpoints": ["/responses"]},
            {"id": "gpt-live", "supported_endpoints": ["/chat/completions"]},
            {"id": "legacy-live"},
            {"id": "hidden", "model_picker_enabled": False},
            {"id": "disabled", "policy": {"state": "disabled"}},
            {"id": "unsupported", "supported_endpoints": ["/embeddings"]},
        ],
        failure=None,
    )

    def handle(request):
        state.calls.append(request)
        if state.failure:
            raise state.failure
        if request.url == auth.DEFAULT_COPILOT_TOKEN_URL:
            assert request.headers["Authorization"].startswith("token fixture-")
            return httpx.Response(
                200,
                json={
                    "token": "fixture-short-lived",
                    "expires_at": 2_000_000_000,
                    "endpoints": {"api": "https://tenant.example/copilot"},
                },
            )
        assert str(request.url) == "https://tenant.example/copilot/models"
        assert request.headers["Authorization"] == "Bearer fixture-short-lived"
        return httpx.Response(200, json={"data": state.rows})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        auth.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    monkeypatch.delenv("DEEPTUTOR_COPILOT_TOKEN_URL", raising=False)
    monkeypatch.setattr(
        cloud_provider, "fetch_models", AsyncMock(side_effect=AssertionError("generic cloud path"))
    )
    monkeypatch.setattr(
        local_provider, "fetch_models", AsyncMock(side_effect=AssertionError("generic local path"))
    )
    return state


def _login():
    auth.get_github_copilot_storage().save(
        GitHubToken("fixture-github", 2_000_000_000_000, "fixture-account")
    )


@pytest.mark.parametrize("binding", ["github_copilot", "github-copilot", " GitHub_Copilot "])
@pytest.mark.parametrize("api_key", [None, "", "***"])
def test_picker_returns_live_selectable_models(client, copilot_http, monkeypatch, binding, api_key):
    _login()
    monkeypatch.setattr(
        settings,
        "get_model_catalog_service",
        lambda: pytest.fail("Copilot must not load API keys from the shared catalog"),
    )
    response = client.post(
        ENDPOINT,
        json={
            "binding": binding,
            "base_url": "",
            "api_key": api_key,
            "profile_id": "copilot-profile",
            "service": "llm",
        },
    )
    assert response.status_code == 200
    ids = ["github-copilot/claude-live", "github-copilot/gpt-live", "github-copilot/legacy-live"]
    assert response.json() == {"models": [{"id": model, "name": model} for model in ids]}
    assert len(copilot_http.calls) == 2
    assert "fixture-" not in response.text


def test_task_picker_ignores_draft_endpoint_and_key(client, copilot_http):
    _login()
    response = client.post(
        ENDPOINT,
        json={
            "binding": "github_copilot",
            "base_url": "http://localhost:1234/v1",
            "api_key": "untrusted-draft-key",
            "api_format": "anthropic",
            "service": "task",
        },
    )
    assert response.status_code == 200
    assert len(copilot_http.calls) == 2
    assert response.json()["models"][0]["id"] == "github-copilot/claude-live"


def test_missing_login_is_actionable_not_empty_success(client, copilot_http):
    response = client.post(ENDPOINT, json={"binding": "github_copilot"})
    assert response.status_code == 502
    assert LOGIN_COMMAND in response.json()["detail"]
    assert "models" not in response.json()
    assert copilot_http.calls == []


@pytest.mark.parametrize("failure_kind", ["unauthorized", "forbidden", "timeout", "invalid"])
def test_provider_errors_are_safe_and_actionable(client, copilot_http, caplog, failure_kind):
    _login()
    secret = "fixture-sensitive-error"
    request = httpx.Request("GET", f"https://tenant.example/?token={secret}")
    if failure_kind in {"unauthorized", "forbidden"}:
        upstream = httpx.Response(
            401 if failure_kind == "unauthorized" else 403,
            request=request,
            json={"error": secret},
        )
        failure = httpx.HTTPStatusError(secret, request=request, response=upstream)
    elif failure_kind == "timeout":
        failure = httpx.ReadTimeout(secret, request=request)
    else:
        failure = ValueError(secret)
    copilot_http.failure = failure

    response = client.post(ENDPOINT, json={"binding": "github_copilot"})

    assert response.status_code == 502
    assert LOGIN_COMMAND in response.json()["detail"]
    assert secret not in response.text
    assert secret not in caplog.text


def test_catalog_failure_is_not_silently_swallowed(client, copilot_http, monkeypatch):
    _login()
    monkeypatch.setattr(
        auth, "fetch_github_copilot_models", AsyncMock(side_effect=RuntimeError("fixture-error"))
    )
    response = client.post(ENDPOINT, json={"binding": "github_copilot"})
    assert response.status_code == 502
    assert LOGIN_COMMAND in response.json()["detail"]
    assert "fixture-error" not in response.text


def test_owner_and_home_scope_are_preserved(client, copilot_http, tmp_path, monkeypatch):
    _login()
    other = CurrentUser(
        id="u_other",
        username="other",
        role="admin",
        scope=UserScope(kind="user", user_id="u_other", root=tmp_path / "other"),
    )
    with user_context(other):
        response = client.post(ENDPOINT, json={"binding": "github_copilot"})
        assert response.status_code == 502
        assert copilot_http.calls == []
        auth.get_github_copilot_storage().save(
            GitHubToken("fixture-other", 2_000_000_000_000, "other")
        )
        response = client.post(ENDPOINT, json={"binding": "github_copilot"})
        assert response.status_code == 200
        assert copilot_http.calls[0].headers["Authorization"] == "token fixture-other"

    copilot_http.calls.clear()
    assert client.post(ENDPOINT, json={"binding": "github_copilot"}).status_code == 200
    assert copilot_http.calls[0].headers["Authorization"] == "token fixture-github"

    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path / "different-home"))
    copilot_http.calls.clear()
    assert client.post(ENDPOINT, json={"binding": "github_copilot"}).status_code == 502
    assert copilot_http.calls == []


@pytest.mark.parametrize("user_id", ["u_reader", f"{PARTNER_USER_PREFIX}ada"])
def test_settings_permission_gate_still_applies(client, copilot_http, tmp_path, user_id):
    user = CurrentUser(
        id=user_id,
        username=user_id,
        role="user",
        scope=UserScope(kind="user", user_id=user_id, root=tmp_path / "reader"),
    )
    with user_context(user):
        response = client.post(ENDPOINT, json={"binding": "github_copilot"})
    assert response.status_code == 403
    assert copilot_http.calls == []


def test_standard_provider_keeps_key_endpoint_format_and_contract(client, monkeypatch):
    fetch = AsyncMock(return_value=["gpt-standard"])
    monkeypatch.setattr(cloud_provider, "fetch_models", fetch)
    response = client.post(
        ENDPOINT,
        json={
            "binding": "OpenAI",
            "base_url": "https://standard.example/v1",
            "api_key": "fixture-standard",
            "api_format": "responses",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"models": [{"id": "gpt-standard", "name": "gpt-standard"}]}
    fetch.assert_awaited_once_with(
        "https://standard.example/v1", "fixture-standard", "openai", api_format="responses"
    )
    assert client.post(ENDPOINT, json={"binding": "openai"}).status_code == 400


def test_copilot_registry_and_probe_accept_empty_api_key():
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.provider_registry import find_by_name

    spec = find_by_name("github_copilot")
    assert spec.is_oauth
    assert spec.auth_mode == "oauth"
    choices = settings._provider_choices()["llm"]
    assert next(row for row in choices if row["value"] == spec.name)["auth_mode"] == "oauth"
    config = LLMConfig(
        model="github-copilot/gpt-live",
        binding=spec.name,
        provider_name=spec.name,
        provider_mode=spec.mode,
        api_key="",
        base_url="",
    )
    assert config.get_api_key() == ""
