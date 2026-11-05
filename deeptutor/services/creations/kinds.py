"""What create mode can author, and how each kind validates and publishes.

A ``CreationKind`` is the only place that knows the difference between a
Skill and a Persona. The loop capability, the ``propose_creation`` tool, the
draft store, and the router all work through this adapter and never branch on
kind — adding a third kind (e.g. a persona-adjacent "soul template") is
adding a class here, not touching any of the shared plumbing.
"""

from __future__ import annotations

from pathlib import Path
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeptutor.services.creations.drafts import CreationDraft

# Shared with SkillService/PersonaService's own slug rule so a name accepted
# here is guaranteed to be accepted by the service that ultimately writes it.
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9\- _]{0,31}$")
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)

_MAX_DESCRIPTION_CHARS = 300
_MAX_CONTENT_CHARS = 60_000
_MAX_TAGS = 6
_MAX_REFERENCE_FILES = 12
_MAX_REFERENCE_FILE_BYTES = 200_000
_MAX_REFERENCE_TOTAL_BYTES = 1_000_000


def _slugify_name(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    return re.sub(r"[\s_]+", "-", text)


def _normalize_common(fields: dict[str, Any]) -> tuple[str, str, str]:
    """Validate the fields every kind shares; raises ``ValueError`` for the model."""
    name = _slugify_name(fields.get("name"))
    if not name or not _NAME_RE.match(name):
        raise ValueError(
            "name must be a lowercase slug (letters, digits, hyphens; "
            "spaces and underscores are folded into hyphens)."
        )
    description = str(fields.get("description") or "").strip()
    if not description:
        raise ValueError("description is required.")
    if "\n" in description:
        raise ValueError("description must be a single line.")
    if len(description) > _MAX_DESCRIPTION_CHARS:
        raise ValueError(f"description must be at most {_MAX_DESCRIPTION_CHARS} characters.")
    # The server composes its own frontmatter when publishing, so any
    # frontmatter the model wrote into the body (including a stray
    # ``always: true``) is dropped here rather than carried through.
    content = _FRONTMATTER_RE.sub("", str(fields.get("content") or ""), count=1).strip()
    if not content:
        raise ValueError("content is required.")
    if len(content) > _MAX_CONTENT_CHARS:
        raise ValueError(f"content must be at most {_MAX_CONTENT_CHARS} characters.")
    return name, description, content


def _validate_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("tags must be a list of strings.")
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw:
        candidate = str(item or "").strip().lower()
        if not candidate or not _TAG_RE.match(candidate):
            # Mirrors SkillService's own tag normalization: a malformed tag
            # is dropped rather than failing the whole draft.
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        cleaned.append(candidate)
    if len(cleaned) > _MAX_TAGS:
        raise ValueError(f"A skill may have at most {_MAX_TAGS} tags.")
    return cleaned


def _validate_references(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("references must be a list of {path, content} objects.")
    if len(raw) > _MAX_REFERENCE_FILES:
        raise ValueError(f"At most {_MAX_REFERENCE_FILES} reference files are allowed.")

    from deeptutor.services.skill.service import _IMPORT_ALLOWED_SUFFIXES

    cleaned: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each reference must be an object with path and content.")
        path = str(item.get("path") or "").strip()
        content = str(item.get("content") or "")
        if not path.startswith("references/"):
            raise ValueError(f"Reference path must start with 'references/': {path!r}")
        if path.startswith("/") or ".." in Path(path).parts:
            raise ValueError(f"Reference path must be a relative path with no '..': {path!r}")
        if path in seen_paths:
            raise ValueError(f"Duplicate reference path: {path!r}")
        suffix = Path(path).suffix.lower()
        if suffix not in _IMPORT_ALLOWED_SUFFIXES:
            raise ValueError(f"Reference file type not allowed: {path!r}")
        size = len(content.encode("utf-8"))
        if size > _MAX_REFERENCE_FILE_BYTES:
            raise ValueError(f"Reference file too large: {path!r}")
        total_bytes += size
        if total_bytes > _MAX_REFERENCE_TOTAL_BYTES:
            raise ValueError("Reference files exceed the total size limit.")
        seen_paths.add(path)
        cleaned.append({"path": path, "content": content})
    return cleaned


class CreationKind:
    """Base adapter for one artifact type create mode can author."""

    key: str
    label: str
    #: Where the review card links the user once the artifact is saved.
    href: str

    def normalize(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Validate raw tool fields into ``{name, description, content, tags, references}``.

        Raises ``ValueError`` with a message the model can act on.
        """
        raise NotImplementedError

    def name_in_use(self, name: str) -> bool:
        raise NotImplementedError

    def list_names(self, limit: int = 60) -> list[str]:
        """Existing names, so the prompt can steer the model away from collisions."""
        raise NotImplementedError

    def publish(self, draft: "CreationDraft", *, replace: bool) -> str:
        """Write the draft through the owning service; returns the saved name."""
        raise NotImplementedError


class SkillKind(CreationKind):
    key = "skill"
    label = "Skill"
    href = "/space/skills"

    def normalize(self, fields: dict[str, Any]) -> dict[str, Any]:
        name, description, content = _normalize_common(fields)
        return {
            "name": name,
            "description": description,
            "content": content,
            "tags": _validate_tags(fields.get("tags")),
            "references": _validate_references(fields.get("references")),
        }

    def name_in_use(self, name: str) -> bool:
        from deeptutor.services.skill import get_skill_service
        from deeptutor.services.skill.service import SkillNotFoundError

        try:
            get_skill_service().get_detail(name)
            return True
        except SkillNotFoundError:
            return False

    def list_names(self, limit: int = 60) -> list[str]:
        from deeptutor.services.skill import get_skill_service

        return [info.name for info in get_skill_service().list_skills()][:limit]

    def publish(self, draft: "CreationDraft", *, replace: bool) -> str:
        import shutil
        import tempfile

        import yaml

        from deeptutor.services.skill import get_skill_service

        staging = Path(tempfile.mkdtemp(prefix="creation-skill-"))
        try:
            frontmatter: dict[str, Any] = {"name": draft.name, "description": draft.description}
            if draft.tags:
                frontmatter["tags"] = list(draft.tags)
            header = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
            (staging / "SKILL.md").write_text(
                f"---\n{header}\n---\n\n{draft.content.strip()}\n", encoding="utf-8"
            )
            for reference in draft.references:
                dest = staging / reference["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(reference.get("content", ""), encoding="utf-8")
            result = get_skill_service().install_tree(
                staging,
                rename_to=draft.name,
                fallback_description=draft.description,
                force=replace,
            )
            return result.info.name
        finally:
            shutil.rmtree(staging, ignore_errors=True)


class PersonaKind(CreationKind):
    key = "persona"
    label = "Persona"
    href = "/space/personas"

    def normalize(self, fields: dict[str, Any]) -> dict[str, Any]:
        # Tags and references are a Skill-only concept; a persona ignores them
        # rather than rejecting a payload that still carries empty defaults.
        name, description, content = _normalize_common(fields)
        return {
            "name": name,
            "description": description,
            "content": content,
            "tags": [],
            "references": [],
        }

    def name_in_use(self, name: str) -> bool:
        from deeptutor.multi_user.paths import get_admin_path_service
        from deeptutor.services.persona import PersonaNotFoundError, get_persona_service
        from deeptutor.services.persona.service import PersonaService

        service = get_persona_service()
        try:
            service.get_detail(name)
            return True
        except PersonaNotFoundError:
            pass
        admin_root = get_admin_path_service().get_workspace_dir() / "personas"
        if admin_root.resolve() == service.root.resolve():
            return False
        try:
            PersonaService(root=admin_root).get_detail(name)
            return True
        except PersonaNotFoundError:
            return False

    def list_names(self, limit: int = 60) -> list[str]:
        from deeptutor.services.persona import get_persona_service

        return [info.name for info in get_persona_service().list_personas()][:limit]

    def publish(self, draft: "CreationDraft", *, replace: bool) -> str:
        from deeptutor.services.persona import get_persona_service

        service = get_persona_service()
        if replace:
            info = service.update(draft.name, description=draft.description, content=draft.content)
        else:
            info = service.create(draft.name, draft.description, draft.content)
        return info.name


CREATION_KINDS: dict[str, CreationKind] = {"skill": SkillKind(), "persona": PersonaKind()}


def get_creation_kind(key: Any) -> CreationKind | None:
    return CREATION_KINDS.get(str(key or ""))


__all__ = [
    "CREATION_KINDS",
    "CreationKind",
    "PersonaKind",
    "SkillKind",
    "get_creation_kind",
]
