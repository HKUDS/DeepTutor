"""Owner-bound LLM profiles an ordinary user signed in for themselves.

An owner-bound profile — an OpenAI Codex OAuth login, today — authenticates
one *person's* subscription rather than a billable team key, so it is never
lent to another account through grants (see
:func:`~deeptutor.multi_user.model_access.is_owner_bound`). Before this
module that left ordinary users with no path to Codex at all: they could
not be granted the administrator's profile (correctly withheld) and could
not sign in for themselves either, because the OAuth endpoints were
admin-only (#781).

The rule that makes per-user sign-in safe is *where the profile lives*: an
ordinary user's Codex profile is written to that user's OWN catalog
(``data/users/<uid>/settings/model_catalog.json``), never into the shared
admin catalog. Nothing an ordinary user does can therefore appear in the
administrator's model list, in another user's options, or in the grant
editor. The profile is merged into the catalog the runtime resolves against
per request instead — which is safe because a managed Codex profile carries
no secret at all (``api_key`` is empty; the token is read from the owner's
credential store at call time by
:class:`~deeptutor.services.llm.provider_core.openai_codex_provider.OpenAICodexProvider`).

Ownership resolution is shared with the credential store via
:func:`~deeptutor.multi_user.paths.get_owner_path_service`, so a profile and
the token that authorizes it can never be resolved to different accounts —
and a partner turn keeps inheriting the login of the human who owns it.
"""

from __future__ import annotations

from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService

from .paths import get_owner_path_service

_CODEX_MANAGED_BY = "openai_codex_oauth"


def _codex_profile_is_current(profile: dict[str, Any]) -> bool:
    try:
        from deeptutor.services.codex_auth import get_codex_oauth_service

        return get_codex_oauth_service().profile_matches_current_account(profile)
    except Exception:
        return False


def owner_catalog_service() -> ModelCatalogService:
    """Model catalog of the account that owns the current scope.

    For an administrator — and for any scope with no request context, i.e.
    CLI runs and background jobs — this is the shared deployment catalog, so
    administrator behaviour is exactly what it was. For an ordinary user it
    is their own file; for a partner, its owner's.
    """
    return ModelCatalogService.get_instance(
        get_owner_path_service().get_settings_file("model_catalog")
    )


def _personal_catalog_profiles() -> list[dict[str, Any]]:
    """Owner-bound LLM profiles from the owner's own catalog.

    Empty for an administrator: their owner-bound profiles already live in
    the shared catalog they manage, and overlaying them would duplicate
    every model in their own option list.
    """
    from .context import get_current_user_or_none
    from .model_access import is_owner_bound

    user = get_current_user_or_none()
    if user is None or user.is_admin:
        return []
    service = owner_catalog_service()
    # Checked rather than loaded blind: ``load()`` writes a default catalog
    # when the file is absent, and a user who never touched Codex should not
    # get a settings file created on every options request.
    if not service.path.exists():
        return []
    profiles = service.load().get("services", {}).get("llm", {}).get("profiles", []) or []
    return [
        profile
        for profile in profiles
        if isinstance(profile, dict)
        and is_owner_bound(profile)
        and (profile.get("managed_by") != _CODEX_MANAGED_BY or _codex_profile_is_current(profile))
    ]


def personal_llm_rows() -> list[dict[str, Any]]:
    """Personal models in the row shape ``redacted_model_access`` returns.

    ``source="personal"`` is what tells the frontend these came from the
    user's own sign-in rather than an administrator's grant, so it can offer
    them a connect/disconnect card instead of a read-only assignment.
    """
    rows: list[dict[str, Any]] = []
    for profile in _personal_catalog_profiles():
        profile_id = str(profile.get("id") or "")
        for model in profile.get("models", []) or []:
            if not isinstance(model, dict):
                continue
            model_id = str(model.get("id") or "")
            if not model_id:
                continue
            rows.append(
                {
                    "profile_id": profile_id,
                    "model_id": model_id,
                    "name": model.get("name") or model_id,
                    "model": model.get("model") or "",
                    "provider": profile.get("binding") or "",
                    "reasoning_effort": model.get("reasoning_effort"),
                    "supported_reasoning_efforts": model.get("codex_supported_reasoning_levels"),
                    "source": "personal",
                    "available": True,
                }
            )
    return rows


def merge_personal_llm_profiles(catalog: dict[str, Any]) -> dict[str, Any]:
    """``catalog`` plus the current owner's personal LLM profiles.

    Used on the resolution path so a personal selection resolves to a real
    profile: the runtime otherwise looks the selection up in the shared
    catalog, where a per-user profile deliberately does not exist. Returns
    the input untouched when there is nothing to add, and never mutates it.

    A personal profile *replaces* a shared one of the same id rather than
    being skipped. Managed profile ids are per-provider constants, so an
    administrator who also signed in to Codex holds a profile under the same
    id — and that one lists the administrator's models, which the user's plan
    may not include. The owner's own profile is the authority inside their
    own scope; the token is resolved per owner regardless.
    """
    personal = _personal_catalog_profiles()
    if not personal:
        return catalog
    personal_ids = {str(profile.get("id") or "") for profile in personal}
    merged = dict(catalog)
    services = dict(merged.get("services") or {})
    llm = dict(services.get("llm") or {})
    shared = [
        profile
        for profile in llm.get("profiles") or []
        if not (isinstance(profile, dict) and str(profile.get("id") or "") in personal_ids)
    ]
    llm["profiles"] = shared + personal
    services["llm"] = llm
    merged["services"] = services
    return merged


__all__ = [
    "merge_personal_llm_profiles",
    "owner_catalog_service",
    "personal_llm_rows",
]
