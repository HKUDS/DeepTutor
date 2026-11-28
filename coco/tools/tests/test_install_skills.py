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


def test_install_handles_persona_packages(tmp_path: Path) -> None:
    source, target = tmp_path / "src", tmp_path / "dst"
    (source / "coco-tutor").mkdir(parents=True)
    (source / "coco-tutor" / "PERSONA.md").write_text("p", encoding="utf-8")
    _skill(source, "not-a-persona", "s")  # SKILL.md only -> ignored for personas

    assert install_skills.install(source, target, "PERSONA.md") == ["coco-tutor"]
    assert not (target / "not-a-persona").exists()


def test_repo_personas_have_valid_names_and_frontmatter() -> None:
    import re

    personas = list(install_skills.PERSONA_SOURCE.glob("*/PERSONA.md"))
    assert personas
    for persona in personas:
        name = persona.parent.name
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name), name
        text = persona.read_text(encoding="utf-8")
        assert text.startswith("---\n") and f"name: {name}\n" in text, persona
