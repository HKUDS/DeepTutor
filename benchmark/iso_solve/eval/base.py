from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import Any

from benchmark.iso_solve.core.types import Problem


def apply_limit(
    problems: list[Problem],
    limit: int | None,
    seed: int = 42,
    sequential: bool = False,
) -> list[Problem]:
    """Apply limit to a problem list: sequential slice or seeded random sample."""
    if not limit or limit >= len(problems):
        return problems
    if sequential:
        return problems[:limit]
    return random.Random(seed).sample(problems, limit)


class BenchmarkAdapter(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def breakdown_keys(self) -> list[str]:
        return []

    @property
    def skip_extract(self) -> bool:
        """If True, skip LLM extraction and pass full model output to judge."""
        return False

    @property
    def extract_hint(self) -> str:
        return ""

    @property
    def judge_hint(self) -> str:
        return ""

    @abstractmethod
    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        pass

    @abstractmethod
    def filter_problems(
        self,
        problems: list[Problem],
        bench_cfg: dict[str, Any],
        args: Any,
    ) -> list[Problem]:
        pass

    def build_direct_request(
        self,
        problem: Problem,
        multimodal: bool = True,  # noqa: ARG002
    ) -> dict[str, Any]:
        return {
            "messages": [
                {"role": "system", "content": problem.system_prompt},
                {"role": "user", "content": problem.question},
            ]
        }

    def build_pipeline_request(
        self,
        problem: Problem,
        multimodal: bool = True,  # noqa: ARG002
    ) -> dict[str, Any]:
        return {"prompt": problem.question, "image_url": None}

    def extract_fallback(self, model_output: str) -> str | None:
        text = model_output.strip()
        return text if text else None

    def judge_fallback(self, problem: Problem, extracted: str | None) -> tuple[bool, str]:
        if extracted is None:
            return False, "No extracted answer"
        correct = extracted.strip().lower() == problem.ground_truth.strip().lower()
        return correct, "string exact match fallback"

    def preview(self, problem: Problem) -> str:
        return f"id={problem.id} question={problem.question[:120]}"
