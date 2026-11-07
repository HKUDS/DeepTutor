from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import time
from typing import Any

from .pipeline import run_solver_pipeline
from .types import BenchmarkReport, EvalResult, Problem

logger = logging.getLogger("iso_solve.runner")


class BenchmarkRunner:
    def __init__(self, adapter: Any, extractor_fn: Any, judge_fn: Any):
        self.adapter = adapter
        self.extractor_fn = extractor_fn
        self.judge_fn = judge_fn

    def _resolve_bench_cfg(self, cfg: dict[str, Any]) -> dict[str, Any]:
        # Backward compatibility: old MATH config lived at root level.
        if self.adapter.name == "math" and self.adapter.name not in cfg:
            return cfg
        return cfg.get(self.adapter.name, {})

    def _resolve_llm_runtime(self, bench_cfg: dict[str, Any]) -> dict[str, Any]:
        model_name = bench_cfg.get("llm", {}).get("model")
        api_key = None
        base_url = None
        try:
            from src.services.llm.config import get_llm_config

            llm_cfg = get_llm_config()
            model_name = model_name or llm_cfg.model or "unknown"
            api_key = llm_cfg.api_key
            base_url = llm_cfg.base_url
        except Exception:
            model_name = model_name or os.getenv("LLM_MODEL", "unknown")
        return {
            "model_name": model_name or "unknown",
            "api_key": api_key,
            "base_url": base_url,
        }

    def _create_output_dir(
        self,
        global_cfg: dict[str, Any],
        mode: str,
        model_name: str,
        timestamp: str,
        args_output: str | None,
    ) -> Path:
        base = args_output or global_cfg.get("output_dir", "benchmark/iso_solve/results")
        model_short = model_name.replace("/", "_").replace(":", "_")
        path = Path(base) / self.adapter.name / mode / f"{model_short}_{timestamp}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def _direct_call(
        self,
        problem: Problem,
        bench_cfg: dict[str, Any],
        model: str | None,
        api_key: str | None,
        base_url: str | None,
    ) -> str:
        from src.services.llm import complete

        llm_cfg = bench_cfg.get("llm", {})
        temperature = llm_cfg.get("temperature", 0.0)
        max_tokens = llm_cfg.get("max_tokens", 4096)
        multimodal = llm_cfg.get("multimodal", True)

        req = self.adapter.build_direct_request(problem, multimodal=multimodal)
        kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if "messages" in req:
            kwargs["prompt"] = ""
            kwargs["messages"] = req["messages"]
        else:
            kwargs["prompt"] = req.get("prompt", problem.question)
            kwargs["system_prompt"] = req.get("system_prompt", problem.system_prompt)
        if model:
            kwargs["model"] = model
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        return await complete(**kwargs)

    async def _pipeline_call(
        self,
        problem: Problem,
        bench_cfg: dict[str, Any],
        problem_workspace: str,
        model: str | None,
    ) -> str:
        pipeline_cfg = bench_cfg.get("pipeline", {})
        tools = pipeline_cfg.get("tools")
        language = pipeline_cfg.get("language", "en")
        pipeline_model = pipeline_cfg.get("model") or model
        multimodal = bench_cfg.get("llm", {}).get("multimodal", True)

        llm_cfg = bench_cfg.get("llm", {})
        max_tokens = pipeline_cfg.get("max_tokens") or llm_cfg.get("max_tokens")
        temperature = pipeline_cfg.get("temperature")
        if temperature is None:
            temperature = llm_cfg.get("temperature")

        req = self.adapter.build_pipeline_request(problem, multimodal=multimodal)
        result = await run_solver_pipeline(
            question=req.get("prompt", problem.question),
            workspace=problem_workspace,
            language=language,
            tools=tools,
            model=pipeline_model,
            image_url=req.get("image_url"),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return result.get("final_answer", "")

    def _save_result(
        self,
        out_dir: Path,
        idx: int,
        result: EvalResult,
    ) -> None:
        prob_dir = out_dir / "outputs" / f"{idx:04d}"
        prob_dir.mkdir(parents=True, exist_ok=True)

        with open(prob_dir / "output.md", "w", encoding="utf-8") as f:
            f.write(result.model_output)

        meta = {
            "id": result.problem.id,
            "benchmark": result.problem.benchmark,
            "question": result.problem.question,
            "ground_truth": result.problem.ground_truth,
            "metadata": result.problem.metadata,
            "extracted_answer": result.extracted_answer,
            "correct": result.correct,
            "score": result.score,
            "confidence": result.confidence,
            "judge_reasoning": result.judge_reasoning,
            "elapsed_sec": round(result.elapsed_sec, 3),
            "error": result.error,
        }
        with open(prob_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    async def run(
        self,
        args: argparse.Namespace,
        cfg: dict[str, Any],
    ) -> BenchmarkReport:
        bench_cfg = self._resolve_bench_cfg(cfg)
        problems = self.adapter.load_dataset(bench_cfg, args)
        problems = self.adapter.filter_problems(problems, bench_cfg, args)

        if not problems:
            raise ValueError(f"No {self.adapter.name} problems after filtering.")

        runtime = self._resolve_llm_runtime(bench_cfg)
        model_name = runtime["model_name"]
        api_key = runtime["api_key"]
        base_url = runtime["base_url"]

        if args.mode == "pipeline":
            pipeline_model = bench_cfg.get("pipeline", {}).get("model")
            if pipeline_model:
                model_name = pipeline_model

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = self._create_output_dir(cfg, args.mode, model_name, timestamp, args.output)

        report = BenchmarkReport(
            benchmark=self.adapter.name,
            mode=args.mode,
            model=model_name,
            timestamp=timestamp,
        )

        if args.dry_run:
            logger.info("=== %s DRY RUN ===", self.adapter.name.upper())
            for i, p in enumerate(problems[: min(10, len(problems))]):
                logger.info("[%d] %s", i + 1, self.adapter.preview(p))
            return report

        eval_cfg = cfg.get("evaluation", {})
        llm_extract = eval_cfg.get("llm_extract", True)
        llm_judge = eval_cfg.get("llm_judge", True)
        extract_model = eval_cfg.get("extract_model")
        extract_temperature = eval_cfg.get("extract_temperature")
        extract_max_tokens = eval_cfg.get("extract_max_tokens", 256)
        judge_model = eval_cfg.get("judge_model")
        judge_temperature = eval_cfg.get("judge_temperature")
        judge_max_tokens = eval_cfg.get("judge_max_tokens", 128)

        concurrency = (
            bench_cfg.get("pipeline", {}).get("concurrency", 1)
            if args.mode == "pipeline"
            else bench_cfg.get("concurrency", 1)
        )
        sem = asyncio.Semaphore(concurrency)
        total = len(problems)

        logger.info(
            "=== %s | mode=%s | model=%s | %d problems | concurrency=%d ===",
            self.adapter.name.upper(),
            args.mode,
            model_name,
            total,
            concurrency,
        )

        start = time.time()
        completed_count = 0
        correct_count = 0
        error_count = 0
        _progress_lock = asyncio.Lock()

        async def _run_one(i: int, prob: Problem) -> EvalResult:
            nonlocal completed_count, correct_count, error_count
            async with sem:
                t0 = time.time()
                try:
                    workspace = str(out_dir / "outputs" / f"{i:04d}")
                    if args.mode == "direct":
                        model_output = await self._direct_call(
                            prob,
                            bench_cfg=bench_cfg,
                            model=bench_cfg.get("llm", {}).get("model"),
                            api_key=api_key,
                            base_url=base_url,
                        )
                    elif args.mode == "pipeline":
                        model_output = await self._pipeline_call(
                            prob,
                            bench_cfg=bench_cfg,
                            problem_workspace=workspace,
                            model=bench_cfg.get("llm", {}).get("model"),
                        )
                    else:
                        raise ValueError(f"Unknown mode: {args.mode}")

                    if self.adapter.skip_extract:
                        extracted = model_output
                    else:
                        extracted = None
                        if llm_extract:
                            extracted = await self.extractor_fn(
                                question=prob.question,
                                model_output=model_output,
                                extract_hint=self.adapter.extract_hint,
                                model=extract_model,
                                api_key=api_key,
                                base_url=base_url,
                                max_tokens=extract_max_tokens,
                                temperature=extract_temperature,
                            )
                        if extracted is None:
                            extracted = self.adapter.extract_fallback(model_output)

                    if llm_judge:
                        correct, reasoning = await self.judge_fn(
                            question=prob.question,
                            predicted=extracted,
                            ground_truth=prob.ground_truth,
                            judge_hint=self.adapter.judge_hint,
                            model=judge_model,
                            api_key=api_key,
                            base_url=base_url,
                            max_tokens=judge_max_tokens,
                            temperature=judge_temperature,
                        )
                    else:
                        correct, reasoning = self.adapter.judge_fallback(prob, extracted)

                    result = EvalResult(
                        problem=prob,
                        model_output=model_output,
                        extracted_answer=extracted,
                        correct=correct,
                        score=1.0 if correct else 0.0,
                        elapsed_sec=time.time() - t0,
                        judge_reasoning=reasoning,
                    )
                except Exception as exc:
                    result = EvalResult(
                        problem=prob,
                        model_output="",
                        extracted_answer=None,
                        correct=False,
                        score=0.0,
                        elapsed_sec=time.time() - t0,
                        judge_reasoning="",
                        error=str(exc),
                    )

                async with _progress_lock:
                    completed_count += 1
                    if result.error:
                        error_count += 1
                    elif result.correct:
                        correct_count += 1
                    elapsed = time.time() - start
                    acc = correct_count / completed_count * 100 if completed_count else 0
                    status = "ERR" if result.error else ("OK" if result.correct else "WRONG")
                    logger.info(
                        "[%d/%d] #%04d %s | acc=%.1f%% | err=%d | %.1fs | elapsed %.0fs",
                        completed_count,
                        total,
                        i,
                        status,
                        acc,
                        error_count,
                        result.elapsed_sec,
                        elapsed,
                    )

                return result

        results = await asyncio.gather(*[_run_one(i, p) for i, p in enumerate(problems)])
        for i, r in enumerate(results):
            report.add(r, self.adapter.breakdown_keys)
            self._save_result(out_dir, i, r)

        report.elapsed_sec = time.time() - start

        report_path = out_dir / "report.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)

        summary_path = out_dir / "summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write("\n".join(report.summary_lines()))

        return report
