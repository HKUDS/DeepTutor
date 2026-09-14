"""Character-level scoring for poetry recitation attempts.

This module deliberately scores only the text returned by the configured STT
provider.  It does not claim to measure tone or phoneme quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import time
from typing import Literal, Sequence
import uuid

from pydantic import BaseModel, ConfigDict, Field

from .models import RecitationSummary


@dataclass
class _LineAlignmentState:
    line_id: str
    expected_text: str
    expected_count: int
    recognized: list[str] = field(default_factory=list)
    omissions: list[str] = field(default_factory=list)
    insertions: list[str] = field(default_factory=list)
    matches: int = 0


class RecitationLineResult(BaseModel):
    """Character alignment evidence for one requested poetry line."""

    model_config = ConfigDict(extra="ignore")

    line_id: str
    expected_text: str
    recognized_text: str
    character_accuracy: float = Field(ge=0.0, le=1.0)
    omissions: list[str] = Field(default_factory=list)
    insertions: list[str] = Field(default_factory=list)


class RecitationAttempt(BaseModel):
    """One scored or unavailable poetry recitation attempt."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"rec_{uuid.uuid4().hex[:12]}")
    book_id: str
    block_id: str
    target_line_ids: list[str]
    transcript: str = ""
    line_results: list[RecitationLineResult] = Field(default_factory=list)
    overall_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)
    data_state: Literal["scored", "stt_failed"]
    created_at: float = Field(default_factory=time.time)


def poetry_line_id(index: int) -> str:
    """Return the stable public id for a poetry payload line index."""

    return f"line-{index + 1}"


def resolve_target_lines(
    lines: object,
    requested_line_ids: Sequence[str],
) -> list[tuple[str, str]]:
    """Resolve requested ids to server-owned poetry text.

    The client sends line ids only.  Text always comes from the persisted block
    payload, preventing a caller from supplying the expected answer.
    """

    if not isinstance(lines, list):
        raise ValueError("Poetry block has no lines.")

    available: dict[str, str] = {}
    for index, item in enumerate(lines):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if text:
            available[poetry_line_id(index)] = text

    clean_ids = [str(line_id).strip() for line_id in requested_line_ids]
    if not clean_ids or any(not line_id for line_id in clean_ids):
        raise ValueError("At least one valid line id is required.")
    if len(clean_ids) != len(set(clean_ids)):
        raise ValueError("Duplicate line ids are not allowed.")

    missing = [line_id for line_id in clean_ids if line_id not in available]
    if missing:
        raise ValueError(f"Unknown poetry line ids: {', '.join(missing)}")
    return [(line_id, available[line_id]) for line_id in clean_ids]


def _scoring_characters(text: str) -> list[str]:
    """Normalize text to characters that should affect recitation accuracy."""

    return [character.casefold() for character in text if character.isalnum()]


