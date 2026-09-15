"""Value-free Settings profile export and review-only import diff.

Profiles carry selections, model anchors, and non-secret configuration
knobs.  Deployment endpoints, local paths, and credentials never enter the
profile; an imported profile can therefore be reviewed without exposing any
of those values.  This module deliberately has no write path.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .model_catalog import get_model_catalog_service
from .runtime_settings import RuntimeSettingsService, get_runtime_settings_service

PROFILE_SCHEMA_VERSION = "deeptutor.settings-profile/v1"

_SECRET_FIELD_HINTS = (
    "api_key",
    "apikey",
    "api_token",
    "extra_headers",
    "password",
    "secret",
)
_DEPLOYMENT_FIELD_HINTS = (
    "url",
    "endpoint",
    "path",
    "host",
    "origin",
    "port",
    "dir",
)
_DEPLOYMENT_FIELD_PREFIXES = ("cors_",)
_SYSTEM_FIELDS = (
    "version_check_enabled",
    "backend_workers",
    "disable_ssl_verify",
    "sandbox_allow_subprocess",
    "capability_routing_enabled",
    "web_search_source_filtering",
    "chat_attachment_max_file_mb",
    "chat_attachment_max_total_mb",
    "chat_attachment_max_chars_per_doc",
    "chat_attachment_max_chars_total",
)
_AUTH_FIELDS = ("enabled", "token_expire_hours", "cookie_secure")
_COORDINATION_FIELDS = (
    "backend",
    "key_prefix",
    "lease_ttl_seconds",
    "renew_interval_seconds",
    "recovery_interval_seconds",
    "stream_retention_seconds",
)
_CATALOG_EXCLUDED_FIELDS = {"base_url"}


class SettingsProfileError(ValueError):
    """The submitted profile is not an export produced by this schema."""


def _is_secret_field(name: str) -> bool:
    normalized = name.lower()
    return any(hint in normalized for hint in _SECRET_FIELD_HINTS)


def _is_deployment_field(name: str) -> bool:
    normalized = name.lower()
    return normalized.startswith(_DEPLOYMENT_FIELD_PREFIXES) or any(
        normalized == hint or normalized.endswith(f"_{hint}") for hint in _DEPLOYMENT_FIELD_HINTS
    )


def _public_value(value: Any) -> Any:
    """Redact credentials and deployment values from untrusted diff output."""

    if isinstance(value, dict):
        public: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_field(str(key)):
                public[key] = {"present": bool(item)}
            elif _is_deployment_field(str(key)):
                public[key] = None
            else:
                public[key] = _public_value(item)
        return public
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    return value


def _value_presence(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value)
    if isinstance(value, (dict, list, tuple, set)):
        return bool(value)
    return True


def _selected_fields(settings: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: deepcopy(settings[field]) for field in fields if field in settings}


def _catalog_profile(profile: dict[str, Any]) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for key, value in profile.items():
        if key in _CATALOG_EXCLUDED_FIELDS:
            continue
        if key == "extra_headers":
            headers = value if isinstance(value, dict) else {}
            public[key] = {
                header: {"present": _value_presence(item)} for header, item in headers.items()
            }
        elif _is_secret_field(key):
            public[key] = {"present": _value_presence(value)}
        else:
            public[key] = _public_value(value)
    return public


def _catalog_profile_settings(catalog: dict[str, Any]) -> dict[str, Any]:
    services = catalog.get("services")
    services = services if isinstance(services, dict) else {}
    public_services: dict[str, Any] = {}
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        profiles = service.get("profiles")
        profiles = profiles if isinstance(profiles, list) else []
        public_services[name] = {
            "active_profile_id": deepcopy(service.get("active_profile_id")),
            "active_model_id": deepcopy(service.get("active_model_id")),
            "profiles": [
                _catalog_profile(profile) for profile in profiles if isinstance(profile, dict)
            ],
        }
    return {"services": public_services}


def _document_parsing_profile(settings: dict[str, Any]) -> dict[str, Any]:
    engines = settings.get("engines")
    engines = engines if isinstance(engines, dict) else {}
    public_engines: dict[str, Any] = {}
    for name, engine in engines.items():
        if not isinstance(engine, dict):
            continue
        if name == "tika":
            public_engines[name] = {"server_url_present": _value_presence(engine.get("server_url"))}
            continue
        public = {
            key: deepcopy(value)
            for key, value in engine.items()
            if not _is_secret_field(key) and not _is_deployment_field(key)
        }
        public_engines[name] = public
    return {
        "engine": deepcopy(settings.get("engine")),
        "engines": public_engines,
    }


def _integrations_profile(settings: dict[str, Any]) -> dict[str, Any]:
    coordination = settings.get("turn_coordination")
    coordination = coordination if isinstance(coordination, dict) else {}
    return {
        "turn_coordination": _selected_fields(coordination, _COORDINATION_FIELDS),
    }


def _effective_profile(
    service: RuntimeSettingsService,
    *,
    catalog: dict[str, Any],
) -> dict[str, Any]:
    return {
        "settings": {
            "system": _selected_fields(
                service.load_system(include_process_overrides=True), _SYSTEM_FIELDS
            ),
            "auth": _selected_fields(
                service.load_auth(include_process_overrides=True), _AUTH_FIELDS
            ),
            "integrations": _integrations_profile(
                service.load_integrations(include_process_overrides=True)
            ),
            "document_parsing": _document_parsing_profile(
                service.load_document_parsing(include_process_overrides=True)
            ),
            "llamaindex": deepcopy(service.load_llamaindex(include_process_overrides=True)),
            "graphrag": deepcopy(service.load_graphrag()),
            "lightrag": deepcopy(service.load_lightrag()),
            "catalog": _catalog_profile_settings(catalog),
        }
    }


def export_settings_profile(
    *,
    service: RuntimeSettingsService | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the effective, value-free profile for API export."""

    runtime_service = service or get_runtime_settings_service()
    catalog_service = catalog or get_model_catalog_service().load()
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "profile": _effective_profile(runtime_service, catalog=catalog_service),
    }


