"""
PersonaService
==============

Loads user-authored PERSONA.md files from ``data/user/workspace/personas/``.

A persona is a behaviour/voice preset ("teacher", "peer", …) the user picks
for a conversation. Unlike capability skills (see
:mod:`deeptutor.services.skill`), a persona must shape the model's voice from
the very first token, so the selected persona's body is injected verbatim
into the system prompt — eagerly, never on demand. Exactly one persona can
be active per turn.

Each persona lives in its own directory:

    data/user/workspace/personas/<name>/PERSONA.md

The file starts with a YAML frontmatter block holding ``name`` and
``description``, followed by the Markdown body that becomes the system-prompt
block when the persona is active.

Legacy migration: persona-type entries that historically lived in the skills
workspace (``peer`` / ``teacher`` / ``research-assistant``) are moved into the
personas root on first service access for a workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
from typing import Any

import yaml

from deeptutor.services.path_service import get_path_service

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

PERSONA_FILE = "PERSONA.md"

# Product-seeded persona skills that predate the persona/skill split. Only
# these well-known names are migrated automatically — arbitrary user skills
# cannot be classified safely and stay where they are.
LEGACY_PERSONA_SKILLS: tuple[str, ...] = ("peer", "teacher", "research-assistant")


@dataclass(slots=True)
class PersonaInfo:
    name: str
    description: str
    source: str = "user"  # "user" | "admin"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "read_only": self.source != "user",
        }


@dataclass(slots=True)
class PersonaDetail:
    name: str
    description: str
    content: str
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "source": self.source,
            "read_only": self.source != "user",
        }


class PersonaNotFoundError(Exception):
    pass


class PersonaExistsError(Exception):
    pass


class InvalidPersonaNameError(Exception):
    pass


class PersonaService:
    """CRUD + context rendering for PERSONA.md files under one workspace."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or (get_path_service().get_workspace_dir() / "personas")

    @property
    def root(self) -> Path:
        return self._root

    # ── path helpers ────────────────────────────────────────────────────

    def _validate_name(self, name: str) -> str:
        candidate = (name or "").strip().lower()
        if not _NAME_RE.match(candidate):
            raise InvalidPersonaNameError("Persona name must match ^[a-z0-9][a-z0-9-]{0,63}$")
        return candidate

    def _persona_dir(self, name: str) -> Path:
        return self._root / self._validate_name(name)

    def _persona_file(self, name: str) -> Path:
        return self._persona_dir(name) / PERSONA_FILE

    # ── parsing ─────────────────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
        match = _FRONTMATTER_RE.match(content)
        if not match:
            return {}, content
        raw = match.group(1)
        body = content[match.end() :]
        try:
            data = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return data, body

    @staticmethod
    def _render_frontmatter(name: str, description: str) -> str:
        header = yaml.safe_dump(
            {"name": name, "description": description.strip()},
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        return f"---\n{header}\n---"

    def _normalize_content(self, name: str, description: str, content: str) -> str:
        """Ensure the saved file carries exactly ``name`` + ``description`` frontmatter."""
        _, body = self._parse_frontmatter(content or "")
        header = self._render_frontmatter(name, description)
        return f"{header}\n\n{body.lstrip()}".rstrip() + "\n"

    # ── public read API ─────────────────────────────────────────────────

    def list_personas(self) -> list[PersonaInfo]:
        if not self._root.exists():
            return []
        out: list[PersonaInfo] = []
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir():
                continue
            file = entry / PERSONA_FILE
            if not file.exists():
                continue
            try:
                text = file.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, _ = self._parse_frontmatter(text)
            out.append(
                PersonaInfo(
                    name=entry.name,
                    description=str(meta.get("description") or "").strip(),
                )
            )
        return out

    def get_detail(self, name: str) -> PersonaDetail:
        file = self._persona_file(name)
        if not file.exists():
            raise PersonaNotFoundError(name)
        text = file.read_text(encoding="utf-8")
        meta, _ = self._parse_frontmatter(text)
        return PersonaDetail(
            name=self._validate_name(name),
            description=str(meta.get("description") or "").strip(),
            content=text,
        )

    def load_for_context(self, name: str) -> str:
        """Render the selected persona into the system-prompt block.

        Returns ``""`` when the persona doesn't exist or has an empty body —
        a missing persona must never break the turn.
        """
        if not name:
            return ""
        try:
            detail = self.get_detail(name)
        except (PersonaNotFoundError, InvalidPersonaNameError):
            return ""
        _, body = self._parse_frontmatter(detail.content)
        body = body.strip()
        if not body:
            return ""
        return (
            "## Active Persona\n"
            "Embody the persona below for this entire conversation. "
            "It overrides generic style defaults.\n\n"
            f"### Persona: {detail.name}\n\n{body}"
        )

    # ── public write API ────────────────────────────────────────────────

    def create(self, name: str, description: str, content: str) -> PersonaInfo:
        slug = self._validate_name(name)
        target_dir = self._persona_dir(slug)
        if target_dir.exists():
            raise PersonaExistsError(slug)
        body = self._normalize_content(slug, description, content)
        target_dir.mkdir(parents=True, exist_ok=False)
        self._persona_file(slug).write_text(body, encoding="utf-8")
        return PersonaInfo(name=slug, description=description.strip())

    def update(
        self,
        name: str,
        *,
        description: str | None = None,
        content: str | None = None,
        rename_to: str | None = None,
    ) -> PersonaInfo:
        slug = self._validate_name(name)
        target_dir = self._persona_dir(slug)
        if not target_dir.exists():
            raise PersonaNotFoundError(slug)

        current = self.get_detail(slug)
        new_description = description if description is not None else current.description
        new_body_source = content if content is not None else current.content

        if rename_to and rename_to != slug:
            new_slug = self._validate_name(rename_to)
            new_dir = self._persona_dir(new_slug)
            if new_dir.exists():
                raise PersonaExistsError(new_slug)
            target_dir.rename(new_dir)
            slug = new_slug

        text = self._normalize_content(slug, new_description, new_body_source)
        self._persona_file(slug).write_text(text, encoding="utf-8")
        return PersonaInfo(name=slug, description=new_description.strip())

    def delete(self, name: str) -> None:
        slug = self._validate_name(name)
        target_dir = self._persona_dir(slug)
        if not target_dir.exists():
            raise PersonaNotFoundError(slug)
        shutil.rmtree(target_dir)

    # ── legacy migration ────────────────────────────────────────────────

    def migrate_legacy_skills(self, skills_root: Path) -> list[str]:
        """Move product-seeded persona skills out of the skills workspace.

        For each well-known legacy name: ``skills/<name>/SKILL.md`` becomes
        ``personas/<name>/PERSONA.md`` with frontmatter reduced to
        ``name`` + ``description`` (legacy ``triggers``/``tags`` keys are
        dropped — keyword routing is retired). Idempotent: names that are
        absent in the skills root or already present in the personas root
        are skipped.

        Returns the list of migrated names.
        """
        migrated: list[str] = []
        for name in LEGACY_PERSONA_SKILLS:
            source_file = skills_root / name / "SKILL.md"
            if not source_file.exists():
                continue
            if self._persona_dir(name).exists():
                continue
            try:
                text = source_file.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = self._parse_frontmatter(text)
            description = str(meta.get("description") or "").strip()
            self._root.mkdir(parents=True, exist_ok=True)
            target_dir = self._persona_dir(name)
            target_dir.mkdir(parents=True, exist_ok=True)
            self._persona_file(name).write_text(
                self._normalize_content(name, description, body),
                encoding="utf-8",
            )
            shutil.rmtree(source_file.parent)
            migrated.append(name)
        return migrated


_instances: dict[str, PersonaService] = {}


def get_persona_service() -> PersonaService:
    """Return the PersonaService for the active user's workspace.

    First access for a workspace also runs the one-shot legacy migration of
    persona-type skills (idempotent, see
    :meth:`PersonaService.migrate_legacy_skills`).
    """
    workspace = get_path_service().get_workspace_dir()
    root = (workspace / "personas").resolve()
    key = str(root)
    if key not in _instances:
        service = PersonaService(root=root)
        service.migrate_legacy_skills(workspace / "skills")
        _instances[key] = service
    return _instances[key]


__all__ = [
    "InvalidPersonaNameError",
    "LEGACY_PERSONA_SKILLS",
    "PERSONA_FILE",
    "PersonaDetail",
    "PersonaExistsError",
    "PersonaInfo",
    "PersonaNotFoundError",
    "PersonaService",
    "get_persona_service",
]
