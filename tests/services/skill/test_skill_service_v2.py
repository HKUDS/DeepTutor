"""SkillService v2: builtin/user layers, manifest, requires gating, read_skill, always."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.skill.service import (
    InvalidSkillPathError,
    SkillNotFoundError,
    SkillReadOnlyError,
    SkillService,
    render_skills_manifest,
)


def _write_skill(root: Path, name: str, frontmatter: str, body: str = "body") -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}\n")


@pytest.fixture
def layered(tmp_path: Path) -> SkillService:
    user_root = tmp_path / "user_skills"
    builtin_root = tmp_path / "builtin_skills"
    _write_skill(builtin_root, "skill-creator", "name: skill-creator\ndescription: builtin one")
    _write_skill(user_root, "my-skill", "name: my-skill\ndescription: user one")
    return SkillService(root=user_root, builtin_root=builtin_root)


def test_list_merges_layers(layered: SkillService) -> None:
    by_name = {s.name: s for s in layered.list_skills()}
    assert by_name["my-skill"].source == "user"
    assert by_name["skill-creator"].source == "builtin"


def test_user_shadows_builtin(tmp_path: Path) -> None:
    user_root = tmp_path / "u"
    builtin_root = tmp_path / "b"
    _write_skill(builtin_root, "dup", "name: dup\ndescription: builtin")
    _write_skill(user_root, "dup", "name: dup\ndescription: user override")
    svc = SkillService(root=user_root, builtin_root=builtin_root)
    detail = svc.get_detail("dup")
    assert detail.source == "user"
    assert detail.description == "user override"
    # only one entry in the list
    assert [s.name for s in svc.list_skills()].count("dup") == 1


def test_manifest_excludes_always_and_marks_unavailable(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _write_skill(root, "normal", "name: normal\ndescription: A normal skill")
    _write_skill(root, "housekeeping", "name: housekeeping\ndescription: rules\nalways: true")
    _write_skill(
        root,
        "needs-git",
        "name: needs-git\ndescription: git stuff\nrequires:\n  bins: [definitely-not-a-real-bin]",
    )
    svc = SkillService(root=root, builtin_root=None)
    manifest = render_skills_manifest(svc.summary_entries())
    assert "**normal**" in manifest
    # always-skills are injected eagerly, not listed in the manifest
    assert "housekeeping" not in manifest
    # unmet requirement is surfaced
    assert "needs-git" in manifest
    assert "unavailable" in manifest


def test_load_always_for_context(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _write_skill(root, "rules", "name: rules\ndescription: d\nalways: true", body="Always do X.")
    _write_skill(root, "ondemand", "name: ondemand\ndescription: d", body="Only sometimes.")
    svc = SkillService(root=root, builtin_root=None)
    always = svc.load_always_for_context()
    assert "Always do X." in always
    assert "Only sometimes." not in always


def test_read_skill_file_default_and_reference(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _write_skill(root, "doc", "name: doc\ndescription: d", body="main body")
    refs = root / "doc" / "references"
    refs.mkdir()
    (refs / "api.md").write_text("reference content")
    svc = SkillService(root=root, builtin_root=None)
    assert "main body" in svc.read_skill_file("doc")
    assert "reference content" in svc.read_skill_file("doc", "references/api.md")


def test_read_skill_file_rejects_traversal(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _write_skill(root, "doc", "name: doc\ndescription: d")
    (tmp_path / "secret.txt").write_text("top secret")
    svc = SkillService(root=root, builtin_root=None)
    with pytest.raises(InvalidSkillPathError):
        svc.read_skill_file("doc", "../../secret.txt")
    with pytest.raises(InvalidSkillPathError):
        svc.read_skill_file("doc", "/etc/passwd")


def test_read_skill_unknown(tmp_path: Path) -> None:
    svc = SkillService(root=tmp_path / "s", builtin_root=None)
    with pytest.raises(SkillNotFoundError):
        svc.read_skill_file("ghost")


def test_builtin_is_read_only(tmp_path: Path) -> None:
    user_root = tmp_path / "u"
    builtin_root = tmp_path / "b"
    _write_skill(builtin_root, "locked", "name: locked\ndescription: d")
    svc = SkillService(root=user_root, builtin_root=builtin_root)
    with pytest.raises(SkillReadOnlyError):
        svc.update("locked", description="hijack")
    with pytest.raises(SkillReadOnlyError):
        svc.delete("locked")


def test_sandbox_requirement_gating(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "s"
    _write_skill(
        root,
        "runner-skill",
        "name: runner-skill\ndescription: needs sandbox\nrequires:\n  sandbox: shell",
    )
    svc = SkillService(root=root, builtin_root=None)

    import deeptutor.services.skill.service as svc_mod

    monkeypatch.setattr(svc_mod, "_sandbox_available", lambda kind: False)
    entry = next(e for e in svc.summary_entries() if e.name == "runner-skill")
    assert not entry.available
    assert any("SANDBOX" in m for m in entry.missing)

    monkeypatch.setattr(svc_mod, "_sandbox_available", lambda kind: True)
    entry = next(e for e in svc.summary_entries() if e.name == "runner-skill")
    assert entry.available
