#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "DeepTutor.env", override=False)
load_dotenv(ROOT / ".env", override=False)

from src.agents.question.agents.generator import Generator
from src.agents.question.agents.validator import Validator
from src.agents.question.models import QAPair, QuestionTemplate


DEEP_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3.5-plus-02-15")
BASELINE_MODEL_CANDIDATES = [
    os.getenv("BASELINE_MODEL", "google/gemini-3-flash-preview"),
    "google/gemini-3-flash-preview",
    "openai/gpt-5-mini",
]

OUT_ROOT = ROOT / "data" / "case_study_question_compare_short"

SPECS = [
    {
        "case_id": "choice_short_search_tradeoff",
        "title": "Short Choice: Search Under Tight Constraints",
        "kb_name": "introduction_to_computer_science_web_19_154",
        "question_type": "choice",
        "difficulty": "hard",
        "concentration": (
            "Compare linear search, sort-plus-binary-search, and hashing under "
            "static data, many queries, no O(N) extra space, and worst-case guarantees."
        ),
        "user_topic": "Generate one short hard CS multiple-choice question on search tradeoffs.",
        "preference": (
            "Keep the prompt short. Include static data, many queries, no O(N) extra "
            "space, and worst-case guarantees. Compare linear search, sort plus "
            "binary search, and hashing. Four options only."
        ),
    },
    {
        "case_id": "written_short_ethics_conflict",
        "title": "Short Written: Ethics Conflict",
        "kb_name": "introduction_to_philosophy_web_cszrkyp_17_148",
        "question_type": "written",
        "difficulty": "hard",
        "concentration": (
            "Write a short but hard ethics question comparing Millian utilitarianism "
            "and Kantian deontology with objection, reply, and final judgment."
        ),
        "user_topic": "Generate one short hard philosophy essay question.",
        "preference": (
            "Keep the scenario short. Compare Mill and Kant. Include lives, trust, "
            "and using people as means. Ask for judgment, objection, reply, and final conclusion."
        ),
    },
    {
        "case_id": "coding_short_binary_range",
        "title": "Short Coding: Binary Search Range",
        "kb_name": "introduction_to_computer_science_web_19_154",
        "question_type": "coding",
        "difficulty": "hard",
        "concentration": (
            "Implement a direct coding task for finding the first and last occurrence "
            "of a target in a sorted array with duplicates using binary search."
        ),
        "user_topic": "Generate one short hard coding question: implement search_range(nums, target).",
        "preference": (
            "Keep the prompt short. This must be a direct implementation task, not "
            "multiple choice, not code selection. The student must implement "
            "`search_range(nums, target)` and return `[first, last]` or `[-1, -1]`. "
            "Require `O(log n)` time, a brief loop-invariant explanation, a complete "
            "reference solution, and executable tests."
        ),
    },
]


def make_tool_flags(spec: dict[str, str]) -> dict[str, bool]:
    if spec["question_type"] == "coding":
        return {"rag_tool": False, "web_search": False, "write_code": True}
    if spec["question_type"] == "written":
        return {"rag_tool": True, "web_search": False, "write_code": False}
    return {"rag_tool": True, "web_search": False, "write_code": False}


def normalize_payload(payload: dict[str, object] | None, template: QuestionTemplate) -> dict[str, object]:
    payload = dict(payload or {})
    payload.setdefault("question_type", template.question_type)
    payload.setdefault("question", "")
    payload.setdefault("correct_answer", "N/A")
    payload.setdefault("explanation", "")
    options = payload.get("options")
    payload["options"] = options if isinstance(options, dict) else None
    return payload


def coding_format_issues(qa_pair: QAPair) -> list[str]:
    if qa_pair.question_type != "coding":
        return []
    issues: list[str] = []
    question = (qa_pair.question or "").lower()
    if qa_pair.options:
        issues.append("coding question should not include answer options")
    markers = [
        "read the following four",
        "choose the unique",
        "choose the correct",
        "four python implementations",
        "candidate programs",
        "multiple-choice",
        "select the correct code",
    ]
    if any(marker in question for marker in markers):
        issues.append("coding question drifted into code-selection format")
    return issues


