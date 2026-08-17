"""Dictionary helpers for immersive reading (ECDICT + local Ollama fallback)."""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path

from deeptutor.immersive_reading.ecdict import ECDictionary
from deeptutor.immersive_reading.models import DictionaryDefinition, DictionaryResult
from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMModelNotFoundError,
    LLMParseError,
    LLMTimeoutError,
)

_DICT_CACHE_LIMIT = 500


class DictionaryMixin:
    # Cache key: lower-case word -> DictionaryResult.
    _dict_cache: OrderedDict[str, DictionaryResult] = OrderedDict()

    @classmethod
    def _cache_get(cls, word: str) -> DictionaryResult | None:
        c = cls._dict_cache
        key = word.strip().casefold()
        if key in c:
            c.move_to_end(key)
            return c[key]
        return None

    @classmethod
    def _cache_put(cls, word: str, result: DictionaryResult) -> None:
        c = cls._dict_cache
        key = word.strip().casefold()
        c[key] = result
        c.move_to_end(key)
        while len(c) > _DICT_CACHE_LIMIT:
            c.popitem(last=False)

    @classmethod
    def _cache_clear(cls) -> None:
        cls._dict_cache.clear()

    @staticmethod
    def _mark_context_match(result: DictionaryResult, context: str) -> DictionaryResult:
        if not context or not result.definitions:
            return result
        stop = frozenset(
            "a an the of to in on at for and or but is are was were be been "
            "being have has had do does did will would could should may might "
            "must can this that these those it he she they we you i his her "
            "their our your my its as with from by not no".split()
        )
        ctx_words = {
            w for w in re.findall(r"[a-z']+", context.lower()) if w not in stop and len(w) > 2
        }
        if not ctx_words:
            return result

        best_idx = 0
        best_score = -1
        for i, d in enumerate(result.definitions):
            def_words = {
                w for w in re.findall(r"[a-z']+", (d.definition + " " + d.example).lower())
            }
            score = len(def_words & ctx_words)
            if score > best_score:
                best_score = score
                best_idx = i

        if best_score > 0:
            new_defs = [
                d.model_copy(update={"context_match": i == best_idx})
                for i, d in enumerate(result.definitions)
            ]
            return result.model_copy(update={"definitions": new_defs})
        return result

    def _local_dictionary_lookup(self, word: str) -> DictionaryResult | None:
        try:
            if self._ecdict is None:
                self._ecdict = ECDictionary(self._ecdict_path())
            entry = self._ecdict.lookup(word)
        except FileNotFoundError:
            self._ecdict = None
            return None

        if entry is None:
            return None
        english_definitions = [
            DictionaryDefinition(definition=line.strip(), part_of_speech=entry.pos)
            for line in entry.definition.splitlines()
            if line.strip()
        ][:6]
        if not english_definitions and not entry.translation:
            return None
        return DictionaryResult(
            word=entry.word or word,
            phonetic=entry.phonetic,
            definitions=english_definitions,
            chinese=entry.translation,
        )

    def dictionary_status(self) -> dict[str, object]:
        path = self._ecdict_path()
        entries: int | None = None
        frequency_fields = False
        error = ""
        version: str | None = None
        checksum: str | None = None
        license: str | None = None
        import_progress: float | None = getattr(self, "_ecdict_import_progress", None)

        if path.is_file():
            try:
                import sqlite3

                with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
                    entries = int(connection.execute("SELECT count(*) FROM entries").fetchone()[0])
                dictionary = ECDictionary(path)
                try:
                    frequency_fields = dictionary.frequency_columns_available
                finally:
                    dictionary.close()
                version = "1.0.28"
                license = "GPL-3.0"
            except Exception as exc:
                error = str(exc)
        return {
            "installed": path.is_file() and entries is not None,
            "frequency_fields": frequency_fields if entries is not None else False,
            "path": str(path),
            "entries": entries,
            "size_bytes": path.stat().st_size if path.exists() else 0,
            "version": version,
            "checksum": checksum,
            "license": license,
            "import_progress": import_progress,
            "error": error,
        }

    def import_ecdict_csv(self, csv_path: str | Path) -> int:
        target = self._ecdict_path()
        count = ECDictionary.import_csv(csv_path, target)
        if self._ecdict is not None:
            self._ecdict.close()
            self._ecdict = None
        self._cache_clear()
        return count

    async def _enrich_with_chinese(self, result: DictionaryResult) -> DictionaryResult:
        if result.chinese:
            return result
        if not result.definitions or all(d.chinese for d in result.definitions):
            return result

        try:
            model = await self._ensure_ollama_ready()
        except Exception:  # model missing / Ollama down
            return result

        items = [{"pos": d.part_of_speech, "definition": d.definition} for d in result.definitions]
        system_prompt = (
            "/no_think\n"
            "You translate English dictionary definitions into concise Chinese "
            "(中文释义). You receive a word and a JSON array of its English "
            'definitions. Return a JSON object whose "translations" key holds '
            "an array of the SAME LENGTH where element i is the concise Chinese "
            "translation of definition i. Each translation should be a short "
            "phrase. Respond with ONLY this JSON (no markdown, no explanation):\n"
            '{"translations": ["中文释义1", "中文释义2"]}'
        )
        user_prompt = (
            f"Word: {result.word}\n"
            f"Definitions to translate:\n{json.dumps(items, ensure_ascii=False)}"
        )
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 1024},
        }

        try:
            import aiohttp as _aiohttp

            timeout = _aiohttp.ClientTimeout(total=45)
            async with _aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post("http://127.0.0.1:11434/api/chat", json=payload) as resp:
                    if resp.status != 200:
                        return result
                    data = await resp.json()
        except Exception:
            return result

        raw = (data.get("message") or {}).get("content", "")
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned).rsplit("```", 1)[0].strip()
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            return result

        translations = parsed.get("translations") if isinstance(parsed, dict) else None
        if not isinstance(translations, list):
            return result

        enriched_defs = []
        for i, d in enumerate(result.definitions):
            candidate = translations[i] if i < len(translations) else ""
            chinese = candidate.strip() if isinstance(candidate, str) and candidate.strip() else d.chinese
            enriched_defs.append(d.model_copy(update={"chinese": chinese}))
        return result.model_copy(update={"definitions": enriched_defs})

    async def lookup_word(self, word: str, context: str = "") -> DictionaryResult:
        import json as _json

        word = word.strip()
        if not word:
            raise ValueError("Provide a word to look up")
        if len(word) > 200:
            raise ValueError("Word is too long")
        context = context.strip()[:2_000]

        cached = self._cache_get(word)
        if cached is not None:
            return self._mark_context_match(cached, context) if context else cached

        local_result = self._local_dictionary_lookup(word)
        if local_result is not None:
            local_result = await self._enrich_with_chinese(local_result)
            self._cache_put(word, local_result)
            return self._mark_context_match(local_result, context) if context else local_result

        model = await self._ensure_ollama_ready()

        system_prompt = (
            "/no_think\n"
            "You are a learner's dictionary designed for ESL students. Given a word and optionally "
            "the sentence it appears in, return JSON with definitions sorted so the meaning that "
            "fits the context comes FIRST.\n\n"
            "IMPORTANT rules:\n"
            "1. Write ALL definitions in SIMPLE English (A2/B1 level). Use short sentences and common "
            "words. Avoid difficult vocabulary in the explanation itself.\n"
            '2. For each definition, also provide a CHINESE translation in the "chinese" field.\n'
            '3. Set "context_match": true only for the definition(s) that match the provided sentence.\n'
            "4. Include IPA pronunciation, part of speech, a simple example sentence, and 0-3 synonyms.\n\n"
            "Respond with ONLY this JSON schema (no markdown fence):\n"
            "{\n"
            '  "word": "<headword>",\n'
            '  "phonetic": "<IPA or empty>",\n'
            '  "definitions": [\n'
            '    {"part_of_speech": "", "definition": "<simple English>", '
            '"chinese": "<中文释义>", "example": "", "synonyms": [], '
            '"context_match": false}\n'
            "  ],\n"
            '  "context_note": "<short note on which meaning fits the context, or empty>"\n'
            "}\n\n"
            "Return at most 4 definitions. If the context makes the word's meaning unambiguous, "
            "put that meaning first and mark it context_match=true."
        )
        user_prompt = f"Word: {word}"
        if context:
            user_prompt += f"\nSentence from the book: {context}"

        import aiohttp as _aiohttp

        ollama_payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 4096},
        }

        try:
            timeout = _aiohttp.ClientTimeout(total=60)
            async with _aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    "http://127.0.0.1:11434/api/chat",
                    json=ollama_payload,
                ) as resp:
                    if resp.status == 404:
                        raise LLMModelNotFoundError(
                            f"Model {model} is not installed. Run `ollama pull {model}`.",
                            model=model,
                            provider="ollama",
                        )
                    if resp.status != 200:
                        body = await resp.text()
                        raise LLMAPIError(
                            f"Ollama returned HTTP {resp.status}: {body[:200]}",
                            status_code=resp.status,
                            provider="ollama",
                        )
                    result = await resp.json()
        except (_aiohttp.ClientError, OSError) as exc:
            raise LLMAPIError(
                "Cannot reach Ollama at 127.0.0.1:11434. Start it with `ollama serve`.",
                status_code=503,
                provider="ollama",
            ) from exc
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError(
                "Dictionary lookup timed out. Is Ollama running and is the model loaded?",
                provider="ollama",
            ) from exc

        raw = (result.get("message") or {}).get("content", "")

        if not raw.strip():
            raise LLMParseError(
                f"Local model returned empty content for word {word!r}.",
                provider="ollama",
            )

        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-z]*\n?", "", cleaned).rsplit("```", 1)[0].strip()
        try:
            data = _json.loads(cleaned)
        except _json.JSONDecodeError:
            raise LLMParseError(
                f"Local model returned unparseable output for word {word!r}.",
                provider="ollama",
            )
        if not isinstance(data, dict) or not isinstance(data.get("definitions"), list):
            raise LLMParseError(
                f"Local model returned an invalid dictionary payload for word {word!r}.",
                provider="ollama",
            )
        for field in ("word", "phonetic", "context_note"):
            if field in data and not isinstance(data[field], str):
                raise LLMParseError(
                    f"Local model returned an invalid {field} for word {word!r}.",
                    provider="ollama",
                )

        defs = []
        for d in data.get("definitions", []):
            if not isinstance(d, dict):
                raise LLMParseError(
                    f"Local model returned an invalid definition for word {word!r}.",
                    provider="ollama",
                )
            for field in ("part_of_speech", "definition", "example"):
                if field in d and not isinstance(d[field], str):
                    raise LLMParseError(
                        f"Local model returned an invalid definition for word {word!r}.",
                        provider="ollama",
                    )
            synonyms = d.get("synonyms", [])
            if not isinstance(synonyms, list) or not all(isinstance(item, str) for item in synonyms):
                raise LLMParseError(
                    f"Local model returned invalid synonyms for word {word!r}.",
                    provider="ollama",
                )
            defs.append(
                DictionaryDefinition(
                    part_of_speech=d.get("part_of_speech", ""),
                    definition=d.get("definition", ""),
                    chinese=d.get("chinese", ""),
                    example=d.get("example", ""),
                    synonyms=d.get("synonyms", []),
                    context_match=bool(d.get("context_match", False)),
                )
            )
        if not defs:
            raise LLMParseError(
                f"Local model returned no definitions for word {word!r}.",
                provider="ollama",
            )
        llm_result = DictionaryResult(
            word=data.get("word", word),
            phonetic=data.get("phonetic", ""),
            definitions=defs,
            context_note=data.get("context_note", ""),
        )
        self._cache_put(word, llm_result)
        return llm_result
