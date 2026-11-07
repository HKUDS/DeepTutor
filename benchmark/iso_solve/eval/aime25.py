from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .base import BenchmarkAdapter, apply_limit
from benchmark.iso_solve.core.types import Problem

AIME_SYSTEM_PROMPT = (
    "You are an expert competition mathematics problem solver. "
    "Solve the given AIME problem step by step with rigorous reasoning. "
    "The answer is an integer from 0 to 999. "
    "Put your final answer inside \\boxed{}."
)

_LEADING_INT_RE = re.compile(r"^[-+]?\d+")
_INTEGER_RE = re.compile(r"[-+]?\d+")


class AIME25Adapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "aime25"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["part"]

    @property
    def extract_hint(self) -> str:
        return "The final answer must be an integer in [0, 999]."

    @property
    def judge_hint(self) -> str:
        return "Judge by integer equality."

    def _parse_answer(self, raw: Any) -> int:
        if isinstance(raw, (int, float)):
            return int(raw)
        s = str(raw).strip()
        m = _LEADING_INT_RE.match(s)
        if not m:
            raise ValueError(f"Cannot parse AIME answer: {raw!r}")
        return int(m.group(0))

    def _load_part_from_hf(self, config_name: str, part: int) -> list[Problem]:
        from datasets import load_dataset

        ds = load_dataset("opencompass/AIME2025", config_name, split="test")
        out: list[Problem] = []
        for idx, row in enumerate(ds):
            answer_int = self._parse_answer(row["answer"])
            out.append(
                Problem(
                    id=f"aime25_{'I' if part == 1 else 'II'}_{idx + 1:02d}",
                    question=row["question"],
                    ground_truth=str(answer_int),
                    benchmark="aime25",
                    system_prompt=AIME_SYSTEM_PROMPT,
                    metadata={"part": part, "problem_number": idx + 1},
                )
            )
        return out

    def _load_part_from_jsonl(self, path: Path, part: int) -> list[Problem]:
        out: list[Problem] = []
        with open(path, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                row = json.loads(line)
                answer_int = self._parse_answer(row["answer"])
                out.append(
                    Problem(
                        id=f"aime25_{'I' if part == 1 else 'II'}_{idx + 1:02d}",
                        question=row["question"],
                        ground_truth=str(answer_int),
                        benchmark="aime25",
                        system_prompt=AIME_SYSTEM_PROMPT,
                        metadata={"part": part, "problem_number": idx + 1},
                    )
                )
        return out

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        parts = getattr(args, "aime_parts", None) or bench_cfg.get("parts") or [1, 2]
        cache_dir = Path(__file__).resolve().parents[1] / "data"
        cache_map = {
            1: cache_dir / "aime2025_I.jsonl",
            2: cache_dir / "aime2025_II.jsonl",
        }
        config_map = {1: "AIME2025-I", 2: "AIME2025-II"}

        problems: list[Problem] = []
        for part in parts:
            cache_file = cache_map[part]
            if cache_file.exists():
                part_probs = self._load_part_from_jsonl(cache_file, part)
            else:
                part_probs = self._load_part_from_hf(config_map[part], part)
                cache_dir.mkdir(parents=True, exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as f:
                    for p in part_probs:
                        json.dump(
                            {"question": p.question, "answer": p.ground_truth},
                            f,
                            ensure_ascii=False,
                        )
                        f.write("\n")
            problems.extend(part_probs)
        return problems

    def filter_problems(
        self,
        problems: list[Problem],
        bench_cfg: dict[str, Any],
        args: Any,
    ) -> list[Problem]:
        filter_cfg = bench_cfg.get("filter", {})
        parts = getattr(args, "aime_parts", None) or bench_cfg.get("parts")
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if parts:
            part_set = {int(p) for p in parts}
            filtered = [p for p in filtered if int(p.metadata.get("part", 0)) in part_set]
        return apply_limit(filtered, limit, seed, sequential)

    def build_pipeline_request(
        self,
        problem: Problem,
        multimodal: bool = True,  # noqa: ARG002
    ) -> dict[str, Any]:
        prompt = (
            f"{problem.question}\n\n"
            "This is an AIME problem. The final answer is an integer from 0 to 999. "
            "Put your final answer inside \\boxed{}."
        )
        return {"prompt": prompt, "image_url": None}

    def extract_fallback(self, model_output: str) -> str | None:
        boxed = re.findall(r"\\boxed\{([^{}]+)\}", model_output)
        if boxed:
            m = _INTEGER_RE.search(boxed[-1])
            if m:
                return m.group(0)
        nums = _INTEGER_RE.findall(model_output)
        return nums[-1] if nums else None

    def judge_fallback(self, problem: Problem, extracted: str | None) -> tuple[bool, str]:
        if extracted is None:
            return False, "No integer extracted"
        try:
            return int(extracted) == int(problem.ground_truth), "integer match fallback"
        except Exception:
            return False, "Invalid integer prediction"

    def preview(self, problem: Problem) -> str:
        return (
            f"id={problem.id} part={problem.metadata.get('part')} "
            f"gt={problem.ground_truth} question={problem.question[:90]}"
        )
