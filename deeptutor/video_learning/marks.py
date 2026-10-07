"""Private learning marks attached to a timed-media material."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from deeptutor.video_learning.service import TimedMediaError, TimedMediaNotFound

MARK_KINDS = frozenset({"key_point", "question", "review"})
MARK_AUTHORS = frozenset({"user", "assistant"})
MARK_SOURCES = frozenset({"immersive"})
MAX_MARKS_PER_MATERIAL = 500
MAX_QUOTE_CHARS = 4000
MAX_NOTE_CHARS = 2000
MAX_SUGGESTIONS = 5
NEARBY_WINDOW_SECONDS = 60.0

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class MarkNotFound(TimedMediaNotFound):
    """A mark does not belong to the requested material."""


def utcnow() -> str:
    """Return the current UTC timestamp formatted as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _clip_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _as_seconds(value: Any) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise TimedMediaError("Mark timestamps must be numbers.") from exc
    if seconds < 0 or seconds > 24 * 60 * 60:
        raise TimedMediaError("Mark timestamps are outside the allowed range.")
    return seconds


def _duration_seconds(material: dict[str, Any]) -> float:
    source = material.get("source") if isinstance(material.get("source"), dict) else {}
    metadata = material.get("metadata") if isinstance(material.get("metadata"), dict) else {}
    for row in (source, metadata):
        try:
            duration = float(row.get("duration_seconds") or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if duration > 0:
            return duration
    return 0.0


def _segments(material: dict[str, Any]) -> list[dict[str, Any]]:
    rows = material.get("segments")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _cues(material: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = material.get("transcript") if isinstance(material.get("transcript"), dict) else {}
    rows = transcript.get("cues")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def locators_for_range(material: dict[str, Any], start: float, end: float) -> tuple[int, int]:
    """Find start and end segment locators overlapping the specified time span."""
    overlapping = [
        row
        for row in _segments(material)
        if float(row.get("end") or 0) >= start and float(row.get("start") or 0) <= end
    ]
    if not overlapping:
        return 0, 0
    start_locator = int(overlapping[0].get("locator") or 0)
    end_locator = int(overlapping[-1].get("locator") or start_locator)
    return max(0, start_locator), max(0, end_locator)


def quote_for_range(material: dict[str, Any], start: float, end: float) -> str:
    """Concatenate subtitle cue text within the specified time span."""
    selected = [
        str(row.get("text") or "").strip()
        for row in _cues(material)
        if str(row.get("text") or "").strip()
        and float(row.get("end") or 0) >= start
        and float(row.get("start") or 0) <= end
    ]
    return _clip_text(" ".join(selected), MAX_QUOTE_CHARS)


def nearby_cues(
    material: dict[str, Any], time_seconds: float, window: float = NEARBY_WINDOW_SECONDS
) -> list[dict[str, Any]]:
    """Return subtitle cues whose start is within the window of time_seconds."""
    return [
        row for row in _cues(material) if abs(float(row.get("start") or 0) - time_seconds) <= window
    ]


def current_segment(material: dict[str, Any], time_seconds: float) -> dict[str, Any] | None:
    """Find the material segment containing time_seconds."""
    return next(
        (
            row
            for row in _segments(material)
            if float(row.get("start") or 0) <= time_seconds <= float(row.get("end") or 0)
        ),
        None,
    )


def marks_list(material: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the mutable marks list in material learning state."""
    learning = material.setdefault("learning", {})
    marks = learning.get("marks")
    if not isinstance(marks, list):
        marks = []
        learning["marks"] = marks
    return marks


def get_mark(material: dict[str, Any], mark_id: str) -> dict[str, Any]:
    """Retrieve a mark by ID from the material or raise MarkNotFound."""
    for mark in marks_list(material):
        if isinstance(mark, dict) and str(mark.get("mark_id") or "") == mark_id:
            return mark
    raise MarkNotFound("Timed media mark was not found.")


def normalize_mark(
    material: dict[str, Any],
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalize mark fields for creation or update."""
    kind = str(payload.get("kind") or (existing or {}).get("kind") or "").strip()
    if kind not in MARK_KINDS:
        raise TimedMediaError("Mark kind must be key_point, question, or review.")
    start = _as_seconds(
        payload["start_seconds"]
        if "start_seconds" in payload
        else (existing or {}).get("start_seconds", 0)
    )
    end = _as_seconds(
        payload["end_seconds"]
        if "end_seconds" in payload
        else (existing or {}).get("end_seconds", start)
    )
    if end < start:
        raise TimedMediaError("Mark end must be at or after the start time.")
    duration = _duration_seconds(material)
    if duration > 0:
        if start > duration:
            raise TimedMediaError("Mark start is beyond the video duration.")
        end = min(end, duration)

    derived_start, derived_end = locators_for_range(material, start, end)
    start_locator = payload.get(
        "start_locator", (existing or {}).get("start_locator", derived_start)
    )
    end_locator = payload.get("end_locator", (existing or {}).get("end_locator", derived_end))
    try:
        start_locator = max(0, int(start_locator or 0))
        end_locator = max(0, int(end_locator or 0))
    except (TypeError, ValueError) as exc:
        raise TimedMediaError("Mark locators must be integers.") from exc
    if start_locator == 0:
        start_locator = derived_start
    if end_locator == 0:
        end_locator = derived_end or start_locator

    quote = payload.get("quote")
    if quote is None:
        quote = (existing or {}).get("quote") or quote_for_range(material, start, end)
    note = payload.get("note")
    if note is None:
        note = (existing or {}).get("note") or ""
    author = str(payload.get("author") or (existing or {}).get("author") or "user")
    if author not in MARK_AUTHORS:
        raise TimedMediaError("Mark author must be user or assistant.")
    source = str(payload.get("source") or (existing or {}).get("source") or "immersive")
    if source not in MARK_SOURCES:
        raise TimedMediaError("Mark source must be immersive.")

    raw_metadata = payload.get("metadata", (existing or {}).get("metadata") or {})
    if raw_metadata is None:
        raw_metadata = {}
    if not isinstance(raw_metadata, dict):
        raise TimedMediaError("Mark metadata must be an object.")
    metadata = dict(raw_metadata)
    if len(metadata) > 16:
        raise TimedMediaError("Mark metadata has too many fields.")
    if len(json.dumps(metadata, ensure_ascii=False, default=str)) > 4000:
        raise TimedMediaError("Mark metadata is too large.")

    stamp = utcnow()
    mark_id = str((existing or {}).get("mark_id") or payload.get("mark_id") or "")
    if not re.fullmatch(r"[0-9a-f]{16,64}", mark_id or ""):
        seed = f"{material.get('material_id')}-{kind}-{start}-{end}-{stamp}"
        mark_id = hashlib.sha256(seed.encode()).hexdigest()[:24]
    mark = {
        "mark_id": mark_id,
        "kind": kind,
        "start_seconds": start,
        "end_seconds": end,
        "start_locator": start_locator,
        "end_locator": end_locator,
        "quote": _clip_text(quote, MAX_QUOTE_CHARS),
        "note": _clip_text(note, MAX_NOTE_CHARS),
        "author": author,
        "source": source,
        "metadata": metadata,
        "created_at": str((existing or {}).get("created_at") or stamp),
        "updated_at": stamp,
    }
    reviewed_at = payload.get("reviewed_at", (existing or {}).get("reviewed_at"))
    if payload.get("reviewed") is True:
        reviewed_at = stamp
    if payload.get("reviewed") is False:
        reviewed_at = None
    if reviewed_at:
        mark["reviewed_at"] = str(reviewed_at)
    return mark


def create_mark(material: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Create a new mark on the material."""
    marks = marks_list(material)
    if len(marks) >= MAX_MARKS_PER_MATERIAL:
        raise TimedMediaError("This video already has the maximum number of marks.")
    mark = normalize_mark(material, payload)
    marks.append(mark)
    return mark


def update_mark(material: dict[str, Any], mark_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update fields on an existing mark."""
    if not payload:
        raise TimedMediaError("No mark fields to update.")
    current = get_mark(material, mark_id)
    updated = normalize_mark(material, payload, existing=current)
    marks = marks_list(material)
    for index, row in enumerate(marks):
        if isinstance(row, dict) and str(row.get("mark_id") or "") == mark_id:
            marks[index] = updated
            return updated
    raise MarkNotFound("Timed media mark was not found.")


def delete_mark(material: dict[str, Any], mark_id: str) -> dict[str, Any]:
    """Delete a mark from the material by mark_id."""
    marks = marks_list(material)
    for index, row in enumerate(marks):
        if isinstance(row, dict) and str(row.get("mark_id") or "") == mark_id:
            return marks.pop(index)
    raise MarkNotFound("Timed media mark was not found.")


def _parse_json_array(text: str) -> list[Any]:
    raw = _JSON_FENCE.sub("", (text or "").strip())
    start = raw.find("[")
    end = raw.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    return payload if isinstance(payload, list) else []


def _public_suggestion(material: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    try:
        mark = normalize_mark(material, {**payload, "author": "assistant"})
    except TimedMediaError:
        return None
    mark.pop("mark_id", None)
    mark["quote"] = quote_for_range(material, mark["start_seconds"], mark["end_seconds"])
    if not mark["quote"]:
        return None
    mark.pop("created_at", None)
    mark.pop("updated_at", None)
    mark.pop("reviewed_at", None)
    return mark


def heuristic_suggestions(material: dict[str, Any], time_seconds: float) -> list[dict[str, Any]]:
    """Generate heuristic candidate marks based on the current segment or nearby cues."""
    segment = current_segment(material, time_seconds)
    if segment is None:
        nearby = nearby_cues(material, time_seconds)
        if not nearby:
            return []
        start = float(nearby[0].get("start") or time_seconds)
        end = float(nearby[-1].get("end") or time_seconds)
        text = " ".join(str(row.get("text") or "") for row in nearby)
    else:
        start = float(segment.get("start") or time_seconds)
        end = float(segment.get("end") or time_seconds)
        text = str(segment.get("text") or "")
    candidates: list[dict[str, Any]] = [
        {
            "kind": "key_point",
            "start_seconds": start,
            "end_seconds": max(start, end),
            "quote": text,
            "note": "",
        }
    ]
    if "?" in text or "？" in text:
        candidates.append(
            {
                "kind": "question",
                "start_seconds": start,
                "end_seconds": max(start, end),
                "quote": text,
                "note": "",
            }
        )
    return [
        suggestion
        for suggestion in (
            _public_suggestion(material, {**row, "author": "assistant"})
            for row in candidates[:MAX_SUGGESTIONS]
        )
        if suggestion is not None
    ]


async def suggest_marks(material: dict[str, Any], time_seconds: float) -> list[dict[str, Any]]:
    """Generate candidate marks without writing any of them."""
    segment = current_segment(material, time_seconds)
    nearby = nearby_cues(material, time_seconds)
    if not segment and not nearby:
        return []
    transcript = "\n".join(
        f"[{float(row.get('start') or 0):.1f}-{float(row.get('end') or 0):.1f}] {row.get('text', '')}"
        for row in nearby[:40]
    )
    prompt = (
        "Extract up to 5 learning marks from this video excerpt. Return JSON only: "
        '[{"kind":"key_point|question|review","start_seconds":number,"end_seconds":number,'
        '"quote":"verbatim subtitle span","note":"optional short note"}]. '
        "Use kind=key_point for core claims, question for unclear or asked points, and "
        "review for items the learner should revisit. Keep quotes short.\n"
        f"Current time: {time_seconds:.1f}\n"
        f"Current segment: {json.dumps(segment or {}, ensure_ascii=False)}\n"
        f"Nearby transcript:\n{transcript}"
    )
    try:
        from deeptutor.services.llm import complete

        raw = await complete(
            prompt,
            system_prompt=(
                "You help a learner mark a video. Reply with a JSON array and no markdown. "
                "Do not invent timestamps outside the supplied transcript."
            ),
            temperature=0.2,
            max_tokens=800,
        )
        parsed = _parse_json_array(str(raw or ""))
    except Exception:
        parsed = []
    suggestions: list[dict[str, Any]] = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        suggestion = _public_suggestion(material, row)
        if suggestion is not None:
            suggestions.append(suggestion)
        if len(suggestions) >= MAX_SUGGESTIONS:
            break
    return suggestions or heuristic_suggestions(material, time_seconds)


__all__ = [
    "MARK_AUTHORS",
    "MARK_KINDS",
    "MARK_SOURCES",
    "MAX_MARKS_PER_MATERIAL",
    "MAX_NOTE_CHARS",
    "MAX_QUOTE_CHARS",
    "MAX_SUGGESTIONS",
    "NEARBY_WINDOW_SECONDS",
    "MarkNotFound",
    "create_mark",
    "current_segment",
    "delete_mark",
    "get_mark",
    "heuristic_suggestions",
    "locators_for_range",
    "marks_list",
    "nearby_cues",
    "normalize_mark",
    "quote_for_range",
    "suggest_marks",
    "update_mark",
    "utcnow",
]
