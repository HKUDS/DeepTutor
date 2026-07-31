"""Request-scoped provider source selection.

This context carries only public references and accounting metadata.  Provider
secrets are resolved at the final runtime boundary from ``byok_vault``.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Literal

from .byok_policy import byok_runtime_enabled, grant_service_enabled
from .context import get_current_user
from .grants import load_grant

SourceKind = Literal["platform", "byok"]


@dataclass(frozen=True, slots=True)
class ExecutionSource:
    source: SourceKind
    service: str
    user_id: str
    profile_id: str | None = None
    profile_generation: int | None = None
    usage_origin: str = "platform"

    @property
    def is_platform(self) -> bool:
        return self.source == "platform"

    @property
    def is_byok(self) -> bool:
        return self.source == "byok"

    def public_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "service": self.service,
            "user_id": self.user_id,
            "profile_id": self.profile_id,
            "profile_generation": self.profile_generation,
            "usage_origin": self.usage_origin,
        }


_CURRENT_SOURCE: ContextVar[ExecutionSource | None] = ContextVar(
    "deeptutor_execution_source", default=None
)


def set_execution_source(source: ExecutionSource | None) -> Token[ExecutionSource | None]:
    return _CURRENT_SOURCE.set(source)


def reset_execution_source(token: Token[ExecutionSource | None]) -> None:
    _CURRENT_SOURCE.reset(token)


def get_execution_source() -> ExecutionSource | None:
    return _CURRENT_SOURCE.get()


def current_source_is_platform(
    service: str | None = None,
    *,
    config_source: str | None = None,
) -> bool:
    """Return whether a service uses platform billing/source semantics.

    Runtime clients should pass their explicit ``config_source`` whenever it is
    available.  The ContextVar fallback is retained only for legacy callers;
    an absent ContextVar has historically meant platform and must not be used
    to classify a config that already identifies itself as BYOK.
    """
    if config_source is not None:
        return config_source != "byok"
    source = get_execution_source()
    if source is None:
        return True
    # A source for a different service must not make this service look like a
    # BYOK call. This matters when a nested embedding/MinerU operation runs
    # during a turn whose LLM source has already been installed.
    if service is not None and source.service != service:
        return True
    return source.is_platform


def _profile_for(preferences: dict[str, Any], service: str, profiles: list[dict[str, Any]]) -> dict[str, Any] | None:
    preferred = preferences.get(service)
    preferred_id = preferred.get("profile_id") if isinstance(preferred, dict) else None
    if preferred_id:
        for profile in profiles:
            if str(profile.get("id") or "") == str(preferred_id):
                return profile
    return profiles[0] if profiles else None


def resolve_execution_source(
    service: str,
    *,
    requested_source: str | None = None,
    profile_id: str | None = None,
    profile_generation: int | None = None,
    grant: dict[str, Any] | None = None,
    preferences: dict[str, Any] | None = None,
    byok_profiles: list[dict[str, Any]] | None = None,
) -> ExecutionSource:
    """Resolve and validate a source for the authenticated request.

    BYOK wins when a valid profile exists and the user did not explicitly
    request platform.  The caller must provide already redacted profile
    metadata; this function never accepts or returns a credential.
    """
    if service not in {"llm", "embedding", "mineru"}:
        raise ValueError(f"Unsupported execution service: {service}")
    user = get_current_user()
    active_grant = grant if isinstance(grant, dict) else load_grant(user.id)
    prefs = preferences if isinstance(preferences, dict) else {}
    profiles = [item for item in (byok_profiles or []) if isinstance(item, dict)]
    preferred = prefs.get(service) if isinstance(prefs.get(service), dict) else {}
    source = str(requested_source or preferred.get("source") or "").strip().lower()

    selected_profile: dict[str, Any] | None = None
    if profile_id:
        selected_profile = next(
            (item for item in profiles if str(item.get("id") or "") == str(profile_id)),
            None,
        )
        if selected_profile is None:
            raise PermissionError("BYOK profile is not available to this user")
    elif source != "platform":
        selected_profile = _profile_for(prefs, service, profiles)

    if not source and selected_profile is not None:
        source = "byok"
    if not source:
        source = "platform"

    if source == "byok":
        if not byok_runtime_enabled(service) or not grant_service_enabled(active_grant, "byok", service):
            raise PermissionError("BYOK is not enabled for this account")
        if selected_profile is None:
            raise PermissionError("Configure a BYOK profile before selecting BYOK")
        generation = profile_generation
        if generation is None:
            try:
                generation = int(selected_profile.get("generation"))
            except (TypeError, ValueError):
                generation = None
        return ExecutionSource(
            source="byok",
            service=service,
            user_id=user.id,
            profile_id=str(selected_profile.get("id") or ""),
            profile_generation=generation,
            usage_origin="byok",
        )

    if source != "platform":
        raise ValueError("Execution source must be platform or byok")
    if not user.is_admin and not grant_service_enabled(active_grant, "platform", service):
        raise PermissionError("Platform access is not enabled for this account")
    return ExecutionSource(
        source="platform",
        service=service,
        user_id=user.id,
        usage_origin="platform",
    )


__all__ = [
    "ExecutionSource",
    "SourceKind",
    "current_source_is_platform",
    "get_execution_source",
    "reset_execution_source",
    "resolve_execution_source",
    "set_execution_source",
]
