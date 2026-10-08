"""Validated, non-interactive setup using the shared runtime settings services."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Annotated
from urllib.parse import parse_qsl, urlparse

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from deeptutor.runtime.home import (
    DEEPTUTOR_HOME_ENV,
    get_runtime_home,
    validate_runtime_home,
)
from deeptutor.services.provider_registry import ApiFormat

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Port = Annotated[int, Field(strict=True, ge=1, le=65535)]


class _SetupSection(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSetup(_SetupSection):
    provider: NonEmptyString
    model: NonEmptyString
    base_url: NonEmptyString | None = None
    api_key_env: NonEmptyString | None = None
    api_version: str = ""
    api_format: ApiFormat | None = None
    dimension: Annotated[int, Field(strict=True, gt=0)] | None = None


class SearchSetup(_SetupSection):
    provider: NonEmptyString
    base_url: NonEmptyString | None = None
    api_key_env: NonEmptyString | None = None


class SystemSetup(_SetupSection):
    backend_port: Port | None = None
    frontend_port: Port | None = None


class SetupConfig(_SetupSection):
    llm: ModelSetup | None = None
    embedding: ModelSetup | None = None
    search: SearchSetup | None = None
    system: SystemSetup | None = None

    @model_validator(mode="after")
    def require_changes(self) -> SetupConfig:
        if not any((self.llm, self.embedding, self.search, self.system)):
            raise ValueError("Provide at least one of llm, embedding, search, or system.")
        if self.system is not None and not self.system.model_dump(exclude_none=True):
            raise ValueError("system must specify at least one port.")
        return self


def select_runtime_home(home: str | Path | None) -> Path:
    """Select the target before importing services that cache settings paths."""
    from .init_cmd import _reset_runtime_singletons

    runtime_home = get_runtime_home(home)
    validate_runtime_home(runtime_home)
    os.environ[DEEPTUTOR_HOME_ENV] = str(runtime_home)
    _reset_runtime_singletons()
    return runtime_home


def _api_key(env_name: str | None, *, required: bool, section: str) -> str:
    if env_name is None:
        if required:
            raise ValueError(f"{section}.api_key_env is required for this provider.")
        return ""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise ValueError(f"{section}.api_key_env must be an environment variable name.")
    value = os.environ.get(env_name, "")
    if not value.strip():
        raise ValueError(
            f"The environment variable named by {section}.api_key_env is empty or unset."
        )
    return value


def _validate_endpoint(endpoint: str, section: str) -> None:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{section}.base_url must be an HTTP(S) URL.")
    if (
        parsed.username is not None
        or parsed.password is not None
        or any(
            key.lower() in {"access_token", "api_key", "key", "token"}
            for key, _ in parse_qsl(parsed.query)
        )
    ):
        raise ValueError(f"{section}.base_url must not contain credentials; use api_key_env.")


def prepare_profiles(config: SetupConfig) -> dict[str, dict]:
    """Resolve credentials and validate every section before any settings writes."""
    from deeptutor.services.config.embedding_endpoint import (
        normalize_embedding_endpoint_for_display,
    )
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS, SEARCH_PROVIDERS
    from deeptutor.services.provider_registry import find_by_name

    profiles: dict[str, dict] = {}
    for section in ("llm", "embedding"):
        choice = getattr(config, section)
        if choice is None:
            continue
        provider = choice.provider.lower()
        llm_spec = find_by_name(provider) if section == "llm" else None
        spec = llm_spec if section == "llm" else EMBEDDING_PROVIDERS.get(provider)
        if spec is None:
            raise ValueError(f"Unsupported {section} provider. See 'deeptutor config providers'.")
        if section == "llm" and choice.dimension is not None:
            raise ValueError("dimension is only supported in the embedding section.")
        if section == "embedding" and choice.api_format is not None:
            raise ValueError("api_format is only supported in the llm section.")
        if llm_spec is not None and choice.api_format is not None:
            allowed = llm_spec.api_formats or (llm_spec.default_api_format,)
            if choice.api_format not in allowed:
                raise ValueError("llm.api_format is not supported by this provider.")
        default_endpoint = spec.default_api_base
        if llm_spec is not None and choice.api_format is not None:
            default_endpoint = dict(llm_spec.api_base_by_format).get(
                choice.api_format, default_endpoint
            )
        endpoint = choice.base_url or default_endpoint
        if section == "embedding":
            endpoint = normalize_embedding_endpoint_for_display(
                provider, endpoint, model=choice.model
            )
        if not endpoint and not (llm_spec is not None and llm_spec.is_oauth):
            raise ValueError(f"{section}.base_url is required for this provider.")
        if endpoint:
            _validate_endpoint(endpoint, section)
        requires_key = (
            not spec.is_local and provider != "custom" and not getattr(spec, "is_oauth", False)
        )
        key = _api_key(choice.api_key_env, required=requires_key, section=section)
        model = {"id": f"{section}-model-agent-setup", "name": choice.model, "model": choice.model}
        if choice.dimension is not None:
            model["dimension"] = choice.dimension
        profile = {
            "id": f"{section}-profile-agent-setup",
            "name": "Agent Setup",
            "binding": provider,
            "base_url": endpoint,
            "api_key": key,
            "api_version": choice.api_version,
            "extra_headers": {},
            "models": [model],
        }
        if choice.api_format is not None:
            profile["api_format"] = choice.api_format
        profiles[section] = profile

    if config.search is not None:
        choice = config.search
        provider = choice.provider.lower()
        search_spec = SEARCH_PROVIDERS.get(provider)
        if search_spec is None:
            raise ValueError("Unsupported search provider. See 'deeptutor config providers'.")
        endpoint = choice.base_url or ""
        if search_spec.requires_base_url and not endpoint:
            raise ValueError("search.base_url is required for this provider.")
        if endpoint:
            _validate_endpoint(endpoint, "search")
        profiles["search"] = {
            "id": "search-profile-agent-setup",
            "name": "Agent Setup",
            "provider": provider,
            "base_url": endpoint,
            "api_key": _api_key(
                choice.api_key_env, required=search_spec.requires_api_key, section="search"
            ),
        }
    return profiles


def _read_settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError(f"Existing settings file is not valid JSON: {path}") from None
    if not isinstance(payload, dict):
        raise ValueError(f"Existing settings file must contain a JSON object: {path}")
    return payload


def prepare_system(config: SetupConfig) -> dict | None:
    from deeptutor.services.config import get_model_catalog_service, get_runtime_settings_service
    from deeptutor.services.config.runtime_settings import DEFAULT_SYSTEM_SETTINGS

    # Refuse to replace an unreadable catalog with defaults during setup.
    if config.llm or config.embedding or config.search:
        _read_settings(get_model_catalog_service().path)
    if config.system is None:
        return None
    runtime = get_runtime_settings_service()
    system = {**DEFAULT_SYSTEM_SETTINGS, **_read_settings(runtime.path_for("system"))}
    system.update(config.system.model_dump(exclude_none=True))
    if system["backend_port"] == system["frontend_port"]:
        raise ValueError("Backend and frontend ports must be different.")
    return system


def apply_setup(profiles: dict[str, dict], system: dict | None) -> None:
    """Update only supplied services in dedicated, repeatable setup profiles."""
    from deeptutor.services.config import get_model_catalog_service, get_runtime_settings_service

    if profiles:

        def update_catalog(catalog: dict) -> None:
            for section, profile in profiles.items():
                service = catalog["services"][section]
                existing = service["profiles"]
                index = next(
                    (i for i, row in enumerate(existing) if row.get("id") == profile["id"]), None
                )
                if index is None:
                    existing.append(profile)
                else:
                    existing[index] = profile
                service["active_profile_id"] = profile["id"]
                if section != "search":
                    service["active_model_id"] = profile["models"][0]["id"]

        get_model_catalog_service().update(update_catalog)
    if system is not None:
        get_runtime_settings_service().save_system(system)


def provider_options() -> dict:
    """Machine-readable provider choices derived from the runtime registries."""
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS, SEARCH_PROVIDERS
    from deeptutor.services.provider_registry import PROVIDERS

    return {
        "llm": [
            {
                "provider": spec.name,
                "base_url": spec.default_api_base,
                "auth": spec.mode,
                "api_formats": list(spec.api_formats),
            }
            for spec in PROVIDERS
            if not spec.is_legacy
        ],
        "embedding": [
            {"provider": name, "base_url": spec.default_api_base, "local": spec.is_local}
            for name, spec in EMBEDDING_PROVIDERS.items()
        ],
        "search": [
            {
                "provider": name,
                "requires_api_key": spec.requires_api_key,
                "requires_base_url": spec.requires_base_url,
            }
            for name, spec in SEARCH_PROVIDERS.items()
        ],
    }
