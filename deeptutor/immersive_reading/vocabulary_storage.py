"""Vocabulary persistence primitives."""

from __future__ import annotations

from pathlib import Path

from deeptutor.immersive_reading.models import VocabEntry
from deeptutor.immersive_reading.storage import read_json as _read_json
from deeptutor.immersive_reading.storage import write_json as _write_json


class VocabularyStorageMixin:
    def _vocabulary_path(self) -> Path:
        return self._root() / "vocabulary.json"

    def _bilingual_source_context(
        self, pairing_id: str, chapter_id: str, group_index: int
    ) -> tuple[str, str]:
        # Keep the service module's patchable path-service access point.
        from deeptutor.immersive_reading import service as service_module

        section_path = (
            service_module.get_path_service().get_immersive_reading_pairing_root(pairing_id)
            / "sections"
            / f"{chapter_id}.json"
        )
        section = _read_json(section_path, {})
        groups = section.get("groups", []) if isinstance(section, dict) else []
        index = max(0, min(group_index, len(groups) - 1)) if groups else -1
        if index < 0:
            return "", ""
        group = groups[index]
        return " ".join(group.get("en", []))[:4000], " ".join(group.get("zh", []))[:4000]

    def _read_vocabulary_entries(self) -> list[VocabEntry]:
        data = _read_json(self._vocabulary_path(), [])
        entries: list[VocabEntry] = []
        for item in data:
            try:
                entries.append(VocabEntry.model_validate(item))
            except Exception:
                continue
        return entries

    def _write_vocabulary_entries(self, entries: list[VocabEntry]) -> None:
        _write_json(self._vocabulary_path(), [entry.model_dump(mode="json") for entry in entries])

