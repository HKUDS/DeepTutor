"""One resolution order for skill manifests and on-demand reads."""

from __future__ import annotations

from contextvars import ContextVar

from deeptutor.services.skill.service import (
    SkillNotFoundError,
    SkillService,
    get_admin_skill_service,
    render_skills_manifest,
)

library_workspace: ContextVar[str] = ContextVar("skill_library_workspace", default="")


def workspace_skill_service(workspace_id: str) -> SkillService:
    from deeptutor.services.workspace import get_content_workspace_service

    binding = get_content_workspace_service().validate_chat_binding(workspace_id, existing=True)
    return SkillService(root=binding.root / "skills", builtin_root=None)


def skill_sources(*, workspace_id: str = ""):
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.multi_user.skill_access import assigned_skill_ids

    if workspace_id:
        yield workspace_skill_service(workspace_id), None, "workspace"
    from deeptutor.services.skill import get_skill_service

    own = get_skill_service()
    yield SkillService(root=own.root, builtin_root=None), None, "account"
    if not get_current_user().is_admin:
        granted = assigned_skill_ids(get_current_user().id)
        if granted:
            yield (
                SkillService(root=get_admin_skill_service().root, builtin_root=None),
                granted,
                "admin",
            )
    # Keep builtins last, including when a granted admin skill shadows one.
    if own._builtin_root is not None:
        yield SkillService(root=own._builtin_root, builtin_root=None), None, "builtin"


def runtime_skills() -> dict[str, SkillService]:
    from deeptutor.services.workspace.context import current_workspace_id
    from deeptutor.services.workspace.resources import current_resources

    selected = current_resources().skills
    resolved: dict[str, SkillService] = {}
    for service, granted, _source in skill_sources(workspace_id=current_workspace_id()):
        for info in service.list_skills():
            name = info.name
            if selected is not None and name not in selected:
                continue
            if granted is not None and name not in granted:
                continue
            resolved.setdefault(name, service)
    return resolved


def skill_manifest() -> str:
    entries = []
    always = []
    resolved = runtime_skills()
    for service in dict.fromkeys(resolved.values()):
        for entry in service.summary_entries():
            if resolved.get(entry.name) is not service:
                continue
            entries.append(entry)
            if entry.always and entry.available:
                always.append(service.load_for_context([entry.name]))
    return "\n\n".join(part for part in (*always, render_skills_manifest(entries)) if part)


def resolve_runtime_skill(name: str) -> SkillService:
    service = runtime_skills().get(name)
    if service is None:
        raise SkillNotFoundError(name)
    return service
