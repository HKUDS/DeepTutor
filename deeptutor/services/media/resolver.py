"""Resolve a durable job to a secret-bearing adapter config (MED-02).

The durable job never persists credentials (§10.5); at execution time this
module reads the model catalog's ``imagegen`` service and hands the adapter the
base URL / api key / model / provider capabilities for exactly that call.
The resolver is injectable so offline tests never touch a real catalog.
"""

from __future__ import annotations

from typing import Any, Callable

from deeptutor.services.config.model_catalog import get_model_catalog_service
from deeptutor.services.config.provider_runtime import (
    IMAGEGEN_PROVIDERS,
    _canonical_generation_provider,
)
from deeptutor.services.media.adapter_config import (
    ADAPTER_MCP,
    ADAPTER_OPENAI_IMAGES,
    ADAPTER_OPENAI_RESPONSES,
    AdapterConfigResolver,
    AdapterRuntimeConfig,
    McpImageToolConfig,
)
from deeptutor.services.media.models import ImageGenerationJob, MediaConfigError

#: Lookup for MCP image-tool mappings by profile id (injectable).
McpToolLookup = Callable[[str], McpImageToolConfig | None]


def _load_catalog(catalog: dict[str, Any] | None) -> dict[str, Any]:
    if catalog is not None:
        return catalog
    return get_model_catalog_service().load()


def _resolve_profile(catalog: dict[str, Any], job: ImageGenerationJob) -> dict[str, Any]:
    """Resolve the job's explicit profile exactly, or fail closed (§11.3).

    The durable job's profile is authoritative: if it no longer exists in the
    model catalog, execution must fail with a stable configuration error rather
    than silently executing with the active profile or the first configured
    entry (different provider credentials).
    """
    service = catalog.get("services", {}).get("imagegen", {})
    profiles = service.get("profiles") or []
    if not job.profile:
        raise MediaConfigError("image job does not name a profile; refusing to guess a provider")
    profile = next((item for item in profiles if item.get("id") == job.profile), None)
    if profile is None:
        raise MediaConfigError(f"image profile {job.profile!r} no longer exists")
    return profile


def _resolve_model(
    profile: dict[str, Any], job: ImageGenerationJob, *, required: bool
) -> dict[str, Any]:
    """Resolve the job's explicit model exactly within *profile*, or fail closed.

    ``required=False`` is used for MCP profiles, where the provider model is not
    selected by this field (the MCP tool mapping is authoritative).
    """
    models = profile.get("models") or []
    if not job.model:
        if required:
            raise MediaConfigError(f"image job does not name a model for profile {job.profile!r}")
        return {}
    model = next(
        (item for item in models if item.get("id") == job.model or item.get("model") == job.model),
        None,
    )
    if model is None:
        raise MediaConfigError(
            f"image model {job.model!r} no longer exists on profile {job.profile!r}"
        )
    return model


#: Explicit image-generation protocols the resolver dispatches (§10, §16.3).
#: ``openai_responses``/``mcp`` are the two dedicated adapters;
#: ``openai_images`` is the explicit Images-API route.  Any other *explicit*
#: value (a typo or an LLM/unsupported protocol) must fail closed with a stable
#: ``MediaConfigError`` before a provider call — never silently route to the
#: Images wire contract.
_DOCUMENTED_IMAGE_PROTOCOLS = frozenset({"openai_responses", "mcp", "openai_images"})


def _adapter_kind(job: ImageGenerationJob, profile: dict[str, Any] | None) -> str:
    protocol = (job.protocol or "").strip().lower()
    if not protocol:
        # Legacy job with no explicit protocol: the profile's adapter field maps
        # to the Images adapter (§16.3, openai_images / chat_completions / ...),
        # the only empty/profile-based mapping the migration contract preserves.
        return ADAPTER_OPENAI_IMAGES
    if protocol not in _DOCUMENTED_IMAGE_PROTOCOLS:
        # An explicit protocol that is not a documented image route must fail
        # closed here — a typo or unsupported value must never call a different
        # wire contract silently (§16.3).
        raise MediaConfigError(f"unsupported image protocol {job.protocol!r}")
    if protocol == "openai_responses":
        return ADAPTER_OPENAI_RESPONSES
    if protocol == "mcp":
        return ADAPTER_MCP
    return ADAPTER_OPENAI_IMAGES  # openai_images


