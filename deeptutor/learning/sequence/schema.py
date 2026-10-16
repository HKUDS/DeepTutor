"""Validate a model-written solution sequence and hide its answer key."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

GOAL = 5
_MIN_CORRECT = 3
_MAX_CORRECT = 5
_DISTRACTORS = 3


class SequenceError(Exception):
    """A request the learner can be told about, with an HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class _StepIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    explanation: str = Field(min_length=8, max_length=400)
    math: str = Field(min_length=1, max_length=500)
    evidence: str = Field(default="", max_length=500)


class _ProblemIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    question: str = Field(min_length=12, max_length=1200)
    explanation: str = Field(min_length=20, max_length=2000)
    formulas: list[str] = Field(default_factory=list, max_length=8)
    correct_steps: list[_StepIn] = Field(min_length=_MIN_CORRECT, max_length=_MAX_CORRECT)
    distractor_steps: list[_StepIn] = Field(min_length=_DISTRACTORS, max_length=_DISTRACTORS)

    def model_post_init(self, _context: Any) -> None:
        formulas = [item.strip() for item in self.formulas if item.strip()]
        if any(len(item) > 300 for item in formulas):
            raise ValueError("A formula is too long.")
        object.__setattr__(self, "formulas", formulas[:8])


def evidence_key(value: str) -> str:
    return " ".join(value.casefold().split())


def _unique_math(steps: list[_StepIn], label: str) -> None:
    seen: set[str] = set()
    for step in steps:
        key = evidence_key(step.math)
        if key in seen:
            raise ValueError(f"{label} steps repeat the same mathematics.")
        seen.add(key)


def parse_problem(data: Any, corpus: str) -> _ProblemIn:
    """Accept one grounded problem, or raise ``SequenceError``."""
    if not isinstance(data, dict) or not data:
        raise SequenceError(422, "The model did not return a problem.")
    if data.get("unsupported") is True:
        reason = data.get("reason")
        detail = reason.strip() if isinstance(reason, str) else ""
        message = detail or "That material does not contain a worked solution for this topic."
        raise SequenceError(422, message[:300])
    try:
        problem = _ProblemIn.model_validate(data)
    except ValidationError as exc:
        raise SequenceError(422, "The model returned a problem in the wrong shape.") from exc
    except ValueError as exc:
        raise SequenceError(422, str(exc)) from exc

    _unique_math(problem.correct_steps, "Correct")
    _unique_math(problem.distractor_steps, "Distractor")
    correct_math = {evidence_key(step.math) for step in problem.correct_steps}
    if any(evidence_key(step.math) in correct_math for step in problem.distractor_steps):
        raise SequenceError(422, "A mistake step copies a correct step.")

    corpus_key = evidence_key(corpus)
    if not corpus_key:
        raise SequenceError(422, "Nothing was retrieved to ground this problem.")
    for step in problem.correct_steps:
        quote = evidence_key(step.evidence)
        if len(quote) < 8 or quote not in corpus_key:
            raise SequenceError(
                422,
                "A correct step is not supported by the retrieved material.",
            )
    return problem


def public_problem(record: dict[str, Any]) -> dict[str, Any]:
    """Learner-facing problem. No roles, no evidence, no answer order."""
    solved = bool(record.get("solved"))
    steps = []
    for step in record.get("steps") or []:
        steps.append(
            {
                "id": step["id"],
                "explanation": step["explanation"],
                "math": step["math"],
            }
        )
    return {
        "problem_id": record["id"],
        "question": record["question"],
        "formulas": list(record.get("formulas") or []),
        "steps": steps,
        "placed_ids": list(record.get("placed_ids") or []),
        "solved": solved,
        "explanation": record["explanation"] if solved else None,
        "progress": {
            "solved": int(record.get("progress_solved") or 0),
            "goal": GOAL,
        },
        "sources": list(record.get("sources") or []),
    }
