"""Skill hub import: install_tree policy, ref parsing, providers, orchestration."""

from __future__ import annotations

import io
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

import httpx
import pytest

from deeptutor.services.skill.hub import (
    ClawHubProvider,
    CommandProvider,
    FetchedSkill,
    HubError,
    HubSkillRef,
    HubVerdict,
    _extract_skill_zip,
    get_hub_provider,
    install_from_hub,
    parse_hub_ref,
)
from deeptutor.services.skill.service import (
    SkillExistsError,
    SkillImportError,
    SkillService,
)

# ── fixtures ──────────────────────────────────────────────────────────────


def _make_package(
    root: Path,
    *,
    frontmatter: str,
    body: str = "Playbook body.",
    extra: dict[str, str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}\n")
    for rel, content in (extra or {}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    return root


@pytest.fixture
def svc(tmp_path: Path) -> SkillService:
    return SkillService(root=tmp_path / "skills", builtin_root=None)


# ── install_tree: frontmatter adaptation ────────────────────────────────


def test_install_tree_adapts_frontmatter_and_keeps_references(
    tmp_path: Path, svc: SkillService
) -> None:
    pkg = _make_package(
        tmp_path / "pkg",
        frontmatter=(
            "name: Demo Skill\n"
            "description: Does demo things\n"
            "always: true\n"
            "bins: [git]\n"
            "env: [DEMO_TOKEN]\n"
            "tags: [tool]\n"
            "version: 1.2.0\n"
        ),
        extra={"references/notes.md": "ref body"},
    )
    result = svc.install_tree(pkg)
    assert result.info.name == "demo-skill"
    assert result.skipped == []

    detail = svc.get_detail("demo-skill")
    meta, _ = svc._parse_frontmatter(detail.content)
    assert meta["name"] == "demo-skill"
    # imported skills must never eager-inject themselves
    assert "always" not in meta
    # flat Agent-Skills keys fold into our requires schema
    assert meta["requires"]["bins"] == ["git"]
    assert meta["requires"]["env"] == ["DEMO_TOKEN"]
    assert "bins" not in meta and "env" not in meta
    # unknown extras ride along
    assert meta["version"] == "1.2.0"
    assert svc.read_skill_file("demo-skill", "references/notes.md") == "ref body"


def test_install_tree_merges_flat_keys_into_existing_requires(
    tmp_path: Path, svc: SkillService
) -> None:
    pkg = _make_package(
        tmp_path / "pkg",
        frontmatter=(
            "name: mixed\ndescription: d\nbins: [jq]\nrequires:\n  bins: [git]\n  sandbox: shell\n"
        ),
    )
    svc.install_tree(pkg)
    meta, _ = svc._parse_frontmatter(svc.get_detail("mixed").content)
    assert meta["requires"]["bins"] == ["git", "jq"]
    assert meta["requires"]["sandbox"] == "shell"


def test_install_tree_rename_and_description_fallback(tmp_path: Path, svc: SkillService) -> None:
    pkg = _make_package(tmp_path / "pkg", frontmatter="name: upstream-name")
    with pytest.raises(SkillImportError):
        svc.install_tree(pkg)  # no description anywhere
    result = svc.install_tree(pkg, rename_to="local-name", fallback_description="from registry")
    assert result.info.name == "local-name"
    assert result.info.description == "from registry"


def test_install_tree_conflict_and_force(tmp_path: Path, svc: SkillService) -> None:
    pkg_v1 = _make_package(
        tmp_path / "v1",
        frontmatter="name: demo\ndescription: v1",
        extra={"references/old.md": "old"},
    )
    pkg_v2 = _make_package(tmp_path / "v2", frontmatter="name: demo\ndescription: v2")
    svc.install_tree(pkg_v1)
    with pytest.raises(SkillExistsError):
        svc.install_tree(pkg_v2)
    svc.install_tree(pkg_v2, force=True)
    assert svc.get_detail("demo").description == "v2"
    # replaced wholesale: v1's support file must not survive
    assert "references/old.md" not in svc.list_skill_files("demo")


def test_install_tree_skips_disallowed_files_and_rejects_symlinks(
    tmp_path: Path, svc: SkillService
) -> None:
    pkg = _make_package(
        tmp_path / "pkg",
        frontmatter="name: demo\ndescription: d",
        extra={"references/ok.md": "fine"},
    )
    (pkg / "logo.png").write_bytes(b"\x89PNG")
    result = svc.install_tree(pkg)
    assert ("logo.png", "file type not allowed") in result.skipped
    assert svc.read_skill_file("demo", "references/ok.md") == "fine"

    pkg2 = _make_package(tmp_path / "pkg2", frontmatter="name: demo2\ndescription: d")
    (pkg2 / "link.md").symlink_to(pkg2 / "SKILL.md")
    with pytest.raises(SkillImportError):
        svc.install_tree(pkg2)
    assert not (svc.root / "demo2").exists()  # staged tree never lands


def test_install_tree_requires_skill_md(tmp_path: Path, svc: SkillService) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(SkillImportError):
        svc.install_tree(empty)


# ── hub provenance ────────────────────────────────────────────────────────


def test_origin_recorded_and_dropped_on_delete(tmp_path: Path, svc: SkillService) -> None:
    pkg = _make_package(tmp_path / "pkg", frontmatter="name: demo\ndescription: d")
    origin = {"hub": "clawhub", "slug": "demo", "version": "1.0.0", "verdict": "ok"}
    svc.install_tree(pkg, origin=origin)
    assert svc.hub_origin("demo") == origin
    assert svc.hub_origin("absent") is None
    svc.delete("demo")
    assert svc.hub_origin("demo") is None


# ── ref parsing ───────────────────────────────────────────────────────────


def test_parse_hub_ref_forms() -> None:
    assert parse_hub_ref("clawhub:my-skill") == ("clawhub", "my-skill", None)
    # No prefix resolves to the built-in default hub (EduHub).
    assert parse_hub_ref("my-skill") == ("eduhub", "my-skill", None)
    assert parse_hub_ref("eduhub:my-skill") == ("eduhub", "my-skill", None)
    assert parse_hub_ref("other:pkg@1.2.0") == ("other", "pkg", "1.2.0")
    with pytest.raises(HubError):
        parse_hub_ref("Bad Name!")
    with pytest.raises(HubError):
        parse_hub_ref("")


# ── safe zip extraction ──────────────────────────────────────────────────


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buf.getvalue()


def test_extract_skill_zip_preserves_dirs_and_blocks_traversal(tmp_path: Path) -> None:
    good = tmp_path / "good.zip"
    good.write_bytes(_zip_bytes({"pkg/SKILL.md": "x", "pkg/references/a.md": "a", ".hidden": "h"}))
    out = tmp_path / "out"
    _extract_skill_zip(good, out)
    assert (out / "pkg" / "references" / "a.md").read_text() == "a"
    assert not (out / ".hidden").exists()

    evil = tmp_path / "evil.zip"
    evil.write_bytes(_zip_bytes({"../escape.md": "x"}))
    with pytest.raises(SkillImportError):
        _extract_skill_zip(evil, tmp_path / "out2")


# ── ClawHubProvider over MockTransport ───────────────────────────────────


def _clawhub_client(zip_payload: bytes, *, ok: bool = True) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "slug": "demo",
                            "displayName": "Demo",
                            "summary": "demo summary",
                            "version": "1.2.0",
                        }
                    ]
                },
            )
        if path == "/api/v1/skills/demo/verify":
            body = {"ok": ok, "decision": "clean" if ok else "malware"}
            return httpx.Response(200, json=body)
        if path == "/api/v1/download":
            return httpx.Response(200, content=zip_payload)
        if path == "/api/v1/skills/demo":
            return httpx.Response(200, json={"latestVersion": {"version": "1.2.0"}})
        return httpx.Response(404, text="nope")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_clawhub_search_verify_fetch(tmp_path: Path) -> None:
    payload = _zip_bytes({"demo/SKILL.md": "---\nname: demo\ndescription: d\n---\n\nbody\n"})
    provider = ClawHubProvider(client=_clawhub_client(payload))

    refs = provider.search("demo")
    assert refs[0].slug == "demo" and refs[0].version == "1.2.0"

    assert provider.verify("demo").status == "ok"

    fetched = provider.fetch("demo")
    try:
        assert (fetched.root / "SKILL.md").is_file()  # wrapper dir unwrapped
        assert fetched.ref.version == "1.2.0"  # resolved from skill detail
    finally:
        fetched.cleanup()
    assert not fetched.cleanup_dir.exists()