def score_recitation(
    *,
    book_id: str,
    block_id: str,
    target_lines: Sequence[tuple[str, str]],
    transcript: str,
) -> RecitationAttempt:
    """Align an STT transcript to one or more target lines and aggregate it."""

    if not target_lines:
        raise ValueError("At least one target line is required.")

    expected_chars: list[str] = []
    expected_line_indexes: list[int] = []
    line_states: list[_LineAlignmentState] = []
    for line_index, (line_id, expected_text) in enumerate(target_lines):
        chars = _scoring_characters(expected_text)
        if not chars:
            raise ValueError(f"Poetry line {line_id} has no scoreable characters.")
        expected_chars.extend(chars)
        expected_line_indexes.extend([line_index] * len(chars))
        line_states.append(
            _LineAlignmentState(
                line_id=line_id,
                expected_text=expected_text,
                expected_count=len(chars),
            )
        )

    recognized_chars = _scoring_characters(transcript)
    matcher = SequenceMatcher(a=expected_chars, b=recognized_chars, autojunk=False)

    def insertion_line_index(expected_position: int) -> int:
        if expected_position < len(expected_line_indexes):
            return expected_line_indexes[expected_position]
        return expected_line_indexes[-1]

    for tag, expected_start, expected_end, actual_start, actual_end in matcher.get_opcodes():
        if tag == "equal":
            for offset, actual_char in enumerate(recognized_chars[actual_start:actual_end]):
                line_index = expected_line_indexes[expected_start + offset]
                state = line_states[line_index]
                state.recognized.append(actual_char)
                state.matches += 1
            continue

        if tag == "delete":
            for expected_index in range(expected_start, expected_end):
                state = line_states[expected_line_indexes[expected_index]]
                state.omissions.append(expected_chars[expected_index])
            continue

        if tag == "insert":
            state = line_states[insertion_line_index(expected_start)]
            inserted = recognized_chars[actual_start:actual_end]
            state.recognized.extend(inserted)
            state.insertions.extend(inserted)
            continue

        # ``replace`` pairs as many characters as possible, then treats the
        # unequal tail as omissions or insertions.  A substitution is exposed
        # as both the expected omission and recognized insertion, but costs one
        # character in the matches/max-length accuracy calculation below.
        expected_count = expected_end - expected_start
        actual_count = actual_end - actual_start
        paired_count = min(expected_count, actual_count)
        for offset in range(paired_count):
            expected_index = expected_start + offset
            actual_char = recognized_chars[actual_start + offset]
            state = line_states[expected_line_indexes[expected_index]]
            state.recognized.append(actual_char)
            state.omissions.append(expected_chars[expected_index])
            state.insertions.append(actual_char)
        for expected_index in range(expected_start + paired_count, expected_end):
            state = line_states[expected_line_indexes[expected_index]]
            state.omissions.append(expected_chars[expected_index])
        if actual_count > paired_count:
            anchor = min(max(expected_end - 1, 0), len(expected_line_indexes) - 1)
            state = line_states[expected_line_indexes[anchor]]
            inserted = recognized_chars[actual_start + paired_count : actual_end]
            state.recognized.extend(inserted)
            state.insertions.extend(inserted)

    line_results: list[RecitationLineResult] = []
    total_matches = 0
    total_recognized = 0
    for state in line_states:
        recognized = "".join(state.recognized)
        total_matches += state.matches
        total_recognized += len(recognized)
        denominator = max(state.expected_count, len(recognized))
        line_results.append(
            RecitationLineResult(
                line_id=state.line_id,
                expected_text=state.expected_text,
                recognized_text=recognized,
                character_accuracy=round(state.matches / denominator, 4),
                omissions=state.omissions,
                insertions=state.insertions,
            )
        )

    overall_denominator = max(len(expected_chars), total_recognized)
    return RecitationAttempt(
        book_id=book_id,
        block_id=block_id,
        target_line_ids=[line_id for line_id, _ in target_lines],
        transcript=transcript.strip(),
        line_results=line_results,
        overall_accuracy=round(total_matches / overall_denominator, 4),
        data_state="scored",
    )


def stt_failed_attempt(
    *,
    book_id: str,
    block_id: str,
    target_line_ids: Sequence[str],
) -> RecitationAttempt:
    """Return an explicitly unscored attempt after STT is unavailable."""

    return RecitationAttempt(
        book_id=book_id,
        block_id=block_id,
        target_line_ids=list(target_line_ids),
        transcript="",
        line_results=[],
        overall_accuracy=None,
        data_state="stt_failed",
    )


def update_recitation_summary(
    current: object,
    attempt: RecitationAttempt,
) -> RecitationSummary:
    """Build the small, non-audio summary persisted in block metadata."""

    try:
        previous = RecitationSummary.model_validate(current)
    except Exception:
        previous = RecitationSummary()

    latest_accuracy = attempt.overall_accuracy if attempt.data_state == "scored" else None
    best_accuracy = previous.best_accuracy
    if latest_accuracy is not None:
        best_accuracy = (
            latest_accuracy if best_accuracy is None else max(best_accuracy, latest_accuracy)
        )
    return RecitationSummary(
        last_attempt_id=attempt.id,
        attempt_count=previous.attempt_count + 1,
        latest_accuracy=latest_accuracy,
        best_accuracy=best_accuracy,
        data_state=attempt.data_state,
        updated_at=attempt.created_at,
    )


__all__ = [
    "RecitationAttempt",
    "RecitationLineResult",
    "poetry_line_id",
    "resolve_target_lines",
    "score_recitation",
    "stt_failed_attempt",
    "update_recitation_summary",
]
