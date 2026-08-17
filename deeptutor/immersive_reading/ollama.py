"""Ollama transport helpers used by immersive-reading services."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from deeptutor.services.llm import get_llm_config
from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMModelNotFoundError,
    LLMTimeoutError,
)
from deeptutor.services.translation.glossary import is_hymt_model

_OLLAMA_MODEL_CACHE_TTL_SECONDS = 60.0

logger = logging.getLogger(__name__)


class OllamaMixin:
    async def _ensure_ollama_ready(
        self, preferred_model: str | None = None, *, for_translation: bool = False
    ) -> str:
        """Verify Ollama is reachable, auto-starting it if needed."""
        models = await self._ensure_ollama_reachable()
        if not models:
            raise LLMModelNotFoundError(
                "No Ollama models are installed. Run `ollama pull <model>`.",
                model=preferred_model,
                provider="ollama",
            )
        if preferred_model is None:
            cfg = get_llm_config()
            preferred_model = str(cfg.model or "")
        selected = self._resolve_ollama_model(
            preferred_model, models, for_translation=for_translation
        )
        if selected not in models:
            raise LLMModelNotFoundError(
                f"Model {selected} is not installed. Run `ollama pull {selected}`.",
                model=selected,
                provider="ollama",
            )
        return selected

    async def _ensure_ollama_reachable(self) -> list[str]:
        """Verify Ollama is reachable, auto-starting it if needed."""
        now = time.monotonic()
        if (
            hasattr(self, "_ollama_models_cache")
            and self._ollama_models_cache is not None
            and now - self._ollama_models_cache[0] < _OLLAMA_MODEL_CACHE_TTL_SECONDS
        ):
            return self._ollama_models_cache[1]

        timeout = 10
        ollama_base = "http://127.0.0.1:11434"

        async def _check_tags() -> dict | None:
            try:
                import aiohttp

                async with aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as session:
                    async with session.get(f"{ollama_base}/api/tags") as resp:
                        if resp.status == 200:
                            return await resp.json()
            except (aiohttp.ClientError, OSError):
                return None
            return None

        data = await _check_tags()
        if data is None:
            await self._auto_start_ollama()
            for _ in range(8):
                await asyncio.sleep(1)
                data = await _check_tags()
                if data is not None:
                    break

        if data is None:
            if hasattr(self, "_ollama_models_cache"):
                self._ollama_models_cache = None
            raise LLMAPIError(
                "Cannot reach Ollama at 127.0.0.1:11434. Start it with `ollama serve`.",
                status_code=503,
                provider="ollama",
            )

        models = [m.get("name", "") for m in data.get("models", [])]
        if hasattr(self, "_ollama_models_cache"):
            self._ollama_models_cache = (time.monotonic(), models)
        return models

    @staticmethod
    def _resolve_ollama_model(
        preferred: str, installed: list[str], *, for_translation: bool = False
    ) -> str:
        """Pick installed model, preferring preferred + configured families."""
        if not installed:
            return preferred
        if preferred in installed:
            return preferred
        if for_translation and is_hymt_model(preferred):
            hymt_match = next((m for m in installed if is_hymt_model(m)), None)
            if hymt_match:
                return hymt_match
        family = preferred.split(":", 1)[0]
        sibling = next((m for m in installed if m.split(":", 1)[0] == family), None)
        if sibling:
            return sibling
        if for_translation:
            hymt_match = next((m for m in installed if is_hymt_model(m)), None)
            if hymt_match:
                return hymt_match
        return installed[0]

    async def _ollama_native_chat(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        think: bool = False,
        temperature: float = 0.1,
        num_predict: int = 4096,
        timeout: float = 180,
    ) -> str:
        import aiohttp

        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": think,
            "keep_alive": "10m",
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.post(
                    "http://127.0.0.1:11434/api/chat",
                    json=payload,
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
                    data = await resp.json()
        except (aiohttp.ClientError, OSError) as exc:
            raise LLMAPIError(
                "Cannot reach Ollama at 127.0.0.1:11434. Start it with `ollama serve`.",
                status_code=503,
                provider="ollama",
            ) from exc
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError("Ollama request timed out.", provider="ollama") from exc
        return (data.get("message") or {}).get("content", "")

    async def _ollama_native_chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        *,
        think: bool = False,
        temperature: float = 0.1,
        num_predict: int = 4096,
        timeout: float = 180,
    ):
        import aiohttp

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "think": think,
            "keep_alive": "10m",
            "options": {"temperature": temperature, "num_predict": num_predict},
        }
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.post(
                    "http://127.0.0.1:11434/api/chat",
                    json=payload,
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

                    async for line in resp.content:
                        if not line:
                            continue
                        for chunk in line.splitlines():
                            if not chunk:
                                continue
                            if chunk == b"[DONE]":
                                return
                            try:
                                payload_chunk = json.loads(chunk)
                            except json.JSONDecodeError:
                                continue
                            if payload_chunk.get("done"):
                                return
                            delta = (payload_chunk.get("message") or {}).get("content", "")
                            if delta:
                                yield delta
        except (aiohttp.ClientError, OSError) as exc:
            raise LLMAPIError(
                "Cannot reach Ollama at 127.0.0.1:11434. Start it with `ollama serve`.",
                status_code=503,
                provider="ollama",
            ) from exc
        except asyncio.TimeoutError as exc:
            raise LLMTimeoutError("Ollama request timed out.", provider="ollama") from exc

    async def _auto_start_ollama(self) -> None:
        """Launch `ollama serve` as a detached background daemon."""
        import shutil
        import subprocess

        ollama_bin = shutil.which("ollama")
        if not ollama_bin:
            for candidate in (
                "/opt/homebrew/bin/ollama",
                "/usr/local/bin/ollama",
                "/usr/bin/ollama",
            ):
                if Path(candidate).exists():
                    ollama_bin = candidate
                    break
        if not ollama_bin:
            return
        try:
            subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info("Auto-started Ollama daemon for dictionary lookup")
        except OSError as exc:
            logger.warning("Failed to auto-start Ollama: %s", exc)
