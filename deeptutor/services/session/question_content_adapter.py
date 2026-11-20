"""Keep canonical question content in step with the notebook's flat fields.

The flat columns remain authoritative: every existing consumer (quiz viewer,
practice queue, mastery analytics, exports) reads them, and two different
vocabularies already ship to different surfaces. Canonical content is a
derived projection that QTI exchange reads, never a second source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from deeptutor.services.practice.fill_blanks import legacy_single_blank_spec
from deeptutor.services.question_content import (
    normalize_question_document,
    project_legacy_question,
)

_FIELDS = ("question", "question_type", "options", "correct_answer", "explanation", "difficulty")

_QUIZ_TYPES = frozenset(
    {"multiple_choice", "choice", "concept", "fill_in_blank", "coding", "short_answer", "written"}
)

_MARKER = re.compile(r"\{\{blank:[^}]+\}\}")
_LEGACY_BLANK = "____"


def _format(item: Mapping[str, Any]) -> str:
    # Deep-question rows keep the historical quiz enum; bank imports and QTI
    # imports use the distinct bank-v1 enum. Matching on the source row keeps
    # ``choice`` from being read as ``single_choice`` and vice versa.
    if (item.get("source") or "deep_question") == "deep_question" and item.get(
        "question_type"
    ) in _QUIZ_TYPES:
        return "quiz-v1"
    return "bank-v1"


def _canonical_input(item: Mapping[str, Any]) -> dict[str, Any]:
    """Translate the chat blank token into the canonical marker form.

    ``deep_question`` emits a single ``____`` token while the canonical model
    addresses every blank by id. Rewriting here keeps the stored question text
    untouched and gives QTI a marker it can place a text-entry interaction on.
    """
    if _format(item) != "quiz-v1" or item.get("question_type") != "fill_in_blank":
        return dict(item)
    question = str(item.get("question") or "")
    if "{{blank:" in question or question.count(_LEGACY_BLANK) != 1:
        return dict(item)
    spec = item.get("fill_spec") or legacy_single_blank_spec(
        "fill_blank", str(item.get("correct_answer") or "")
    )
    if not spec:
        return dict(item)
    return {
        **item,
        "question": question.replace(_LEGACY_BLANK, f"{{{{blank:{spec['blanks'][0]['id']}}}}}", 1),
        "fill_spec": spec,
    }


def _flat_question(value: str) -> str:
    return _MARKER.sub(_LEGACY_BLANK, value)


def _same_flat_fields(existing: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    for key in _FIELDS:
        default = {} if key == "options" else ""
        if existing.get(key, default) != item.get(key, default):
            return False
    return True


def _matches(document: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    if document.get("itemId") != item.get("question_id"):
        return False
    subject = document.get("subject") or {}
    if "tags" in item and subject.get("tags") != item["tags"]:
        return False
    if "topic" in item and subject.get("topic") != item["topic"]:
        return False

    target = _format(item)
    trusted_import_sidecar = item.get("source") == "import" and str(
        item.get("material_id") or ""
    ).startswith(("import:", "qti3:"))
    try:
        projected = project_legacy_question(
            document, target_format=target, allow_asset_sidecar=trusted_import_sidecar
        )
    except ValueError:
        return False
    for key in _FIELDS:
        default = {} if key == "options" else ""
        projected_value = projected.get(key, default)
        source_value = item.get(key, default)
        if key == "options" and target == "quiz-v1":
            projected_value = projected_value or {}
            source_value = source_value or {}
        if (
            key == "correct_answer"
            and not projected_value
            and (document.get("author") or {}).get("fillSpec") is not None
        ):
            # A fill item's canonical answer lives in fillSpec; the flat column
            # may carry a readable reference answer derived from it.
            continue
        if (
            key == "question"
            and target == "quiz-v1"
            and item.get("question_type") == "fill_in_blank"
        ):
            projected_value = _flat_question(projected_value)
        if projected_value != source_value:
            return False

    expected_spec = item.get("fill_spec")
    if expected_spec is None and item.get("question_type") in {"fill_blank", "fill_in_blank"}:
        answer = item.get("correct_answer") or ""
        if answer:
            expected_spec = legacy_single_blank_spec("fill_blank", answer)
    return projected.get("fill_spec") == expected_spec


def resolved_fill_spec(item: Mapping[str, Any], existing: Mapping[str, Any] | None) -> Any:
    """Return the fill spec an upsert should persist.

    An explicit ``fill_spec`` always wins. Otherwise a spec is retained only
    while the authored fields still describe the same item; regeneration with
    a new answer rebuilds it from the flat answer instead of failing the write,
    because the chat quiz path never sends a spec of its own.
    """
    if "fill_spec" in item:
        return item["fill_spec"]
    if existing is None or existing.get("fill_spec") is None:
        return None
    if not _same_flat_fields(existing, item):
        return None
    if "shared_context" in item:
        previous = "".join(
            part["text"]
            for material in (existing.get("question_content") or {}).get("materials", [])
            if material.get("role") == "shared_context"
            for part in material.get("body", [])
            if part.get("kind") == "text"
        )
        if (item["shared_context"] or "") != previous:
            return None
    return existing["fill_spec"]


def content_for_write(
    item: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return validated canonical content for an atomic notebook write.

    Callers may supply ``question_content`` explicitly; otherwise a semantic
    edit rebuilds it from the flat fields so an older canonical answer can
    never shadow the row's current grading authority.
    """
    supplied = item.get("question_content")
    if supplied is not None:
        document = normalize_question_document(supplied, source_format="content-v1")
        if not _matches(document, item):
            raise ValueError("Canonical and notebook question fields conflict")
        return document

    if existing and existing.get("question_content") and _same_flat_fields(existing, item):
        if existing.get("fill_spec") == item.get("fill_spec"):
            return existing["question_content"]

    try:
        return normalize_question_document(
            _canonical_input(item),
            source_format=_format(item),
            question_id=item.get("question_id"),
        )
    except ValueError:
        # Some historical notebook kinds have no supported bank projection.
        # They stay readable through the flat fields instead of failing writes.
        return None


def content_for_read(
    stored: dict[str, Any] | None,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the stored document only when it still describes this row."""
    if stored is not None:
        try:
            document = normalize_question_document(stored, source_format="content-v1")
            if _matches(document, item):
                return document
        except ValueError:
            pass
    try:
        return normalize_question_document(
            _canonical_input(item),
            source_format=_format(item),
            question_id=item.get("question_id"),
        )
    except ValueError:
        return None


__all__ = ["content_for_read", "content_for_write", "resolved_fill_spec"]
