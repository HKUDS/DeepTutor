"""Default grant templates for the K12 roles (teacher / student / parent).

The production walkthrough (2026-09-09) found new accounts fully locked — no
LLM, no KBs — because every assignment required an admin hand-crafting a grant
per account, and a missing ``model_ids`` field matched zero models without an
error. Assigning a role should open the account: :func:`apply_role_template`
seeds the default grant for the role at the moment an admin changes it, and
leaves accounts that already carry grants untouched.

Templates are logical (ids only, same contract as every grant) and
environment-adaptive: the LLM slot resolves from the model catalog's *active*
LLM profile, the KB slots resolve from the admin workspace's KB registry, and
the skill slots resolve against the admin skill catalog at apply time —
nothing is hardcoded to one deployment.
"""

from __future__ import annotations

from copy import deepcopy
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

#: Skill name prefixes each role receives from the admin skill catalog. The
#: 教学平台 series (yuedu-*) ships as its own set; whatever the catalog
#: carries under the prefix is assigned wholesale.
TEACHER_SKILL_PREFIXES = ("yuedu-",)
STUDENT_SKILL_PREFIXES = ("yuedu-",)

#: Explicit skill names per role, in the order the walkthrough (2026-09-09)
#: configured them by hand. Names missing from this deployment's catalog are
#: silently skipped (see :func:`_resolve_skill_names`) — the whitelist says
#: what a role *may* get, the catalog says what it *does* get.
TEACHER_SKILL_NAMES = (
    # 学科教学技能
    "s01",
    "s02",
    "s03",
    "s04",
    "s05",
    "s06",
    "s07",
    "s08",
    "s09",
    "s10",
    "s11",
    "s12",
    "concept-explainer",
    "exam-blueprint",
    "essay-feedback",
    "english-homework-grader",
    "flashcard-deck",
    "flashcards",
    "quiz",
    "quiz-generator",
    "rubric-builder",
    "lesson-plan-architect",
    "lesson-plan-studio",
    "math-mentor-simple",
    "math-tutor-lite",
    "textbook-example-extraction",
    "homework",
    "khan-tutor",
    "learning-coach",
    "study-planner",
    # 基础文档/教学工具
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    "exam-review",
    "lesson-prep",
    "potential-scanner",
    "pre-exam-checklist",
    "question-reader",
    "score-diagnosis",
    "type-cards",
    "wrong-tracer",
)

STUDENT_SKILL_NAMES = (
    "s01",
    "s02",
    "s03",
    "s04",
    "s05",
    "s06",
    "s07",
    "s08",
    "s09",
    "s10",
    "s11",
    "s12",
    "concept-explainer",
    "flashcard-deck",
    "quiz",
    "math-mentor-simple",
    "math-tutor-lite",
    "learning-coach",
    "study-planner",
    "homework",
    "khan-tutor",
)

#: parent sees what a student sees — the learning set, nothing administrative.
PARENT_SKILL_NAMES = STUDENT_SKILL_NAMES

#: The learning_policy both learner templates (student / parent) ship. The
#: 09-10 walkthrough found learner accounts unusable without one — the policy
#: gates every capability/surface check, so a learner grant without it locks
#: the account out of chat/reading/daily-plan/assignments. Mirrors
#: :func:`grants.learner_grant`'s server-enforced defaults (extensions are the
#: base reading whitelist), passes :func:`grants.validate_grant` as-is.
#: ``teacher`` carries none — the template default stays ``None`` (full pool).
LEARNER_LEARNING_POLICY = {
    "age_band": "9-12",
    "locked_persona": "teacher",
    "allowed_capabilities": ["chat", "immersive_reading"],
    "default_capability": "immersive_reading",
    "allowed_surfaces": ["chat", "reading", "daily-plan", "assignments"],
    "reading": {
        "allow_upload": False,
        "material_ids": [],
        "extensions": ["read_aloud", "guided_learning", "vocabulary", "quiz", "translation"],
    },
}


def _admin_skill_names() -> set[str]:
    """Names in the admin skill catalog (workspace skills + builtins).

    Best-effort: a deployment that cannot load its catalog yields an empty
    set, and the templates then ship without skills rather than breaking the
    role change.
    """
    try:
        from deeptutor.services.skill.service import SkillService

        from .paths import get_admin_path_service

        service = SkillService(root=get_admin_path_service().get_workspace_dir() / "skills")
        return {info.name for info in service.list_skills()}
    except Exception:  # noqa: BLE001 — skill seeding must never block a role change
        return set()


def _resolve_skill_names(prefixes: tuple[str, ...], names: tuple[str, ...]) -> list[str]:
    """Intersect the role's whitelist with the catalog, silently skipping
    names the deployment does not have. Prefix matches (yuedu-*) come first
    sorted, then explicit names in whitelist order.
    """
    catalog = _admin_skill_names()
    if not catalog:
        return []
    resolved = sorted(name for name in catalog if name.startswith(prefixes))
    resolved.extend(name for name in names if name in catalog and name not in set(resolved))
    return resolved


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
    skill_prefixes, skill_names = {
        "teacher": (TEACHER_SKILL_PREFIXES, TEACHER_SKILL_NAMES),
        "student": (STUDENT_SKILL_PREFIXES, STUDENT_SKILL_NAMES),
        "parent": (STUDENT_SKILL_PREFIXES, PARENT_SKILL_NAMES),
    }[role]
    grant["skills"] = [
        {"skill_id": name} for name in _resolve_skill_names(skill_prefixes, skill_names)
    ]
    if role in ("student", "parent"):
        grant["learning_policy"] = deepcopy(LEARNER_LEARNING_POLICY)
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
            # Nothing to seed — report "not applied" instead of writing a
            # default-shaped file that pretends otherwise. (Learner templates
            # always carry learning_policy, so they seed even without a usable
            # LLM default; models stay an admin onboarding action.)
            return None
        return save_grant(user_id, template)
    except Exception:  # noqa: BLE001 — role change must never fail on template seeding
        return None
