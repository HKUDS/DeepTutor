"""Deployment-wide BYOK policy and endpoint safety checks."""

from __future__ import annotations

from collections.abc import Mapping
import ipaddress
import json
import os
from pathlib import Path
import socket
from typing import Any
from urllib.parse import urlparse

from deeptutor.services.config import load_auth_settings
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.provider_registry import find_by_name

from . import paths

POLICY_FILENAME = "byok_policy.v1.json"
SERVICES = ("llm", "embedding", "mineru")

DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "enabled": True,
    "default_source": {service: "byok" for service in SERVICES},
    "services": {
        "llm": {
            "enabled": True,
            "allowed_bindings": ["openai", "anthropic", "gemini", "openrouter"],
            "allow_custom_endpoints": False,
        },
        "embedding": {
            "enabled": True,
            "allowed_bindings": [
                "openai",
                "gemini",
                "openrouter",
                "jina",
                "cohere",
                "siliconflow",
                "aliyun",
            ],
            "allow_custom_endpoints": False,
        },
        "mineru": {"enabled": True, "allow_cloud": True, "allowed_bindings": ["mineru"]},
    },
    "endpoint_allowlist": [],
    "limits": {
        "byok_requests_per_minute": 60,
        "max_single_request_tokens": 64_000,
        "max_pages_per_file": 50,
    },
}


def policy_path() -> Path:
    paths.ensure_system_dirs()
    return paths.SYSTEM_ROOT / POLICY_FILENAME


def _copy_default() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_POLICY))


def _clean_bindings(value: Any, fallback: list[str]) -> list[str]:
    if not isinstance(value, list):
        return list(fallback)
    return sorted({str(item).strip().lower() for item in value if str(item).strip()})