def resolve_runtime_config(
    job: ImageGenerationJob,
    *,
    catalog: dict[str, Any] | None = None,
    mcp_tool_lookup: McpToolLookup | None = None,
) -> AdapterRuntimeConfig:
    """Build the adapter config for *job* from the model catalog.

    Profile and model resolution is fail-closed (§11.3): the job's explicit
    choices are authoritative, and a missing profile/model raises a stable
    ``MediaConfigError`` instead of silently falling back to the active profile
    or the first configured entry.  The job's explicit protocol and model choice
    are preserved verbatim.
    """
    loaded = _load_catalog(catalog)
    profile = _resolve_profile(loaded, job)
    kind = _adapter_kind(job, profile)
    model = _resolve_model(profile, job, required=(kind != ADAPTER_MCP))
    provider_name = _canonical_generation_provider(
        str((profile or {}).get("binding") or ""), IMAGEGEN_PROVIDERS
    )
    spec = IMAGEGEN_PROVIDERS.get(provider_name, IMAGEGEN_PROVIDERS["custom"])
    base_url = str((profile or {}).get("base_url") or spec.default_api_base or "")
    api_key = str((profile or {}).get("api_key") or "")
    resolved_model = str((model or {}).get("model") or "")

    if kind != ADAPTER_MCP and not resolved_model:
        # A non-MCP job must resolve to a real provider model — never the
        # catalog entry id.  An empty provider model fails closed with a stable
        # configuration error instead of silently sending the catalog id (or an
        # empty string) to the provider (§11.3/§16.3).
        raise MediaConfigError(
            f"image model {job.model!r} on profile {job.profile!r} resolves to no provider model"
        )

    size = str((model or {}).get("size") or "")
    quality = str((model or {}).get("quality") or "")
    style = str((model or {}).get("style") or "")
    response_format = str((model or {}).get("response_format") or "")

    mcp_config: McpImageToolConfig | None = None
    supports_edit = True
    supports_continuation = False
    supports_background = False

    if kind == ADAPTER_MCP:
        if mcp_tool_lookup is not None:
            mcp_config = mcp_tool_lookup(job.profile)
        if mcp_config is None:
            mcp_config = mcp_tool_lookup_global(job.profile)
        supports_edit = bool(mcp_config and mcp_config.supports_edit)
        supports_continuation = False
        supports_background = False
    elif kind == ADAPTER_OPENAI_RESPONSES:
        # Responses edits are only possible through a continuation job; source
        # edits are rejected by the adapter itself (never a silent generate).
        supports_edit = False
        supports_continuation = True
        supports_background = True

    return AdapterRuntimeConfig(
        adapter_kind=kind,
        base_url=base_url,
        api_key=api_key,
        model=resolved_model,
        auth_style=str(spec.auth_style or "bearer"),
        extra_headers=_as_headers((profile or {}).get("extra_headers")),
        api_version=str((profile or {}).get("api_version") or ""),
        size=size,
        quality=quality,
        style=style,
        response_format=response_format,
        supports_edit=supports_edit,
        supports_continuation=supports_continuation,
        supports_background=supports_background,
        mcp=mcp_config,
    )


def _as_headers(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items() if str(k).strip() and v is not None}
    if isinstance(value, str) and value.strip():
        import json

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items() if str(k).strip() and v is not None}
    return {}


# ── MCP image-tool registry (profile id -> tool mapping) ────────────────────

_MCP_IMAGE_TOOLS: dict[str, McpImageToolConfig] = {}


def register_mcp_image_tool(profile_id: str, config: McpImageToolConfig) -> None:
    """Register an MCP image-tool mapping for a profile (production wiring)."""
    _MCP_IMAGE_TOOLS[profile_id] = config


def mcp_tool_lookup_global(profile_id: str) -> McpImageToolConfig | None:
    return _MCP_IMAGE_TOOLS.get(profile_id or "")


def default_resolver(catalog: dict[str, Any] | None = None) -> AdapterConfigResolver:
    """A resolver bound to the live catalog (or an injected one for tests)."""

    def _resolve(job: ImageGenerationJob) -> AdapterRuntimeConfig:
        return resolve_runtime_config(job, catalog=catalog)

    return _resolve


__all__ = [
    "AdapterConfigResolver",
    "default_resolver",
    "mcp_tool_lookup_global",
    "register_mcp_image_tool",
    "resolve_runtime_config",
]
