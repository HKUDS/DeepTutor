"""Learning-account policy resolution and turn enforcement."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .context import get_current_user
from .grants import load_grant


def learning_policy_for_user(user_id: str, *, is_admin: bool = False) -> dict[str, Any] | None:
    """Return the sanitized public policy for an account."""
    if is_admin:
        return None
    policy = load_grant(user_id).get("learning_policy")
    return deepcopy(policy) if isinstance(policy, dict) else None


def current_learning_policy() -> dict[str, Any] | None:
    user = get_current_user()
    return learning_policy_for_user(user.id, is_admin=user.is_admin)


def apply_learning_policy(payload: dict[str, Any]) -> dict[str, Any]:
    """Apply the account policy before a turn is validated or persisted."""
    policy = current_learning_policy()
    if policy is None:
        return payload

    capability = str(payload.get("capability") or "chat")
    allowed = set(policy.get("allowed_capabilities") or [])
    if capability not in allowed:
        raise PermissionError(
            "This learning account cannot use this mode. Please choose Chat or Immersive Reading."
        )
    return {**payload, "persona": str(policy.get("locked_persona") or "")}


__all__ = ["apply_learning_policy", "current_learning_policy", "learning_policy_for_user"]