def apply_format_guard(validation: dict[str, object], qa_pair: QAPair) -> dict[str, object]:
    issues = coding_format_issues(qa_pair)
    if not issues:
        return validation
    guarded = deepcopy(validation)
    guarded["approved"] = False
    guarded["decision"] = "reject"
    guarded["issues"] = list(guarded.get("issues", [])) + issues
    extra = " Format mismatch: " + "; ".join(issues) + "."
    guarded["feedback"] = (str(guarded.get("feedback", "")) + extra).strip()
    return guarded


def build_template(spec: dict[str, str]) -> QuestionTemplate:
    return QuestionTemplate(
        question_id="q_1",
        concentration=spec["concentration"],
        question_type=spec["question_type"],
        difficulty=spec["difficulty"],
        source="custom",
        metadata={
            "case_id": spec["case_id"],
            "case_title": spec["title"],
            "case_prompt": {
                "user_topic": spec["user_topic"],
                "preference": spec["preference"],
            },
        },
    )


async def generate_deeptutor_case(
    spec: dict[str, str],
) -> tuple[QuestionTemplate, QAPair, dict[str, object], list[dict[str, object]], Generator, Validator]:
    template = build_template(spec)
    tool_flags = make_tool_flags(spec)
    generator = Generator(
        kb_name=spec["kb_name"],
        rag_mode="naive",
        language="en",
        tool_flags=tool_flags,
        model=DEEP_MODEL,
    )
    validator = Validator(language="en", tool_flags=tool_flags, model=DEEP_MODEL)

    feedback = ""
    attempts: list[dict[str, object]] = []
    final_qa: QAPair | None = None
    final_validation: dict[str, object] | None = None

    for attempt in range(1, 4):
        qa_pair = await generator.process(
            template=template,
            user_topic=spec["user_topic"],
            preference=spec["preference"],
            validator_feedback=feedback,
        )
        validation = await validator.process(template=template, qa_pair=qa_pair)
        validation = apply_format_guard(validation, qa_pair)
        attempts.append(
            {
                "attempt": attempt,
                "qa_pair": qa_pair.__dict__,
                "validation": validation,
            }
        )
        final_qa = qa_pair
        final_validation = validation
        if validation.get("approved"):
            break
        feedback = str(validation.get("feedback", ""))

    assert final_qa is not None
    assert final_validation is not None
    final_qa.validation = final_validation
    return template, final_qa, final_validation, attempts, generator, validator


async def generate_baseline_case(
    spec: dict[str, str],
    template: QuestionTemplate,
    deeptutor_qa: QAPair,
    validator: Validator,
    generator: Generator,
) -> tuple[QAPair, dict[str, object]]:
    prompt_trace = (
        deeptutor_qa.metadata.get("prompt_trace", {}).get("generation_prompt", {})
    )
    system_prompt = str(prompt_trace.get("system_prompt", ""))
    user_prompt = str(prompt_trace.get("user_prompt", ""))

    last_error: Exception | None = None
    raw_response = ""
    used_model = ""
    seen_models: set[str] = set()
    for model_name in BASELINE_MODEL_CANDIDATES:
        if not model_name or model_name in seen_models:
            continue
        seen_models.add(model_name)
        try:
            raw_response = await generator.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
                temperature=0.2,
                model=model_name,
                stage=f"baseline_{spec['case_id']}",
            )
            used_model = model_name
            break
        except Exception as exc:
            last_error = exc
            try:
                raw_response = await generator.call_llm(
                    user_prompt=user_prompt,
                    system_prompt=system_prompt,
                    temperature=0.2,
                    model=model_name,
                    stage=f"baseline_{spec['case_id']}_fallback",
                )
                used_model = model_name
                break
            except Exception as fallback_exc:
                last_error = fallback_exc
                continue
    if not raw_response:
        raise RuntimeError(f"All baseline models failed: {last_error}")

    payload = normalize_payload(generator._parse_json_like(raw_response), template)
    qa_pair = QAPair(
        question_id=template.question_id,
        question=str(payload.get("question", "")),
        correct_answer=str(payload.get("correct_answer", "")),
        explanation=str(payload.get("explanation", "")),
        question_type=str(payload.get("question_type", template.question_type)),
        options=payload.get("options"),
        concentration=template.concentration,
        difficulty=template.difficulty,
        metadata={
            "source": "baseline_same_prompt",
            "model": used_model,
            "prompt_trace": {"generation_prompt": prompt_trace},
            "raw_response": raw_response,
            "verification_code": payload.get("verification_code", ""),
        },
    )
    validation = await validator.process(template=template, qa_pair=qa_pair)
    validation = apply_format_guard(validation, qa_pair)
    qa_pair.validation = validation
    return qa_pair, validation


