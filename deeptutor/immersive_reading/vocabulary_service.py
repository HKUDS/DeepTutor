"""Persistent vocabulary workflow for immersive reading."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import time
from typing import Any
import uuid

from deeptutor.immersive_reading.models import DictionaryResult, VocabEntry
from deeptutor.immersive_reading.storage import read_json as _read_json
from deeptutor.immersive_reading.storage import write_json as _write_json
from deeptutor.immersive_reading.vocabulary import (
    chapter_difficulty,
    ensure_cards,
    grade_review,
    review_queue,
    vocabulary_apkg,
    vocabulary_csv,
)
from deeptutor.services.llm import get_llm_config

logger = logging.getLogger(__name__)


class VocabularyMixin:
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

    async def add_word(
        self,
        word: str,
        context: str = "",
        document_id: str = "",
        document_title: str = "",
        section_title: str = "",
        pairing_id: str = "",
        chapter_id: str = "",
        chapter_index: int = 0,
        group_index: int = 0,
    ) -> VocabEntry:
        """Look up a word and persist it without losing selections on lookup failure."""
        word = word.strip()
        if not word:
            raise ValueError("Provide a word to save")
        if len(word) > 200:
            raise ValueError("Word is too long")
        try:
            result = await self.lookup_word(word, context)
        except Exception as exc:
            logger.warning("Dictionary lookup failed for %r: %s", word, exc)
            result = DictionaryResult(word=word)
        now = time.time()
        entries = self.list_vocabulary()
        existing = next(
            (item for item in entries if item.word.casefold() == (result.word or word).casefold()),
            None,
        )
        is_new = existing is None
        if existing is None:
            existing = VocabEntry(id=uuid.uuid4().hex[:12], word=result.word or word, created_at=now)
            entries.append(existing)

        bilingual_en, bilingual_zh = (
            self._bilingual_source_context(pairing_id, chapter_id, group_index)
            if pairing_id and chapter_id
            else ("", "")
        )
        context_en = bilingual_en or context.strip()[:4000]
        updates: dict[str, Any] = {
            "updated_at": now,
            "occurrence_count": 1 if is_new else existing.occurrence_count + 1,
            "context_en": context_en,
        }
        if bilingual_zh:
            updates["context_zh"] = bilingual_zh
        if result.phonetic:
            updates["phonetic"] = result.phonetic
        if result.definitions:
            updates["definitions"] = result.definitions
        if result.chinese:
            updates["chinese"] = result.chinese
        if result.context_note:
            updates["context_note"] = result.context_note
        if document_id or pairing_id:
            updates.update(
                {
                    "document_id": document_id,
                    "document_title": document_title,
                    "section_title": section_title,
                    "pairing_id": pairing_id,
                    "chapter_id": chapter_id,
                    "chapter_index": max(0, chapter_index),
                    "group_index": max(0, group_index),
                }
            )
        entry = existing.model_copy(update=updates)
        entries[entries.index(existing)] = entry
        entries = [ensure_cards(item, entries) for item in entries]
        entry = next(item for item in entries if item.id == entry.id)
        _write_json(self._vocabulary_path(), [item.model_dump(mode="json") for item in entries])

        if document_id and "mn4" in document_id.lower():
            cfg = get_llm_config()
            model_name = str(getattr(cfg, "model", ""))
            content_hash = hashlib.sha256(context_en.encode("utf-8")).hexdigest()
            self.create_mn4_writeback(
                source_type="word",
                source_object_id=entry.id,
                content_hash=content_hash,
                idempotency_key=f"word_{entry.id}_{now}",
                model=model_name,
            )
        return entry

    def list_vocabulary(
        self, document_id: str | None = None, pairing_id: str | None = None
    ) -> list[VocabEntry]:
        data = _read_json(self._vocabulary_path(), [])
        entries: list[VocabEntry] = []
        for item in data:
            try:
                entries.append(VocabEntry.model_validate(item))
            except Exception:
                continue
        # Legacy files predate generated cards; reads remain non-mutating.
        if any(not entry.cards for entry in entries):
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
        _write_json(self._vocabulary_path(), [entry.model_dump(mode="json") for entry in entries])
        return updated

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

    def analyze_vocabulary_difficulty(self, content: str) -> dict[str, Any]:
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

    def delete_word(self, entry_id: str) -> None:
        entries = self.list_vocabulary()
        remaining = [entry for entry in entries if entry.id != entry_id]
        if len(remaining) == len(entries):
            raise ValueError("Vocabulary entry not found")
        _write_json(self._vocabulary_path(), [entry.model_dump(mode="json") for entry in remaining])
