"""Authenticated BYOK profile and policy APIs."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator

from deeptutor.api.routers.auth import require_admin, require_auth
from deeptutor.multi_user.byok_policy import (
    SERVICES,
    allowed_binding,
    auth_is_enabled,
    byok_runtime_enabled,
    grant_service_enabled,
    load_policy,
    normalize_policy,
    save_policy,
    validate_endpoint,
)
from deeptutor.multi_user.byok_vault import (
    ByokProfileNotFound,
    ByokVaultConflict,
    ByokVaultError,
    ByokVaultUnavailable,
    UserByokCredentialVault,
)
from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.grants import load_grant, save_grant

router = APIRouter()

ServiceName = Literal["llm", "embedding", "mineru"]


class ByokProfileRequest(BaseModel):
    service: ServiceName
    provider: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    dimension: int = Field(default=0, ge=0, le=1_000_000)
    mode: str = Field(default="", max_length=32)
    generation: int | None = Field(default=None, ge=1)
    secret: SecretStr | None = None

    @field_validator("provider", "model", "name", "mode")
    @classmethod
    def trim_text(cls, value: str) -> str:
        return value.strip()


class ByokPreferenceRequest(BaseModel):
    service: ServiceName
    source: Literal["platform", "byok"]
    profile_id: str | None = Field(default=None, max_length=80)


class AdminByokPolicyRequest(BaseModel):
    policy: dict[str, Any]


class SuspendByokRequest(BaseModel):
    service: ServiceName
    enabled: bool = False


def _vault() -> UserByokCredentialVault:
    return UserByokCredentialVault()


def _current_user_id() -> str:
    user = get_current_user()
    if not auth_is_enabled():
        raise HTTPException(status_code=400, detail="Auth must be enabled before using BYOK")
    return user.id


def _profile_metadata(payload: ByokProfileRequest) -> dict[str, Any]:
    return {
        "service": payload.service,
        "provider": payload.provider,
        "name": payload.name,
        "model": payload.model,
        "base_url": payload.base_url or "",
        "dimension": payload.dimension,
        "mode": payload.mode or ("cloud" if payload.service == "mineru" else ""),
    }


def _validate_profile_request(payload: ByokProfileRequest) -> None:
    policy = load_policy()
    if not byok_runtime_enabled(payload.service, policy):
        raise HTTPException(status_code=403, detail=f"BYOK is disabled for {payload.service}")
    if not allowed_binding(payload.service, payload.provider, policy):
        raise HTTPException(status_code=400, detail="This provider is not allowed by the administrator")
    if payload.service == "mineru" and payload.mode not in {"", "cloud"}:
        raise HTTPException(status_code=400, detail="MinerU BYOK only supports cloud mode")
    try:
        validate_endpoint(
            payload.base_url,
            service=payload.service,
            binding=payload.provider,
            policy=policy,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _translate_vault_error(exc: ByokVaultError) -> HTTPException:
    if isinstance(exc, ByokVaultConflict):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ByokProfileNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ByokVaultUnavailable):
        return HTTPException(status_code=503, detail="BYOK Vault is unavailable")
    return HTTPException(status_code=500, detail="BYOK storage is unavailable")


@router.get("/byok/status")
async def get_byok_status(_: object = Depends(require_auth)) -> dict[str, Any]:
    user_id = _current_user_id()
    user = get_current_user()
    grant = load_grant(user_id)
    policy = load_policy()
    vault = _vault()
    profiles = vault.list_profiles(user_id)
    return {
        "auth_enabled": True,
        "vault_available": vault.is_available(),
        "policy": {
            "enabled": bool(policy.get("enabled")),
            "services": {
                service: {
                    "enabled": byok_runtime_enabled(service, policy),
                    "allowed": user.is_admin or bool((grant.get("byok") or {}).get(service, {}).get("enabled", False)),
                }
                for service in SERVICES
            },
        },
        "profiles": profiles,
        "preferences": vault.get_preferences(user_id),
        "platform": {
            service: grant_service_enabled(grant, "platform", service) or user.is_admin
            for service in SERVICES
        },
    }


@router.post("/byok/profiles")
async def create_byok_profile(
    payload: ByokProfileRequest,
    _: object = Depends(require_auth),
) -> dict[str, Any]:
    user_id = _current_user_id()
    _validate_profile_request(payload)
    if payload.secret is None or not payload.secret.get_secret_value():
        raise HTTPException(status_code=400, detail="A BYOK secret is required")
    vault = _vault()
    try:
        result = vault.save_profile(user_id, _profile_metadata(payload), payload.secret.get_secret_value())
        preferences = vault.get_preferences(user_id)
        if payload.service not in preferences:
            preferences[payload.service] = {"source": "byok", "profile_id": result["id"]}
            vault.save_preferences(user_id, preferences)
        return {"profile": result, "preferences": vault.get_preferences(user_id)}
    except ByokVaultError as exc:
        raise _translate_vault_error(exc) from exc


@router.patch("/byok/profiles/{profile_id}")
async def update_byok_profile(
    profile_id: str,
    payload: ByokProfileRequest,
    _: object = Depends(require_auth),
) -> dict[str, Any]:
    user_id = _current_user_id()
    _validate_profile_request(payload)
    vault = _vault()
    try:
        result = vault.save_profile(
            user_id,
            _profile_metadata(payload),
            payload.secret.get_secret_value() if payload.secret is not None else None,
            profile_id=profile_id,
            expected_generation=payload.generation,
        )
        return {"profile": result}
    except ByokVaultError as exc:
        raise _translate_vault_error(exc) from exc


@router.post("/byok/profiles/{profile_id}/validate")
async def validate_byok_profile(
    profile_id: str,
    _: object = Depends(require_auth),
) -> dict[str, Any]:
    """Validate policy, ownership and decryptability before a provider probe.

    Provider-specific probes are added by each service adapter; this endpoint
    deliberately never returns the provider's raw response or secret.
    """
    user_id = _current_user_id()
    vault = _vault()
    try:
        metadata, _secret = vault.load_secret(user_id, profile_id)
        policy = load_policy()
        if not byok_runtime_enabled(str(metadata.get("service") or ""), policy):
            raise HTTPException(status_code=403, detail="BYOK is disabled for this service")
        if metadata.get("base_url"):
            validate_endpoint(
                str(metadata["base_url"]),
                service=str(metadata.get("service") or ""),
                binding=str(metadata.get("provider") or ""),
                policy=policy,
            )
        return {"ok": True, "profile_id": profile_id, "status": "validated"}
    except HTTPException:
        raise
    except ByokVaultError as exc:
        raise _translate_vault_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/byok/profiles/{profile_id}")
async def delete_byok_profile(
    profile_id: str,
    _: object = Depends(require_auth),
) -> dict[str, Any]:
    user_id = _current_user_id()
    vault = _vault()
    try:
        deleted = vault.delete_profile(user_id, profile_id)
    except ByokVaultError as exc:
        raise _translate_vault_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="BYOK profile not found")
    preferences = vault.get_preferences(user_id)
    for service, preference in list(preferences.items()):
        if isinstance(preference, dict) and preference.get("profile_id") == profile_id:
            remaining = vault.list_profiles(user_id, service=service)
            preferences[service] = (
                {"source": "byok", "profile_id": remaining[0]["id"]}
                if remaining
                else {"source": "platform"}
            )
    vault.save_preferences(user_id, preferences)
    return {"ok": True, "preferences": vault.get_preferences(user_id)}


@router.put("/byok/preferences")
async def set_byok_preference(
    payload: ByokPreferenceRequest,
    _: object = Depends(require_auth),
) -> dict[str, Any]:
    user_id = _current_user_id()
    user = get_current_user()
    grant = load_grant(user_id)
    vault = _vault()
    if not user.is_admin and not grant_service_enabled(grant, payload.source, payload.service):
        raise HTTPException(status_code=403, detail="This source is not enabled for your account")
    if payload.source == "byok":
        policy = load_policy()
        if not byok_runtime_enabled(payload.service, policy):
            raise HTTPException(status_code=403, detail=f"BYOK is disabled for {payload.service}")
        profiles = vault.list_profiles(user_id, service=payload.service)
        selected = next((item for item in profiles if item.get("id") == payload.profile_id), None)
        if selected is None:
            raise HTTPException(status_code=400, detail="Select a BYOK profile belonging to your account")
        if not allowed_binding(payload.service, str(selected.get("provider") or ""), policy):
            raise HTTPException(status_code=400, detail="This BYOK provider is not allowed by the administrator")
    preferences = vault.get_preferences(user_id)
    preferences[payload.service] = {
        "source": payload.source,
        **({"profile_id": payload.profile_id} if payload.profile_id else {}),
    }
    vault.save_preferences(user_id, preferences)
    return {"preferences": vault.get_preferences(user_id)}


@router.get("/admin/byok/policy")
async def get_admin_byok_policy(_: object = Depends(require_admin)) -> dict[str, Any]:
    policy = load_policy()
    return {
        "policy": normalize_policy(policy),
        "auth_enabled": auth_is_enabled(),
        "vault_available": _vault().is_available(),
    }


@router.put("/admin/byok/policy")
async def put_admin_byok_policy(
    payload: AdminByokPolicyRequest,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    policy = save_policy(payload.policy)
    return {"policy": policy, "auth_enabled": auth_is_enabled()}


@router.post("/admin/users/{user_id}/byok/suspend")
async def suspend_user_byok(
    user_id: str,
    payload: SuspendByokRequest,
    _: object = Depends(require_admin),
) -> dict[str, Any]:
    target = load_grant(user_id)
    byok = dict(target.get("byok") or {})
    byok[payload.service] = {"enabled": payload.enabled}
    target["byok"] = byok
    try:
        saved = save_grant(user_id, target)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"grant": saved}


__all__ = ["router"]