def test_clawhub_verify_states() -> None:
    provider = ClawHubProvider(client=_clawhub_client(b"", ok=False))
    assert provider.verify("demo").status == "suspicious"

    # any transport/protocol failure degrades to unknown, never crashes
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    offline = ClawHubProvider(client=httpx.Client(transport=httpx.MockTransport(boom)))
    assert offline.verify("demo").status == "unknown"


# ── ClawHubProvider: in-app browser (catalog / detail / web origin) ────────


def _browse_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/skills":
            return httpx.Response(
                200,
                json={
                    "skills": [
                        {
                            "slug": "socratic-tutor",
                            "displayName": "Socratic Tutor",
                            "summary": "Teach by asking.",
                            "version": "1.0.0",
                            "stats": {"downloads": 8, "stars": 2},
                            "ownerHandle": "deeptutor",
                            "owner": {
                                "displayName": "DeepTutor",
                                "htmlUrl": "https://deeptutor.info",
                            },
                        },
                        {"slug": "", "displayName": "blank"},  # dropped: no slug
                    ]
                },
            )
        if path == "/api/v1/search":
            return httpx.Response(
                200,
                json={"results": [{"slug": "socratic-tutor", "displayName": "Socratic Tutor"}]},
            )
        if path == "/api/v1/skills/socratic-tutor":
            return httpx.Response(
                200,
                json={
                    "skill": {
                        "slug": "socratic-tutor",
                        "displayName": "Socratic Tutor",
                        "summary": "Teach.",
                        "description": "---\nname: socratic-tutor\n---\n\n# Body\n",
                        # EduHub stores dist-tags under `tags`; topical labels
                        # live in `keywords`.
                        "tags": {"latest": "1.0.0"},
                        "keywords": ["tutor", "socratic"],
                        "stats": {"downloads": 8, "stars": 2},
                    },
                    "owner": {"displayName": "DeepTutor", "htmlUrl": "https://deeptutor.info"},
                    "distTags": {"latest": "1.0.0"},
                },
            )
        return httpx.Response(404, text="nope")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_clawhub_catalog_normalises_rows() -> None:
    rows = ClawHubProvider(client=_browse_client()).catalog()
    assert len(rows) == 1  # the blank-slug row is dropped
    row = rows[0]
    assert (row["slug"], row["name"]) == ("socratic-tutor", "Socratic Tutor")
    assert (row["downloads"], row["stars"]) == (8, 2)
    assert row["owner"] == "DeepTutor"
    assert row["owner_url"] == "https://deeptutor.info"


