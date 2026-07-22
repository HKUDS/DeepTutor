"""Partner workspace layout + asset provisioning.

The partner workspace is a verbatim clone of the chat user-workspace format
(``PathService`` layout), so the chat agent loop's tools read it natively:

    data/partners/<id>/workspace/          ← synthetic scope root
    ├── knowledge_bases/<kb>/              ← copied KBs (rag)
    └── user/
        ├── workspace/
        │   ├── SOUL.md                    ← the partner's persona
        │   ├── skills/<name>/SKILL.md     ← copied skills (read_skill)
        │   ├── notebook/…                 ← copied notebooks (list_notebook/write_note)
        │   └── memory/…
        └── settings/ …

Provisioning runs in the *requesting user's* context: sources are resolved
with that user's permissions (``resolve_kb`` / assigned-skill grants), then
copied into the partner scope as plain files. All three asset classes are
self-contained on disk, so a copy is a complete transfer:

* KB: the whole ``<kb>/`` tree (raw + LlamaIndex ``version-N`` dirs); the
  partner-side ``KnowledgeBaseManager`` auto-registers it on first list.
* Skill: the whole ``<name>/`` dir (SKILL.md + references).
* Notebook: ``<id>.json`` plus its ``notebooks_index.json`` entry.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil
from typing import Any

from deeptutor.multi_user.paths import (
    ensure_scope_workspace,
    get_admin_path_service,
    get_path_service_for_scope,
)
from deeptutor.services.partners.scope import partner_scope
from deeptutor.services.path_service import PathService

logger = logging.getLogger(__name__)


def _requester_path_service() -> PathService:
    """Path service for the user driving this provisioning call.

    Resolved through ``get_current_user()`` (which falls back to the local
    admin) rather than ``get_path_service()`` — the latter short-circuits to
    the process-default instance when no user contextvar is set, bypassing
    scope resolution entirely.
    """
    from deeptutor.multi_user.context import get_current_user

    return get_path_service_for_scope(get_current_user().scope)


SOUL_FILENAME = "SOUL.md"

DEFAULT_SOUL = """# Soul

I am a learning companion. I help with questions patiently and clearly,
adapt to the user's level, and value accuracy over speed.
"""


def ensure_partner_workspace(partner_id: str) -> Path:
    """Create the full chat-format workspace tree; returns the scope root."""
    return ensure_scope_workspace(partner_scope(partner_id))


def strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (``---`` … ``---``) if present.

    Used when cloning a chat persona (PERSONA.md carries name/description
    frontmatter) into a partner SOUL.md, which is plain markdown.
    """
    raw = (text or "").lstrip()
    if not raw.startswith("---"):
        return text or ""
    end = raw.find("\n---", 3)
    if end == -1:
        return text or ""
    return raw[end + 4 :].lstrip("\n")


def _partner_path_service(partner_id: str) -> PathService:
    return PathService(workspace_root=ensure_partner_workspace(partner_id))


# ── Soul ──────────────────────────────────────────────────────────


def soul_path(partner_id: str) -> Path:
    return _partner_path_service(partner_id).get_workspace_dir() / SOUL_FILENAME


def read_soul(partner_id: str) -> str:
    path = soul_path(partner_id)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read SOUL.md for partner %s", partner_id)
        return ""


