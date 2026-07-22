"""Tests for the interactive publish/update plumbing: preflight, taxonomy,
the overrides merge in publish_to_hub, and the two-level domain picker."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.skill import taxonomy
from deeptutor.services.skill.hub import (
    PublishOutcome,
    preflight_skill_dir,
    publish_to_hub,
    resolve_publish_identity,
)


def _write_skill(tmp_path: Path, *, frontmatter: str = "", body: str = "hello") -> Path:
    root = tmp_path / "skill"
    root.mkdir()
    fm = f"---\n{frontmatter}\n---\n" if frontmatter else ""
    (root / "SKILL.md").write_text(f"{fm}\n# Skill\n\n{body}\n", encoding="utf-8")
    return root


# ── taxonomy ────────────────────────────────────────────────────────────


def test_taxonomy_tracks_match_hub() -> None:
    assert [o.value for o in taxonomy.TRACK_OPTIONS] == [
        "academics",
        "companions",
        "skills-interests",
        "educators",
    ]
    assert taxonomy.is_valid_track("academics")
    assert not taxonomy.is_valid_track("nope")


def test_taxonomy_domain_tree_dotted_children() -> None:
    assert "arts.instruments" in taxonomy.DOMAIN_VALUES
    assert "arts" in taxonomy.DOMAIN_VALUES
    assert taxonomy.domain_label("arts.instruments") == "器乐"
    assert taxonomy.domain_label("arts") == "艺术与创意"
    # every child slug carries its parent prefix
    for node in taxonomy.DOMAIN_TREE:
        for child in node.children:
            assert child.value.startswith(f"{node.value}.")


# ── preflight ─────────────────────────────────────────────────────────────


def test_preflight_clean(tmp_path: Path) -> None:
    root = _write_skill(tmp_path, frontmatter="name: x\ndescription: does y")
    pre = preflight_skill_dir(root)
    assert pre.ok
    assert pre.errors == []
    assert pre.file_count == 1


def test_preflight_missing_skill_md(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    pre = preflight_skill_dir(tmp_path / "empty")
    assert not pre.ok
    assert any("SKILL.md" in e for e in pre.errors)


def test_preflight_rejects_native_executable(tmp_path: Path) -> None:
    root = _write_skill(tmp_path)
    (root / "tool.exe").write_bytes(b"MZ\x00\x00")
    pre = preflight_skill_dir(root)
    assert not pre.ok
    assert any("tool.exe" in e for e in pre.errors)


def test_preflight_warns_missing_description(tmp_path: Path) -> None:
    root = _write_skill(tmp_path, frontmatter="name: x")
    pre = preflight_skill_dir(root)
    assert pre.ok  # warning, not error
    assert any("description" in w for w in pre.warnings)


# ── identity resolution ────────────────────────────────────────────────────


def test_resolve_identity_prefers_explicit(tmp_path: Path) -> None:
    root = _write_skill(tmp_path, frontmatter="name: My Skill\nversion: 1.2.0")
    assert resolve_publish_identity(root) == ("my-skill", "1.2.0")
    assert resolve_publish_identity(root, slug="other", version="2.0.0") == ("other", "2.0.0")


# ── publish overrides merge ─────────────────────────────────────────────────


class _CapturingProvider:
    """Fake publish-capable provider that records the fields it was handed."""

    name = "fake"

    def __init__(self) -> None:
        self.captured: dict[str, str] = {}

    def publish(self, *, slug, version, zip_bytes, token, fields):  # noqa: ANN001
        self.captured = dict(fields)
        assert token == "tok"
        assert zip_bytes  # non-empty zip
        return {"slug": slug, "version": version}


def test_publish_passes_frontmatter_fields(tmp_path: Path) -> None:
    root = _write_skill(
        tmp_path,
        frontmatter=(
            "name: Guitar\n"
            "description: coach chords\n"
            "track: skills-interests\n"
            "language: zh\n"
            "domains: [arts.instruments]\n"
            "version: 1.0.0\n"
        ),
    )
    provider = _CapturingProvider()
    outcome = publish_to_hub(root, token="tok", provider=provider)
    assert isinstance(outcome, PublishOutcome)
    assert outcome.slug == "guitar" and outcome.version == "1.0.0"
    assert provider.captured["track"] == "skills-interests"
    assert provider.captured["domains"] == "arts.instruments"
    assert provider.captured["language"] == "zh"


def test_publish_overrides_win_over_frontmatter(tmp_path: Path) -> None:
    root = _write_skill(
        tmp_path,
        frontmatter="name: Guitar\ntrack: academics\ndomains: [math]\nversion: 1.0.0\n",
    )
    provider = _CapturingProvider()
    publish_to_hub(
        root,
        token="tok",
        provider=provider,
        overrides={
            "track": "skills-interests",
            "domains": "arts.instruments",
            "stages": "",  # explicit empty clears
        },
    )
    assert provider.captured["track"] == "skills-interests"
    assert provider.captured["domains"] == "arts.instruments"
    assert provider.captured["stages"] == ""


def test_publish_requires_version(tmp_path: Path) -> None:
    from deeptutor.services.skill.service import SkillImportError

    root = _write_skill(tmp_path, frontmatter="name: NoVersion")
    with pytest.raises(SkillImportError):
        publish_to_hub(root, token="tok", provider=_CapturingProvider())


# ── two-level domain picker resolution ─────────────────────────────────────


def test_select_domains_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    from deeptutor_cli import skill_prompts

    # Script the multi-selects: roots = [arts, math]; arts children = [instruments];
    # math children = [] (so math contributes itself).
    calls: list[list[str]] = [["arts", "math"], ["arts.instruments"], []]

    def fake_select_many(options, title, **kwargs):  # noqa: ANN001
        return calls.pop(0)

    monkeypatch.setattr(skill_prompts, "select_many", fake_select_many)
    result = skill_prompts.select_domains()
    assert result == ["arts.instruments", "math"]


def test_parse_indices() -> None:
    from deeptutor_cli.skill_prompts import _parse_indices

    assert _parse_indices("1, 3 4", 5) == [0, 2, 3]
    assert _parse_indices("", 5) == []
    assert _parse_indices("9", 5) is None
    assert _parse_indices("x", 5) is None
