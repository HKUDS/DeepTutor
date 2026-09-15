"""Best-effort learning-data readers for the YuEdu error-loop blocks.

``error_diagnosis`` / ``retrieval_practice`` / ``module_test`` draw on two
per-learner stores:

* KP-bound question banks — ``kp.meta["question_bank"]``, written by the
  ``mastery_path`` router (``set_kp_question_bank``) and the textbook ingest
  pipeline (``learning/ingest_pipeline._stage_qb_mounted``). Read through
  ``LearningStore``.
* Wrong-answer evidence — the append-only rows of
  ``deeptutor.learning.evidence_store.EvidenceStore``.

Both reads are fail-open: compiling a book must never break because the
learner has no mastery path / evidence yet, or because the workspace is
read-only. Any failure yields an empty result and a debug log; the
generators decide what "no data" means (skip, or fall back to the LLM).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: ``ErrorType`` values (learning/models.py) → learner-facing label per language.
_ERROR_TYPE_LABELS: dict[str, dict[str, str]] = {
    "structural": {"zh": "知识结构没搭起来", "en": "shaky knowledge structure"},
    "deviation": {"zh": "理解有偏差", "en": "misunderstanding"},
    "application": {"zh": "会知识但用错", "en": "knows it, misapplies it"},
    "metacognitive": {"zh": "审题/检查出了问题", "en": "rushed reading or checking"},
}

_ERROR_TYPE_DEFAULTS: dict[str, str] = {"zh": "未标注", "en": "unlabelled"}


def error_type_label(error_type: str, language: str) -> str:
    """Learner-facing label for one recorded ``error_type`` (fail-open)."""
    key = str(error_type or "").strip().lower()
    table = _ERROR_TYPE_LABELS.get(key) or {}
    return table.get(language) or _ERROR_TYPE_DEFAULTS.get(language, _ERROR_TYPE_DEFAULTS["en"])


def clean_bank_item(item: Any) -> dict[str, Any] | None:
    """Normalise one ``kp.meta["question_bank"]`` entry, or drop it.

    Mirrors the strictness ``mastery_quiz`` applies in
    ``deeptutor/capabilities/mastery/tools.py``: a choice item must carry an
    answer, otherwise the learner would be graded against nothing.
    """
    if not isinstance(item, dict):
        return None
    question = str(item.get("question") or "").strip()
    if not question:
        return None
    question_type = str(item.get("question_type") or "choice").strip() or "choice"
    answer = str(item.get("answer") or "").strip()
    if question_type == "choice" and not answer:
        return None
    raw_options = item.get("options")
    options = (
        {str(k): str(v) for k, v in raw_options.items() if str(v).strip()}
        if isinstance(raw_options, dict)
        else {}
    )
    return {
        "question": question[:2000],
        "question_type": question_type,
        "options": options,
        "answer": answer[:500],
        "explanation": str(item.get("explanation") or "").strip()[:2000],
        "difficulty": str(item.get("difficulty") or "").strip()[:16],
        "source": "bank",
    }


def load_kp_question_banks(book_id: str) -> list[dict[str, Any]]:
    """Flatten the KP-bound question banks of *book_id*.

    Returns one entry per knowledge point that carries a non-empty bank:
    ``{"kp_id", "kp_name", "module_id", "module_name", "items"}``. Items are
    already cleaned (see :func:`clean_bank_item`).
    """
    if not book_id:
        return []
    try:
        from deeptutor.learning.storage import LearningStore

        progress = LearningStore().load(book_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"question-bank lookup skipped for {book_id}: {exc}")
        return []
    if progress is None:
        return []

    entries: list[dict[str, Any]] = []
    for module in progress.modules or []:
        for kp in module.knowledge_points or []:
            bank = (kp.meta or {}).get("question_bank") or []
            items = [clean for clean in (clean_bank_item(item) for item in bank) if clean]
            if items:
                entries.append(
                    {
                        "kp_id": kp.id,
                        "kp_name": kp.name,
                        "module_id": module.id,
                        "module_name": module.name,
                        "items": items,
                    }
                )
    return entries


def load_kp_names(book_id: str) -> dict[str, str]:
    """``kp_id → kp_name`` map for *book_id* (fail-open, may be empty)."""
    if not book_id:
        return {}
    try:
        from deeptutor.learning.storage import LearningStore

        progress = LearningStore().load(book_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"kp-name lookup skipped for {book_id}: {exc}")
        return {}
    if progress is None:
        return {}
    return {
        kp.id: kp.name
        for module in progress.modules or []
        for kp in module.knowledge_points or []
        if kp.id
    }


def load_error_evidence(book_id: str) -> list[Any]:
    """Wrong-answer evidence rows for *book_id*, newest first.

    A row counts as an error when the graded quiz was answered incorrectly
    (``is_correct is False``) or a qualitative gate failed (``passed is
    False``). Ungraded rows (both ``None``) are not errors.
    """
    if not book_id:
        return []
    try:
        from deeptutor.learning.evidence_store import EvidenceStore

        rows = EvidenceStore().query_evidence(book_id=book_id, limit=200)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"error-evidence lookup skipped for {book_id}: {exc}")
        return []
    return [
        row
        for row in rows
        if (row.is_correct is False)
        or (row.evidence_type == "qualitative_gate" and row.passed is False)
    ]


def pick_bank_items(
    entries: list[dict[str, Any]],
    count: int,
    *,
    module_id: str | None = None,
) -> list[dict[str, Any]]:
    """Take *count* bank questions, spread across knowledge points.

    Round-robin so a single deep KP cannot crowd the others out. When
    *module_id* is given, only that module's KPs contribute.
    """
    selected: list[dict[str, Any]] = []
    pools = [
        entry
        for entry in entries
        if (module_id is None or entry.get("module_id") == module_id) and entry.get("items")
    ]
    if not pools:
        return selected

    cursors = [0] * len(pools)
    while len(selected) < count:
        progressed = False
        for index, pool in enumerate(pools):
            if len(selected) >= count:
                break
            items = pool["items"]
            if cursors[index] >= len(items):
                continue
            item = {
                **items[cursors[index]],
                "kp_id": pool.get("kp_id", ""),
                "kp_name": pool.get("kp_name", ""),
            }
            cursors[index] += 1
            selected.append(item)
            progressed = True
        if not progressed:
            break
    return selected


__all__ = [
    "clean_bank_item",
    "error_type_label",
    "load_error_evidence",
    "load_kp_names",
    "load_kp_question_banks",
    "pick_bank_items",
]
