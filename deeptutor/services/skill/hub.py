"""
Skill hub providers
===================

Import skills from external registries ("hubs") into the local skill layer.

A hub skill is the same artefact DeepTutor already speaks natively — a
directory with a ``SKILL.md`` (YAML frontmatter + markdown playbook) plus
optional support files — so importing is a fetch + adapt + install pipeline,
not a format translation:

1. **verify** — ask the hub for its security verdict on the package. A
   ``suspicious`` verdict aborts the install unless the caller explicitly
   opts out (registries of this kind have shipped malware before).
2. **fetch** — download and safely extract the package into a temp dir
   (zip-slip / zip-bomb guards live here).
3. **install** — :meth:`SkillService.install_tree` applies the import
   policy (frontmatter adaptation, ``always`` stripping, suffix whitelist)
   and records provenance in ``.hub-lock.json``.

Providers are addressed as ``<hub>:<slug>[@version]`` (e.g.
``eduhub:socratic-tutor@1.2.0``; the hub prefix defaults to ``eduhub``).
Two provider shapes ship in v1:

* :class:`ClawHubProvider` — speaks the ClawHub HTTP API directly (search /
  download / verify), so no Node toolchain is required;
* :class:`CommandProvider` — wraps an arbitrary fetch command for registries
  that only publish a CLI. The command must drop the package into the
  directory given as ``{dest}``; everything after that goes through the same
  verify-less install gate (verdict is ``unknown``).

Extra hubs are declared in ``settings/skill_hubs.json``::

    {
      "hubs": {
        "myhub": {"type": "command", "fetch_cmd": "myhub pull {slug} --out {dest}"},
        "mirror": {"type": "clawhub", "base_url": "https://mirror.example/api/v1"}
      }
    }
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from typing import Any, Protocol
import zipfile

import httpx

from deeptutor.services.path_service import get_path_service

from .service import SkillImportError, SkillInstallResult, SkillService

logger = logging.getLogger(__name__)

# DeepTutor ships pointing at EduHub, its native open skill registry: a bare
# ``install <slug>`` with no ``<hub>:`` prefix resolves here.
DEFAULT_HUB = "eduhub"
_CLAWHUB_BASE_URL = "https://clawhub.ai/api/v1"
_EDUHUB_BASE_URL = "https://eduhub.deeptutor.info/api/v1"
_HUBS_SETTINGS_FILE = "skill_hubs"

# Hubs available out of the box, no settings file required. Both speak the
# ClawHub HTTP protocol. A user's ``skill_hubs.json`` is layered on top and may
# override any entry (e.g. point ``eduhub`` at a local dev server).
_BUILTIN_HUBS: dict[str, dict[str, str]] = {
    "clawhub": {"type": "clawhub", "base_url": _CLAWHUB_BASE_URL},
    "eduhub": {"type": "clawhub", "base_url": _EDUHUB_BASE_URL},
}

_REF_RE = re.compile(
    r"^(?:(?P<hub>[a-z0-9][a-z0-9-]{0,31}):)?"
    r"(?P<slug>[a-z0-9][a-z0-9._-]{0,127})"
    r"(?:@(?P<version>[A-Za-z0-9][A-Za-z0-9._-]{0,63}))?$"
)

# Extraction bounds for a downloaded package archive. Structural safety only —
# the per-file suffix whitelist is applied later by ``install_tree``.
_ZIP_MAX_ENTRIES = 600
_ZIP_MAX_ENTRY_BYTES = 4_000_000
_ZIP_MAX_TOTAL_BYTES = 40_000_000
_ZIP_MAX_RATIO = 200.0

_HTTP_TIMEOUT = 30.0
_FETCH_CMD_TIMEOUT = 120.0


class HubError(Exception):
    """A hub interaction failed (network, protocol, or configuration)."""


@dataclass(slots=True)
class HubSkillRef:
    """One hub listing: enough to show a search row and stamp provenance."""

    hub: str
    slug: str
    display_name: str = ""
    summary: str = ""
    version: str = ""


@dataclass(slots=True)
class HubVerdict:
    """Hub security verdict, collapsed to a tri-state.

    ``ok`` — the hub vouches for the package; ``suspicious`` — the hub
    flags it (install is refused without an explicit override);
    ``unknown`` — the hub has no verdict surface or the call failed,
    so the caller should warn rather than block.
    """

    status: str  # "ok" | "suspicious" | "unknown"
    detail: str = ""


@dataclass(slots=True)
class FetchedSkill:
    """A downloaded package on local disk, pending install."""

    ref: HubSkillRef
    root: Path  # directory containing SKILL.md
    cleanup_dir: Path  # temp tree to remove once installed

    def cleanup(self) -> None:
        shutil.rmtree(self.cleanup_dir, ignore_errors=True)


@dataclass(slots=True)
class HubInstallOutcome:
    """Everything the caller needs to report an install."""

    result: SkillInstallResult
    ref: HubSkillRef
    verdict: HubVerdict


class SkillHubProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int = 10) -> list[HubSkillRef]: ...

    def fetch(self, slug: str, *, version: str | None = None) -> FetchedSkill: ...

    def verify(self, slug: str, *, version: str | None = None) -> HubVerdict: ...


# ── ref parsing ──────────────────────────────────────────────────────────


def parse_hub_ref(ref: str) -> tuple[str, str, str | None]:
    """Split ``<hub>:<slug>[@version]`` into its parts; hub defaults."""
    match = _REF_RE.match((ref or "").strip())
    if match is None:
        raise HubError(f"Invalid skill reference `{ref}`. Expected <hub>:<slug>[@version].")
    return (
        match.group("hub") or default_hub(),
        match.group("slug"),
        match.group("version"),
    )


# ── safe archive extraction (directory-preserving) ──────────────────────


def _extract_skill_zip(zip_path: Path, dest: Path) -> None:
    """Extract a package zip preserving subdirectories, defensively.

    The KB upload extractor (:func:`safe_extract_zip`) flattens paths, which
    would destroy a skill's ``references/`` layout — so this sibling keeps
    relative paths and instead rejects traversal segments outright. Bomb
    guards mirror the extractor's posture. Members are streamed through
    ``ZipFile.open``, so no permission bits or links materialise.
    """
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    total = 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise SkillImportError(f"Downloaded package is not a valid zip: {exc}") from exc
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > _ZIP_MAX_ENTRIES:
            raise SkillImportError("Package archive has too many entries.")
        for info in members:
            raw = info.filename.replace("\\", "/")
            rel = Path(raw)
            if rel.is_absolute() or ".." in rel.parts:
                raise SkillImportError(f"Illegal path in package archive: {raw}")
            if raw.startswith("__MACOSX/") or rel.name.startswith("."):
                continue
            if info.file_size > _ZIP_MAX_ENTRY_BYTES:
                raise SkillImportError(f"Package entry too large: {raw}")
            if info.compress_size > 0:
                if info.file_size / info.compress_size > _ZIP_MAX_RATIO:
                    raise SkillImportError(f"Suspicious compression ratio: {raw}")
            total += info.file_size
            if total > _ZIP_MAX_TOTAL_BYTES:
                raise SkillImportError("Package archive exceeds the size limit.")
            target = (dest_root / rel).resolve()
            if not target.is_relative_to(dest_root):  # defense in depth
                raise SkillImportError(f"Illegal path in package archive: {raw}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as sink:
                shutil.copyfileobj(source, sink, length=1 << 16)
            if target.stat().st_size > info.file_size:
                target.unlink(missing_ok=True)
                raise SkillImportError(f"Entry decompressed past declared size: {raw}")


def _locate_package_root(extracted: Path) -> Path:
    """Find the directory holding ``SKILL.md`` (top level or one wrapper deep).

    Hub zips routinely wrap the package in a single named folder; anything
    deeper or ambiguous is rejected rather than guessed at.
    """
    if (extracted / "SKILL.md").is_file():
        return extracted
    subdirs = [p for p in extracted.iterdir() if p.is_dir()]
    if len(subdirs) == 1 and (subdirs[0] / "SKILL.md").is_file():
        return subdirs[0]
    raise SkillImportError("Package does not contain a SKILL.md.")


# ── providers ─────────────────────────────────────────────────────────────


class ClawHubProvider:
    """ClawHub registry over its public read-only HTTP API.

    Speaking HTTP directly (instead of shelling out to the ``clawhub`` npm
    CLI) keeps the pipeline free of a Node toolchain dependency and lets the
    security verdict gate run inside our install path.
    """

    def __init__(
        self,
        name: str = "clawhub",
        *,
        base_url: str = _CLAWHUB_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True)

    @property
    def base_url(self) -> str:
        """The configured ``/api/v1`` base URL (used to derive the web origin)."""
        return self._base_url

    @property
    def web_origin(self) -> str:
        """The hub's website origin — ``base_url`` minus the ``/api/...`` suffix.

        Used to build "view on EduHub" links for the in-app skill browser.
        """
        marker = "/api/"
        idx = self._base_url.find(marker)
        return self._base_url[:idx] if idx != -1 else self._base_url

    def _get(self, path: str, **params: Any) -> httpx.Response:
        url = f"{self._base_url}{path}"
        try:
            response = self._client.get(
                url, params={k: v for k, v in params.items() if v is not None}
            )
        except httpx.HTTPError as exc:
            raise HubError(f"{self.name}: request failed: {exc}") from exc
        if response.status_code == 404:
            raise HubError(f"{self.name}: not found: {path}")
        if response.status_code >= 400:
            raise HubError(
                f"{self.name}: HTTP {response.status_code} for {path}: {response.text[:200]}"
            )
        return response

    def search(self, query: str, *, limit: int = 10) -> list[HubSkillRef]:
        response = self._get("/search", q=query, limit=limit)
        try:
            payload = response.json()
        except ValueError as exc:
            raise HubError(f"{self.name}: search returned invalid JSON") from exc
        rows = payload if isinstance(payload, list) else None
        if rows is None and isinstance(payload, dict):
            for key in ("results", "items", "skills"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
        if rows is None:
            raise HubError(f"{self.name}: unrecognised search response shape")
        refs: list[HubSkillRef] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = str(row.get("slug") or "").strip()
            if not slug:
                continue
            refs.append(
                HubSkillRef(
                    hub=self.name,
                    slug=slug,
                    display_name=str(row.get("displayName") or row.get("name") or slug),
                    summary=str(row.get("summary") or row.get("description") or ""),
                    version=str(row.get("version") or ""),
                )
            )
        return refs

    def verify(self, slug: str, *, version: str | None = None) -> HubVerdict:
        try:
            response = self._get(
                f"/skills/{slug}/verify", version=version, tag=None if version else "latest"
            )
            payload = response.json()
        except (HubError, ValueError) as exc:
            return HubVerdict(status="unknown", detail=str(exc))
        if not isinstance(payload, dict):
            return HubVerdict(status="unknown", detail="unrecognised verify response")
        decision = str(payload.get("decision") or "").strip().lower()
        if payload.get("ok") is True:
            return HubVerdict(status="ok", detail=decision)
        return HubVerdict(status="suspicious", detail=decision or "hub flagged this package")

    def fetch(self, slug: str, *, version: str | None = None) -> FetchedSkill:
        response = self._get(
            "/download", slug=slug, version=version, tag=None if version else "latest"
        )
        tmp = Path(tempfile.mkdtemp(prefix="deeptutor-skill-"))
        try:
            zip_path = tmp / "package.zip"
            zip_path.write_bytes(response.content)
            extracted = tmp / "extracted"
            _extract_skill_zip(zip_path, extracted)
            root = _locate_package_root(extracted)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        resolved_version = version or self._latest_version(slug)
        return FetchedSkill(
            ref=HubSkillRef(hub=self.name, slug=slug, version=resolved_version),
            root=root,
            cleanup_dir=tmp,
        )

    def _latest_version(self, slug: str) -> str:
        """Resolve the version actually served by an untagged download."""
        try:
            payload = self._get(f"/skills/{slug}").json()
        except (HubError, ValueError):
            return ""
        if not isinstance(payload, dict):
            return ""
        latest = payload.get("latestVersion") or payload.get("latest_version")
        if isinstance(latest, dict):
            latest = latest.get("version")
        if latest is None and isinstance(payload.get("skill"), dict):
            latest = payload["skill"].get("latestVersion")
        return str(latest or "").strip()

    @staticmethod
    def _listing_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
        """Normalise one hub catalog/detail row into a display-ready dict."""
        slug = str(row.get("slug") or "").strip()
        if not slug:
            return None
        stats = row.get("stats") if isinstance(row.get("stats"), dict) else {}
        owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
        return {
            "slug": slug,
            "name": str(row.get("displayName") or row.get("name") or slug),
            "summary": str(row.get("summary") or row.get("description") or ""),
            "version": str(row.get("version") or ""),
            "downloads": int(stats.get("downloads") or 0),
            "stars": int(stats.get("stars") or 0),
            "owner": str(owner.get("displayName") or row.get("ownerHandle") or ""),
            "owner_url": str(owner.get("htmlUrl") or ""),
            "updated_at": row.get("updatedAt"),
        }

    def catalog(
        self, *, query: str = "", limit: int = 50, sort: str = "createdAt"
    ) -> list[dict[str, Any]]:
        """List skills published on the hub, for the in-app skill browser.

        Uses ``/search`` when a query is given (server-side relevance) and the
        plain ``/skills`` explore feed otherwise. Rows carry display name,
        summary, version, download/star counts and owner — everything the
        DeepTutor-native browser renders without a second round-trip.
        """
        if query.strip():
            response = self._get("/search", q=query.strip(), limit=limit)
        else:
            response = self._get("/skills", limit=limit, sort=sort)
        try:
            payload = response.json()
        except ValueError as exc:
            raise HubError(f"{self.name}: catalog returned invalid JSON") from exc
        rows = payload if isinstance(payload, list) else None
        if rows is None and isinstance(payload, dict):
            for key in ("results", "skills", "items"):
                if isinstance(payload.get(key), list):
                    rows = payload[key]
                    break
        if rows is None:
            raise HubError(f"{self.name}: unrecognised catalog response shape")
        out: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                listing = self._listing_from_row(row)
                if listing is not None:
                    out.append(listing)
        return out

    def detail(self, slug: str) -> dict[str, Any]:
        """Full metadata + SKILL.md body for one hub skill (browser detail view)."""
        try:
            payload = self._get(f"/skills/{slug}").json()
        except ValueError as exc:
            raise HubError(f"{self.name}: skill detail returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HubError(f"{self.name}: unrecognised skill detail shape")
        skill = payload.get("skill") if isinstance(payload.get("skill"), dict) else payload
        listing = self._listing_from_row(skill) or {"slug": slug, "name": slug}
        # Owner sometimes lives at the envelope top level, not inside ``skill``.
        if not listing.get("owner") and isinstance(payload.get("owner"), dict):
            owner = payload["owner"]
            listing["owner"] = str(owner.get("displayName") or owner.get("handle") or "")
            listing["owner_url"] = str(owner.get("htmlUrl") or "")
        dist = payload.get("distTags") if isinstance(payload.get("distTags"), dict) else {}
        listing["version"] = str(dist.get("latest") or listing.get("version") or "")
        listing["content"] = str(skill.get("description") or "")
        # EduHub's ``tags`` field is a dist-tags map; the topical labels live in
        # ``keywords``. Fall back to a list-shaped ``tags`` for other hubs.
        keywords = skill.get("keywords")
        if not isinstance(keywords, list):
            keywords = skill.get("tags") if isinstance(skill.get("tags"), list) else []
        listing["tags"] = [str(t) for t in keywords if str(t).strip()]
        return listing

    def publish(
        self,
        *,
        slug: str,
        version: str,
        zip_bytes: bytes,
        token: str,
        fields: dict[str, str],
    ) -> dict[str, Any]:
        """Publish a version via ``POST /skills`` (multipart + bearer token).

        Read-only ClawHub mirrors will reject this; eduhub (same /api/v1 shape)
        accepts it. Surfaces the API's JSON ``error`` message on failure.
        """
        url = f"{self._base_url}/skills"
        try:
            response = self._client.post(
                url,
                data={"slug": slug, "version": version, **fields},
                files={"zip": ("package.zip", zip_bytes, "application/zip")},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise HubError(f"{self.name}: publish request failed: {exc}") from exc
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("error") or "")
            except ValueError:
                detail = response.text[:200]
            raise HubError(f"{self.name}: publish failed (HTTP {response.status_code}): {detail}")
        try:
            return response.json()
        except ValueError:
            return {}

    def list_my_skills(self, token: str) -> list[dict[str, Any]]:
        """List the authenticated user's skills via ``GET /skills?owner=me``.

        Each row carries the slug, current ``version`` (latest), the full
        ``versions`` list (for rollback) and the current classification (for
        pre-filling an upgrade's tagging) — see ``buildMySkills`` on the hub.
        """
        url = f"{self._base_url}/skills"
        try:
            response = self._client.get(
                url, params={"owner": "me"}, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.HTTPError as exc:
            raise HubError(f"{self.name}: request failed: {exc}") from exc
        if response.status_code in (401, 403):
            raise HubError(
                f"{self.name}: not authenticated — run `skill login` or pass a valid token."
            )
        if response.status_code >= 400:
            raise HubError(f"{self.name}: HTTP {response.status_code}: {response.text[:200]}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise HubError(f"{self.name}: invalid JSON listing skills") from exc
        rows = payload.get("skills") if isinstance(payload, dict) else None
        return [row for row in (rows or []) if isinstance(row, dict)]

    def set_dist_tag(
        self,
        slug: str,
        *,
        version: str,
        token: str,
        tag: str = "latest",
    ) -> dict[str, Any]:
        """Move a dist-tag (default ``latest``) to an existing version (rollback)."""
        url = f"{self._base_url}/skills/{slug}/dist-tags"
        try:
            response = self._client.post(
                url,
                json={"tag": tag, "version": version},
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            raise HubError(f"{self.name}: request failed: {exc}") from exc
        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("error") or "")
            except ValueError:
                detail = response.text[:200]
            raise HubError(
                f"{self.name}: set dist-tag failed (HTTP {response.status_code}): {detail}"
            )
        try:
            return response.json()
        except ValueError:
            return {}


class CommandProvider:
    """Generic fetch-by-command provider for registries without a public API.

    The configured ``fetch_cmd`` template receives ``{slug}``, ``{version}``
    (empty string when unpinned) and ``{dest}`` — it must leave the package
    (a ``SKILL.md`` tree, or a zip we can extract) under ``{dest}``. The
    command runs without a shell; pipes and substitutions won't work, which
    is the point.
    """

    def __init__(self, name: str, *, fetch_cmd: str) -> None:
        self.name = name
        self._fetch_cmd = fetch_cmd

    def search(self, query: str, *, limit: int = 10) -> list[HubSkillRef]:
        raise HubError(f"{self.name}: this hub does not support search.")

    def verify(self, slug: str, *, version: str | None = None) -> HubVerdict:
        return HubVerdict(status="unknown", detail="command hubs have no verdict API")

    def fetch(self, slug: str, *, version: str | None = None) -> FetchedSkill:
        tmp = Path(tempfile.mkdtemp(prefix="deeptutor-skill-"))
        dest = tmp / "fetched"
        dest.mkdir()
        argv = [
            part.format(slug=slug, version=version or "", dest=str(dest))
            for part in shlex.split(self._fetch_cmd)
        ]
        try:
            completed = subprocess.run(
                argv,
                cwd=str(tmp),
                capture_output=True,
                text=True,
                timeout=_FETCH_CMD_TIMEOUT,
                check=False,
            )
            if completed.returncode != 0:
                raise HubError(
                    f"{self.name}: fetch command failed "
                    f"({completed.returncode}): {(completed.stderr or completed.stdout)[:300]}"
                )
            root = self._resolve_fetched_root(dest, tmp)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        return FetchedSkill(
            ref=HubSkillRef(hub=self.name, slug=slug, version=version or ""),
            root=root,
            cleanup_dir=tmp,
        )

    @staticmethod
    def _resolve_fetched_root(dest: Path, tmp: Path) -> Path:
        """Accept either an extracted tree or a single zip in ``dest``."""
        zips = sorted(dest.glob("*.zip"))
        if len(zips) == 1 and not (dest / "SKILL.md").is_file():
            extracted = tmp / "extracted"
            _extract_skill_zip(zips[0], extracted)
            return _locate_package_root(extracted)
        return _locate_package_root(dest)


# ── provider registry ─────────────────────────────────────────────────────


def _load_hub_config() -> dict[str, Any]:
    """Read the whole skill_hubs settings doc (``{}`` if absent/unreadable)."""
    try:
        path = get_path_service().get_settings_file(_HUBS_SETTINGS_FILE)
    except Exception:
        return {}
    if not isinstance(path, Path) or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("skill_hubs settings file is unreadable; ignoring it")
        return {}
    return data if isinstance(data, dict) else {}


def _load_hub_settings() -> dict[str, dict[str, Any]]:
    hubs = _load_hub_config().get("hubs")
    if not isinstance(hubs, dict):
        return {}
    return {str(name): value for name, value in hubs.items() if isinstance(value, dict)}


def default_hub() -> str:
    """The hub used when a ref carries no ``<hub>:`` prefix.

    Settings-driven (``"default": "eduhub"`` in skill_hubs.json) so a
    deployment can point the bare ``install <slug>`` at its own hub without
    forking the code; falls back to the built-in ``eduhub``.
    """
    chosen = str(_load_hub_config().get("default") or "").strip().lower()
    return chosen or DEFAULT_HUB


def get_hub_provider(name: str) -> SkillHubProvider:
    """Resolve a hub name to a provider.

    Built-in hubs (``eduhub``, ``clawhub``) work with no configuration; entries
    in ``settings/skill_hubs.json`` are layered on top and override built-ins.
    """
    hub = (name or DEFAULT_HUB).strip().lower()
    configured = _load_hub_settings().get(hub) or _BUILTIN_HUBS.get(hub)
    if configured is not None:
        kind = str(configured.get("type") or "").strip().lower()
        if kind == "clawhub":
            return ClawHubProvider(
                hub, base_url=str(configured.get("base_url") or _CLAWHUB_BASE_URL)
            )
        if kind == "command":
            fetch_cmd = str(configured.get("fetch_cmd") or "").strip()
            if not fetch_cmd:
                raise HubError(f"Hub `{hub}` is missing fetch_cmd in skill_hubs settings.")
            return CommandProvider(hub, fetch_cmd=fetch_cmd)
        raise HubError(f"Hub `{hub}` has unknown type `{kind}` in skill_hubs settings.")
    raise HubError(f"Unknown hub `{hub}`. Configure it in settings/skill_hubs.json.")


# ── orchestration ─────────────────────────────────────────────────────────


def install_from_hub(
    ref: str,
    *,
    service: SkillService,
    rename_to: str | None = None,
    force: bool = False,
    allow_unverified: bool = False,
    provider: SkillHubProvider | None = None,
) -> HubInstallOutcome:
    """One-shot pipeline: verify → fetch → install → record provenance.

    ``suspicious`` verdicts abort unless ``allow_unverified`` is set;
    ``unknown`` verdicts install but are stamped into provenance so the
    caller can warn. ``provider`` is injectable for tests.
    """
    hub, slug, version = parse_hub_ref(ref)
    resolved = provider or get_hub_provider(hub)

    verdict = resolved.verify(slug, version=version)
    if verdict.status == "suspicious" and not allow_unverified:
        raise SkillImportError(
            f"{hub} flags `{slug}` as suspicious"
            + (f" ({verdict.detail})" if verdict.detail else "")
            + ". Pass --allow-unverified to install anyway."
        )

    fetched = resolved.fetch(slug, version=version)
    try:
        result = service.install_tree(
            fetched.root,
            rename_to=rename_to,
            fallback_description=fetched.ref.summary or None,
            force=force,
            # Stamp the source hub as a tag so imported skills are visibly
            # grouped (e.g. an ``eduhub`` tag) in the user's Skills list.
            extra_tags=[hub],
            origin={
                "hub": hub,
                "slug": slug,
                "version": fetched.ref.version or version or "",
                "verdict": verdict.status,
                "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            },
        )
    finally:
        fetched.cleanup()
    return HubInstallOutcome(result=result, ref=fetched.ref, verdict=verdict)


# ── publish ─────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class PublishOutcome:
    hub: str
    slug: str
    version: str
    response: dict[str, Any]


@dataclass(slots=True)
class SkillPreflight:
    """Result of the local pre-publish format check.

    ``errors`` would make the hub reject the upload (the CLI should stop);
    ``warnings`` are advisory. ``file_count``/``total_bytes`` are reported so
    the caller can show what is about to be zipped.
    """

    errors: list[str]
    warnings: list[str]
    file_count: int
    total_bytes: int

    @property
    def ok(self) -> bool:
        return not self.errors


# Native executables / installers have no place in a document-shaped skill;
# mirrors the hub scanner's DANGEROUS_BINARY_EXT so the CLI flags them locally
# before upload rather than after a server-side ``review`` verdict.
_DANGEROUS_BINARY_EXT = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bin",
        ".msi",
        ".dmg",
        ".pkg",
        ".app",
        ".bat",
        ".cmd",
        ".scr",
        ".com",
        ".jar",
        ".apk",
    }
)


def preflight_skill_dir(directory: str | Path) -> SkillPreflight:
    """Check a skill directory against the hub's structural constraints.

    Local mirror of ``normalizePackage`` / scanner bounds (SKILL.md present,
    ≤600 files, ≤4 MB/file, ≤40 MB total, no native executables) plus advisory
    checks on the SKILL.md frontmatter. Catches the common rejections before a
    round-trip; the authoritative scan still runs server-side on publish.
    """
    root = Path(directory).expanduser().resolve()
    errors: list[str] = []
    warnings: list[str] = []
    file_count = 0
    total_bytes = 0

    if not root.is_dir():
        return SkillPreflight([f"Not a directory: {root}"], [], 0, 0)

    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        errors.append("Missing SKILL.md at the package root.")
    else:
        fm = _read_frontmatter(skill_md)
        if not str(fm.get("name") or "").strip():
            warnings.append(
                "SKILL.md frontmatter has no `name:` (display name falls back to slug)."
            )
        if not str(fm.get("description") or "").strip():
            warnings.append(
                "SKILL.md frontmatter has no `description:` — agents rely on it to decide when to use the skill."
            )

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") or part == "__MACOSX" for part in rel.parts):
            continue  # dotfiles / __MACOSX are dropped at zip time
        file_count += 1
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        total_bytes += size
        if size > _ZIP_MAX_ENTRY_BYTES:
            errors.append(f"File exceeds 4 MB: {rel.as_posix()} ({size // 1_000_000} MB).")
        if rel.suffix.lower() in _DANGEROUS_BINARY_EXT:
            errors.append(f"Native executable/installer not allowed: {rel.as_posix()}.")

    if file_count == 0:
        errors.append("No publishable files found (only dotfiles/__MACOSX present).")
    if file_count > _ZIP_MAX_ENTRIES:
        errors.append(f"Too many files: {file_count} (limit {_ZIP_MAX_ENTRIES}).")
    if total_bytes > _ZIP_MAX_TOTAL_BYTES:
        errors.append(f"Package too large: {total_bytes // 1_000_000} MB (limit 40 MB).")

    return SkillPreflight(errors, warnings, file_count, total_bytes)


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# frontmatter 字段直通到发布表单（track/name/description 另行处理）。
_PUBLISH_PASSTHROUGH = (
    "language",
    "domains",
    "stages",
    "forms",
    "audiences",
    "tags",
    "changelog",
    "license",
    "longDescription",
)


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", (text or "").lower()).strip("-")
    return cleaned or "skill"


def _read_frontmatter(skill_md: Path) -> dict[str, Any]:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return {}
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    try:
        import yaml

        data = yaml.safe_load(match.group(1))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_skill_metadata(directory: str | Path) -> dict[str, Any]:
    """Public reader for a skill dir's SKILL.md frontmatter (``{}`` if absent).

    Lets the interactive CLI pre-fill prompts from frontmatter without
    re-implementing the parser.
    """
    return _read_frontmatter(Path(directory).expanduser().resolve() / "SKILL.md")


def resolve_publish_identity(
    directory: str | Path,
    *,
    slug: str | None = None,
    version: str | None = None,
) -> tuple[str, str]:
    """Resolve the (slug, version) a publish would use; version may be ``""``.

    Same precedence as :func:`publish_to_hub` (explicit arg → frontmatter →
    slug from name/dir), exposed so the CLI can show an accurate confirmation
    summary before uploading.
    """
    root = Path(directory).expanduser().resolve()
    fm = _read_frontmatter(root / "SKILL.md")
    eff_slug = slug or str(fm.get("slug") or "") or _slugify(str(fm.get("name") or root.name))
    eff_version = (version or str(fm.get("version") or "")).strip()
    return eff_slug, eff_version


def _zip_dir(root: Path) -> bytes:
    """Zip a skill directory (skip dotfiles and __MACOSX), paths relative to root."""
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root)
            if any(part.startswith(".") or part == "__MACOSX" for part in rel.parts):
                continue
            archive.write(path, rel.as_posix())
    return buf.getvalue()


def publish_to_hub(
    directory: str | Path,
    *,
    token: str,
    version: str | None = None,
    slug: str | None = None,
    track: str | None = None,
    hub: str | None = None,
    overrides: dict[str, str] | None = None,
    provider: SkillHubProvider | None = None,
) -> PublishOutcome:
    """Zip a local skill dir and publish a version to a publish-capable hub.

    Metadata defaults come from the SKILL.md frontmatter; explicit args win.
    ``slug``/``version``/``track`` are what eduhub requires (track is
    mandatory there). ``overrides`` carries the classification an interactive
    caller resolved (track / language / domains / stages / forms / audiences /
    tags / changelog); each present key replaces the frontmatter-derived value
    verbatim — including an empty string, which clears a multi-select facet.
    Auth is a bearer ``token`` minted on the hub web UI.
    """
    root = Path(directory).expanduser().resolve()
    skill_md = root / "SKILL.md"
    if not skill_md.is_file():
        raise SkillImportError(f"No SKILL.md found in {root}")

    fm = _read_frontmatter(skill_md)
    hub = hub or default_hub()
    resolved = provider or get_hub_provider(hub)
    publish = getattr(resolved, "publish", None)
    if not callable(publish):
        raise HubError(f"Hub `{hub}` does not support publishing.")

    eff_slug, eff_version = resolve_publish_identity(root, slug=slug, version=version)
    if not eff_version:
        raise SkillImportError(
            "A version is required (pass --version or set `version:` in SKILL.md)."
        )

    fields: dict[str, str] = {}
    if fm.get("name"):
        fields["name"] = str(fm["name"])
    if fm.get("description"):
        fields["description"] = str(fm["description"])
    eff_track = track or str(fm.get("track") or "")
    if eff_track:
        fields["track"] = eff_track
    for key in _PUBLISH_PASSTHROUGH:
        value = fm.get(key)
        if isinstance(value, list):
            fields[key] = ",".join(str(x) for x in value)
        elif value is not None:
            fields[key] = str(value)

    # An interactive caller's resolved classification is authoritative: present
    # keys replace the frontmatter-derived value as-is (empty string clears).
    if overrides:
        fields.update(overrides)

    response = publish(
        slug=eff_slug,
        version=eff_version,
        zip_bytes=_zip_dir(root),
        token=token,
        fields=fields,
    )
    return PublishOutcome(hub=hub, slug=eff_slug, version=eff_version, response=response)


__all__ = [
    "DEFAULT_HUB",
    "ClawHubProvider",
    "CommandProvider",
    "FetchedSkill",
    "HubError",
    "HubInstallOutcome",
    "HubSkillRef",
    "HubVerdict",
    "PublishOutcome",
    "SkillHubProvider",
    "SkillPreflight",
    "default_hub",
    "get_hub_provider",
    "install_from_hub",
    "parse_hub_ref",
    "preflight_skill_dir",
    "publish_to_hub",
    "read_skill_metadata",
    "resolve_publish_identity",
]
