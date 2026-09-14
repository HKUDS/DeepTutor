"""Error-diagnosis block — YuEdu error loop (错题诊断).

Reads the learner's *real* wrong-answer evidence from the append-only
``EvidenceStore`` and turns it into a diagnosis card. This block never
invents errors: with no recorded evidence for the book it skips silently
(:class:`BlockSkipped`) — the block is pruned from the page entirely, so
the learner sees neither an empty card nor an ERROR card.

The only LLM-written part is the coaching text around the real numbers;
the numbers themselves always come from the store. When the model
contributes, the payload is marked ``generated: true``.

Prompts live in ``deeptutor/book/prompts/{en,zh}/error_diagnosis.yaml``.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..models import BlockType, SourceAnchor
from ._learning_data import error_type_label, load_error_evidence, load_kp_names
from ._llm_writer import llm_json
from ._prompts import get_book_prompt, load_book_prompts
from .base import BlockContext, BlockGenerator, BlockSkipped

_MAX_DIAGNOSES = 6
_MAX_QUESTION_IDS_PER_KPS = 6


class ErrorDiagnosisGenerator(BlockGenerator):
    block_type = BlockType.ERROR_DIAGNOSIS

    async def _generate(
        self, ctx: BlockContext
    ) -> tuple[dict[str, Any], list[SourceAnchor], dict[str, Any]]:
        # D4 hard rule: only real error data may appear here. `ctx.extra` is
        # the injection point (same pattern as the concept_graph block); the
        # store read is the fail-open fallback.
        errors = ctx.extra.get("error_evidence") or load_error_evidence(ctx.book_id)
        if not errors:
            raise BlockSkipped(
                "No real error data recorded for this book; skipping error_diagnosis."
            )

        kp_names = load_kp_names(ctx.book_id)
        diagnoses = _aggregate(errors, kp_names, ctx.language)

        payload: dict[str, Any] = {
            "diagnoses": diagnoses,
            "total_errors": len(errors),
        }

        # The coaching text is best-effort: a provider hiccup must not throw
        # away the real diagnosis the store already gave us.
        guidance, advice_by_kp = await self._llm_coaching(ctx, diagnoses)
        if guidance or advice_by_kp:
            payload["generated"] = True
        if guidance:
            payload["guidance"] = guidance
        if advice_by_kp:
            for diagnosis in payload["diagnoses"]:
                advice = advice_by_kp.get(str(diagnosis.get("kp_name", "")).strip())
                if advice:
                    diagnosis["advice"] = advice

        return payload, [], {}

    async def _llm_coaching(
        self, ctx: BlockContext, diagnoses: list[dict[str, Any]]
    ) -> tuple[str, dict[str, str]]:
        prompts = load_book_prompts("error_diagnosis", ctx.language)
        lines = [
            f"- {d.get('kp_name')}: {d.get('error_label')} ×{d.get('count')}"
            for d in diagnoses
        ]
        user_prompt = get_book_prompt(prompts, "user_template").format(
            error_summary="\n".join(lines),
            total_errors=len(diagnoses),
        )
        try:
            data = await llm_json(
                user_prompt=user_prompt,
                system_prompt=get_book_prompt(prompts, "system"),
                max_tokens=600,
                temperature=0.4,
                language=ctx.language,
                expected_key="guidance",
            )
        except Exception:  # noqa: BLE001 — real numbers survive without the coach
            return "", {}
        if not isinstance(data, dict):
            return "", {}
        guidance = str(data.get("guidance") or "").strip()
        focus = data.get("focus")
        advice_by_kp: dict[str, str] = {}
        if isinstance(focus, list):
            for entry in focus:
                if not isinstance(entry, dict):
                    continue
                kp_name = str(entry.get("kp_name") or "").strip()
                advice = str(entry.get("advice") or "").strip()[:600]
                if kp_name and advice:
                    advice_by_kp[kp_name] = advice
        return guidance, advice_by_kp


def _aggregate(
    errors: list[Any], kp_names: dict[str, str], language: str
) -> list[dict[str, Any]]:
    """Group the raw evidence rows by (kp, error_type), hottest first."""
    grouped: Counter[tuple[str, str]] = Counter()
    question_ids: dict[tuple[str, str], list[str]] = {}
    for row in errors:
        kp_id = str(getattr(row, "kp_id", "") or "")
        error_type = str(getattr(row, "error_type", "") or "").strip().lower()
        key = (kp_id, error_type)
        grouped[key] += 1
        question_id = str(getattr(row, "question_id", "") or "")
        if question_id:
            bucket = question_ids.setdefault(key, [])
            if question_id not in bucket and len(bucket) < _MAX_QUESTION_IDS_PER_KPS:
                bucket.append(question_id)

    diagnoses: list[dict[str, Any]] = []
    for (kp_id, error_type), count in grouped.most_common(_MAX_DIAGNOSES):
        diagnoses.append(
            {
                "kp_id": kp_id,
                "kp_name": kp_names.get(kp_id, kp_id) if kp_id else "",
                "error_type": error_type,
                "error_label": error_type_label(error_type, language),
                "count": count,
                "question_ids": question_ids.get((kp_id, error_type), []),
            }
        )
    return diagnoses


__all__ = ["ErrorDiagnosisGenerator"]
