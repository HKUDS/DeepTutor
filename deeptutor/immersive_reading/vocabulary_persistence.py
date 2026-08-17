"""Vocabulary listing, review, grading, and deletion."""

from __future__ import annotations

from deeptutor.immersive_reading.models import VocabEntry
from deeptutor.immersive_reading.vocabulary import grade_review, review_queue

from .vocabulary_storage import VocabularyStorageMixin


class VocabularyPersistenceMixin(VocabularyStorageMixin):
    def list_vocabulary(
        self, document_id: str | None = None, pairing_id: str | None = None
    ) -> list[VocabEntry]:
        entries = self._read_vocabulary_entries()
        # Legacy files predate generated cards; reads remain non-mutating.
        if any(not entry.cards for entry in entries):
            from deeptutor.immersive_reading.vocabulary import ensure_cards

            entries = [ensure_cards(entry, entries) for entry in entries]
        if document_id:
            entries = [entry for entry in entries if entry.document_id == document_id]
        if pairing_id:
            entries = [entry for entry in entries if entry.pairing_id == pairing_id]
        entries.sort(key=lambda entry: entry.created_at, reverse=True)
        return entries

    def review_vocabulary(self, limit: int = 10) -> list[VocabEntry]:
        return review_queue(self.list_vocabulary(), limit=max(1, min(50, limit)))

    def grade_vocabulary_review(self, entry_id: str, *, correct: bool) -> VocabEntry:
        entries, updated = grade_review(self.list_vocabulary(), entry_id, correct=correct)
        self._write_vocabulary_entries(entries)
        return updated

    def delete_word(self, entry_id: str) -> None:
        entries = self.list_vocabulary()
        remaining = [entry for entry in entries if entry.id != entry_id]
        if len(remaining) == len(entries):
            raise ValueError("Vocabulary entry not found")
        self._write_vocabulary_entries(remaining)