def test_clawhub_catalog_uses_search_when_queried() -> None:
    rows = ClawHubProvider(client=_browse_client()).catalog(query="socratic")
    assert rows and rows[0]["slug"] == "socratic-tutor"


def test_clawhub_detail_includes_body_version_and_tags() -> None:
    detail = ClawHubProvider(client=_browse_client()).detail("socratic-tutor")
    assert detail["version"] == "1.0.0"  # resolved from distTags
    # topical labels come from `keywords`, not EduHub's dist-tags `tags` map
    assert detail["tags"] == ["tutor", "socratic"]
    assert "# Body" in detail["content"]
    assert detail["owner"] == "DeepTutor"  # lifted from the envelope top level


def test_clawhub_web_origin_strips_api_suffix() -> None:
    provider = ClawHubProvider("eduhub", base_url="https://eduhub.deeptutor.info/api/v1")
    assert provider.web_origin == "https://eduhub.deeptutor.info"


# ── orchestration ────────────────────────────────────────────────────────


class _FakeProvider:
    """Serves a fixed on-disk package; lets tests choose the verdict."""

    name = "fakehub"

    def __init__(self, pkg: Path, verdict: HubVerdict) -> None:
        self._pkg = pkg
        self._verdict = verdict
        self.last_cleanup: Path | None = None

    def search(self, query: str, *, limit: int = 10) -> list[HubSkillRef]:
        return []

    def verify(self, slug: str, *, version: str | None = None) -> HubVerdict:
        return self._verdict

    def fetch(self, slug: str, *, version: str | None = None) -> FetchedSkill:
        tmp = Path(tempfile.mkdtemp(prefix="fakehub-"))
        root = tmp / "pkg"
        shutil.copytree(self._pkg, root)
        self.last_cleanup = tmp
        return FetchedSkill(
            ref=HubSkillRef(hub=self.name, slug=slug, summary="registry summary", version="0.9.0"),
            root=root,
            cleanup_dir=tmp,
        )


