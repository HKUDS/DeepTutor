from __future__ import annotations

import re
from typing import Any

from .base import BenchmarkAdapter, apply_limit
from benchmark.iso_solve.core.types import Problem

ALL_CATEGORIES = [
    "reasoning",
    "math",
    "coding",
    "data_analysis",
    "instruction_following",
    "language",
]

_HF_DATASET_MAP = {
    "reasoning": "livebench/reasoning",
    "math": "livebench/math",
    "coding": "livebench/coding",
    "data_analysis": "livebench/data_analysis",
    "instruction_following": "livebench/instruction_following",
    "language": "livebench/language",
}

LIVEBENCH_SYSTEM_PROMPT = (
    "You are an expert AI assistant solving a benchmark question. "
    "Think step-by-step, then provide your final answer clearly. "
    "Follow any output format instructions given in the question exactly."
)


class LiveBenchAdapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "livebench"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["category", "task"]

    @property
    def extract_hint(self) -> str:
        return "Extract the model's final answer according to the requested output format."

    @property
    def judge_hint(self) -> str:
        return "Be strict about correctness and lenient about whitespace/case differences."

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        from datasets import load_dataset

        categories = getattr(args, "livebench_categories", None) or bench_cfg.get("categories") or ALL_CATEGORIES
        out: list[Problem] = []
        for cat in categories:
            dataset_id = _HF_DATASET_MAP.get(cat)
            if not dataset_id:
                continue
            try:
                ds = load_dataset(dataset_id, split="test")
            except Exception:
                ds = load_dataset(dataset_id, split="train")
            for row in ds:
                removal = row.get("livebench_removal_date")
                if removal is not None and str(removal).strip():
                    continue
                turns = row.get("turns", [])
                question = turns[0] if turns else ""
                gt = row.get("ground_truth", "")
                if isinstance(gt, list):
                    gt = ", ".join(str(x) for x in gt)
                out.append(
                    Problem(
                        id=str(row.get("question_id", f"{cat}_{len(out):04d}")),
                        question=question,
                        ground_truth=str(gt),
                        benchmark="livebench",
                        system_prompt=LIVEBENCH_SYSTEM_PROMPT,
                        metadata={
                            "category": row.get("category", cat),
                            "task": row.get("task", "unknown"),
                        },
                    )
                )
        return out

    def filter_problems(
        self,
        problems: list[Problem],
        bench_cfg: dict[str, Any],
        args: Any,
    ) -> list[Problem]:
        filter_cfg = bench_cfg.get("filter", {})
        categories = getattr(args, "livebench_categories", None) or bench_cfg.get("categories")
        tasks = filter_cfg.get("tasks")
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if categories:
            cat_set = {str(v).lower() for v in categories}
            filtered = [p for p in filtered if str(p.metadata.get("category", "")).lower() in cat_set]
        if tasks:
            task_set = {str(v).lower() for v in tasks}
            filtered = [p for p in filtered if str(p.metadata.get("task", "")).lower() in task_set]
        return apply_limit(filtered, limit, seed, sequential)

    def build_pipeline_request(self, problem: Problem, multimodal: bool = True) -> dict[str, Any]:
        prompt = (
            f"{problem.question}\n\n"
            "Think carefully step-by-step. Provide your final answer clearly, "
            "following any format instructions exactly."
        )
        return {"prompt": prompt, "image_url": None}

    def extract_fallback(self, model_output: str) -> str | None:
        text = model_output.strip()
        if not text:
            return None
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return lines[-1] if lines else text

    def judge_fallback(self, problem: Problem, extracted: str | None) -> tuple[bool, str]:
        if extracted is None:
            return False, "No extracted answer"
        norm_pred = re.sub(r"\s+", " ", extracted.strip().lower()).strip(".,;!? ")
        norm_gt = re.sub(r"\s+", " ", problem.ground_truth.strip().lower()).strip(".,;!? ")
        return norm_pred == norm_gt, "normalized exact match fallback"
