from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .base import BenchmarkAdapter, apply_limit
from benchmark.iso_solve.core.types import Problem
from .scorers.math_equivalence import is_equiv

SUBJECTS = [
    "Prealgebra",
    "Algebra",
    "Number Theory",
    "Counting & Probability",
    "Geometry",
    "Intermediate Algebra",
    "Precalculus",
]

MATH_SYSTEM_PROMPT = (
    "You are a precise mathematics problem solver. "
    "Solve step by step and put your final answer inside \\boxed{}."
)

_HF_PARQUET_URL = (
    "hf://datasets/qwedsacf/competition_math/data/"
    "train-00000-of-00001-7320a6f3aba8ebd2.parquet"
)


class MathAdapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "math"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["subject", "level"]

    @property
    def extract_hint(self) -> str:
        return "This is a math problem. Extract the final expression, preferably from \\boxed{}."

    @property
    def judge_hint(self) -> str:
        return "Judge mathematical equivalence, not formatting."

    def _parse_level(self, level_raw: Any) -> int | None:
        if isinstance(level_raw, int):
            return level_raw
        if isinstance(level_raw, str) and "Level " in level_raw:
            try:
                return int(level_raw.split("Level ")[1])
            except Exception:
                return None
        return None

    def _df_to_problems(self, df: Any, source: str) -> list[Problem]:
        out: list[Problem] = []
        for idx, row in df.iterrows():
            solution = str(row.get("solution", ""))
            gt = self._extract_from_solution(solution)
            out.append(
                Problem(
                    id=f"math_{idx:05d}",
                    question=str(row.get("problem", "")),
                    ground_truth=gt or "",
                    benchmark="math",
                    system_prompt=MATH_SYSTEM_PROMPT,
                    metadata={
                        "subject": str(row.get("type", "Unknown")),
                        "level": self._parse_level(row.get("level", "")),
                        "source_file": f"{source}#{idx}",
                    },
                )
            )
        return out

    def _load_from_local(self, dataroot: str) -> list[Problem]:
        root = Path(dataroot)
        if "*" in dataroot:
            import glob as globmod
            files = [Path(p) for p in globmod.glob(dataroot)]
        else:
            files = list(root.rglob("*.json"))
        out: list[Problem] = []
        for idx, fpath in enumerate(files):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                solution = str(data.get("solution", ""))
                gt = self._extract_from_solution(solution) or ""
                out.append(
                    Problem(
                        id=f"math_local_{idx:05d}",
                        question=str(data.get("problem", "")),
                        ground_truth=gt,
                        benchmark="math",
                        system_prompt=MATH_SYSTEM_PROMPT,
                        metadata={
                            "subject": str(data.get("type", "Unknown")),
                            "level": self._parse_level(data.get("level", "")),
                            "source_file": str(fpath),
                        },
                    )
                )
            except Exception:
                continue
        return out

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        import pandas as pd

        dataroot = getattr(args, "dataroot", None)
        if dataroot:
            if dataroot.endswith(".parquet"):
                df = pd.read_parquet(dataroot)
                return self._df_to_problems(df, dataroot)
            return self._load_from_local(dataroot)

        dataset_cfg = bench_cfg.get("dataset", {})
        parquet_url = dataset_cfg.get("parquet_url", _HF_PARQUET_URL)
        cache_dir = Path(__file__).resolve().parents[1] / "data"
        cache_file = cache_dir / "competition_math.parquet"
        if cache_file.exists():
            df = pd.read_parquet(cache_file)
        else:
            df = pd.read_parquet(parquet_url)
            cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_file, index=False)

        df = df[df["level"] != "Level ?"].reset_index(drop=True)
        return self._df_to_problems(df, "competition_math")

    def filter_problems(
        self,
        problems: list[Problem],
        bench_cfg: dict[str, Any],
        args: Any,
    ) -> list[Problem]:
        filter_cfg = bench_cfg.get("filter", {})
        subjects = getattr(args, "subjects", None) or filter_cfg.get("subjects")
        levels = getattr(args, "levels", None) or filter_cfg.get("levels")
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if subjects:
            subj_set = set(subjects)
            filtered = [p for p in filtered if p.metadata.get("subject") in subj_set]
        if levels:
            level_set = {int(v) for v in levels}
            filtered = [p for p in filtered if p.metadata.get("level") in level_set]
        return apply_limit(filtered, limit, seed, sequential)

    def _extract_from_solution(self, text: str) -> str | None:
        matches = re.findall(r"\\boxed\{([^{}]+)\}", text, flags=re.DOTALL)
        if matches:
            return matches[-1].strip()
        return None

    def extract_fallback(self, model_output: str) -> str | None:
        boxed = self._extract_from_solution(model_output)
        if boxed:
            return boxed
        text = model_output.strip()
        return text.splitlines()[-1].strip() if text else None

    def judge_fallback(self, problem: Problem, extracted: str | None) -> tuple[bool, str]:
        if not extracted:
            return False, "No extracted answer"
        return is_equiv(extracted, problem.ground_truth), "math equivalence fallback"