def _join_path(parent: str, key: Any) -> str:
    if not parent:
        return str(key)
    return f"{parent}.{key}"


def _path_kind(key: str) -> str | None:
    if _is_secret_field(key):
        return "secret_not_exported"
    if _is_deployment_field(key):
        return "deployment_value_not_exported"
    return None


def _is_presence_anchor(value: Any) -> bool:
    return (
        isinstance(value, dict) and set(value) == {"present"} and isinstance(value["present"], bool)
    )


def _is_secret_anchor(value: Any) -> bool:
    if _is_presence_anchor(value):
        return True
    return (
        bool(value)
        and isinstance(value, dict)
        and all(_is_presence_anchor(item) for item in value.values())
    )


def _diff_settings(
    proposed: Any,
    current: Any,
    *,
    path: str,
    changes: list[dict[str, Any]],
    unsupported: list[dict[str, Any]],
) -> None:
    if isinstance(proposed, dict):
        if not isinstance(current, dict):
            unsupported.append({"path": path, "reason": "type_mismatch"})
            return
        for key, child in proposed.items():
            child_path = _join_path(path, key)
            reason = _path_kind(str(key))
            if (
                reason == "secret_not_exported"
                and _is_secret_anchor(child)
                and _is_secret_anchor(current.get(key))
            ):
                reason = None
            if reason is not None:
                unsupported.append({"path": child_path, "reason": reason})
                continue
            if key not in current:
                unsupported.append({"path": child_path, "reason": "unknown_field"})
                continue
            _diff_settings(
                child,
                current[key],
                path=child_path,
                changes=changes,
                unsupported=unsupported,
            )
        return

    if (
        isinstance(proposed, list)
        and isinstance(current, list)
        and len(proposed) == len(current)
        and all(
            isinstance(item, dict) and isinstance(current[index], dict)
            for index, item in enumerate(proposed)
        )
    ):
        for index, child in enumerate(proposed):
            _diff_settings(
                child,
                current[index],
                path=_join_path(path, index),
                changes=changes,
                unsupported=unsupported,
            )
        return

    if isinstance(proposed, list) and isinstance(current, list) and len(proposed) != len(current):
        unsupported.append({"path": path, "reason": "list_length_changed"})
        return

    if proposed != current:
        changes.append(
            {
                "path": path,
                "kind": "changed",
                "current": _public_value(current),
                "proposed": _public_value(proposed),
            }
        )


def review_settings_profile_import(
    payload: dict[str, Any],
    *,
    service: RuntimeSettingsService | None = None,
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an exported profile and compare it with effective settings."""

    if not isinstance(payload, dict):
        raise SettingsProfileError("profile payload must be an object")
    if payload.get("schema_version") != PROFILE_SCHEMA_VERSION:
        raise SettingsProfileError(f"unsupported schema_version: expected {PROFILE_SCHEMA_VERSION}")
    profile = payload.get("profile")
    if not isinstance(profile, dict) or not isinstance(profile.get("settings"), dict):
        raise SettingsProfileError("profile.settings must be an object")
    unknown_profile_fields = set(profile) - {"settings"}
    if unknown_profile_fields:
        raise SettingsProfileError(
            f"unknown profile fields: {', '.join(sorted(unknown_profile_fields))}"
        )

    runtime_service = service or get_runtime_settings_service()
    catalog_value = catalog or get_model_catalog_service().load()
    current = _effective_profile(runtime_service, catalog=catalog_value)
    proposed = deepcopy(profile)
    changes: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    _diff_settings(
        proposed["settings"],
        current["settings"],
        path="settings",
        changes=changes,
        unsupported=unsupported,
    )
    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "changes": sorted(changes, key=lambda item: item["path"]),
        "unsupported": sorted(unsupported, key=lambda item: item["path"]),
        "summary": {
            "changed": len(changes),
            "unsupported": len(unsupported),
            "compatible": not unsupported,
        },
    }


__all__ = [
    "PROFILE_SCHEMA_VERSION",
    "SettingsProfileError",
    "export_settings_profile",
    "review_settings_profile_import",
]
