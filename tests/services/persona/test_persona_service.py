"""PersonaService: CRUD, single-persona context rendering, legacy migration."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.persona.service import (
    InvalidPersonaNameError,
    PersonaExistsError,
    PersonaNotFoundError,
    PersonaService,
)


@pytest.fixture
def service(tmp_path: Path) -> PersonaService:
    return PersonaService(root=tmp_path / "personas")


def test_create_and_get(service: PersonaService) -> None:
    service.create("teacher", "Patient tutor", "Explain step by step.")
    detail = service.get_detail("teacher")
    assert detail.name == "teacher"
    assert detail.description == "Patient tutor"
    assert "Explain step by step." in detail.content
    assert detail.source == "user"


def test_create_duplicate_rejected(service: PersonaService) -> None:
    service.create("peer", "A peer", "body")
    with pytest.raises(PersonaExistsError):
        service.create("peer", "again", "body")


def test_invalid_name_rejected(service: PersonaService) -> None:
    with pytest.raises(InvalidPersonaNameError):
        service.create("Has Spaces", "d", "b")


def test_load_for_context_wraps_body(service: PersonaService) -> None:
    service.create("peer", "Study partner", "Think out loud with the user.")
    rendered = service.load_for_context("peer")
    assert "## Active Persona" in rendered
    assert "### Persona: peer" in rendered
    assert "Think out loud with the user." in rendered


def test_load_for_context_missing_is_empty(service: PersonaService) -> None:
    assert service.load_for_context("ghost") == ""
    assert service.load_for_context("") == ""


def test_update_description_and_rename(service: PersonaService) -> None:
    service.create("coach", "old", "body")
    service.update("coach", description="new desc")
    assert service.get_detail("coach").description == "new desc"
    service.update("coach", rename_to="mentor")
    assert service.get_detail("mentor").description == "new desc"
    with pytest.raises(PersonaNotFoundError):
        service.get_detail("coach")


def test_delete(service: PersonaService) -> None:
    service.create("temp", "d", "b")
    service.delete("temp")
    with pytest.raises(PersonaNotFoundError):
        service.get_detail("temp")


def test_list_personas(service: PersonaService) -> None:
    service.create("a", "first", "b")
    service.create("b", "second", "b")
    names = {p.name for p in service.list_personas()}
    assert names == {"a", "b"}


def test_migrate_legacy_skills(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    peer_dir = skills_root / "peer"
    peer_dir.mkdir(parents=True)
    (peer_dir / "SKILL.md").write_text(
        "---\nname: peer\ndescription: Study partner\ntriggers: [discuss]\n---\n\nBe a peer.\n"
    )
    # A non-persona skill must be left untouched.
    other = skills_root / "data-tool"
    other.mkdir()
    (other / "SKILL.md").write_text("---\nname: data-tool\ndescription: x\n---\n\nbody\n")

    service = PersonaService(root=tmp_path / "personas")
    migrated = service.migrate_legacy_skills(skills_root)

    assert migrated == ["peer"]
    detail = service.get_detail("peer")
    assert detail.description == "Study partner"
    assert "Be a peer." in detail.content
    # legacy frontmatter keys (triggers) are dropped
    assert "triggers" not in detail.content
    # source skill dir removed, unrelated skill preserved
    assert not peer_dir.exists()
    assert (other / "SKILL.md").exists()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    skills_root = tmp_path / "skills"
    (skills_root / "teacher").mkdir(parents=True)
    (skills_root / "teacher" / "SKILL.md").write_text(
        "---\nname: teacher\ndescription: T\n---\n\nbody\n"
    )
    service = PersonaService(root=tmp_path / "personas")
    assert service.migrate_legacy_skills(skills_root) == ["teacher"]
    # second run finds nothing new
    assert service.migrate_legacy_skills(skills_root) == []
