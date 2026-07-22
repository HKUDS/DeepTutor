"""
SkillService
============

Capability-skill storage and runtime loading, nanobot-style.

A skill is a self-contained capability package the model consults *on
demand*: a ``SKILL.md`` playbook plus optional ``references/`` (and, once the
execution sandbox ships, ``scripts/``). Skills are never injected wholesale
into the system prompt — the prompt carries a one-line-per-skill manifest
(see :func:`render_skills_manifest`) and the model fetches full content
through the ``read_skill`` tool when a task matches. The exceptions are
skills marked ``always: true`` in frontmatter, whose bodies are eagerly
injected (used for house rules that must apply to every turn).

Two layers, user shadows builtin:

* builtin — shipped with the product under ``deeptutor/skills/builtin/``,
  read-only at runtime;
* user — authored via the API under ``data/user/workspace/skills/``.

Each skill lives in its own directory::

    <root>/<name>/SKILL.md
    <root>/<name>/references/...   (optional, readable via read_skill)

Frontmatter schema::

    ---
    name: my-skill
    description: One-line summary shown in the manifest.
    tags: [style]            # optional, user-facing organisation only
    always: false            # optional, eager-inject when true
    requires:                 # optional availability gates
      bins: [git]            # CLI binaries that must exist on PATH
      env: [GITHUB_TOKEN]    # environment variables that must be set
      sandbox: shell         # needs the shell execution sandbox
    ---

A small ``.tags.json`` file next to the user skill directories holds the
canonical user-managed tag vocabulary so tags can be created, renamed, or
deleted independently of the skills that use them.

Behaviour/voice presets ("teacher", "peer", …) are NOT skills — they live in
:mod:`deeptutor.services.persona` and are eagerly injected because a persona
must shape the voice from the first token.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

import yaml

from deeptutor.services.path_service import get_path_service

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_TAG_RE = re.compile(r"^[a-z0-9][a-z0-9\- _]{0,31}$")
_DEFAULT_TAGS: tuple[str, ...] = ("style", "tool")
_TAGS_FILE = ".tags.json"

# Builtin skills shipped inside the package. Partners run on the chat agent
# loop, so this is the single builtin set for both product chat and partner
# workspaces (the old TutorBot-only skill set died with its engine).
BUILTIN_SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills" / "builtin"

# Hard cap for read_skill payloads so a huge reference file cannot flood the
# context window. Mirrors the truncation posture of the other read tools.
_MAX_READ_CHARS = 100_000

# Provenance ledger for skills imported from an external hub (ClawHub, …).
# Sits beside ``.tags.json`` so the UI/CLI can show "from clawhub@1.2.0" and
# an update path knows where each imported skill came from.
_HUB_LOCK_FILE = ".hub-lock.json"

# Bounds for importing a skill package from an untrusted source. A skill is a
# text playbook plus small supporting files — anything bigger is suspect, so
# the import fails closed instead of filling the workspace.
_IMPORT_MAX_FILE_BYTES = 1_000_000
_IMPORT_MAX_TOTAL_BYTES = 20_000_000
_IMPORT_MAX_FILES = 500

# Supporting-file suffixes an imported skill may carry (whitelist, lowercase).
# Text playbooks, references, and scripts only — never binaries or archives.
# Suffix-less files (LICENSE, Makefile) are allowed; copies drop the exec bit.
_IMPORT_ALLOWED_SUFFIXES = frozenset(
    {
        "",
        ".md", ".markdown", ".txt", ".rst",
        ".py", ".js", ".mjs", ".ts", ".sh", ".rb", ".lua", ".r",
        ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg",
        ".csv", ".tsv", ".html", ".htm", ".css", ".xml", ".sql",
        ".jinja", ".j2", ".tmpl", ".template",
    }
)  # fmt: skip


@dataclass(slots=True)
class SkillInfo:
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    source: str = "user"  # "user" | "builtin" | "admin"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "tags": list(self.tags),
            "source": self.source,
            "read_only": self.source != "user",
        }


@dataclass(slots=True)
class SkillDetail:
    name: str
    description: str
    content: str
    tags: list[str] = field(default_factory=list)
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "tags": list(self.tags),
            "source": self.source,
            "read_only": self.source != "user",
        }


@dataclass(slots=True)
class SkillSummaryEntry:
    """One manifest row: what the model sees about a skill before reading it."""

    name: str
    description: str
    available: bool = True
    missing: list[str] = field(default_factory=list)
    always: bool = False


@dataclass(slots=True)
class SkillInstallResult:
    """Outcome of :meth:`SkillService.install_tree`.

    ``skipped`` lists support files the import gate dropped, as
    ``(relative-path, reason)`` pairs, so callers can surface what did not
    make it into the workspace instead of failing the whole install.
    """

    info: SkillInfo
    skipped: list[tuple[str, str]] = field(default_factory=list)


class SkillNotFoundError(Exception):
    pass


class SkillExistsError(Exception):
    pass


class SkillReadOnlyError(Exception):
    """Raised when a write targets a builtin (read-only) skill."""


class InvalidSkillNameError(Exception):
    pass


class InvalidSkillPathError(Exception):
    """Raised when ``read_skill_file`` is asked for a path outside the skill dir."""


class SkillImportError(Exception):
    """Raised when an imported skill package fails a structural/safety gate."""


class InvalidTagError(Exception):
    pass


class TagNotFoundError(Exception):
    pass


class TagExistsError(Exception):
    pass


def _sandbox_available(kind: str) -> bool:
    """Whether the execution sandbox satisfies a ``requires.sandbox`` gate.

    Late import so the skill layer stays decoupled from the sandbox layer;
    fails closed when the sandbox service is absent or disabled.
    """
    try:
        from deeptutor.services.sandbox import exec_capability_available

        return exec_capability_available(kind)
    except Exception:
        return False


class SkillService:
    """CRUD + runtime loading for SKILL.md packages (builtin + user layers)."""

    def __init__(
        self,
        root: Path | None = None,
        builtin_root: Path | None = BUILTIN_SKILLS_ROOT,
    ) -> None:
        self._root = root or (get_path_service().get_workspace_dir() / "skills")
        self._builtin_root = builtin_root

    @property
    def root(self) -> Path:
        return self._root

    # ── path helpers ────────────────────────────────────────────────────

    def _validate_name(self, name: str) -> str:
        candidate = (name or "").strip().lower()
        if not _NAME_RE.match(candidate):
            raise InvalidSkillNameError("Skill name must match ^[a-z0-9][a-z0-9-]{0,63}$")
        return candidate

    def _skill_dir(self, name: str) -> Path:
        return self._root / self._validate_name(name)

    def _skill_file(self, name: str) -> Path:
        return self._skill_dir(name) / "SKILL.md"

    def _resolve_skill_dir(self, name: str) -> tuple[Path, str] | None:
        """Locate a skill across layers: user first, then builtin."""
        slug = self._validate_name(name)
        user_dir = self._root / slug
        if (user_dir / "SKILL.md").exists():
            return user_dir, "user"
        if self._builtin_root is not None:
            builtin_dir = self._builtin_root / slug
            if (builtin_dir / "SKILL.md").exists():
                return builtin_dir, "builtin"
        return None

    # ── tag helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _normalize_tag(raw: Any) -> str:
        candidate = str(raw or "").strip().lower()
        if not candidate:
            raise InvalidTagError("Tag name must not be empty.")
        if not _TAG_RE.match(candidate):
            raise InvalidTagError(
                "Tag must match ^[a-z0-9][a-z0-9- _]{0,31}$ (letters/digits/dash/space/underscore)."
            )
        return candidate

    @staticmethod
    def _dedupe_tags(values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for v in values:
            if v in seen:
                continue
            seen.add(v)
            out.append(v)
        return out

    def _tags_path(self) -> Path:
        return self._root / _TAGS_FILE

    def _read_tag_vocab(self) -> list[str]:
        path = self._tags_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw = data.get("tags") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            try:
                out.append(self._normalize_tag(item))
            except InvalidTagError:
                continue
        return self._dedupe_tags(out)

    def _write_tag_vocab(self, tags: list[str]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = {"tags": self._dedupe_tags(tags)}
        self._tags_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _tags_from_meta(self, meta: dict[str, Any]) -> list[str]:
        raw = meta.get("tags")
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            try:
                out.append(self._normalize_tag(item))
            except InvalidTagError:
                continue
        return self._dedupe_tags(out)

    def _collect_skill_tags(self) -> list[str]:
        """Scan user skills and collect tags present in their frontmatter."""
        found: list[str] = []
        for info in self.list_skills():
            if info.source != "user":
                continue
            for tag in info.tags:
                if tag not in found:
                    found.append(tag)
        return found

    def _ensure_initialized_vocab(self) -> list[str]:
        """Seed default tags on first access and backfill any tags found on skills."""
        vocab = self._read_tag_vocab()
        existed = self._tags_path().exists()
        if not existed:
            vocab = list(_DEFAULT_TAGS)
        union = self._dedupe_tags(vocab + self._collect_skill_tags())
        if not existed or union != vocab:
            self._write_tag_vocab(union)
        return union

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
    def _requires_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
        raw = meta.get("requires")
        return raw if isinstance(raw, dict) else {}

    @classmethod
    def _availability(cls, meta: dict[str, Any]) -> tuple[bool, list[str]]:
        """Check ``requires`` gates; return ``(available, missing-labels)``.

        ``bins`` are checked against the host PATH. Once the runner-sidecar
        sandbox ships, exec-flavoured skills should prefer the
        ``sandbox`` gate over host ``bins`` (the runner image carries its
        own binaries).
        """
        requires = cls._requires_from_meta(meta)
        missing: list[str] = []
        for b in requires.get("bins") or []:
            label = str(b).strip()
            if label and not shutil.which(label):
                missing.append(f"CLI: {label}")
        for env_var in requires.get("env") or []:
            label = str(env_var).strip()
            if label and not os.environ.get(label):
                missing.append(f"ENV: {label}")
        sandbox = requires.get("sandbox")
        if sandbox:
            kind = "shell" if sandbox is True else str(sandbox).strip()
            if kind and not _sandbox_available(kind):
                missing.append(f"SANDBOX: {kind}")
        return (not missing), missing

    def _load_info(self, skill_dir: Path, source: str) -> SkillInfo | None:
        file = skill_dir / "SKILL.md"
        try:
            text = file.read_text(encoding="utf-8")
        except OSError:
            return None
        meta, _ = self._parse_frontmatter(text)
        return SkillInfo(
            name=skill_dir.name,
            description=str(meta.get("description") or "").strip(),
            tags=self._tags_from_meta(meta),
            source=source,
        )

    # ── public read API ─────────────────────────────────────────────────

    def list_skills(self) -> list[SkillInfo]:
        """All skills visible from this service: user layer + unshadowed builtin."""
        out: list[SkillInfo] = []
        seen: set[str] = set()
        if self._root.exists():
            for entry in sorted(self._root.iterdir()):
                if not entry.is_dir() or not (entry / "SKILL.md").exists():
                    continue
                if not _NAME_RE.match(entry.name):
                    continue
                info = self._load_info(entry, "user")
                if info is not None:
                    out.append(info)
                    seen.add(info.name)
        if self._builtin_root is not None and self._builtin_root.exists():
            for entry in sorted(self._builtin_root.iterdir()):
                if not entry.is_dir() or not (entry / "SKILL.md").exists():
                    continue
                if entry.name in seen or not _NAME_RE.match(entry.name):
                    continue
                info = self._load_info(entry, "builtin")
                if info is not None:
                    out.append(info)
        return out

    def get_detail(self, name: str) -> SkillDetail:
        resolved = self._resolve_skill_dir(name)
        if resolved is None:
            raise SkillNotFoundError(name)
        skill_dir, source = resolved
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        meta, _ = self._parse_frontmatter(text)
        return SkillDetail(
            name=skill_dir.name,
            description=str(meta.get("description") or "").strip(),
            content=text,
            tags=self._tags_from_meta(meta),
            source=source,
        )

    def read_skill_file(self, name: str, rel_path: str = "SKILL.md") -> str:
        """Read a file from inside a skill package (for the ``read_skill`` tool).

        ``rel_path`` is resolved strictly within the skill directory —
        absolute paths and traversal segments are rejected. Content longer
        than the read cap is truncated with an explicit marker.
        """
        resolved = self._resolve_skill_dir(name)
        if resolved is None:
            raise SkillNotFoundError(name)
        skill_dir, _source = resolved

        candidate = (rel_path or "SKILL.md").strip() or "SKILL.md"
        rel = Path(candidate)
        if rel.is_absolute() or ".." in rel.parts:
            raise InvalidSkillPathError(f"Illegal skill file path: {rel_path}")
        target = (skill_dir / rel).resolve()
        if not target.is_relative_to(skill_dir.resolve()):
            raise InvalidSkillPathError(f"Illegal skill file path: {rel_path}")
        if not target.is_file():
            raise SkillNotFoundError(f"{name}/{candidate}")
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > _MAX_READ_CHARS:
            text = text[:_MAX_READ_CHARS] + "\n\n[... truncated ...]"
        return text

    def list_skill_files(self, name: str) -> list[str]:
        """Relative paths of readable files inside a skill package."""
        resolved = self._resolve_skill_dir(name)
        if resolved is None:
            raise SkillNotFoundError(name)
        skill_dir, _source = resolved
        files: list[str] = []
        for path in sorted(skill_dir.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                files.append(str(path.relative_to(skill_dir)))
        return files

    # ── runtime loading (manifest + always) ─────────────────────────────

    def summary_entries(self) -> list[SkillSummaryEntry]:
        """Manifest rows for every skill visible from this service."""
        entries: list[SkillSummaryEntry] = []
        for info in self.list_skills():
            resolved = self._resolve_skill_dir(info.name)
            if resolved is None:
                continue
            skill_dir, _source = resolved
            meta, _ = self._parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
            available, missing = self._availability(meta)
            entries.append(
                SkillSummaryEntry(
                    name=info.name,
                    description=info.description,
                    available=available,
                    missing=missing,
                    always=bool(meta.get("always")),
                )
            )
        return entries

    def load_for_context(self, names: list[str]) -> str:
        """Render the given skills' full bodies into a system-prompt block.

        Used for ``always: true`` skills only — everything else reaches the
        model through the manifest + ``read_skill``.
        """
        if not names:
            return ""
        parts: list[str] = []
        for name in names:
            try:
                detail = self.get_detail(name)
            except (SkillNotFoundError, InvalidSkillNameError):
                continue
            _, body = self._parse_frontmatter(detail.content)
            body = body.strip()
            if not body:
                continue
            parts.append(f"### Skill: {detail.name}\n\n{body}")
        if not parts:
            return ""
        return (
            "## Active Skills\n"
            "Follow the playbooks below. They override generic defaults.\n\n"
            + "\n\n---\n\n".join(parts)
        )

    def load_always_for_context(self) -> str:
        """Eagerly render skills marked ``always: true`` (and available)."""
        names = [e.name for e in self.summary_entries() if e.always and e.available]
        return self.load_for_context(names)

    # ── public write API (user layer only) ──────────────────────────────

    def _assert_writable(self, slug: str) -> None:
        """Writes must target the user layer; builtin skills are read-only."""
        if (self._root / slug / "SKILL.md").exists():
            return
        if self._builtin_root is not None and (self._builtin_root / slug / "SKILL.md").exists():
            raise SkillReadOnlyError(f"Skill is builtin (read-only): {slug}")
        raise SkillNotFoundError(slug)

    def create(
        self,
        name: str,
        description: str,
        content: str,
        tags: list[str] | None = None,
    ) -> SkillInfo:
        slug = self._validate_name(name)
        target_dir = self._skill_dir(slug)
        if target_dir.exists():
            raise SkillExistsError(slug)
        clean_tags = self._validate_tag_list(tags)
        body = self._normalize_content(
            slug,
            description,
            content,
            tags=clean_tags,
        )
        target_dir.mkdir(parents=True, exist_ok=False)
        self._skill_file(slug).write_text(body, encoding="utf-8")
        self._merge_tags_into_vocab(clean_tags)
        return SkillInfo(name=slug, description=description.strip(), tags=clean_tags)

    def update(
        self,
        name: str,
        *,
        description: str | None = None,
        content: str | None = None,
        rename_to: str | None = None,
        tags: list[str] | None = None,
    ) -> SkillInfo:
        slug = self._validate_name(name)
        self._assert_writable(slug)
        target_dir = self._skill_dir(slug)

        if content is not None:
            text = content
        else:
            text = self._skill_file(slug).read_text(encoding="utf-8")

        if description is not None:
            text = self._rewrite_frontmatter(text, description=description.strip())

        clean_tags: list[str] | None = None
        if tags is not None:
            clean_tags = self._validate_tag_list(tags)
            text = self._rewrite_frontmatter(text, tags=clean_tags)

        meta, _ = self._parse_frontmatter(text)
        final_description = str(meta.get("description") or "").strip()
        final_tags = self._tags_from_meta(meta)

        if rename_to and rename_to != slug:
            new_slug = self._validate_name(rename_to)
            new_dir = self._skill_dir(new_slug)
            if new_dir.exists():
                raise SkillExistsError(new_slug)
            text = self._rewrite_frontmatter(text, name=new_slug)
            target_dir.rename(new_dir)
            slug = new_slug
            target_dir = new_dir

        self._skill_file(slug).write_text(text, encoding="utf-8")
        if clean_tags is not None:
            self._merge_tags_into_vocab(clean_tags)
        return SkillInfo(name=slug, description=final_description, tags=final_tags)

    def delete(self, name: str) -> None:
        slug = self._validate_name(name)
        self._assert_writable(slug)
        shutil.rmtree(self._skill_dir(slug))
        self._drop_hub_origin(slug)

    # ── imported skill packages (hub) ────────────────────────────────────

    def install_tree(
        self,
        source_dir: str | Path,
        *,
        rename_to: str | None = None,
        fallback_description: str | None = None,
        origin: dict[str, Any] | None = None,
        force: bool = False,
        extra_tags: list[str] | None = None,
    ) -> SkillInstallResult:
        """Import an extracted skill package directory into the user layer.

        Unlike :meth:`create` (single authored ``SKILL.md``), this takes a
        whole package tree — ``SKILL.md`` plus support files — as produced by
        an external hub download, and applies the import policy:

        * frontmatter is adapted: ``name`` is forced to the slug, flat
          ``bins:``/``env:`` keys (Agent-Skills style) fold into
          ``requires.*``, and ``always:`` is **stripped** — an imported skill
          must never eager-inject itself into the system prompt;
        * support files pass a suffix whitelist plus size/count caps;
          symlinks abort the import (see :meth:`_copy_support_tree`);
        * the tree is staged and swapped in atomically, so a failed import
          never leaves a half-written skill;
        * ``extra_tags`` are merged into the package's own tags (the hub
          installer stamps the source hub, e.g. ``eduhub``, this way);
        * ``origin`` (hub provenance) is recorded in ``.hub-lock.json``.
        """
        source = Path(source_dir).resolve()
        skill_md = source / "SKILL.md"
        if not skill_md.is_file():
            raise SkillImportError("Package has no SKILL.md at its root.")
        if skill_md.stat().st_size > _IMPORT_MAX_FILE_BYTES:
            raise SkillImportError("SKILL.md exceeds the import size limit.")
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        meta, body = self._parse_frontmatter(text)

        slug = self._validate_name(self._slugify(str(rename_to or meta.get("name") or source.name)))
        description = (
            str(meta.get("description") or "").strip() or (fallback_description or "").strip()
        )
        if not description:
            raise SkillImportError("SKILL.md has no description and no fallback was provided.")
        tags = self._validate_tag_list(
            (meta.get("tags") if isinstance(meta.get("tags"), list) else [])
            + list(extra_tags or [])
        )

        target_dir = self._skill_dir(slug)
        if target_dir.exists() and not force:
            raise SkillExistsError(slug)

        header = yaml.safe_dump(
            self._compose_imported_frontmatter(meta, slug=slug, description=description, tags=tags),
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        adapted = f"---\n{header}\n---\n\n{body.lstrip()}".rstrip() + "\n"

        staging = self._root / f".install-{slug}.tmp"
        if staging.exists():
            shutil.rmtree(staging)
        try:
            staging.mkdir(parents=True)
            skipped = self._copy_support_tree(source, staging)
            (staging / "SKILL.md").write_text(adapted, encoding="utf-8")
            if target_dir.exists():
                shutil.rmtree(target_dir)
            staging.rename(target_dir)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        self._merge_tags_into_vocab(tags)
        if origin is not None:
            self.record_hub_origin(slug, origin)
        else:
            self._drop_hub_origin(slug)
        return SkillInstallResult(
            info=SkillInfo(name=slug, description=description, tags=tags),
            skipped=skipped,
        )

    @staticmethod
    def _slugify(raw: str) -> str:
        candidate = re.sub(r"[^a-z0-9-]+", "-", (raw or "").strip().lower())
        return re.sub(r"-{2,}", "-", candidate).strip("-")[:64]

    @staticmethod
    def _as_str_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _compose_imported_frontmatter(
        self,
        meta: dict[str, Any],
        *,
        slug: str,
        description: str,
        tags: list[str],
    ) -> dict[str, Any]:
        """Frontmatter for an imported skill: our schema, their extras.

        Flat ``bins``/``env`` (the Agent-Skills/ClawHub spelling) merge into
        ``requires.*``; ``always`` is dropped — letting a downloaded package
        force itself into every system prompt would be an injection vector.
        Unknown keys (version, license, metadata, …) ride along untouched.
        """
        requires_raw = meta.get("requires")
        requires = dict(requires_raw) if isinstance(requires_raw, dict) else {}
        bins = self._dedupe_tags(
            self._as_str_list(requires.get("bins")) + self._as_str_list(meta.get("bins"))
        )
        env = self._dedupe_tags(
            self._as_str_list(requires.get("env")) + self._as_str_list(meta.get("env"))
        )
        if bins:
            requires["bins"] = bins
        if env:
            requires["env"] = env

        out: dict[str, Any] = {"name": slug, "description": description}
        if tags:
            out["tags"] = list(tags)
        if requires:
            out["requires"] = requires
        for key, value in meta.items():
            if key in {"name", "description", "tags", "requires", "bins", "env", "always"}:
                continue
            out[key] = value
        return out

    def _copy_support_tree(self, source: Path, staging: Path) -> list[tuple[str, str]]:
        """Copy a package's support files into the staging dir, gated.

        Dotfiles/dot-dirs are silently ignored; disallowed suffixes and
        oversized files are skipped and reported; symlinks abort the whole
        import (a link can alias content outside the package). Copies go
        through ``shutil.copyfile`` so no permission bits (notably exec)
        survive the import.
        """
        skipped: list[tuple[str, str]] = []
        count = 0
        total = 0
        for path in sorted(source.rglob("*")):
            rel = path.relative_to(source)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if path.is_symlink():
                raise SkillImportError(f"Symbolic links are not allowed: {rel}")
            if path.is_dir():
                continue
            if rel.as_posix() == "SKILL.md":
                continue  # rewritten separately after frontmatter adaptation
            if path.suffix.lower() not in _IMPORT_ALLOWED_SUFFIXES:
                skipped.append((rel.as_posix(), "file type not allowed"))
                continue
            size = path.stat().st_size
            if size > _IMPORT_MAX_FILE_BYTES:
                skipped.append((rel.as_posix(), "file exceeds size limit"))
                continue
            count += 1
            total += size
            if count > _IMPORT_MAX_FILES:
                raise SkillImportError("Package has too many files.")
            if total > _IMPORT_MAX_TOTAL_BYTES:
                raise SkillImportError("Package exceeds the total size limit.")
            dest = staging / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)
        return skipped

    # ── hub provenance (.hub-lock.json) ──────────────────────────────────

    def _hub_lock_path(self) -> Path:
        return self._root / _HUB_LOCK_FILE

    def _read_hub_lock(self) -> dict[str, dict[str, Any]]:
        path = self._hub_lock_path()
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            key: value
            for key, value in data.items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def _write_hub_lock(self, data: dict[str, dict[str, Any]]) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        self._hub_lock_path().write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def record_hub_origin(self, name: str, origin: dict[str, Any]) -> None:
        slug = self._validate_name(name)
        lock = self._read_hub_lock()
        lock[slug] = dict(origin)
        self._write_hub_lock(lock)

    def hub_origin(self, name: str) -> dict[str, Any] | None:
        try:
            slug = self._validate_name(name)
        except InvalidSkillNameError:
            return None
        return self._read_hub_lock().get(slug)

    def _drop_hub_origin(self, slug: str) -> None:
        lock = self._read_hub_lock()
        if slug in lock:
            del lock[slug]
            self._write_hub_lock(lock)

    # ── tag management API ─────────────────────────────────────────────

    def list_tags(self) -> list[str]:
        return self._ensure_initialized_vocab()

    def create_tag(self, name: str) -> str:
        tag = self._normalize_tag(name)
        vocab = self._ensure_initialized_vocab()
        if tag in vocab:
            raise TagExistsError(tag)
        self._write_tag_vocab(vocab + [tag])
        return tag

    def rename_tag(self, old: str, new: str) -> str:
        old_tag = self._normalize_tag(old)
        new_tag = self._normalize_tag(new)
        vocab = self._ensure_initialized_vocab()
        if old_tag not in vocab:
            raise TagNotFoundError(old_tag)
        if new_tag != old_tag and new_tag in vocab:
            raise TagExistsError(new_tag)
        if new_tag == old_tag:
            return old_tag
        new_vocab = [new_tag if t == old_tag else t for t in vocab]
        self._write_tag_vocab(new_vocab)
        # Cascade: rewrite frontmatter on every user skill that used the old tag.
        self._replace_tag_in_skills(old_tag, new_tag)
        return new_tag

    def delete_tag(self, name: str) -> None:
        tag = self._normalize_tag(name)
        vocab = self._ensure_initialized_vocab()
        if tag not in vocab:
            raise TagNotFoundError(tag)
        new_vocab = [t for t in vocab if t != tag]
        self._write_tag_vocab(new_vocab)
        self._replace_tag_in_skills(tag, None)

    # ── internal tag helpers ───────────────────────────────────────────

    def _validate_tag_list(self, tags: list[str] | None) -> list[str]:
        if not tags:
            return []
        cleaned: list[str] = []
        for raw in tags:
            try:
                cleaned.append(self._normalize_tag(raw))
            except InvalidTagError:
                continue
        return self._dedupe_tags(cleaned)

    def _merge_tags_into_vocab(self, new_tags: list[str]) -> None:
        if not new_tags:
            # Still trigger init so the vocab file exists after first write.
            self._ensure_initialized_vocab()
            return
        vocab = self._ensure_initialized_vocab()
        merged = self._dedupe_tags(vocab + new_tags)
        if merged != vocab:
            self._write_tag_vocab(merged)

    def _replace_tag_in_skills(self, old_tag: str, new_tag: str | None) -> None:
        if not self._root.exists():
            return
        for entry in sorted(self._root.iterdir()):
            if not entry.is_dir() or not (entry / "SKILL.md").exists():
                continue
            info = self._load_info(entry, "user")
            if info is None or old_tag not in info.tags:
                continue
            updated: list[str] = []
            for t in info.tags:
                if t == old_tag:
                    if new_tag and new_tag not in updated:
                        updated.append(new_tag)
                elif t not in updated:
                    updated.append(t)
            text = (entry / "SKILL.md").read_text(encoding="utf-8")
            new_text = self._rewrite_frontmatter(text, tags=updated)
            (entry / "SKILL.md").write_text(new_text, encoding="utf-8")

    # ── content helpers ────────────────────────────────────────────────

    def _normalize_content(
        self,
        name: str,
        description: str,
        content: str,
        *,
        tags: list[str] | None = None,
    ) -> str:
        """Ensure the saved file has a valid frontmatter block with ``name``/``description``.

        If the user-provided ``content`` already has frontmatter we patch the
        ``name``, ``description`` and ``tags`` fields; otherwise we synthesise
        a header.
        """
        text = content if content is not None else ""
        if _FRONTMATTER_RE.match(text):
            text = self._rewrite_frontmatter(
                text,
                name=name,
                description=description.strip(),
                tags=tags,
            )
            return text
        payload: dict[str, Any] = {
            "name": name,
            "description": description.strip(),
        }
        if tags:
            payload["tags"] = list(tags)
        header = yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        body = text.lstrip()
        return f"---\n{header}\n---\n\n{body}".rstrip() + "\n"

    def _rewrite_frontmatter(
        self,
        text: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> str:
        meta, body = self._parse_frontmatter(text)
        if name is not None:
            meta["name"] = name
        if description is not None:
            meta["description"] = description
        if tags is not None:
            if tags:
                meta["tags"] = list(tags)
            elif "tags" in meta:
                meta.pop("tags", None)
        if not meta:
            return text
        header = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{header}\n---\n\n{body.lstrip()}".rstrip() + "\n"


def render_skills_manifest(entries: list[SkillSummaryEntry]) -> str:
    """Render manifest rows into the system-prompt Skills block.

    ``always`` entries are excluded — their full bodies are already injected
    eagerly, so listing them again would only waste tokens. Duplicate names
    keep their first occurrence (caller orders user > admin > builtin).
    """
    seen: set[str] = set()
    lines: list[str] = []
    for entry in entries:
        if entry.always or entry.name in seen:
            continue
        seen.add(entry.name)
        suffix = ""
        if not entry.available:
            suffix = f" (unavailable: {', '.join(entry.missing)})"
        description = entry.description or entry.name
        lines.append(f"- **{entry.name}** — {description}{suffix}")
    if not lines:
        return ""
    return (
        "## Skills\n"
        "Specialised playbooks available on demand. When a task matches a "
        "skill's description, call `read_skill` with its name BEFORE "
        "attempting the task, then follow the returned instructions. Skills "
        "marked unavailable cannot be used until their requirements are met.\n\n" + "\n".join(lines)
    )


_instances: dict[str, SkillService] = {}


def get_skill_service() -> SkillService:
    root = (get_path_service().get_workspace_dir() / "skills").resolve()
    key = str(root)
    if key not in _instances:
        _instances[key] = SkillService(root=root)
    return _instances[key]


__all__ = [
    "BUILTIN_SKILLS_ROOT",
    "InvalidSkillNameError",
    "InvalidSkillPathError",
    "InvalidTagError",
    "SkillDetail",
    "SkillExistsError",
    "SkillImportError",
    "SkillInfo",
    "SkillInstallResult",
    "SkillNotFoundError",
    "SkillReadOnlyError",
    "SkillService",
    "SkillSummaryEntry",
    "TagExistsError",
    "TagNotFoundError",
    "get_skill_service",
    "render_skills_manifest",
]
