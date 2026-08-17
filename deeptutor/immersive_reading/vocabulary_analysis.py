"""Vocabulary difficulty analysis."""

from __future__ import annotations

from deeptutor.immersive_reading.vocabulary import chapter_difficulty

from .vocabulary_exports import VocabularyExportMixin


class VocabularyAnalysisMixin(VocabularyExportMixin):
    def analyze_vocabulary_difficulty(self, content: str) -> dict:
        from deeptutor.immersive_reading.ecdict import ECDictionary

        try:
            dictionary = ECDictionary(self._ecdict_path())
            result = chapter_difficulty(
                content,
                dictionary,
                saved_words=[entry.word for entry in self.list_vocabulary()],
            )
        finally:
            try:
                dictionary.close()
            except UnboundLocalError:
                pass
        return result.model_dump(mode="json")

