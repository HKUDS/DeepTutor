"""Conservative objective grading; prose and qualitative work uses self-assessment."""

from __future__ import annotations

import json
import re


def check_answer(entry: dict, answer: str) -> bool | None:
    kind = entry.get("question_type", "")
    options = entry.get("options") or json.loads(entry.get("options_json") or "{}")
    expected = str(entry.get("correct_answer") or "").strip()
    if (
        not options
        or not expected
        or kind in {"qualitative", "short_answer", "essay", "free_response"}
    ):
        return None

    def folded(text: str) -> str:
        return " ".join(text.strip().upper().split())

    def keys(value: str) -> set[str]:
        for key, text in options.items():
            if folded(value) in {
                folded(key),
                folded(text),
                folded(f"{key}. {text}"),
                folded(f"{key}) {text}"),
            }:
                return {key}
        parts = {part.strip().upper() for part in re.split(r"[,;，；\s]+", value) if part.strip()}
        if (
            kind in {"multi_choice", "multiple_select"}
            and len(parts) == 1
            and not parts <= options.keys()
        ):
            parts = set(value.strip().upper())
        return parts

    expected_keys, actual_keys = keys(expected), keys(answer)
    if not expected_keys or not expected_keys <= options.keys():
        return None  # A malformed legacy answer key must never invent a grade.
    return bool(actual_keys) and actual_keys == expected_keys
