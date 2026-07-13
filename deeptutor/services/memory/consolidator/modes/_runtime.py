"""Shared runtime helpers used by every mode.

These keep the per-mode files focused on algorithm, not plumbing:

* Prompt loading (en/zh, cached).
* SSE event emission (``_emit``).
* Document load + atomic write.
* LLM call wrapper with retries + a one-line warning on failure.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import tempfile
from typing import Any, Awaitable, Callable

import yaml

from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.llm import complete as llm_complete
from deeptutor.services.llm import stream as llm_stream
from deeptutor.services.memory.document import Document, parse, serialize

logger = logging.getLogger(__name__)

OnEvent = Callable[[dict[str, Any]], Awaitable[None]]

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"
_PROMPT_CACHE: dict[tuple[str, str], dict[str, str]] = {}


_META_CACHE: dict[str, dict[str, Any]] = {}


def load_prompt(name: str, language: str) -> dict[str, str]:
    """Load and cache one prompt YAML by name + language (en/zh)."""
    lang = _lang_code(language)
    key = (lang, name)
    cached = _PROMPT_CACHE.get(key)
    if cached is not None:
        return cached
    path = _PROMPTS_DIR / lang / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or "system" not in data or "user" not in data:
        raise RuntimeError(f"prompt {path} missing 'system'/'user' keys")
    _PROMPT_CACHE[key] = {"system": data["system"], "user": data["user"]}
    return _PROMPT_CACHE[key]


def load_focus_meta(language: str) -> dict[str, Any]:
    """Load the per-surface / per-slot focus + sections map for a language."""
    lang = _lang_code(language)
    cached = _META_CACHE.get(lang)
    if cached is not None:
        return cached
    path = _PROMPTS_DIR / lang / "_meta.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _META_CACHE[lang] = data
    return data


def surface_focus(language: str, surface: str) -> tuple[str, list[str]]:
    meta = load_focus_meta(language).get("surfaces", {}).get(surface) or {}
    return meta.get("focus", ""), list(meta.get("sections", []) or [])


def slot_focus(language: str, slot: str) -> tuple[str, list[str]]:
    meta = load_focus_meta(language).get("slots", {}).get(slot) or {}
    return meta.get("focus", ""), list(meta.get("sections", []) or [])


def _lang_code(language: str) -> str:
    return "zh" if (language or "").lower().startswith("zh") else "en"


async def emit(on_event: OnEvent | None, event: dict[str, Any]) -> None:
    if on_event is None:
        return
    try:
        await on_event(event)
    except Exception:
        logger.debug("consolidator: on_event consumer raised", exc_info=True)


async def call_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    on_event: OnEvent | None = None,
    turn: int | None = None,
    chunk_index: int | None = None,
    label: str | None = None,
) -> str:
    """Single LLM call. Returns the raw text body; "" on failure.

    The model/provider is resolved from the *active* LLM config — the
    mode is expected to have installed a scoped config via
    :func:`activate_llm_selection` if the user picked a non-default
    model. Emits ``llm_io_start`` / ``llm_io_end`` events for the
    workbench trace.
    """
    from deeptutor.services.llm import get_llm_config

    model_label = get_llm_config().model or None
    if on_event is not None:
        await on_event(
            {
                "stage": "llm_io_start",
                "turn": turn,
                "chunk_index": chunk_index,
                "label": label,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model_label,
            }
        )
    response_parts: list[str] = []
    in_think_block = False
    try:
        async for delta in llm_stream(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream_coalesce_chars=64,
            stream_coalesce_seconds=0.05,
        ):
            if not delta:
                continue
            response_parts.append(delta)
            visible_delta, in_think_block = _strip_thinking_delta(delta, in_think_block)
            if on_event is not None:
                if visible_delta:
                    await on_event(
                        {
                            "stage": "llm_io_delta",
                            "turn": turn,
                            "chunk_index": chunk_index,
                            "label": label,
                            "delta": visible_delta,
                            "model": model_label,
                        }
                    )
        response = clean_thinking_tags("".join(response_parts))
        if on_event is not None:
            await on_event(
                {
                    "stage": "llm_io_end",
                    "turn": turn,
                    "chunk_index": chunk_index,
                    "label": label,
                    "response": response,
                    "error": None,
                    "model": model_label,
                }
            )
        return response
    except Exception as exc:  # noqa: BLE001
        # Some providers still do not implement streaming. Fall back to the
        # non-streaming path so memory jobs remain usable.
        logger.warning("consolidator streaming LLM call failed; falling back: %s", exc)
        try:
            response = await llm_complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            response = clean_thinking_tags(response)
            if on_event is not None:
                await on_event(
                    {
                        "stage": "llm_io_delta",
                        "turn": turn,
                        "chunk_index": chunk_index,
                        "label": label,
                        "delta": response,
                        "model": model_label,
                    }
                )
                await on_event(
                    {
                        "stage": "llm_io_end",
                        "turn": turn,
                        "chunk_index": chunk_index,
                        "label": label,
                        "response": response,
                        "error": None,
                        "model": model_label,
                    }
                )
            return response
        except Exception as fallback_exc:  # noqa: BLE001
            logger.warning("consolidator LLM call failed: %s", fallback_exc)
            if on_event is not None:
                await on_event(
                    {
                        "stage": "llm_io_end",
                        "turn": turn,
                        "chunk_index": chunk_index,
                        "label": label,
                        "response": "",
                        "error": str(fallback_exc),
                        "model": model_label,
                    }
                )
            return ""


def load_doc(path: Path, *, default_title: str) -> Document:
    if not path.exists():
        return Document(title=default_title)
    return parse(path.read_text(encoding="utf-8"))


async def write_doc_atomic(path: Path, doc: Document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = serialize(doc)
    await asyncio.to_thread(_atomic_write, path, text)


async def write_doc_checkpoint(
    path: Path,
    doc: Document,
    *,
    layer: str,
    key: str,
    on_event: OnEvent | None = None,
    turn: int | None = None,
    label: str | None = None,
    action: str = "write",
) -> int:
    """Write a doc now and register one run-scoped undo checkpoint."""
    existed = path.exists()
    previous = path.read_text(encoding="utf-8") if existed else ""
    await write_doc_atomic(path, doc)
    from deeptutor.services.memory.consolidator.runs import push_undo_checkpoint

    undo_depth = push_undo_checkpoint(
        layer=layer,
        key=key,
        path=path,
        existed=existed,
        previous_content=previous,
        action=action,
        turn=turn,
        label=label,
    )
    await emit(
        on_event,
        {
            "stage": "doc_updated",
            "layer": layer,
            "key": key,
            "turn": turn,
            "label": label,
            "action": action,
            "undo_depth": undo_depth,
        },
    )
    return undo_depth


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_str, path)
    finally:
        if os.path.exists(tmp_str):
            try:
                os.remove(tmp_str)
            except OSError:
                pass


def _strip_thinking_delta(delta: str, in_block: bool) -> tuple[str, bool]:
    """Remove streamed <think> blocks before they reach the workbench UI."""
    out: list[str] = []
    text = delta
    while text:
        lower = text.lower()
        if in_block:
            close_at = lower.find("</think>")
            close_len = len("</think>")
            alt_close = lower.find("</thinking>")
            if alt_close != -1 and (close_at == -1 or alt_close < close_at):
                close_at = alt_close
                close_len = len("</thinking>")
            if close_at == -1:
                return "".join(out), True
            text = text[close_at + close_len :]
            in_block = False
            continue

        open_at = lower.find("<think>")
        open_len = len("<think>")
        alt_open = lower.find("<thinking>")
        if alt_open != -1 and (open_at == -1 or alt_open < open_at):
            open_at = alt_open
            open_len = len("<thinking>")
        if open_at == -1:
            out.append(text)
            break
        out.append(text[:open_at])
        text = text[open_at + open_len :]
        in_block = True
    return "".join(out), in_block


def today_iso() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


__all__ = [
    "OnEvent",
    "call_llm",
    "emit",
    "load_doc",
    "load_focus_meta",
    "load_prompt",
    "slot_focus",
    "surface_focus",
    "today_iso",
    "write_doc_atomic",
    "write_doc_checkpoint",
]
