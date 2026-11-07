from __future__ import annotations

from typing import Any
from pathlib import Path

from .base import BenchmarkAdapter, apply_limit
from benchmark.iso_solve.core.types import Problem
from benchmark.iso_solve.multimodal import build_messages

HLE_SYSTEM_PROMPT = (
    "Your response should be in the following format:\n"
    "Explanation: {your explanation for your answer choice}\n"
    "Answer: {your chosen answer}\n"
    "Confidence: {your confidence score between 0% and 100% for your answer}"
)

_HF_HLE_PARQUET_URL = "hf://datasets/cais/hle/data/test-00000-of-00001.parquet"


class HLEAdapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "hle"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["subject", "answer_type"]

    @property
    def extract_hint(self) -> str:
        return "Extract the final answer from the line starting with 'Answer:'."

    @property
    def judge_hint(self) -> str:
        return "For numerical answers allow tiny rounding tolerance."

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        import pandas as pd

        parquet_url = bench_cfg.get("parquet_url", _HF_HLE_PARQUET_URL)
        cache_dir = Path(__file__).resolve().parents[1] / "data"
        cache_file = cache_dir / "hle.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
        else:
            df = pd.read_parquet(parquet_url)
            cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_file, index=False)

        out: list[Problem] = []
        for _, row in df.iterrows():
            image = str(row.get("image", "") or "")
            out.append(
                Problem(
                    id=str(row.get("id", "")),
                    question=str(row.get("question", "")),
                    ground_truth=str(row.get("answer", "")),
                    benchmark="hle",
                    system_prompt=HLE_SYSTEM_PROMPT,
                    metadata={
                        "subject": str(row.get("subject", "Unknown") or "Unknown"),
                        "answer_type": str(row.get("answer_type", "short_answer") or "short_answer"),
                        "image": image,
                        "is_multimodal": bool(image),
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
        subjects = getattr(args, "subjects", None) or filter_cfg.get("subjects")
        skip_multimodal = bench_cfg.get("skip_multimodal", False)
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if subjects:
            subj_set = set(subjects)
            filtered = [p for p in filtered if p.metadata.get("subject") in subj_set]
        if skip_multimodal:
            filtered = [p for p in filtered if not p.metadata.get("is_multimodal")]
        return apply_limit(filtered, limit, seed, sequential)

    def build_direct_request(self, problem: Problem, multimodal: bool = True) -> dict[str, Any]:
        image = str(problem.metadata.get("image", "") or "")
        if multimodal and image:
            return {"messages": build_messages(problem.system_prompt, problem.question, [image])}
        return super().build_direct_request(problem, multimodal=multimodal)

    def build_pipeline_request(self, problem: Problem, multimodal: bool = True) -> dict[str, Any]:
        image = str(problem.metadata.get("image", "") or "")
        return {
            "prompt": problem.question,
            "image_url": image if multimodal and image else None,
        }

    def extract_fallback(self, model_output: str) -> str | None:
        for line in reversed(model_output.splitlines()):
            stripped = line.strip()
            if stripped.lower().startswith("answer:"):
                return stripped.split(":", 1)[1].strip()
        text = model_output.strip()
        return text.splitlines()[-1].strip() if text else None
