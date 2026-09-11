from __future__ import annotations

import base64
import json

import pytest

from deeptutor.services.codex_auth.constants import (
    CODEX_CALLBACK_PORTS,
    CODEX_CLIENT_VERSION,
    CODEX_DEFAULT_MODEL,
    CODEX_MODELS_URL,
    CODEX_OAUTH_CLIENT_ID,
)
from deeptutor.services.codex_auth.contracts import (
    CatalogSnapshot,
    CodexAuthError,
    CodexCredentials,
    CodexModel,
    TokenClaims,
    decode_codex_jwt,
)


def _jwt_for_test(payload: dict[str, object]) -> str:
    def encode(value: dict[str, object]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f"{encode({'alg': 'none'})}.{encode(payload)}."


def _model() -> CodexModel:
    return CodexModel(
        slug="gpt-5.6-sol",
        display_name="GPT-5.6-Sol",
        priority=10,
        visibility="list",
        default_reasoning_level="medium",
        supported_reasoning_levels=("low", "medium", "high"),
        supports_reasoning_summary=True,
        supports_parallel_tool_calls=True,
        use_responses_lite=False,
    )


def test_codex_upstream_contract_is_pinned() -> None:
    assert CODEX_OAUTH_CLIENT_ID == "app_EMoamEEZ73f0CkXaXp7hrann"
    assert CODEX_CALLBACK_PORTS == (1455, 1457)
    assert CODEX_CLIENT_VERSION == "0.153.4"
    assert CODEX_MODELS_URL.endswith("/backend-api/codex/models")
    assert CODEX_DEFAULT_MODEL == "gpt-5.6-sol"


def test_decode_token_claims_drops_email() -> None:
    token = _jwt_for_test(
        {
            "exp": 2_000_000_000,
            "email": "must-not-leave-backend@example.test",
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "account-123",
                "chatgpt_plan_type": "plus",
            },
        }
    )

    claims = decode_codex_jwt(token)

    assert claims == TokenClaims(expires_at=2_000_000_000, account_id="account-123")
    assert "email" not in repr(claims).lower()
    assert "example.test" not in repr(claims)


def test_decode_token_claims_ignores_wrong_field_types() -> None:
    token = _jwt_for_test(
        {
            "exp": "not-an-integer",
            "https://api.openai.com/auth": {"chatgpt_account_id": 42},
        }
    )

    assert decode_codex_jwt(token) == TokenClaims(expires_at=None, account_id=None)


def test_decode_token_claims_rejects_malformed_payload_without_echoing_token() -> None:
    token = "header.not-base64.secret"

    with pytest.raises(CodexAuthError) as exc_info:
        decode_codex_jwt(token)

    error = exc_info.value
    assert error.code == "invalid_token"
    assert error.http_status == 401
    assert str(error) == error.public_message
    assert token not in str(error)


def test_credentials_round_trip_and_public_token() -> None:
    credentials = CodexCredentials(
        schema_version=1,
        access_token="access-secret",
        refresh_token="refresh-secret",
        id_token="id-secret",
        account_id="account-123",
        expires_at=2_000_000_000,
        generation=7,
    )

    restored = CodexCredentials.from_dict(credentials.to_dict())

    assert restored == credentials
    assert restored.public_token().access_token == "access-secret"
    assert not hasattr(restored.public_token(), "refresh_token")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_token", None),
        ("refresh_token", ""),
        ("id_token", 123),
        ("account_id", None),
        ("expires_at", True),
        ("generation", True),
        ("schema_version", 2),
    ],
)
def test_credentials_reject_corrupt_field_types(
    field: str,
    value: object,
) -> None:
    payload = CodexCredentials(
        schema_version=1,
        access_token="access-secret",
        refresh_token="refresh-secret",
        id_token="id-secret",
        account_id="account-123",
        expires_at=2_000_000_000,
        generation=7,
    ).to_dict()
    payload[field] = value

    with pytest.raises(CodexAuthError) as exc_info:
        CodexCredentials.from_dict(payload)

    assert exc_info.value.code == "credential_corrupt"


def test_catalog_snapshot_round_trip_preserves_tuples() -> None:
    snapshot = CatalogSnapshot(
        models=(_model(),),
        source="live",
        fetched_at=2_000_000_000,
        etag='"catalog-v1"',
        generation=7,
        account_hash="account-hash",
    )

    restored = CatalogSnapshot.from_dict(snapshot.to_dict())

    assert restored == snapshot
    assert isinstance(restored.models, tuple)
    assert isinstance(restored.models[0].supported_reasoning_levels, tuple)


def test_codex_model_round_trip_preserves_context_windows() -> None:
    model = CodexModel(
        slug="gpt-5.6-sol",
        display_name="GPT-5.6-Sol",
        priority=10,
        visibility="list",
        default_reasoning_level="medium",
        supported_reasoning_levels=("low", "medium", "high"),
        supports_reasoning_summary=True,
        supports_parallel_tool_calls=True,
        use_responses_lite=False,
        context_window=272_000,
        max_context_window=272_000,
    )

    restored = CodexModel.from_dict(model.to_dict())

    assert restored == model


def test_codex_model_accepts_cache_without_context_windows() -> None:
    payload = _model().to_dict()
    payload.pop("context_window")
    payload.pop("max_context_window")

    restored = CodexModel.from_dict(payload)

    assert restored.context_window is None
    assert restored.max_context_window is None
