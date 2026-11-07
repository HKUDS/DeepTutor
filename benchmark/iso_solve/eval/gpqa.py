from __future__ import annotations

import random
import re
from typing import Any

from .base import BenchmarkAdapter, apply_limit
from benchmark.iso_solve.core.types import Problem

CHOICE_LABELS = ["A", "B", "C", "D"]

GPQA_SYSTEM_PROMPT = (
    "You are an expert scientist answering a multiple-choice question. "
    "Think step-by-step, then finish your response with the line:\n"
    "Answer: X\n"
    "where X is exactly one of A, B, C, or D."
)


class GPQAAdapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "gpqa"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["domain"]

    @property
    def extract_hint(self) -> str:
        return "The final answer must be exactly one letter: A, B, C, or D."

    @property
    def judge_hint(self) -> str:
        return "This is a multiple-choice question. Compare only the final letter answer."

    def _build_choices(self, row: dict[str, Any], seed: int) -> tuple[list[str], int]:
        correct_ans = row["Correct Answer"]
        incorrect = [
            row["Incorrect Answer 1"],
            row["Incorrect Answer 2"],
            row["Incorrect Answer 3"],
        ]
        choices = [correct_ans] + incorrect
        rng = random.Random(seed)
        rng.shuffle(choices)
        correct_idx = choices.index(correct_ans)
        return choices, correct_idx

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        from datasets import load_dataset

        dataset_id = bench_cfg.get("dataset_id", "Idavidrein/gpqa")
        config_name = bench_cfg.get("config_name", "gpqa_diamond")
        choice_seed = bench_cfg.get("choice_shuffle_seed", 42)
        ds = load_dataset(dataset_id, config_name, split="train")

        problems: list[Problem] = []
        for idx, row in enumerate(ds):
            choices, correct_idx = self._build_choices(row, choice_seed + idx)
            formatted = "\n".join(f"{CHOICE_LABELS[i]}. {c}" for i, c in enumerate(choices))
            q = f"{row['Question']}\n\n{formatted}"
            problems.append(
                Problem(
                    id=row.get("Record ID", f"gpqa_{idx:04d}"),
                    question=q,
                    ground_truth=CHOICE_LABELS[correct_idx],
                    benchmark="gpqa",
                    system_prompt=GPQA_SYSTEM_PROMPT,
                    metadata={
                        "domain": row.get("High-level domain", "Unknown"),
                        "subdomain": row.get("Subdomain", "Unknown"),
                        "choices": choices,
                        "correct_idx": correct_idx,
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
        domains = getattr(args, "gpqa_domains", None) or filter_cfg.get("domains")
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if domains:
            domain_set = {d.lower() for d in domains}
            filtered = [p for p in filtered if str(p.metadata.get("domain", "")).lower() in domain_set]

        return apply_limit(filtered, limit, seed, sequential)

    def build_pipeline_request(
        self,
        problem: Problem,
        multimodal: bool = True,  # noqa: ARG002
    ) -> dict[str, Any]:
        prompt = (
            f"{problem.question}\n\n"
            "Think carefully step-by-step. Your final answer must be exactly one of A, B, C, or D."
        )
        return {"prompt": prompt, "image_url": None}

    def extract_fallback(self, model_output: str) -> str | None:
        for line in reversed(model_output.splitlines()):
            m = re.match(r"(?:Answer|answer|ANSWER)\s*[:：]\s*([A-Da-d])", line.strip())
            if m:
                return m.group(1).upper()
        m = re.search(r"\b([A-D])\b", model_output[-200:] if len(model_output) > 200 else model_output)
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
            f"id={problem.id} domain={problem.metadata.get('domain', 'Unknown')} "
            f"gt={problem.ground_truth} question={problem.question[:100]}"
        )
