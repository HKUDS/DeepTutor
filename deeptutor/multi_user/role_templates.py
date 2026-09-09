"""Default grant templates for the K12 roles (teacher / student / parent).

The production walkthrough (2026-09-09) found new accounts fully locked — no
LLM, no KBs — because every assignment required an admin hand-crafting a grant
per account, and a missing ``model_ids`` field matched zero models without an
error. Assigning a role should open the account: :func:`apply_role_template`
seeds the default grant for the role at the moment an admin changes it, and
leaves accounts that already carry grants untouched.

Templates are logical (ids only, same contract as every grant) and
environment-adaptive: the LLM slot resolves from the model catalog's *active*
LLM profile, and the KB slots resolve from the admin workspace's KB registry
at apply time — nothing is hardcoded to one deployment.
"""

from __future__ import annotations

from typing import Any

from .grants import empty_grant, load_grant, save_grant

#: Roles that carry a default template. ``admin`` manages the catalog itself
#: and plain ``user`` accounts get onboarded through presets, so neither is
#: seeded here.
TEMPLATE_ROLES = frozenset({"teacher", "student", "parent"})

#: Admin-workspace KB name prefixes each role receives. ``教材-v2-`` is the
#: per-subject textbook series the admin workspace publishes (教材-v2-数学,
#: 教材-v2-语文, …); teachers and students both read them, parents do not.
TEACHER_KB_PREFIXES = ("教材-v2-",)
STUDENT_KB_PREFIXES = ("教材-v2-",)


def active_llm_grant_item() -> dict[str, Any] | None:
    """The grant item for the catalog's active LLM profile, or ``None``.

    ``None`` means "the deployment has no usable active LLM default" — the
    template then ships without a model slot rather than with one that cannot
    resolve, and the role change still succeeds (model onboarding stays an
    admin action for that account).
    """
    from .model_access import admin_catalog, is_owner_bound

    service = admin_catalog().get("services", {}).get("llm", {})
    profile_id = str(service.get("active_profile_id") or "").strip()
    model_id = str(service.get("active_model_id") or "").strip()
    if not profile_id or not model_id:
        return None
    profile = next(
        (
            profile
            for profile in service.get("profiles", []) or []
            if str(profile.get("id") or "") == profile_id
        ),
        None,
    )
    if profile is None or is_owner_bound(profile):
        return None
    if not any(str(model.get("id") or "") == model_id for model in profile.get("models", []) or []):
        return None
    return {
        "profile_id": profile_id,
        "model_ids": [model_id],
    }


def build_role_template(
    user_id: str,
    role: str,
    *,
    admin_kb_names: list[str] | None = None,
) -> dict[str, Any] | None:
    """The default grant for ``role``, or ``None`` when the role has none.

    ``admin_kb_names`` overrides the admin KB registry (tests pass a fixed
    list); ``None`` reads the live registry.
    """
    role = str(role or "").strip()
    if role not in TEMPLATE_ROLES:
        return None
    grant = empty_grant(user_id)
    llm_item = active_llm_grant_item()
    if llm_item is not None:
        grant["models"]["llm"] = [llm_item]
    prefixes = {
        "teacher": TEACHER_KB_PREFIXES,
        "student": STUDENT_KB_PREFIXES,
        "parent": (),
    }[role]
    if prefixes:
        if admin_kb_names is None:
            from .knowledge_access import admin_kb_manager

            admin_kb_names = list(admin_kb_manager().list_knowledge_bases())
        grant["knowledge_bases"] = [
            {"resource_id": f"admin:kb:{name}", "name": name}
            for name in sorted(admin_kb_names)
            if str(name).startswith(prefixes)
        ]
    return grant


def _has_existing_grants(user_id: str) -> bool:
    """Whether ``user_id`` already carries anything beyond the empty default."""
    return load_grant(user_id) != empty_grant(user_id)


def apply_role_template(user_id: str, role: str) -> dict[str, Any] | None:
    """Seed ``user_id`` with ``role``'s default grant when appropriate.

    Only fires for template roles, only when the account's grants are still
    empty/default — an account an admin has already personalized is never
    overwritten. Any failure (unknown user, invalid template for this
    deployment) degrades to "no template applied" rather than blocking the
    role change that triggered it. Returns the saved grant, or ``None`` when
    nothing was applied.
    """
    if str(role or "") not in TEMPLATE_ROLES:
        return None
    try:
        if _has_existing_grants(user_id):
            return None
        template = build_role_template(user_id, role)
        if template is None or template == empty_grant(user_id):
            # Nothing to seed (e.g. a parent template on a deployment without
            # a usable active LLM default) — report "not applied" instead of
            # writing a default-shaped file that pretends otherwise.
            return None
        return save_grant(user_id, template)
    except Exception:  # noqa: BLE001 — role change must never fail on template seeding
        return None
