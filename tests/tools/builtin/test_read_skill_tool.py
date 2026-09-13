from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.services.skill.service import (
    SkillFileNotFoundError,
    SkillService,
)
from deeptutor.tools.builtin import ReadSkillTool


def _write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: demo\ndescription: Demo\n---\n")


def _use_service(monkeypatch: pytest.MonkeyPatch, service: SkillService) -> None:
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", lambda: service)
    monkeypatch.setattr(
        "deeptutor.multi_user.context.get_current_user",
        lambda: SimpleNamespace(id="u_test", is_admin=False),
    )
    monkeypatch.setattr(
        "deeptutor.multi_user.skill_access.assigned_skill_ids",
        lambda _user_id: set(),
    )


@pytest.mark.asyncio
async def test_missing_file_names_the_existing_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "ncea-tutor")
    (root / "ncea-tutor" / "references").mkdir()
    (root / "ncea-tutor" / "references" / "outline.md").write_text("outline")
    _use_service(monkeypatch, SkillService(root=root, builtin_root=None))

    result = await ReadSkillTool().execute(name="ncea-tutor", file="references/qbank.md")

    assert result.success is False
    assert "file not found: 'references/qbank.md'" in result.content
    assert "skill 'ncea-tutor'" in result.content
    # Naming the files it does hold is what ends the retry loop — the model
    # can see the path it should have asked for.
    assert "SKILL.md, references/outline.md" in result.content


@pytest.mark.asyncio
async def test_missing_skill_lists_available_skills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "another-skill")
    _use_service(monkeypatch, SkillService(root=root, builtin_root=None))

    result = await ReadSkillTool().execute(name="ghost-skill")

    assert result.success is False
    assert "skill not found: 'ghost-skill'" in result.content
    assert "Available skills: another-skill" in result.content


def test_missing_file_has_a_distinct_service_exception(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    _write_skill(root, "demo")
    service = SkillService(root=root, builtin_root=None)

    with pytest.raises(SkillFileNotFoundError):
        service.read_skill_file("demo", "references/missing.md")


@pytest.mark.asyncio
async def test_a_large_skill_does_not_flood_the_turn_with_its_own_file_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The listing identifies the right path; it is not an inventory.

    A skill carrying a big references/ tree would otherwise spend the turn's
    context listing itself on every wrong path.
    """
    from deeptutor.tools.builtin import _SKILL_FILE_LIST_LIMIT

    root = tmp_path / "skills"
    _write_skill(root, "big-skill")
    refs = root / "big-skill" / "references"
    refs.mkdir()
    extra = 25
    # +1 for the SKILL.md every skill has: the cut counts total files, not
    # just the ones this loop writes.
    for index in range(_SKILL_FILE_LIST_LIMIT + extra):
        (refs / f"note-{index:03d}.md").write_text("x")
    _use_service(monkeypatch, SkillService(root=root, builtin_root=None))

    result = await ReadSkillTool().execute(name="big-skill", file="references/absent.md")

    assert result.success is False
    assert result.content.count(".md") <= _SKILL_FILE_LIST_LIMIT + 1
    assert f"({extra + 1} more)" in result.content