def normalize_policy(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {}
    policy = _copy_default()
    policy["enabled"] = bool(raw.get("enabled", policy["enabled"]))
    defaults = raw.get("default_source")
    if isinstance(defaults, Mapping):
        for service in SERVICES:
            source = str(defaults.get(service) or "").strip().lower()
            if source in {"platform", "byok"}:
                policy["default_source"][service] = source
    service_values = raw.get("services")
    if isinstance(service_values, Mapping):
        for service in SERVICES:
            incoming = service_values.get(service)
            if not isinstance(incoming, Mapping):
                continue
            current = policy["services"][service]
            current["enabled"] = bool(incoming.get("enabled", current.get("enabled", True)))
            current["allowed_bindings"] = _clean_bindings(
                incoming.get("allowed_bindings"), current.get("allowed_bindings", [])
            )
            if service != "mineru":
                current["allow_custom_endpoints"] = bool(
                    incoming.get("allow_custom_endpoints", current.get("allow_custom_endpoints", False))
                )
            else:
                current["allow_cloud"] = bool(incoming.get("allow_cloud", current.get("allow_cloud", True)))
    endpoints = raw.get("endpoint_allowlist")
    if isinstance(endpoints, list):
        policy["endpoint_allowlist"] = sorted(
            {str(item).strip().rstrip("/") for item in endpoints if str(item).strip()}
        )
    limits = raw.get("limits")
    if isinstance(limits, Mapping):
        for key, default in policy["limits"].items():
            try:
                parsed = int(limits.get(key, default))
            except (TypeError, ValueError):
                parsed = int(default)
            policy["limits"][key] = max(0, parsed)
    policy["version"] = 1
    return policy


def load_policy() -> dict[str, Any]:
    raw: Any = None
    path = policy_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = None
    policy = normalize_policy(raw)
    env_enabled = os.getenv("DEEPTUTOR_BYOK_ENABLED")
    if env_enabled is not None:
        policy["enabled"] = env_enabled.strip().lower() in {"1", "true", "yes", "on"}
    return policy


def save_policy(value: Mapping[str, Any]) -> dict[str, Any]:
    policy = normalize_policy(value)
    atomic_write_json(policy_path(), policy)
    return policy


def auth_is_enabled() -> bool:
    return bool(load_auth_settings().get("enabled"))


def byok_runtime_enabled(service: str, policy: Mapping[str, Any] | None = None) -> bool:
    if service not in SERVICES or not auth_is_enabled():
        return False
    current = normalize_policy(policy if policy is not None else load_policy())
    service_policy = current["services"].get(service, {})
    if not current["enabled"] or not bool(service_policy.get("enabled", False)):
        return False
    if service == "mineru" and not bool(service_policy.get("allow_cloud", False)):
        return False
    return True


def allowed_binding(service: str, binding: str, policy: Mapping[str, Any] | None = None) -> bool:
    if service not in SERVICES:
        return False
    current = normalize_policy(policy if policy is not None else load_policy())
    configured = set(current["services"].get(service, {}).get("allowed_bindings", []))
    candidate = str(binding or "").strip().lower()
    try:
        from deeptutor.services.provider_registry import canonical_provider_name

        candidate = canonical_provider_name(candidate) or candidate
    except Exception:
        pass
    return candidate in configured or str(binding or "").strip().lower() in configured


def official_endpoint(binding: str, service: str | None = None) -> str | None:
    if str(binding or "").strip().lower() == "mineru":
        return "https://mineru.net"
    if service == "embedding":
        try:
            from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS

            spec = EMBEDDING_PROVIDERS.get(str(binding or "").strip().lower())
            value = getattr(spec, "default_api_base", None) if spec is not None else None
            return str(value).rstrip("/") if value else None
        except Exception:
            return None
    spec = find_by_name(str(binding or "").strip())
    value = getattr(spec, "default_api_base", None) if spec is not None else None
    return str(value).rstrip("/") if value else None


def _is_blocked_address(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        # Hostnames are checked after DNS resolution below.  Treating every
        # non-literal hostname as blocked here would reject all public
        # providers before their addresses can be inspected.
        return False
    return bool(
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or ip in ipaddress.ip_network("100.64.0.0/10")
    )


def validate_endpoint(
    endpoint: str | None,
    *,
    service: str,
    binding: str,
    policy: Mapping[str, Any] | None = None,
    resolve_dns: bool = True,
) -> str | None:
    """Validate and normalize a user-controlled provider endpoint.

    The endpoint is optional when the provider registry supplies the official
    endpoint.  Custom endpoints require admin policy and are still subject to
    DNS/IP checks both here and at the eventual outbound connector boundary.
    """
    if not endpoint:
        return None
    value = str(endpoint).strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("BYOK endpoint must be an HTTPS URL without embedded credentials")
    if parsed.fragment or parsed.query:
        raise ValueError("BYOK endpoint must not contain a query or fragment")
    hostname = parsed.hostname
    if _is_blocked_address(hostname):
        raise ValueError("BYOK endpoint resolves to a blocked network address")
    if resolve_dns:
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise ValueError("BYOK endpoint DNS resolution failed") from exc
        if not addresses or any(_is_blocked_address(address) for address in addresses):
            raise ValueError("BYOK endpoint resolves to a blocked network address")
    current = normalize_policy(policy if policy is not None else load_policy())
    service_policy = current["services"].get(service, {})
    official = official_endpoint(binding, service)
    allowlisted = value in set(current.get("endpoint_allowlist", []))
    if value != official and not bool(service_policy.get("allow_custom_endpoints", False)) and not allowlisted:
        raise ValueError("This BYOK provider endpoint is not allowed by the administrator")
    return value


def grant_service_enabled(grant: Mapping[str, Any], source: str, service: str) -> bool:
    if source == "byok":
        return bool((grant.get("byok") or {}).get(service, {}).get("enabled", False))
    if source == "platform":
        if service == "llm":
            return bool((grant.get("models") or {}).get("llm"))
        return bool((grant.get("platform") or {}).get(service, {}).get("enabled", False))
    return False


__all__ = [
    "DEFAULT_POLICY",
    "SERVICES",
    "allowed_binding",
    "auth_is_enabled",
    "byok_runtime_enabled",
    "grant_service_enabled",
    "load_policy",
    "normalize_policy",
    "official_endpoint",
    "policy_path",
    "save_policy",
    "validate_endpoint",
]
