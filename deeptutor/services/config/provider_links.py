"""Provider references layered over legacy profiles, preserving all model IDs.

A legacy profile remains a provider source. New connections and models refer to
sources by identity, never by vendor, URL, or masked credential equality.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

CREDENTIAL_FIELDS = ("api_key", "api_version", "extra_headers", "proxy", "app_id")
PROVIDER_FIELDS = (
    "name",
    "provider",
    "binding",
    "base_url",
    "api_format",
    "wire_api",
    *CREDENTIAL_FIELDS,
    "discovery",
    "source_service",
    "service_overrides",
    "user_name",
)


def provider_source(catalog: dict, ref: dict) -> tuple[dict, str | None]:
    if ref.get("connection_id"):
        for source in catalog.get("connections", []):
            if source.get("id") == ref["connection_id"]:
                return source, source.get("source_service")
    elif ref.get("service") and ref.get("profile_id"):
        for source in catalog.get("services", {}).get(ref["service"], {}).get("profiles", []):
            if source.get("id") == ref["profile_id"] and not source.get("provider_ref"):
                return source, ref["service"]
    raise ValueError("This provider is no longer configured. Choose an existing provider.")


def provider_endpoint(
    url: str, source_service: str | None, service: str, binding: str = "custom"
) -> str:
    """Keep legacy endpoints exact for their original use; derive only new uses."""
    if service == source_service or {service, source_service} <= {"llm", "task"}:
        return url
    base = url.rstrip("/")
    for suffix in (
        "/embeddings",
        "/api/embed",
        "/api/embeddings",
        "/v2/embed",
        "/audio/speech",
        "/audio/transcriptions",
        "/tts/unidirectional/sse",
        "/tts/unidirectional",
        "/auc/bigmodel/recognize/flash",
        "/images/generations",
        "/videos/generations",
        "/chat/completions",
        "/responses",
        "/messages",
    ):
        if base.endswith(suffix):
            base = base.removesuffix(suffix)
            break
    if service == "embedding" and base:
        from urllib.parse import urlsplit, urlunsplit

        parsed = urlsplit(base)
        if binding == "ollama":
            path = parsed.path.removesuffix("/v1").removesuffix("/api") + "/api/embed"
        elif binding == "cohere":
            path = (
                parsed.path.removesuffix("/v1").removesuffix("/v2").removesuffix("/embed")
                + "/v2/embed"
            )
        else:
            path = parsed.path + "/embeddings"
        return urlunsplit(parsed._replace(path=path))
    return base


def _source_default_url(source: dict, service: str | None) -> str:
    """Recognize registry defaults before translating across native protocols."""
    from deeptutor.services.config.provider_runtime import (
        EMBEDDING_PROVIDERS,
        IMAGEGEN_PROVIDERS,
        STT_PROVIDERS,
        TTS_PROVIDERS,
        VIDEOGEN_PROVIDERS,
    )
    from deeptutor.services.provider_registry import (
        api_format_for_provider,
        api_format_from_legacy,
        find_by_name,
    )

    binding = source.get("binding") or source.get("provider") or ""
    if service in {"llm", "task"}:
        spec = find_by_name(binding)
        if spec:
            api_format = (
                api_format_for_provider(source["api_format"], spec)
                if source.get("api_format") is not None
                else api_format_from_legacy(spec, source.get("wire_api"))
            )
            return spec.default_api_base_for(api_format)
    else:
        tables: dict[str, Any] = {
            "embedding": EMBEDDING_PROVIDERS,
            "tts": TTS_PROVIDERS,
            "stt": STT_PROVIDERS,
            "imagegen": IMAGEGEN_PROVIDERS,
            "videogen": VIDEOGEN_PROVIDERS,
        }
        spec = tables.get(service, {}).get(binding)
    return getattr(spec, "default_api_base", "") or ""


def resolve_profile_provider(
    catalog: dict, service: str, profile: dict, model: dict | None = None
) -> dict:
    ref = (model or {}).get("provider_ref") or profile.get("provider_ref")
    if not isinstance(ref, dict):
        overrides = profile.get("service_overrides")
        override = (
            overrides.get("llm" if service == "task" else service)
            if isinstance(overrides, dict)
            else None
        )
        if not isinstance(override, dict) or not override.get("enabled"):
            return profile
        result = deepcopy(profile)
        if override.get("binding"):
            result["provider" if service == "search" else "binding"] = override["binding"]
        if override.get("base_url"):
            result["base_url"] = override["base_url"]
        return result
    source, source_service = provider_source(catalog, ref)
    result = deepcopy(profile)
    overrides = source.get("service_overrides")
    override = (
        overrides.get("llm" if service == "task" else service, {})
        if isinstance(overrides, dict)
        else {}
    )
    if not isinstance(override, dict) or not override.get("enabled"):
        override = {}
    binding = (
        override.get("binding")
        or ref.get("binding")
        or source.get("binding")
        or source.get("provider")
        or "custom"
    )
    result["provider" if service == "search" else "binding"] = binding
    for field in CREDENTIAL_FIELDS:
        result[field] = deepcopy(source.get(field, {} if field == "extra_headers" else ""))
    # An empty provider URL deliberately uses the service's registry default.
    source_url = str(source.get("base_url") or "")
    target_default = (
        _source_default_url({"binding": binding}, service)
        if override.get("binding") and binding != ref.get("binding")
        else ref.get("default_base_url", "")
    )
    if service in {"llm", "task"}:
        # References may have been created before the connection changed
        # protocol. Resolve the current vendor default instead of freezing the
        # address captured on the model; explicit connection URLs still win.
        target_default = (
            _source_default_url({**source, "binding": binding}, service) or target_default
        )
    result["base_url"] = (
        provider_endpoint(source_url, source_service, service, binding)
        if source_url
        else target_default
    )
    uses_default = not source_url
    if source_url and source_service != service and target_default:
        default = _source_default_url(source, source_service)
        if default and source_url.rstrip("/") == default.rstrip("/"):
            result["base_url"] = target_default
            uses_default = True
    if override.get("base_url"):
        result["base_url"] = str(override["base_url"])
        uses_default = False
    if service == "embedding":
        from .embedding_endpoint import normalize_embedding_endpoint_for_display

        if uses_default and binding == "gemini":
            result["base_url"] = ""
        result["base_url"] = normalize_embedding_endpoint_for_display(
            binding, result["base_url"], (model or {}).get("model")
        )
    for field in ("api_format", "wire_api"):
        result[field] = source.get(field) or "auto"
    if source.get("owner_bound"):
        result["owner_bound"] = True
    result["name"] = source.get("name") or profile.get("name", "")
    return result


def referenced_models(catalog: dict, ref: dict) -> list[tuple[str, str, str | None]]:
    result = []
    for service, bucket in catalog.get("services", {}).items():
        for profile in bucket.get("profiles", []):
            inherited = profile.get("provider_ref") or (
                {"connection_id": profile["connection_id"]}
                if profile.get("connection_id")
                else {"service": service, "profile_id": profile["id"]}
            )
            models = (
                profile.get("models", [])
                if service != "search"
                else ([{}] if not profile.get("provider_only") else [])
            )
            for model in models:
                source = model.get("provider_ref") or inherited
                identity = (
                    source.get("connection_id"),
                    source.get("service"),
                    source.get("profile_id"),
                )
                if identity == (
                    ref.get("connection_id"),
                    ref.get("service"),
                    ref.get("profile_id"),
                ):
                    result.append((service, profile["id"], model.get("id")))
    return result
