from __future__ import annotations

import re
from typing import Any

from .base import BenchmarkAdapter, apply_limit
from benchmark.iso_solve.core.types import Problem

CHOICE_LABELS = list("ABCDEFGHIJ")

SUPER_GPQA_SYSTEM_PROMPT = (
    "You are an expert answering a graduate-level multiple-choice question. "
    "Think step-by-step, then finish your response with the line:\n"
    "Answer: X\n"
    "where X is exactly one of the option letters (e.g. A, B, C, D, ...)."
)


class SuperGPQAAdapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "super_gpqa"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["discipline", "field", "difficulty"]

    @property
    def extract_hint(self) -> str:
        return "The final answer must be exactly one option letter such as A, B, C, D, etc."

    @property
    def judge_hint(self) -> str:
        return "This is a multiple-choice question. Compare only the final letter answer."

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        import polars as pl

        dataset_url = bench_cfg.get(
            "dataset_url",
            "hf://datasets/m-a-p/SuperGPQA/SuperGPQA-all.jsonl",
        )
        df = pl.read_ndjson(dataset_url)

        problems: list[Problem] = []
        for row in df.iter_rows(named=True):
            options: list[str] = row["options"]
            formatted = "\n".join(
                f"{CHOICE_LABELS[i]}. {opt}" for i, opt in enumerate(options)
            )
            q = f"{row['question']}\n\n{formatted}"

            answer_letter = row.get("answer_letter", "").strip()

            problems.append(
                Problem(
                    id=row.get("uuid", ""),
                    question=q,
                    ground_truth=answer_letter,
                    benchmark="super_gpqa",
                    system_prompt=SUPER_GPQA_SYSTEM_PROMPT,
                    metadata={
                        "discipline": row.get("discipline", "Unknown"),
                        "field": row.get("field", "Unknown"),
                        "subfield": row.get("subfield", "Unknown"),
                        "difficulty": row.get("difficulty", "Unknown"),
                        "is_calculation": row.get("is_calculation", False),
                        "num_options": len(options),
                    },
                )
            )
        return problems

    def filter_problems(
        self,
        problems: list[Problem],
        bench_cfg: dict[str, Any],
        args: Any,
    ) -> list[Problem]:
        filter_cfg = bench_cfg.get("filter", {})
        disciplines = getattr(args, "super_gpqa_disciplines", None) or filter_cfg.get("disciplines")
        difficulties = getattr(args, "super_gpqa_difficulties", None) or filter_cfg.get("difficulties")
        fields = filter_cfg.get("fields")
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if disciplines:
            disc_set = {d.lower() for d in disciplines}
            filtered = [
                p for p in filtered
                if str(p.metadata.get("discipline", "")).lower() in disc_set
            ]
        if difficulties:
            diff_set = {d.lower() for d in difficulties}
            filtered = [
                p for p in filtered
                if str(p.metadata.get("difficulty", "")).lower() in diff_set
            ]
        if fields:
            field_set = {f.lower() for f in fields}
            filtered = [
                p for p in filtered
                if str(p.metadata.get("field", "")).lower() in field_set
            ]

        return apply_limit(filtered, limit, seed, sequential)

    def build_pipeline_request(
        self,
        problem: Problem,
        multimodal: bool = True,  # noqa: ARG002
    ) -> dict[str, Any]:
        prompt = (
            f"{problem.question}\n\n"
            "Think carefully step-by-step. "
            "Your final answer must be exactly one of the option letters."
        )
        return {"prompt": prompt, "image_url": None}

    def extract_fallback(self, model_output: str) -> str | None:
        for line in reversed(model_output.splitlines()):
            m = re.match(r"(?:Answer|answer|ANSWER)\s*[:：]\s*([A-Ja-j])", line.strip())
            if m:
                return m.group(1).upper()
        tail = model_output[-200:] if len(model_output) > 200 else model_output
        m = re.search(r"\b([A-J])\b", tail)
        if m:
            return m.group(1).upper()
        return None

    def judge_fallback(self, problem: Problem, extracted: str | None) -> tuple[bool, str]:
        if extracted is None:
            return False, "No extracted option letter"
        correct = extracted.strip().upper() == problem.ground_truth.strip().upper()
        return correct, "letter match fallback"

    def preview(self, problem: Problem) -> str:
        return (
            f"id={problem.id} "
            f"discipline={problem.metadata.get('discipline', 'Unknown')} "
            f"difficulty={problem.metadata.get('difficulty', 'Unknown')} "
            f"gt={problem.ground_truth} question={problem.question[:100]}"
        )