def test_install_from_hub_happy_path(tmp_path: Path, svc: SkillService) -> None:
    pkg = _make_package(tmp_path / "pkg", frontmatter="name: demo\ndescription: d")
    provider = _FakeProvider(pkg, HubVerdict(status="ok"))
    outcome = install_from_hub("fakehub:demo", service=svc, provider=provider)
    assert outcome.result.info.name == "demo"
    origin = svc.hub_origin("demo")
    assert origin is not None
    assert (origin["hub"], origin["version"], origin["verdict"]) == (
        "fakehub",
        "0.9.0",
        "ok",
    )
    assert origin["installed_at"]
    assert provider.last_cleanup is not None and not provider.last_cleanup.exists()


def test_install_from_hub_blocks_suspicious_unless_overridden(
    tmp_path: Path, svc: SkillService
) -> None:
    pkg = _make_package(tmp_path / "pkg", frontmatter="name: demo\ndescription: d")
    provider = _FakeProvider(pkg, HubVerdict(status="suspicious", detail="flagged"))
    with pytest.raises(SkillImportError, match="suspicious"):
        install_from_hub("fakehub:demo", service=svc, provider=provider)
    assert svc.hub_origin("demo") is None

    outcome = install_from_hub(
        "fakehub:demo", service=svc, provider=provider, allow_unverified=True
    )
    assert outcome.verdict.status == "suspicious"
    origin = svc.hub_origin("demo")
    assert origin is not None and origin["verdict"] == "suspicious"


def test_install_from_hub_uses_registry_summary_as_fallback(
    tmp_path: Path, svc: SkillService
) -> None:
    pkg = _make_package(tmp_path / "pkg", frontmatter="name: demo")  # no description
    provider = _FakeProvider(pkg, HubVerdict(status="ok"))
    outcome = install_from_hub("fakehub:demo", service=svc, provider=provider)
    assert outcome.result.info.description == "registry summary"


def test_install_from_hub_stamps_source_hub_as_tag(tmp_path: Path, svc: SkillService) -> None:
    pkg = _make_package(tmp_path / "pkg", frontmatter="name: demo\ndescription: d\ntags: [tutor]\n")
    provider = _FakeProvider(pkg, HubVerdict(status="ok"))
    outcome = install_from_hub("fakehub:demo", service=svc, provider=provider)
    # the source hub rides along as a tag, alongside the package's own tags
    assert "fakehub" in outcome.result.info.tags
    assert "tutor" in outcome.result.info.tags
    meta, _ = svc._parse_frontmatter(svc.get_detail("demo").content)
    assert "fakehub" in meta["tags"]


# ── CommandProvider ──────────────────────────────────────────────────────


@pytest.mark.skipif(os.name == "nt", reason="POSIX cp in fetch command")
def test_command_provider_fetch(tmp_path: Path, svc: SkillService) -> None:
    pkg = _make_package(tmp_path / "srcpkg", frontmatter="name: demo\ndescription: d")
    provider = CommandProvider("myhub", fetch_cmd=f"cp -r {pkg} {{dest}}/pkg")
    fetched = provider.fetch("demo")
    try:
        assert (fetched.root / "SKILL.md").is_file()
    finally:
        fetched.cleanup()
    assert provider.verify("demo").status == "unknown"
    with pytest.raises(HubError):
        provider.search("anything")


def test_command_provider_failure_cleans_up() -> None:
    provider = CommandProvider("myhub", fetch_cmd="false")
    with pytest.raises(HubError):
        provider.fetch("demo")


# ── provider registry ────────────────────────────────────────────────────


def test_get_hub_provider_default_and_unknown() -> None:
    assert isinstance(get_hub_provider("clawhub"), ClawHubProvider)
    # EduHub is a built-in hub: resolvable with no settings file.
    eduhub = get_hub_provider("eduhub")
    assert isinstance(eduhub, ClawHubProvider)
    assert eduhub.name == "eduhub"
    # Empty name falls back to the default hub, which is also a provider.
    assert isinstance(get_hub_provider(""), ClawHubProvider)
    with pytest.raises(HubError):
        get_hub_provider("no-such-hub")
