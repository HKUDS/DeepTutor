"""A failed package replacement must preserve the installed skill."""

from pathlib import Path

import pytest

from deeptutor.services.skill.service import SkillService


def test_failed_replacement_preserves_package_and_origin(tmp_path: Path, monkeypatch) -> None:
    """Exercise the public installer with a filesystem publication failure."""
    service = SkillService(root=tmp_path / "skills", builtin_root=None)
    old = tmp_path / "old"
    old.mkdir()
    (old / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Old version\n---\nOriginal playbook\n",
        encoding="utf-8",
    )
    (old / "references").mkdir()
    (old / "references" / "guide.md").write_text("Original reference", encoding="utf-8")
    origin = {"hub": "eduhub", "version": "1.0.0"}
    service.install_tree(old, origin=origin)
    target = service.root / "demo"
    original = {p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    new = tmp_path / "new"
    new.mkdir()
    (new / "SKILL.md").write_text(
        "---\nname: demo\ndescription: New version\n---\nReplacement playbook\n",
        encoding="utf-8",
    )
    rename = Path.rename

    def fail_publication(path: Path, destination: Path) -> Path:
        if path.name.startswith(".install-") and Path(destination) == target:
            raise PermissionError("publication denied")
        return rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_publication)
    with pytest.raises(PermissionError, match="publication denied"):
        service.install_tree(new, force=True, origin={"hub": "eduhub", "version": "2.0.0"})

    assert target.is_dir()
    assert {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    } == original
    assert service.hub_origin("demo") == origin
    assert service.get_detail("demo").description == "Old version"
    assert service.read_skill_file("demo", "references/guide.md") == "Original reference"
