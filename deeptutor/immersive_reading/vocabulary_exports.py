"""Vocabulary export helpers."""

from __future__ import annotations

from pathlib import Path

from deeptutor.immersive_reading.vocabulary import vocabulary_apkg, vocabulary_csv

from .vocabulary_persistence import VocabularyPersistenceMixin


class VocabularyExportMixin(VocabularyPersistenceMixin):
    def export_vocabulary_csv(self) -> Path:
        entries = self.list_vocabulary()
        if not entries:
            raise ValueError("No vocabulary entries to export")
        target = self._root() / "exports" / "vocabulary.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(vocabulary_csv(entries))
        return target

    def export_vocabulary_apkg(self) -> Path:
        entries = self.list_vocabulary()
        if not entries:
            raise ValueError("No vocabulary entries to export")
        target = self._root() / "exports" / "vocabulary.apkg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(vocabulary_apkg(entries, "DeepTutor Vocabulary"))
        return target

