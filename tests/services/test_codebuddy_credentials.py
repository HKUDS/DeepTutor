"""Tests for reading the shared CodeBuddy login state."""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path
import time

import pytest

from deeptutor.services import codebuddy_credentials
from deeptutor.services.codebuddy_credentials import (
    INTERNAL_ENDPOINT,
    OVERSEAS_ENDPOINT,
    CodeBuddyAuthUnavailable,
    CodeBuddyCredentials,
    cached_model_catalog,
    load_credentials,
    refresh_credentials,
    resolve_api_base,
)


def _write_auth_file(tmp_path: Path, monkeypatch, **auth_overrides) -> Path:
    auth = {
        "accessToken": "access-token",
        "refreshToken": "refresh-token",
        "tokenType": "Bearer",
        "expiresAt": 1791055241000,
        "refreshExpiresAt": 1793647241000,
        "domain": "www.codebuddy.cn",
    }
    auth.update(auth_overrides)
    path = tmp_path / "Tencent-Cloud.coding-copilot.info"
    path.write_text(
        json.dumps({"account": {"uid": "uid-1", "nickname": "tester"}, "auth": auth}),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_AUTH_FILE", str(path))
    return path


def test_load_credentials_parses_session(tmp_path, monkeypatch) -> None:
    _write_auth_file(tmp_path, monkeypatch)

    credentials = load_credentials()

    assert credentials is not None
    assert credentials.access_token == "access-token"
    assert credentials.refresh_token == "refresh-token"
    assert credentials.user_id == "uid-1"
    assert credentials.user_label == "tester"
    # Epoch milliseconds in the file, seconds in the dataclass.
    assert credentials.expires_at == pytest.approx(1791055241.0)
    assert credentials.is_expired() is False


def test_load_credentials_returns_none_when_signed_out() -> None:
    assert load_credentials() is None


def test_load_credentials_rejects_file_without_token(tmp_path, monkeypatch) -> None:
    path = tmp_path / "Tencent-Cloud.coding-copilot.info"
    path.write_text(json.dumps({"auth": {"refreshToken": "only-refresh"}}), encoding="utf-8")
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_AUTH_FILE", str(path))

    assert load_credentials() is None


def test_resolve_api_base_follows_account_domain() -> None:
    assert resolve_api_base("www.codebuddy.cn") == INTERNAL_ENDPOINT + "/v2"
    assert resolve_api_base("www.codebuddy.ai") == OVERSEAS_ENDPOINT + "/v2"


def test_resolve_api_base_honours_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CODEBUDDY_BASE_URL", "https://proxy.example.com")
    assert resolve_api_base("www.codebuddy.ai") == "https://proxy.example.com/v2"

    monkeypatch.delenv("CODEBUDDY_BASE_URL")
    monkeypatch.setenv("CODEBUDDY_INTERNET_ENVIRONMENT", "internal")
    assert resolve_api_base("www.codebuddy.ai") == INTERNAL_ENDPOINT + "/v2"


def test_cached_model_catalog_reads_cli_cache(tmp_path, monkeypatch) -> None:
    config = {"endpoint": INTERNAL_ENDPOINT, "models": [{"id": "default"}, {"id": "glm-5.2"}]}
    blob = base64.b64encode(gzip.compress(json.dumps(config).encode())).decode()
    (tmp_path / "entry_abc.info").write_text(json.dumps(blob), encoding="utf-8")
    monkeypatch.setattr(codebuddy_credentials, "_local_storage_dir", lambda: tmp_path)

    assert cached_model_catalog() == ["default", "glm-5.2"]
    assert resolve_api_base("www.codebuddy.ai") == INTERNAL_ENDPOINT + "/v2"


def test_expired_session_without_refresh_token_is_reported(tmp_path, monkeypatch) -> None:
    _write_auth_file(
        tmp_path,
        monkeypatch,
        refreshToken="",
        expiresAt=int((time.time() - 60) * 1000),
    )

    credentials = load_credentials()

    assert credentials is not None
    assert credentials.is_expired() is True
    assert credentials.can_refresh() is False


@pytest.mark.asyncio
async def test_refresh_credentials_requires_a_refresh_token() -> None:
    credentials = CodeBuddyCredentials(access_token="stale", refresh_token="")

    with pytest.raises(CodeBuddyAuthUnavailable):
        await refresh_credentials(credentials)


def test_a_cached_endpoint_cannot_redirect_the_bearer_token(tmp_path, monkeypatch) -> None:
    """The product cache belongs to another application on this host.

    Anything able to write under the service account's home could otherwise
    name the host that receives the CodeBuddy access token.
    """
    import base64
    import gzip
    import json

    from deeptutor.services import codebuddy_credentials as creds

    storage = tmp_path / ".codebuddy" / "local_storage"
    storage.mkdir(parents=True)
    blob = {"models": [{"id": "default"}], "endpoint": "http://attacker.example"}
    packed = base64.b64encode(gzip.compress(json.dumps(blob).encode())).decode()
    (storage / "entry_1.info").write_text(json.dumps(packed), encoding="utf-8")
    monkeypatch.setattr(creds, "_local_storage_dir", lambda: storage)
    monkeypatch.delenv("CODEBUDDY_BASE_URL", raising=False)
    monkeypatch.delenv("CODEBUDDY_INTERNET_ENVIRONMENT", raising=False)

    assert creds.cached_product_endpoint() is None
    # The untrusted host must not reach the request either.
    assert "attacker.example" not in creds.resolve_api_base("")


def test_a_trusted_cached_endpoint_is_still_honoured(tmp_path, monkeypatch) -> None:
    import base64
    import gzip
    import json

    from deeptutor.services import codebuddy_credentials as creds

    storage = tmp_path / ".codebuddy" / "local_storage"
    storage.mkdir(parents=True)
    blob = {"models": [{"id": "default"}], "endpoint": creds.INTERNAL_ENDPOINT}
    packed = base64.b64encode(gzip.compress(json.dumps(blob).encode())).decode()
    (storage / "entry_1.info").write_text(json.dumps(packed), encoding="utf-8")
    monkeypatch.setattr(creds, "_local_storage_dir", lambda: storage)
    monkeypatch.delenv("CODEBUDDY_BASE_URL", raising=False)
    monkeypatch.delenv("CODEBUDDY_INTERNET_ENVIRONMENT", raising=False)

    assert creds.cached_product_endpoint() == creds.INTERNAL_ENDPOINT
