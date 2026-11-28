from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import install_skills  # noqa: E402


def _skill(root: Path, name: str, body: str) -> None:
    (root / name).mkdir(parents=True)
    (root / name / "SKILL.md").write_text(body, encoding="utf-8")


def test_install_copies_skill_packages_and_replaces_old_copies(tmp_path: Path) -> None:
    source, target = tmp_path / "src", tmp_path / "dst"
    _skill(source, "coco-bars", "new")
    (source / "notes").mkdir()  # no SKILL.md -> ignored
    _skill(target, "coco-bars", "old")
    (target / "coco-bars" / "stale.txt").write_text("x", encoding="utf-8")

    assert install_skills.install(source, target) == ["coco-bars"]
    assert (target / "coco-bars" / "SKILL.md").read_text(encoding="utf-8") == "new"
    assert not (target / "coco-bars" / "stale.txt").exists()
    assert not (target / "notes").exists()


def test_repo_skills_have_frontmatter() -> None:
    for skill in install_skills.SOURCE.glob("*/SKILL.md"):
        text = skill.read_text(encoding="utf-8")
        assert text.startswith("---\n"), skill
        assert f"name: {skill.parent.name}\n" in text, skill
