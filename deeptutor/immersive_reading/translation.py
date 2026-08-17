"""Translation cache and streaming jobs for immersive reading."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
import time
from typing import Any

from deeptutor.services.llm import clean_thinking_tags, get_llm_config
from deeptutor.services.llm.exceptions import LLMConfigError
from deeptutor.services.translation.glossary import (
    build_hymt_translation_prompt,
    build_translation_guardrail,
    is_hymt_model,
)
from deeptutor.services.translation.protection import (
    TranslationProtectionError,
    protect_translation_text,
    restore_translation_text,
)

IMMERSIVE_TRANSLATION_PROMPT_VERSION = "immersive-translate-v1"
_TRANSLATION_JOB_EVENT_QUEUE_SIZE = 64
_TRANSLATION_JOB_TTL_SECONDS = 60 * 60 * 24
_TRANSLATION_CACHE_LIMIT = 500

logger = logging.getLogger(__name__)


def normalize_translation_target_language(target_language: str | None) -> str:
    raw = (target_language or "").strip()
    if not raw:
        return "Chinese"

    normalized = raw.casefold().replace("_", "-")
    if normalized in {"zh", "zh-cn", "zh-hans", "zh-hant", "zh-cmn"}:
        return "Chinese"
    if normalized in {"en", "en-us", "en-gb", "en-au", "en-ca", "en-us"}:
        return "English"
    return raw


class TranslationMixin:
    @staticmethod
    def _translation_cache_key_parts(
        text: str,
        target_language: str,
        *,
        glossary: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        target_language = normalize_translation_target_language(target_language)
        cfg = get_llm_config()
        provider_name = (
            str(getattr(cfg, "provider_name", "") or getattr(cfg, "binding", "") or "")
            .strip()
            .lower()
        )
        model = str(cfg.model or "").strip()
        glossary_entries = [
            {
                "source": str(item.get("term") or item.get("source", "")).strip(),
                "translation": str(item.get("translation", "")).strip(),
                "protected": bool(item.get("protected", False)),
            }
            for item in glossary or []
        ]
        glossary_entries.sort(
            key=lambda item: (item["source"], item["translation"], item["protected"])
        )
        glossary_payload = json.dumps(glossary_entries, ensure_ascii=False)
        return [
            text.casefold(),
            target_language.strip().casefold(),
            provider_name,
            model,
            IMMERSIVE_TRANSLATION_PROMPT_VERSION,
            glossary_payload,
        ]

    def _translation_cache_key(
        self,
        text: str,
        target_language: str,
        glossary: list[dict[str, Any]] | None = None,
    ) -> str:
        material = "\n".join(
            self._translation_cache_key_parts(text, target_language, glossary=glossary)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _translation_cache_db_path(self) -> Path:
        return self._root() / "translation_cache.db"

    def _ensure_translation_cache_db(self) -> None:
        if self._translation_cache_db_initialized:
            return
        path = self._translation_cache_db_path()
        try:
            import sqlite3

            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS translation_cache (
                        cache_key TEXT PRIMARY KEY,
                        source_hash TEXT NOT NULL,
                        normalized_source TEXT NOT NULL,
                        target_language TEXT NOT NULL,
                        provider_name TEXT NOT NULL,
                        model_name TEXT NOT NULL,
                        prompt_version TEXT NOT NULL,
                        glossary_version TEXT NOT NULL,
                        translation TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        hit_count INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_translation_cache_target ON translation_cache(target_language)"
                )
            self._translation_cache_db_initialized = True
        except Exception as exc:
            logger.debug("Translation cache DB init failed: %s", exc)
            self._translation_cache_db_initialized = False

    def _translation_cache_hit(self, cache_key: str) -> tuple[str, int] | None:
        if not cache_key:
            return None
        try:
            import sqlite3

            self._ensure_translation_cache_db()
            with sqlite3.connect(self._translation_cache_db_path()) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    "SELECT translation, hit_count FROM translation_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
            if row is None:
                return None
            translation = str(row["translation"] or "")
            if not translation:
                return None
            connection = sqlite3.connect(self._translation_cache_db_path())
            with connection:
                connection.execute(
                    "UPDATE translation_cache SET hit_count = hit_count + 1, updated_at = ? WHERE cache_key = ?",
                    (time.time(), cache_key),
                )
            return (translation, int(row["hit_count"] or 0) + 1)
        except Exception as exc:
            logger.debug("Translation cache read failed for %s: %s", cache_key, exc)
            return None

    def _translation_cache_store(
        self,
        cache_key: str,
        source: str,
        target_language: str,
        translation: str,
        *,
        glossary: list[dict[str, Any]] | None = None,
    ) -> None:
        if not cache_key:
            return
        try:
            import sqlite3

            self._ensure_translation_cache_db()
            cfg = get_llm_config()
            provider_name = (
                str(getattr(cfg, "provider_name", "") or getattr(cfg, "binding", "") or "")
                .strip()
                .lower()
            )
            model_name = str(cfg.model or "")
            glossary_entries = [
                {
                    "source": str(item.get("term") or item.get("source", "")).strip(),
                    "translation": str(item.get("translation", "")).strip(),
                    "protected": bool(item.get("protected", False)),
                }
                for item in glossary or []
            ]
            glossary_entries.sort(
                key=lambda item: (item["source"], item["translation"], item["protected"])
            )
            glossary_payload = json.dumps(glossary_entries, ensure_ascii=False)
            source_text = source.strip()
            now = time.time()
            with sqlite3.connect(self._translation_cache_db_path()) as connection:
                connection.execute(
                    """
                    INSERT INTO translation_cache (
                        cache_key,
                        source_hash,
                        normalized_source,
                        target_language,
                        provider_name,
                        model_name,
                        prompt_version,
                        glossary_version,
                        translation,
                        created_at,
                        updated_at,
                        hit_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        source_hash = excluded.source_hash,
                        normalized_source = excluded.normalized_source,
                        target_language = excluded.target_language,
                        provider_name = excluded.provider_name,
                        model_name = excluded.model_name,
                        prompt_version = excluded.prompt_version,
                        glossary_version = excluded.glossary_version,
                        translation = excluded.translation,
                        updated_at = excluded.updated_at,
                        hit_count = translation_cache.hit_count + 1
                    """,
                    (
                        cache_key,
                        hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
                        source_text.casefold(),
                        target_language.strip().casefold(),
                        provider_name,
                        model_name,
                        IMMERSIVE_TRANSLATION_PROMPT_VERSION,
                        glossary_payload,
                        translation,
                        now,
                        now,
                    ),
                )
        except Exception as exc:
            logger.debug("Translation cache write failed for %s: %s", cache_key, exc)

    async def _cleanup_stale_translation_jobs(self) -> None:
        now = time.time()
        async with self._translation_jobs_lock:
            expired = [
                job_id
                for job_id, job in self._translation_jobs.items()
                if job.get("status") in {"completed", "failed", "cancelled"}
                and now - float(job.get("updated_at") or now) > _TRANSLATION_JOB_TTL_SECONDS
            ]
            for job_id in expired:
                self._translation_jobs.pop(job_id, None)

    async def _emit_translation_job_event(self, job_id: str, event: dict[str, Any]) -> None:
        job = self._translation_jobs.get(job_id)
        if not job:
            return
        event["job_id"] = job_id
        event["time"] = time.time()
        event["sequence"] = int(job.get("sequence", 0)) + 1
        job["sequence"] = event["sequence"]
        listeners: set[asyncio.Queue[dict[str, Any]]] = job.setdefault("listeners", set())
        for listener in list(listeners):
            try:
                listener.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("Translation job event queue full for %s", job_id)

    async def get_translation_job_status(self, job_id: str) -> dict[str, Any]:
        await self._cleanup_stale_translation_jobs()
        job = self._translation_jobs.get(job_id)
        if job is None:
            raise ValueError("Translation job not found")
        return {
            "job_id": job_id,
            "status": job.get("status", "queued"),
            "created_at": float(job.get("created_at") or 0),
            "updated_at": float(job.get("updated_at") or job.get("created_at") or 0),
            "result": job.get("result"),
            "error": job.get("error", ""),
            "cache_key": job.get("cache_key"),
            "target_language": job.get("target_language"),
        }

    def _subscribe_translation_job(self, job_id: str) -> asyncio.Queue[dict[str, Any]]:
        job = self._translation_jobs.get(job_id)
        if job is None:
            raise ValueError("Translation job not found")
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=_TRANSLATION_JOB_EVENT_QUEUE_SIZE
        )
        job.setdefault("listeners", set()).add(queue)
        return queue

    async def _unsubscribe_translation_job(
        self, job_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        job = self._translation_jobs.get(job_id)
        if not job:
            return
        listeners = job.setdefault("listeners", set())
        listeners.discard(queue)

    async def start_translation_job(
        self,
        text: str,
        target_language: str,
        glossary: list[dict[str, Any]] | None = None,
    ) -> str:
        target_language = normalize_translation_target_language(target_language)
        selected = text.strip()
        if not selected:
            raise ValueError("Select some text to translate")
        if len(selected) > 12_000:
            raise ValueError("The selected passage is too long")

        cache_key = self._translation_cache_key(selected, target_language, glossary=glossary)
        now = time.time()
        async with self._translation_jobs_lock:
            existing = self._translation_jobs.get(cache_key)
            if existing is not None and existing.get("status") in {
                "queued",
                "running",
                "completed",
            }:
                existing["updated_at"] = now
                return cache_key

        job = {
            "job_id": cache_key,
            "cache_key": cache_key,
            "text": selected,
            "target_language": target_language,
            "glossary": glossary or [],
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": "",
            "sequence": 0,
            "listeners": set(),
            "task": None,
        }
        self._translation_jobs[cache_key] = job
        job["task"] = asyncio.create_task(
            self._run_translation_job(cache_key, selected, target_language, glossary)
        )
        return cache_key

    async def cancel_translation_job(self, job_id: str) -> dict[str, Any]:
        await self._cleanup_stale_translation_jobs()
        job = self._translation_jobs.get(job_id)
        if job is None:
            raise ValueError("Translation job not found")
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return {"job_id": job_id, "status": job.get("status"), "cancelled": False}
        task = job.get("task")
        job["status"] = "cancelled"
        job["updated_at"] = time.time()
        job["error"] = "cancelled_by_client"
        if isinstance(task, asyncio.Task) and not task.done():
            task.cancel()
        await self._emit_translation_job_event(
            job_id,
            {"type": "cancelled", "status": "cancelled", "translation": None, "error": ""},
        )
        return {"job_id": job_id, "status": "cancelled", "cancelled": True}

    async def _run_translation_job(
        self,
        job_id: str,
        text: str,
        target_language: str,
        glossary: list[dict[str, Any]] | None,
    ) -> None:
        target_language = normalize_translation_target_language(target_language)
        job = self._translation_jobs.get(job_id)
        if job is None:
            return
        try:
            job.update(status="running", updated_at=time.time())
            await self._emit_translation_job_event(job_id, {"type": "started", "status": "running"})

            cache_key = job.get("cache_key") or self._translation_cache_key(
                text, target_language, glossary=glossary
            )
            cached = self._translation_cache.get(cache_key)
            if cached is not None:
                self._translation_cache.move_to_end(cache_key)
            else:
                db_hit = self._translation_cache_hit(cache_key)
                if db_hit is not None:
                    cached = db_hit[0]
                    self._translation_cache[cache_key] = cached
                    self._translation_cache.move_to_end(cache_key)

            if cached is not None:
                job.update(
                    status="completed",
                    result=cached,
                    updated_at=time.time(),
                )
                await self._emit_translation_job_event(
                    job_id,
                    {"type": "completed", "status": "completed", "translation": cached},
                )
                return

            async def emit_delta(delta: str) -> None:
                if not delta:
                    return
                await self._emit_translation_job_event(
                    job_id,
                    {"type": "delta", "status": "running", "delta": delta},
                )

            translated = await self._translate_uncached(
                text,
                target_language,
                glossary=glossary,
                on_delta=emit_delta,
            )
            self._translation_cache[cache_key] = translated
            self._translation_cache.move_to_end(cache_key)
            while len(self._translation_cache) > _TRANSLATION_CACHE_LIMIT:
                self._translation_cache.popitem(last=False)
            self._translation_cache_store(
                cache_key,
                text,
                target_language,
                translated,
                glossary=glossary,
            )
            job.update(
                status="completed",
                result=translated,
                updated_at=time.time(),
            )
            await self._emit_translation_job_event(
                job_id,
                {"type": "completed", "status": "completed", "translation": translated},
            )
        except asyncio.CancelledError:
            job.update(status="cancelled", updated_at=time.time())
            await self._emit_translation_job_event(
                job_id,
                {"type": "cancelled", "status": "cancelled", "error": "cancelled"},
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Immersive reading translation job failed: %s", exc)
            job.update(
                status="failed",
                error=str(exc),
                updated_at=time.time(),
            )
            await self._emit_translation_job_event(
                job_id,
                {"type": "failed", "status": "failed", "error": str(exc)},
            )

    async def translate(
        self,
        text: str,
        target_language: str,
        glossary: list[dict[str, Any]] | None = None,
    ) -> str:
        target_language = normalize_translation_target_language(target_language)
        selected = text.strip()
        if not selected:
            raise ValueError("Select some text to translate")
        if len(selected) > 12_000:
            raise ValueError("The selected passage is too long")
        glossary = glossary or None
        cache_key = self._translation_cache_key(selected, target_language, glossary=glossary)
        cached = self._translation_cache.get(cache_key)
        if cached is not None:
            self._translation_cache.move_to_end(cache_key)
            return cached

        db_hit = self._translation_cache_hit(cache_key)
        if db_hit is not None:
            cached = db_hit[0]
            self._translation_cache[cache_key] = cached
            self._translation_cache.move_to_end(cache_key)
            while len(self._translation_cache) > _TRANSLATION_CACHE_LIMIT:
                self._translation_cache.popitem(last=False)
            return cached

        pending = self._translation_tasks.get(cache_key)
        if pending is not None:
            return await asyncio.shield(pending)

        coro = (
            self._translate_uncached(selected, target_language, glossary)
            if glossary
            else self._translate_uncached(selected, target_language)
        )
        task = asyncio.create_task(coro)
        self._translation_tasks[cache_key] = task
        try:
            translated = await asyncio.shield(task)
        finally:
            if self._translation_tasks.get(cache_key) is task:
                self._translation_tasks.pop(cache_key, None)

        self._translation_cache[cache_key] = translated
        self._translation_cache.move_to_end(cache_key)
        while len(self._translation_cache) > _TRANSLATION_CACHE_LIMIT:
            self._translation_cache.popitem(last=False)
        self._translation_cache_store(
            cache_key,
            selected,
            target_language,
            translated,
            glossary=glossary,
        )
        return translated

    async def _translate_uncached(
        self,
        selected: str,
        target_language: str,
        glossary: list[dict[str, Any]] | None = None,
        on_delta: Any | None = None,
    ) -> str:
        target_language = normalize_translation_target_language(target_language)
        glossary = glossary or []
        selected, protected_fragments = protect_translation_text(selected, glossary)
        cfg = get_llm_config()
        provider_name = str(
            getattr(cfg, "provider_name", "") or getattr(cfg, "binding", "") or ""
        ).lower()
        if provider_name != "ollama":
            raise LLMConfigError(
                "Immersive translation is in strict-local mode. Configure the LLM provider "
                "as Ollama for bilingual reading translation.",
                provider="immersive-reading",
            )
        base_url = getattr(cfg, "base_url", "") or getattr(cfg, "effective_url", "") or ""
        if base_url and "11434" not in base_url and "localhost" not in base_url:
            raise LLMConfigError(
                "Immersive translation is in strict-local mode. Configure a local Ollama endpoint.",
                provider="ollama",
            )

        model = await self._ensure_ollama_ready(for_translation=True)
        if is_hymt_model(model):
            user_prompt = build_hymt_translation_prompt(selected, target_language, glossary)
            messages = [{"role": "user", "content": user_prompt}]
            temperature = 0.7
        else:
            system_prompt = (
                "Translate the supplied book passage faithfully. Preserve paragraph breaks, names, tone, "
                "and uncertainty. Output only the translation, with no commentary."
            )
            user_prompt = (
                f"{build_translation_guardrail(target_language, glossary)}\n\nText:\n{selected}"
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            temperature = 0.1

        if on_delta is None:
            raw = await self._ollama_native_chat(
                model,
                messages,
                think=False,
                temperature=temperature,
                num_predict=512
                if len(selected) <= 200
                else 1024
                if len(selected) <= 1000
                else 4096,
            )
        else:
            chunks: list[str] = []

            async def _collect_delta(delta: str) -> None:
                chunks.append(delta)
                await on_delta(delta)

            async for chunk in self._ollama_native_chat_stream(
                model,
                messages,
                think=False,
                temperature=temperature,
                num_predict=512
                if len(selected) <= 200
                else 1024
                if len(selected) <= 1000
                else 4096,
            ):
                await _collect_delta(chunk)
            raw = "".join(chunks)

        # Strict local path: Ollama native endpoint only.
        cleaned = clean_thinking_tags(raw, getattr(cfg, "binding", None), cfg.model).strip()
        try:
            return restore_translation_text(cleaned, protected_fragments)
        except TranslationProtectionError:
            # One retry is deliberate: protected output is rejected before the
            # translation is written to any chapter or task sink.
            raw = await self._ollama_native_chat(
                model,
                messages,
                think=False,
                temperature=temperature,
                num_predict=512
                if len(selected) <= 200
                else 1024
                if len(selected) <= 1000
                else 4096,
            )
            cleaned = clean_thinking_tags(raw, getattr(cfg, "binding", None), cfg.model).strip()
            return restore_translation_text(cleaned, protected_fragments)
