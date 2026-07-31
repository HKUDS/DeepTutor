"""Normalized embedding configuration resolved from the model catalog."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config import resolve_embedding_runtime_config


@dataclass
class EmbeddingConfig:
    """Embedding runtime configuration."""

    model: str
    api_key: str
    base_url: str | None = None
    effective_url: str | None = None
    binding: str = "openai"
    provider_name: str = "openai"
    provider_mode: str = "standard"
    api_version: str | None = None
    extra_headers: dict[str, str] | None = None
    dim: int = 0
    send_dimensions: bool | None = None
    request_timeout: int = 60
    batch_size: int = 10
    batch_delay: float = 0.0
    # Accounting/source metadata is public reference data only. The API key
    # remains in the adapter instance and is never serialized with this object.
    source: str = "platform"
    profile_id: str | None = None
    profile_generation: int | None = None


def _get_byok_embedding_config() -> EmbeddingConfig | None:
    """Resolve the current user's BYOK embedding profile when applicable."""
    from deeptutor.multi_user.byok_policy import (
        allowed_binding,
        byok_runtime_enabled,
        grant_service_enabled,
        validate_endpoint,
    )
    from deeptutor.multi_user.byok_vault import ByokVaultError, UserByokCredentialVault
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.execution_source import (
        get_execution_source,
        resolve_execution_source,
    )
    from deeptutor.multi_user.grants import load_grant
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS
    from deeptutor.services.provider_registry import canonical_provider_name

    current = get_current_user()
    grant = load_grant(current.id)
    source = get_execution_source()
    vault = UserByokCredentialVault()
    profiles = vault.list_profiles(current.id, service="embedding")
    if not profiles:
        if not current.is_admin and not grant_service_enabled(
            grant, "platform", "embedding"
        ):
            raise ValueError(
                "No embedding source is enabled for your account. Configure BYOK or contact an administrator."
            )
        return None
    preferences = vault.get_preferences(current.id)
    try:
        resolved_source = source
        if resolved_source is None or resolved_source.service != "embedding":
            resolved_source = resolve_execution_source(
                "embedding",
                grant=grant,
                preferences=preferences,
                byok_profiles=profiles,
            )
        if not resolved_source.is_byok:
            if not current.is_admin and not grant_service_enabled(
                grant, "platform", "embedding"
            ):
                raise ValueError(
                    "Platform embedding access is not enabled for your account."
                )
            return None
        profile, secret = vault.load_secret(current.id, str(resolved_source.profile_id))
    except ByokVaultError as exc:
        raise ValueError("The selected BYOK embedding profile is unavailable; update your BYOK settings.") from exc

    raw_provider = str(profile.get("provider") or "").strip().lower()
    provider = canonical_provider_name(raw_provider) or raw_provider
    if not byok_runtime_enabled("embedding") or not allowed_binding("embedding", provider):
        raise ValueError("Embedding BYOK is not enabled for this provider")
    model = str(profile.get("model") or "").strip()
    if not model:
        raise ValueError("Embedding BYOK profile must specify a model")
    spec = EMBEDDING_PROVIDERS.get(provider)
    if spec is None:
        raise ValueError("Unsupported embedding BYOK provider")
    endpoint = str(profile.get("base_url") or "").strip() or spec.default_api_base
    validated_endpoint = validate_endpoint(endpoint, service="embedding", binding=provider)
    if not validated_endpoint:
        raise ValueError("Embedding BYOK profile has no usable endpoint")
    endpoint = validated_endpoint
    dimension = int(profile.get("dimension") or 0)
    return EmbeddingConfig(
        model=model,
        api_key=secret,
        base_url=endpoint,
        effective_url=endpoint,
        binding=provider,
        provider_name=provider,
        provider_mode=spec.mode,
        dim=max(0, dimension),
        source="byok",
        profile_id=str(profile.get("id") or ""),
        profile_generation=int(profile.get("generation") or 0),
    )


def get_embedding_config() -> EmbeddingConfig:
    """Load embedding config from provider runtime resolver."""
    byok = _get_byok_embedding_config()
    if byok is not None:
        return byok
    resolved = resolve_embedding_runtime_config()

    if not resolved.model:
        raise ValueError("Embedding model not set. Please configure it in Settings > Catalog.")

    if not resolved.effective_url:
        raise ValueError(
            "No effective embedding endpoint resolved. Please configure base_url/host for the active profile."
        )

    if resolved.provider_mode != "local" and not resolved.api_key:
        raise ValueError(
            "Embedding API key not set. Please configure the active profile in Settings > Catalog."
        )

    return EmbeddingConfig(
        model=resolved.model,
        api_key=resolved.api_key,
        base_url=resolved.base_url,
        effective_url=resolved.effective_url,
        binding=resolved.binding,
        provider_name=resolved.provider_name,
        provider_mode=resolved.provider_mode,
        api_version=resolved.api_version,
        extra_headers=resolved.extra_headers,
        dim=resolved.dimension,
        send_dimensions=resolved.send_dimensions,
        request_timeout=max(1, resolved.request_timeout),
        batch_size=max(1, resolved.batch_size),
        batch_delay=max(0.0, resolved.batch_delay),
    )
