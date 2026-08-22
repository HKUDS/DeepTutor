"""Who may let the setup agent change what.

Two rules, both inherited from where the settings files already live rather
than invented here:

*Personal* rows are the ones :class:`~deeptutor.services.path_service.PathService`
already resolves per user — a write lands in the caller's own
``settings/interface.json`` and is invisible to everyone else. Any signed-in
person may therefore change their own.

*Global* rows are the shared deployment settings under
``data/user/settings`` (``get_runtime_settings_dir`` does not go through the
per-user path service). Changing one changes it for every account on the
install, which is exactly the boundary
:func:`deeptutor.api.routers.settings._require_settings_admin` already guards —
so the capability requires the same administrator role rather than inventing a
softer rule for the chat surface than the settings page enforces.

A **partner is refused outright**, for either scope. A partner is a synthetic
user whose owner is a real account: its turns resolve ownership to that person
(:func:`~deeptutor.multi_user.paths.get_owner_path_service`), so honouring a
configuration request from an IM-facing companion would mean letting whoever is
chatting with it reconfigure the owner's DeepTutor — including, if the owner is
an administrator, the whole deployment.
"""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.services.config.settings_spec import Scope


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """Whether a write may proceed, and what to tell the model when it may not.

    ``reason`` is written for the model to relay to the user, so it names the
    human remedy ("ask an administrator") rather than the internal rule.
    """

    allowed: bool
    reason: str = ""


def _is_partner_turn() -> bool:
    try:
        from deeptutor.multi_user.context import get_current_user
        from deeptutor.services.partners.scope import is_partner_user_id

        return bool(is_partner_user_id(get_current_user().id))
    except Exception:  # noqa: BLE001 - no multi-user layer configured
        return False


def _is_admin() -> bool:
    """Whether the caller may change deployment-wide settings.

    A missing multi-user layer means a single-user install, whose only user *is*
    the administrator — so ImportError grants. Any other failure is narrowed to
    a refusal: if identity cannot be resolved, granting administrator rights is
    the wrong way to be wrong, and the caller still keeps their personal
    preferences either way.
    """
    try:
        from deeptutor.multi_user.context import get_current_user
    except ImportError:
        return True
    try:
        return bool(get_current_user().is_admin)
    except Exception:  # noqa: BLE001 - unresolvable identity: refuse, do not grant
        return False


def can_write(scope: Scope) -> AccessDecision:
    """Decide whether the current turn may write a row of the given scope."""
    if _is_partner_turn():
        return AccessDecision(
            allowed=False,
            reason=(
                "Configuration cannot be changed from a partner conversation. "
                "The owner can make this change in DeepTutor directly."
            ),
        )
    if scope == "personal":
        return AccessDecision(allowed=True)
    if _is_admin():
        return AccessDecision(allowed=True)
    return AccessDecision(
        allowed=False,
        reason=(
            "This is a deployment-wide setting that applies to every account, so only an "
            "administrator can change it. Personal preferences (interface language, reply "
            "language, theme) can still be changed here."
        ),
    )


def writable_scopes() -> tuple[Scope, ...]:
    """Scopes the current turn may write — used to describe the surface up front."""
    scopes: tuple[Scope, ...] = ("personal", "global")
    return tuple(scope for scope in scopes if can_write(scope).allowed)


__all__ = ["AccessDecision", "can_write", "writable_scopes"]