def write_soul(partner_id: str, content: str) -> None:
    path = soul_path(partner_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")


# ── Asset provisioning (runs in the requesting user's context) ────


def provision_assets(
    partner_id: str,
    *,
    knowledge_bases: list[str] | None = None,
    skills: list[str] | None = None,
    notebooks: list[str] | None = None,
) -> dict[str, Any]:
    """Copy the requested assets into the partner workspace.

    Source resolution honours the calling user's permissions. Returns a
    report dict: ``{"copied": {...}, "errors": [{"type","name","error"}]}``.
    """
    root = ensure_partner_workspace(partner_id)
    copied: dict[str, list[str]] = {"knowledge_bases": [], "skills": [], "notebooks": []}
    errors: list[dict[str, str]] = []

    for kb_ref in knowledge_bases or []:
        try:
            copied["knowledge_bases"].append(_copy_knowledge_base(kb_ref, root))
        except Exception as exc:
            logger.exception("KB provisioning failed for %s", kb_ref)
            errors.append({"type": "knowledge_base", "name": kb_ref, "error": _err(exc)})

    for skill_name in skills or []:
        try:
            copied["skills"].append(_copy_skill(skill_name, partner_id))
        except Exception as exc:
            logger.exception("Skill provisioning failed for %s", skill_name)
            errors.append({"type": "skill", "name": skill_name, "error": _err(exc)})

    for notebook_id in notebooks or []:
        try:
            copied["notebooks"].append(_copy_notebook(notebook_id, partner_id))
        except Exception as exc:
            logger.exception("Notebook provisioning failed for %s", notebook_id)
            errors.append({"type": "notebook", "name": notebook_id, "error": _err(exc)})

    return {"copied": copied, "errors": errors}


def _err(exc: Exception) -> str:
    detail = getattr(exc, "detail", None)
    return str(detail) if detail else f"{type(exc).__name__}: {exc}"


def _copy_knowledge_base(kb_ref: str, partner_root: Path) -> str:
    from deeptutor.multi_user.knowledge_access import resolve_kb

    resource = resolve_kb(kb_ref)
    src = Path(resource.base_dir) / resource.name
    if not src.is_dir():
        raise FileNotFoundError(f"Knowledge base directory missing: {resource.name}")
    dst = partner_root / "knowledge_bases" / resource.name
    if dst.exists():
        return resource.name  # already provisioned
    shutil.copytree(src, dst)
    return resource.name


def _skill_source_dir(skill_name: str) -> Path:
    """Resolve a skill the calling user may read.

    Resolution order mirrors SkillService visibility: the user's own
    workspace shadows the packaged builtin set; non-admins may also copy
    admin-assigned skills. (Builtins are visible to every partner anyway —
    copying one just pins a workspace-local snapshot.)
    """
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.services.skill.service import BUILTIN_SKILLS_ROOT

    own = _requester_path_service().get_workspace_dir() / "skills" / skill_name
    if (own / "SKILL.md").exists():
        return own

    builtin = BUILTIN_SKILLS_ROOT / skill_name
    if (builtin / "SKILL.md").exists():
        return builtin

    user = get_current_user()
    if not user.is_admin:
        from deeptutor.multi_user.skill_access import assigned_skill_ids

        if skill_name in assigned_skill_ids(user.id):
            assigned = get_admin_path_service().get_workspace_dir() / "skills" / skill_name
            if (assigned / "SKILL.md").exists():
                return assigned
    raise FileNotFoundError(f"Skill '{skill_name}' not found or not accessible")


def _copy_skill(skill_name: str, partner_id: str) -> str:
    src = _skill_source_dir(skill_name)
    dst = _partner_path_service(partner_id).get_workspace_dir() / "skills" / skill_name
    if dst.exists():
        return skill_name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
    return skill_name


def _copy_notebook(notebook_id: str, partner_id: str) -> str:
    src_dir = _requester_path_service().get_notebook_dir()
    src_file = src_dir / f"{notebook_id}.json"
    if not src_file.exists():
        raise FileNotFoundError(f"Notebook '{notebook_id}' not found")

    dst_dir = _partner_path_service(partner_id).get_notebook_dir()
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst_file = dst_dir / f"{notebook_id}.json"
    if not dst_file.exists():
        shutil.copy2(src_file, dst_file)

    entry = _index_entry(src_dir / "notebooks_index.json", notebook_id)
    if entry is None:
        # Fall back to a minimal entry derived from the notebook payload.
        try:
            payload = json.loads(src_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        entry = {
            "id": notebook_id,
            "name": str(payload.get("name") or notebook_id),
            "description": str(payload.get("description") or ""),
            "created_at": payload.get("created_at") or 0,
            "updated_at": payload.get("updated_at") or 0,
            "record_count": len(payload.get("records") or []),
            "color": payload.get("color") or "#3B82F6",
            "icon": payload.get("icon") or "book",
        }
    _merge_index_entry(dst_dir / "notebooks_index.json", entry)
    return notebook_id


def _index_entry(index_path: Path, notebook_id: str) -> dict[str, Any] | None:
    if not index_path.exists():
        return None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    for entry in data.get("notebooks", []) or []:
        if str(entry.get("id")) == notebook_id:
            return dict(entry)
    return None


def _merge_index_entry(index_path: Path, entry: dict[str, Any]) -> None:
    data: dict[str, Any] = {"notebooks": []}
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("notebooks"), list):
                data = loaded
        except (OSError, json.JSONDecodeError):
            pass
    notebooks = [n for n in data["notebooks"] if str(n.get("id")) != str(entry.get("id"))]
    notebooks.append(entry)
    data["notebooks"] = notebooks
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Asset inventory / removal (partner-side, no user context needed) ──


def list_assets(partner_id: str) -> dict[str, list[dict[str, Any]]]:
    root = ensure_partner_workspace(partner_id)
    service = _partner_path_service(partner_id)

    kbs: list[dict[str, Any]] = []
    kb_root = root / "knowledge_bases"
    if kb_root.is_dir():
        for entry in sorted(kb_root.iterdir()):
            if entry.is_dir() and not entry.name.startswith((".", "_")):
                raw_count = sum(1 for f in (entry / "raw").glob("*") if f.is_file())
                kbs.append({"name": entry.name, "documents": raw_count})

    skills: list[dict[str, Any]] = []
    skills_root = service.get_workspace_dir() / "skills"
    if skills_root.is_dir():
        for entry in sorted(skills_root.iterdir()):
            if entry.is_dir() and (entry / "SKILL.md").exists():
                skills.append({"name": entry.name})

    notebooks: list[dict[str, Any]] = []
    index_path = service.get_notebook_dir() / "notebooks_index.json"
    if index_path.exists():
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            for nb_entry in data.get("notebooks", []) or []:
                notebooks.append(
                    {
                        "id": str(nb_entry.get("id", "")),
                        "name": str(nb_entry.get("name", "")),
                        "record_count": nb_entry.get("record_count", 0),
                    }
                )
        except (OSError, json.JSONDecodeError):
            pass

    return {"knowledge_bases": kbs, "skills": skills, "notebooks": notebooks}


def remove_asset(partner_id: str, asset_type: str, name: str) -> bool:
    root = ensure_partner_workspace(partner_id)
    service = _partner_path_service(partner_id)
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("Invalid asset name")

    if asset_type == "knowledge_base":
        target = root / "knowledge_bases" / name
        if not target.is_dir():
            return False
        shutil.rmtree(target)
        config_file = root / "knowledge_bases" / "kb_config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                if name in config.get("knowledge_bases", {}):
                    config["knowledge_bases"].pop(name, None)
                    config_file.write_text(
                        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
            except (OSError, json.JSONDecodeError):
                logger.warning("Could not prune kb_config entry for %s", name, exc_info=True)
        return True

    if asset_type == "skill":
        target = service.get_workspace_dir() / "skills" / name
        if not target.is_dir():
            return False
        shutil.rmtree(target)
        return True

    if asset_type == "notebook":
        notebook_dir = service.get_notebook_dir()
        target = notebook_dir / f"{name}.json"
        removed = False
        if target.exists():
            target.unlink()
            removed = True
        index_path = notebook_dir / "notebooks_index.json"
        if index_path.exists():
            try:
                data = json.loads(index_path.read_text(encoding="utf-8"))
                before = len(data.get("notebooks", []) or [])
                data["notebooks"] = [
                    n for n in data.get("notebooks", []) or [] if str(n.get("id")) != name
                ]
                if len(data["notebooks"]) != before:
                    removed = True
                index_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except (OSError, json.JSONDecodeError):
                pass
        return removed

    raise ValueError(f"Unknown asset type: {asset_type}")


__all__ = [
    "DEFAULT_SOUL",
    "ensure_partner_workspace",
    "list_assets",
    "provision_assets",
    "read_soul",
    "remove_asset",
    "soul_path",
    "write_soul",
]
