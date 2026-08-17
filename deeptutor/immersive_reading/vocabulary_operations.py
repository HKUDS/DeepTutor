"""Vocabulary mutation operations."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any
import uuid

from deeptutor.immersive_reading.models import DictionaryResult, VocabEntry
from deeptutor.immersive_reading.vocabulary import ensure_cards
from deeptutor.services.llm import get_llm_config

from .vocabulary_storage import VocabularyStorageMixin

logger = logging.getLogger(__name__)


class VocabularyOperationsMixin(VocabularyStorageMixin):
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
        self._write_vocabulary_entries(entries)

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
