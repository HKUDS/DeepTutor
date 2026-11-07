from __future__ import annotations

import logging

logger = logging.getLogger("iso_solve.judge")

JUDGE_SYSTEM = (
    "You are a rigorous answer grader. "
    "Given a problem, a predicted answer, and a ground-truth answer, "
    "determine whether they are equivalent.\n\n"
    "Ignore superficial formatting differences.\n"
    "Output exactly one word: CORRECT or INCORRECT."
)

JUDGE_USER = """\
## Problem
{question}

## Ground-Truth Answer
{ground_truth}

## Predicted Answer
{predicted}

{judge_hint}

Verdict:"""


def _fallback_compare(predicted: str | None, ground_truth: str) -> bool:
    if predicted is None:
        return False
    return predicted.strip().lower() == ground_truth.strip().lower()


async def judge_answer(
    question: str,
    predicted: str | None,
    ground_truth: str,
    judge_hint: str = "",
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 32,
    temperature: float | None = None,
) -> tuple[bool, str]:
    if predicted is None:
        return False, "No extracted answer"

    from src.services.llm import complete

    prompt = JUDGE_USER.format(
        question=question,
        predicted=predicted,
        ground_truth=ground_truth,
        judge_hint=judge_hint or "",
    )
    kwargs = {
        "prompt": prompt,
        "system_prompt": JUDGE_SYSTEM,
        "temperature": temperature if temperature is not None else 0.0,
        "max_tokens": max_tokens,
    }
    if model:
        kwargs["model"] = model
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    try:
        response = await complete(**kwargs)
        verdict = response.strip().upper()
        if "CORRECT" in verdict and "INCORRECT" not in verdict:
            return True, verdict
        if "INCORRECT" in verdict:
            return False, verdict
        fallback = _fallback_compare(predicted, ground_truth)
        return fallback, f"Ambiguous verdict: {verdict}"
    except Exception as exc:
        logger.warning("LLM judge failed: %s", exc)
        fallback = _fallback_compare(predicted, ground_truth)
        return fallback, f"Judge failed: {exc}"
