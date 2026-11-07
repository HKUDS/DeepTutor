from __future__ import annotations

import os
import re
from typing import Any

from .base import BenchmarkAdapter, apply_limit
from .scorers import question_scorer
from benchmark.iso_solve.core.types import Problem
from benchmark.iso_solve.multimodal import (
    build_messages,
    build_multimodal_context,
)

GAIA_SYSTEM_PROMPT = (
    "You are a general AI assistant. I will ask you a question. "
    "Report your thoughts, and finish your answer with the following template: "
    "FINAL ANSWER: [YOUR FINAL ANSWER]."
)

_FINAL_ANSWER_RE = re.compile(r"FINAL\s+ANSWER\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)


class GAIAAdapter(BenchmarkAdapter):
    @property
    def name(self) -> str:
        return "gaia"

    @property
    def breakdown_keys(self) -> list[str]:
        return ["level"]

    @property
    def extract_hint(self) -> str:
        return "Extract the final answer after 'FINAL ANSWER:'."

    @property
    def judge_hint(self) -> str:
        return "Answers may be numbers, short strings, or comma-separated lists."

    def load_dataset(self, bench_cfg: dict[str, Any], args: Any) -> list[Problem]:
        from datasets import load_dataset
        from huggingface_hub import snapshot_download

        dataset_id = bench_cfg.get("dataset_id", "gaia-benchmark/GAIA")
        config_name = getattr(args, "gaia_config_name", None) or bench_cfg.get("config_name", "2023_all")
        split = getattr(args, "gaia_split", None) or bench_cfg.get("split", "validation")

        data_dir = snapshot_download(repo_id=dataset_id, repo_type="dataset")
        ds = load_dataset(data_dir, config_name, split=split)

        problems: list[Problem] = []
        for row in ds:
            gt = row.get("Final answer") or row.get("final_answer")
            if gt is None:
                continue
            file_name = row.get("file_name") or ""
            file_path_rel = row.get("file_path") or ""
            abs_file_path = os.path.join(data_dir, file_path_rel) if file_path_rel else None
            problems.append(
                Problem(
                    id=row["task_id"],
                    question=row["Question"],
                    ground_truth=str(gt),
                    benchmark="gaia",
                    system_prompt=GAIA_SYSTEM_PROMPT,
                    metadata={
                        "level": int(row["Level"]),
                        "file_name": file_name or None,
                        "file_path": abs_file_path,
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
        levels = getattr(args, "gaia_levels", None) or filter_cfg.get("levels")
        limit = args.limit or filter_cfg.get("limit")
        seed = getattr(args, "seed", filter_cfg.get("seed", 42))
        sequential = getattr(args, "sequential", False)

        filtered = problems
        if levels:
            level_set = {int(v) for v in levels}
            filtered = [p for p in filtered if int(p.metadata.get("level", 0)) in level_set]
        return apply_limit(filtered, limit, seed, sequential)

    def _prepare_multimodal(
        self,
        problem: Problem,
        multimodal: bool,
    ) -> tuple[str, list[str]]:
        file_path = problem.metadata.get("file_path")
        file_name = problem.metadata.get("file_name")
        if not file_path or not os.path.exists(file_path):
            return problem.question, []
        ctx = build_multimodal_context([(file_path, file_name)], multimodal=multimodal)
        text_parts = [problem.question]
        if ctx.extra_text:
            text_parts.append(ctx.extra_text)
        return "\n\n".join(text_parts), ctx.image_data_uris

    def build_direct_request(self, problem: Problem, multimodal: bool = True) -> dict[str, Any]:
        user_text, image_data_uris = self._prepare_multimodal(problem, multimodal=multimodal)
        if image_data_uris:
            return {"messages": build_messages(problem.system_prompt, user_text, image_data_uris)}
        return {
            "messages": [
                {"role": "system", "content": problem.system_prompt},
                {"role": "user", "content": user_text},
            ]
        }

    def build_pipeline_request(self, problem: Problem, multimodal: bool = True) -> dict[str, Any]:
        user_text, image_data_uris = self._prepare_multimodal(problem, multimodal=multimodal)
        return {
            "prompt": user_text,
            "image_url": image_data_uris[0] if image_data_uris else None,
        }

    def extract_fallback(self, model_output: str) -> str | None:
        matches = _FINAL_ANSWER_RE.findall(model_output)
        if matches:
            ans = matches[-1].strip()
            return ans.split("\n")[0].strip() if ans else None
        text = model_output.strip()
        return text.splitlines()[-1].strip() if text else None

    def judge_fallback(self, problem: Problem, extracted: str | None) -> tuple[bool, str]:
        if extracted is None:
            return False, "No extracted answer"
        return question_scorer(extracted, problem.ground_truth), "gaia scorer fallback"
