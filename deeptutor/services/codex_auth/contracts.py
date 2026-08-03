"""Data contracts shared by the independent Codex OAuth components."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, field
import json
from typing import Any, Literal

CatalogSource = Literal["live", "fresh-cache", "revalidated-cache", "stale-cache"]


class CodexAuthError(RuntimeError):
    """An OAuth error whose string form is safe to expose to a user."""

    def __init__(self, code: str, public_message: str, http_status: int = 400) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.http_status = http_status

    def __str__(self) -> str:
        return self.public_message


@dataclass(frozen=True)
class TokenClaims:
    expires_at: int | None
    account_id: str | None


@dataclass(frozen=True)
class CodexCredentials:
    schema_version: int
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    id_token: str = field(repr=False)
    account_id: str
    expires_at: int
    generation: int

    def public_token(self) -> CodexToken:
        return CodexToken(
            access_token=self.access_token,
            account_id=self.account_id,
            expires_at=self.expires_at,
            generation=self.generation,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "id_token": self.id_token,
            "account_id": self.account_id,
            "expires_at": self.expires_at,
            "generation": self.generation,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CodexCredentials:
        try:
            schema_version = payload["schema_version"]
            access_token = payload["access_token"]
            refresh_token = payload["refresh_token"]
            id_token = payload["id_token"]
            account_id = payload["account_id"]
            expires_at = payload["expires_at"]
            generation = payload["generation"]
            if (
                isinstance(schema_version, bool)
                or schema_version != 1
                or not all(
                    isinstance(value, str) and bool(value)
                    for value in (
                        access_token,
                        refresh_token,
                        id_token,
                        account_id,
                    )
                )
                or isinstance(expires_at, bool)
                or not isinstance(expires_at, int)
                or expires_at <= 0
                or isinstance(generation, bool)
                or not isinstance(generation, int)
                or generation < 0
            ):
                raise ValueError
            return cls(
                schema_version=schema_version,
                access_token=access_token,
                refresh_token=refresh_token,
                id_token=id_token,
                account_id=account_id,
                expires_at=expires_at,
                generation=generation,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CodexAuthError(
                "credential_corrupt",
                "Stored Codex credentials are invalid.",
                500,
            ) from exc


@dataclass(frozen=True)
class CodexToken:
    access_token: str = field(repr=False)
    account_id: str
    expires_at: int
    generation: int


@dataclass(frozen=True)
class CodexModel:
    slug: str
    display_name: str
    priority: int
    visibility: str
    default_reasoning_level: str | None
    supported_reasoning_levels: tuple[str, ...]
    supports_reasoning_summary: bool
    supports_parallel_tool_calls: bool
    use_responses_lite: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "slug": self.slug,
            "display_name": self.display_name,
            "priority": self.priority,
            "visibility": self.visibility,
            "default_reasoning_level": self.default_reasoning_level,
            "supported_reasoning_levels": list(self.supported_reasoning_levels),
            "supports_reasoning_summary": self.supports_reasoning_summary,
            "supports_parallel_tool_calls": self.supports_parallel_tool_calls,
            "use_responses_lite": self.use_responses_lite,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CodexModel:
        try:
            reasoning_levels = payload["supported_reasoning_levels"]
            if not isinstance(reasoning_levels, list):
                raise TypeError
            return cls(
                slug=str(payload["slug"]),
                display_name=str(payload["display_name"]),
                priority=int(payload["priority"]),
                visibility=str(payload["visibility"]),
                default_reasoning_level=(
                    str(payload["default_reasoning_level"])
                    if payload.get("default_reasoning_level") is not None
                    else None
                ),
                supported_reasoning_levels=tuple(str(item) for item in reasoning_levels),
                supports_reasoning_summary=bool(payload["supports_reasoning_summary"]),
                supports_parallel_tool_calls=bool(payload["supports_parallel_tool_calls"]),
                use_responses_lite=bool(payload["use_responses_lite"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CodexAuthError(
                "catalog_corrupt",
                "Stored Codex model data is invalid.",
                500,
            ) from exc


@dataclass(frozen=True)
class CatalogSnapshot:
    models: tuple[CodexModel, ...]
    source: CatalogSource
    fetched_at: int
    etag: str | None
    generation: int
    account_hash: str

    def to_dict(self) -> dict[str, object]:
        return {
            "models": [model.to_dict() for model in self.models],
            "source": self.source,
            "fetched_at": self.fetched_at,
            "etag": self.etag,
            "generation": self.generation,
            "account_hash": self.account_hash,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CatalogSnapshot:
        try:
            models = payload["models"]
            source = payload["source"]
            if not isinstance(models, list):
                raise TypeError
            if source not in {"live", "fresh-cache", "revalidated-cache", "stale-cache"}:
                raise ValueError
            return cls(
                models=tuple(CodexModel.from_dict(item) for item in models),
                source=source,
                fetched_at=int(payload["fetched_at"]),
                etag=str(payload["etag"]) if payload.get("etag") is not None else None,
                generation=int(payload["generation"]),
                account_hash=str(payload["account_hash"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CodexAuthError(
                "catalog_corrupt",
                "Stored Codex model data is invalid.",
                500,
            ) from exc


def decode_codex_jwt(token: str) -> TokenClaims:
    """Decode the minimal unverified claims needed after a trusted TLS exchange."""

    try:
        payload_part = token.split(".")[1]
        padding = "=" * (-len(payload_part) % 4)
        raw = base64.urlsafe_b64decode(payload_part + padding)
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise TypeError
    except (IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CodexAuthError("invalid_token", "Codex returned an invalid token.", 401) from exc

    expires_at = payload.get("exp")
    if isinstance(expires_at, bool) or not isinstance(expires_at, int):
        expires_at = None

    account_id: str | None = None
    auth_claim = payload.get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        raw_account_id = auth_claim.get("chatgpt_account_id")
        if isinstance(raw_account_id, str) and raw_account_id:
            account_id = raw_account_id

    return TokenClaims(expires_at=expires_at, account_id=account_id)