def verdict_for(
    deep_validation: dict[str, object],
    baseline_validation: dict[str, object],
) -> str:
    deep_ok = bool(deep_validation.get("approved"))
    base_ok = bool(baseline_validation.get("approved"))
    if deep_ok and not base_ok:
        return "deeptutor_better"
    if base_ok and not deep_ok:
        return "baseline_better"
    if deep_ok and base_ok:
        return "tie_both_approved"
    return "tie_both_rejected"


async def main() -> None:
    batch_dir = OUT_ROOT / f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    case_ids_raw = os.getenv("CASE_IDS", "").strip()
    selected_case_ids = {
        item.strip() for item in case_ids_raw.split(",") if item.strip()
    }
    selected_specs = [
        spec for spec in SPECS if not selected_case_ids or spec["case_id"] in selected_case_ids
    ]

    summary: dict[str, object] = {
        "batch_dir": str(batch_dir),
        "deep_model": DEEP_MODEL,
        "baseline_models": BASELINE_MODEL_CANDIDATES,
        "selected_case_ids": sorted(selected_case_ids),
        "cases": [],
    }

    for spec in selected_specs:
        case_dir = batch_dir / spec["case_id"]
        case_dir.mkdir(parents=True, exist_ok=True)

        template, deep_qa, deep_validation, deep_attempts, generator, validator = await generate_deeptutor_case(spec)
        baseline_qa, baseline_validation = await generate_baseline_case(
            spec, template, deep_qa, validator, generator
        )

        result = {
            "case_id": spec["case_id"],
            "title": spec["title"],
            "kb_name": spec["kb_name"],
            "template": template.__dict__,
            "case_prompt": {
                "user_topic": spec["user_topic"],
                "preference": spec["preference"],
            },
            "deeptutor": {
                "qa_pair": deep_qa.__dict__,
                "validation": deep_validation,
                "attempts": deep_attempts,
                "question_preview": {
                    "question": deep_qa.question,
                    "question_type": deep_qa.question_type,
                    "options": deep_qa.options,
                    "correct_answer": deep_qa.correct_answer,
                    "explanation": deep_qa.explanation,
                },
            },
            "baseline": {
                "qa_pair": baseline_qa.__dict__,
                "validation": baseline_validation,
                "question_preview": {
                    "question": baseline_qa.question,
                    "question_type": baseline_qa.question_type,
                    "options": baseline_qa.options,
                    "correct_answer": baseline_qa.correct_answer,
                    "explanation": baseline_qa.explanation,
                },
            },
            "comparison": {
                "same_prompt": True,
                "verdict": verdict_for(deep_validation, baseline_validation),
                "deeptutor_approved": bool(deep_validation.get("approved")),
                "baseline_approved": bool(baseline_validation.get("approved")),
            },
        }

        (case_dir / "result.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        summary["cases"].append(
            {
                "case_id": spec["case_id"],
                "title": spec["title"],
                "result_file": str(case_dir / "result.json"),
                "verdict": result["comparison"]["verdict"],
                "deeptutor_approved": result["comparison"]["deeptutor_approved"],
                "baseline_approved": result["comparison"]["baseline_approved"],
            }
        )
        print(f"{spec['case_id']}: {result['comparison']['verdict']}", flush=True)

    (batch_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"BATCH_DIR={batch_dir}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
