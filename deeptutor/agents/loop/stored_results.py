"""Full tool output stays in the session. The model sees a preview and an id.

A later ``read_stored_result`` call reads a character range from that id. It
does not re-execute the tool that produced the text.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from pathlib import Path
import re
from typing import Any

from deeptutor.services.memory.ids import new_ulid

logger = logging.getLogger(__name__)

# Same text estimate as ``estimate_prompt_tokens``: tokens ≈ chars / 3.5.
_CHARS_PER_TOKEN = 3.5
# One preview, or one later read, may use this share of the model input window.
# The rest stays stored. A larger window shows more; one call still cannot
# pull a longer result back in full.
_OBSERVATION_WINDOW_SHARE = 0.05
_RESULT_ID = re.compile(r"result_id=([A-Za-z0-9_]+)")
_CHECKPOINT_NAME = "loop_checkpoint.json"


def observation_char_budget(window_tokens: int | None) -> int:
    """Characters one preview or one ranged read may occupy.

    Five percent of the model's input window. Unknown windows use the same
    fallback the rest of context planning uses.
    """
    from deeptutor.services.llm.context_window import DEFAULT_CONTEXT_WINDOW_FALLBACK

    try:
        tokens = int(window_tokens or 0)
    except (TypeError, ValueError):
        tokens = 0
    if tokens <= 0:
        tokens = DEFAULT_CONTEXT_WINDOW_FALLBACK
    return max(1, int(tokens * _CHARS_PER_TOKEN * _OBSERVATION_WINDOW_SHARE))


def observation_char_budget_for_config(config: Any, model: str = "") -> int:
    """Budget for the model that will actually receive this turn."""
    from deeptutor.services.llm.context_window import resolve_effective_context_window

    window: int | None
    try:
        window = resolve_effective_context_window(
            context_window=getattr(config, "context_window", None),
            model=str(model or getattr(config, "model", "") or ""),
            max_tokens=getattr(config, "max_tokens", None),
        )
    except Exception:
        logger.debug("observation budget fell back to the default window", exc_info=True)
        window = None
    return observation_char_budget(window)


def _page_chars(max_chars: int | None) -> int:
    if max_chars is None:
        return observation_char_budget(None)
    try:
        return max(1, int(max_chars))
    except (TypeError, ValueError):
        return observation_char_budget(None)


def new_result_id() -> str:
    return f"tr_{new_ulid()}"


# File reads stay on disk. The preview names the path and the existing range
# parameters instead of saving a second copy of the file.
FILE_READ_TOOLS = {
    "read_file": "lines",
    "workspace_read": "characters",
}
_FILE_PATH = re.compile(r"^file_path=(.+)$", re.MULTILINE)
_FILE_TOOL = re.compile(r"^read_with=(.+)$", re.MULTILINE)


def preview_stored(
    text: str,
    *,
    language: str = "en",
    max_chars: int | None = None,
) -> tuple[str, tuple[str, str] | None]:
    """Return ``(model_text, (id, full_text) or None)``.

    Text within the current model's page budget is returned unchanged and is
    not stored. ``max_chars`` is that budget; omit it only when no model
    window is known.
    """
    page = _page_chars(max_chars)
    body = str(text or "")
    if len(body) <= page:
        return body, None
    result_id = new_result_id()
    preview = body[:page]
    if language.startswith("zh"):
        header = (
            "结果过长，全文已保存。\n"
            f"result_id={result_id}\n"
            f"总长度：{len(body)} 字符。下面是前 {page} 字符。\n"
            f"单次最多再读 {page} 字符，这个上限按当前模型的输入窗口计算。\n"
            "要看后面，调用 read_stored_result，传入这个 result_id，以及 offset 和 limit。\n"
            "不要再次调用刚才那个工具。\n\n"
        )
    else:
        header = (
            "Result stored because it is too long for the conversation.\n"
            f"result_id={result_id}\n"
            f"Total length: {len(body)} characters. The first {page} follow.\n"
            f"One read returns at most {page} characters, from this model's input window.\n"
            "To read more, call read_stored_result with this result_id, plus offset and limit.\n"
            "Do not call the original tool again.\n\n"
        )
    return header + preview, (result_id, body)


def result_id_in(text: str) -> str:
    match = _RESULT_ID.search(str(text or ""))
    return match.group(1) if match else ""


def file_read_in(text: str) -> tuple[str, str]:
    """Return ``(tool_name, path)`` when a preview points at a file on disk."""
    body = str(text or "")
    path = _FILE_PATH.search(body)
    tool = _FILE_TOOL.search(body)
    if path is None or tool is None:
        return "", ""
    return tool.group(1).strip(), path.group(1).strip()


def preview_file_read(
    tool_name: str,
    args: Mapping[str, Any] | None,
    text: str,
    metadata: Mapping[str, Any] | None = None,
    *,
    language: str = "en",
    max_chars: int | None = None,
) -> str | None:
    """Preview a long file read without storing another copy of the file."""
    page = _page_chars(max_chars)
    unit = FILE_READ_TOOLS.get(tool_name)
    body = str(text or "")
    if unit is None or len(body) <= page:
        return None
    path = ""
    if isinstance(args, Mapping):
        path = str(args.get("path") or "")
    nested = metadata.get("workspace_read") if isinstance(metadata, Mapping) else None
    if isinstance(nested, Mapping) and nested.get("path"):
        path = str(nested["path"])
    if not path:
        return None
    preview = body[:page]
    if language.startswith("zh"):
        unit_label = "行号" if unit == "lines" else "字符偏移"
        header = (
            "文件已在磁盘上，不再另存一份。\n"
            f"file_path={path}\n"
            f"read_with={tool_name}\n"
            f"用 {tool_name} 按范围读取，offset 和 limit 是{unit_label}。\n"
            f"下面是这次结果的前 {page} 字符。这个长度按当前模型的输入窗口计算。\n\n"
        )
    else:
        unit_label = "line numbers" if unit == "lines" else "character offsets"
        header = (
            "This file is already on disk, so it was not stored again.\n"
            f"file_path={path}\n"
            f"read_with={tool_name}\n"
            f"Read a range with {tool_name}. offset and limit are {unit_label}.\n"
            f"The first {page} characters of this result follow, sized from this model's input window.\n\n"
        )
    return header + preview


def slice_stored(text: str, offset: Any, limit: Any, *, max_chars: int | None = None) -> str:
    """Return one capped window and say where the next window starts."""
    page = _page_chars(max_chars)
    body = str(text or "")
    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    try:
        window = int(limit if limit is not None else page)
    except (TypeError, ValueError):
        window = page
    window = max(1, min(window, page))
    if start >= len(body):
        return (
            f"offset {start} is past the end of this stored result "
            f"({len(body)} characters)."
        )
    chunk = body[start : start + window]
    end = start + len(chunk)
    note = f"Showing characters {start}-{end} of {len(body)}."
    if end < len(body):
        note += f" Next offset={end}, limit up to {page}."
    return f"{note}\n\n{chunk}"


def retain_observation(
    store: dict[str, str],
    text: str,
    *,
    language: str = "en",
    max_chars: int | None = None,
) -> str:
    """Store a long injected observation and return the preview the model sees."""
    shown, stored = preview_stored(text, language=language, max_chars=max_chars)
    if stored is not None:
        store[stored[0]] = stored[1]
    return shown


def collect_stored_results(records: list[dict[str, Any]] | None) -> dict[str, str]:
    """Merge ``stored_results`` dicts from persisted model turns."""
    found: dict[str, str] = {}
    for record in records or []:
        bodies = record.get("stored_results") if isinstance(record, dict) else None
        if not isinstance(bodies, Mapping):
            continue
        for key, value in bodies.items():
            if isinstance(key, str) and isinstance(value, str) and key:
                found[key] = value
    return found


def _checkpoint_path(session_id: str) -> Path | None:
    if not session_id:
        return None
    try:
        from deeptutor.services.path_service import get_path_service

        return get_path_service().get_session_workspace("chat", session_id) / _CHECKPOINT_NAME
    except Exception:
        logger.debug("loop checkpoint path unavailable", exc_info=True)
        return None


def write_loop_checkpoint(
    session_id: str,
    turn_id: str,
    model_turn: dict[str, Any],
    *,
    anchor: str = "",
) -> None:
    """Replace the session's in-progress checkpoint. The chat transcript is unchanged."""
    path = _checkpoint_path(session_id)
    if path is None or not model_turn:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "anchor": anchor,
                    "model_turn": model_turn,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except (OSError, TypeError, ValueError):
        logger.warning("failed to write loop checkpoint", exc_info=True)


def read_loop_checkpoint(session_id: str) -> dict[str, Any] | None:
    path = _checkpoint_path(session_id)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("failed to read loop checkpoint", exc_info=True)
        return None
    if not isinstance(payload, dict) or payload.get("session_id") != session_id:
        return None
    turn = payload.get("model_turn")
    if not isinstance(turn, dict):
        return None
    return payload


def clear_loop_checkpoint(session_id: str) -> None:
    path = _checkpoint_path(session_id)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("failed to clear loop checkpoint", exc_info=True)
