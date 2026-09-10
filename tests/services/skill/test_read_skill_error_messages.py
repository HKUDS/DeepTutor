"""Tests that read_skill distinguishes missing skill from missing file."""

from pathlib import Path

import pytest

from deeptutor.services.skill.service import SkillService


class TestReadSkillErrorMessages:
    def _make_skill(self, root: Path) -> SkillService:
        skill_dir = root / "skills" / "ncea-tutor"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# NCEA Tutor\n")
        return SkillService(root=root / "skills")

    def test_missing_file_returns_file_error(self, tmp_path: Path) -> None:
        service = self._make_skill(tmp_path)
        with pytest.raises(Exception) as exc_info:
            service.read_skill_file("ncea-tutor", "references/qbank.md")
        assert "ncea-tutor/references/qbank.md" in str(exc_info.value)
        assert "not found" in str(exc_info.value).lower()

    def test_missing_skill_still_raises_skill_not_found(self, tmp_path: Path) -> None:
        service = self._make_skill(tmp_path)
        from deeptutor.services.skill.service import SkillNotFoundError

        with pytest.raises(SkillNotFoundError):
            service.read_skill_file("nonexistent", "SKILL.md")

    def test_existing_file_reads_correctly(self, tmp_path: Path) -> None:
        service = self._make_skill(tmp_path)
        refs = tmp_path / "skills" / "ncea-tutor" / "references"
        refs.mkdir()
        (refs / "qbank.md").write_text("# QBank\n")
        content = service.read_skill_file("ncea-tutor", "references/qbank.md")
        assert "# QBank" in content
