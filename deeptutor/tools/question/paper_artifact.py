"""Immutable, traceable question-paper artifacts.

The extractor emits a deliberately loose JSON payload.  This module is the
single adapter that validates that payload, reuses the canonical
``ParsedQuestion`` identity, and keeps paper-only metadata (original number,
images and knowledge-point labels) beside it without changing the agent model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
from typing import Any

from deeptutor.agents.question.parsed_question import ParsedQuestion

_VALID_DIFFICULTIES = {"easy", "medium", "hard"}
_VALID_QUESTION_TYPES = {
    "choice",
    "concept",
    "fill_in_blank",
    "short_answer",
    "written",
    "coding",
}


class PaperArtifactError(ValueError):
    """Raised when an extractor artifact is missing or cannot be trusted."""


@dataclass(frozen=True, slots=True)
class PaperQuestionArtifact:
    """One canonical source question plus immutable paper metadata."""

    parsed_question: ParsedQuestion
    original_number: str
    images: tuple[str, ...] = ()
    knowledge_point_ids: tuple[str, ...] = ()

    @property
    def stable_id(self) -> str:
        return self.parsed_question.stable_id


@dataclass(frozen=True, slots=True)
class PaperArtifact:
    """Validated input consumed by the deterministic paper reorderer."""

    source_id: str
    source_paper: str
    questions: tuple[PaperQuestionArtifact, ...]
    missing_image_refs: tuple[str, ...] = ()


def _clean_enum(raw: object, valid: set[str], default: str) -> str:
    value = str(raw or "").strip().lower()
    return value if value in valid else default


def _clean_string_list(raw: object, *, field_name: str, index: int) -> tuple[str, ...]:
    if raw in (None, ""):
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise PaperArtifactError(f"Question {index} field {field_name!r} must be a list")

    values: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value and value not in values:
            values.append(value)
    return tuple(values)


def paper_artifact_from_extractor_json(
    payload: Mapping[str, Any],
    *,
    source_id: str,
    source_paper: str = "",
) -> PaperArtifact:
    """Normalize extractor JSON into canonical ``ParsedQuestion`` records.

    Invalid entries fail the whole artifact instead of being silently dropped:
    conservation cannot be proven if the adapter quietly loses source rows.
    """
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise PaperArtifactError("Extractor artifact must contain a non-empty questions list")
    declared_count = payload.get("total_questions")
    if declared_count is not None:
        try:
            count_matches = int(declared_count) == len(raw_questions)
        except (TypeError, ValueError):
            count_matches = False
        if not count_matches:
            raise PaperArtifactError("Extractor total_questions does not match the question list")

    resolved_source = source_paper or str(payload.get("paper_name") or source_id)
    questions: list[PaperQuestionArtifact] = []
    for index, item in enumerate(raw_questions, 1):
        if not isinstance(item, Mapping):
            raise PaperArtifactError(f"Question {index} must be an object")

        question_text = str(item.get("question_text") or "").strip()
        if not question_text:
            raise PaperArtifactError(f"Question {index} has no question_text")

        raw_options = item.get("options")
        if raw_options is not None and not isinstance(raw_options, Mapping):
            raise PaperArtifactError(f"Question {index} field 'options' must be an object")
        options = (
            {str(key): str(value) for key, value in raw_options.items()}
            if isinstance(raw_options, Mapping)
            else None
        )

        images = _clean_string_list(item.get("images"), field_name="images", index=index)
        for image in images:
            path = PurePosixPath(image.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise PaperArtifactError(
                    f"Question {index} contains an unsafe image reference: {image}"
                )

        knowledge_point_ids = _clean_string_list(
            item.get("knowledge_point_ids") or item.get("knowledge_points"),
            field_name="knowledge_point_ids",
            index=index,
        )
        parsed = ParsedQuestion(
            question_text=question_text,
            question_type=_clean_enum(item.get("question_type"), _VALID_QUESTION_TYPES, "written"),
            difficulty=_clean_enum(item.get("difficulty"), _VALID_DIFFICULTIES, "medium"),
            answer=str(item.get("answer") or "").strip() or None,
            options=options,
            source_paper=resolved_source,
            original_index=index,
        )
        questions.append(
            PaperQuestionArtifact(
                parsed_question=parsed,
                original_number=str(item.get("question_number") or index).strip(),
                images=images,
                knowledge_point_ids=knowledge_point_ids,
            )
        )

    return PaperArtifact(
        source_id=source_id,
        source_paper=resolved_source,
        questions=tuple(questions),
    )


def resolve_question_source(question_root: Path, source_id: str) -> Path:
    """Resolve a user-scoped source id to exactly one extractor JSON file."""
    normalized = source_id.strip()
    if not normalized:
        raise PaperArtifactError("source_id is required")

    relative = Path(normalized)
    if relative.is_absolute():
        raise PaperArtifactError("source_id must be relative to the question workspace")

    root = question_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PaperArtifactError("source_id escapes the question workspace") from exc

    if candidate.is_dir():
        matches = sorted(candidate.glob("*_questions.json"))
        if len(matches) != 1:
            raise PaperArtifactError(
                f"source_id directory must contain exactly one *_questions.json file; found {len(matches)}"
            )
        return matches[0]
    if not candidate.is_file() or not candidate.name.endswith("_questions.json"):
        raise PaperArtifactError("source_id must identify an existing *_questions.json file")
    return candidate


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _image_exists(image_ref: str, roots: Sequence[Path]) -> bool:
    relative = Path(image_ref.replace("\\", "/"))
    for root in roots:
        direct = (root / relative).resolve()
        if _is_within(direct, root) and direct.is_file():
            return True
        # Older nested MinerU outputs place ``images/`` below auto/hybrid_auto
        # while the extractor JSON lives at the paper root.
        for match in root.rglob(relative.name):
            if match.is_file() and (
                len(relative.parts) == 1
                or tuple(match.parts[-len(relative.parts) :]) == relative.parts
            ):
                return True
    return False


def load_paper_artifact(
    question_file: Path,
    *,
    source_id: str,
    allowed_image_root: Path | None = None,
) -> PaperArtifact:
    """Load an extractor file and record any image references that disappeared."""
    try:
        with question_file.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise PaperArtifactError(f"Unable to read extractor artifact: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PaperArtifactError("Extractor artifact root must be an object")

    artifact = paper_artifact_from_extractor_json(
        payload,
        source_id=source_id,
        source_paper=str(payload.get("paper_name") or question_file),
    )

    image_roots = [question_file.parent]
    declared_images_dir = payload.get("images_dir")
    if declared_images_dir:
        declared = Path(str(declared_images_dir)).resolve()
        if allowed_image_root is None or _is_within(declared, allowed_image_root):
            image_roots.insert(0, declared)

    missing = tuple(
        f"{question.stable_id}:{image_ref}"
        for question in artifact.questions
        for image_ref in question.images
        if not _image_exists(image_ref, image_roots)
    )
    return PaperArtifact(
        source_id=artifact.source_id,
        source_paper=artifact.source_paper,
        questions=artifact.questions,
        missing_image_refs=missing,
    )


__all__ = [
    "PaperArtifact",
    "PaperArtifactError",
    "PaperQuestionArtifact",
    "load_paper_artifact",
    "paper_artifact_from_extractor_json",
    "resolve_question_source",
]
