"""Re-judge / re-score existing benchmark results.

Modes:
  (default)   Dry-run re-judge: show flipped verdicts without writing.
  --overwrite Re-judge and overwrite flipped meta.json / report / summary.
  --rescore   Full re-score with retry:
              1) Detect incomplete cases (no solver output)
              2) Re-run solver for those cases (loop until done or max rounds)
              3) Extract + judge ALL cases
              4) Rebuild report.json + summary.txt from scratch

Usage:
    # Default (dry-run comparison)
    python -m benchmark.iso_solve.rejudge \
        --results-dir benchmark/iso_solve/results/aalcr/pipeline/qwen3.5-plus_20260223_131936

    # Overwrite flipped verdicts in-place
    python -m benchmark.iso_solve.rejudge \
        --results-dir benchmark/iso_solve/results/aalcr/pipeline/qwen3.5-plus_20260223_131936 \
        --overwrite

    # Full re-score with retry (handles incomplete runs)
    python -m benchmark.iso_solve.rejudge \
        --results-dir benchmark/iso_solve/results/gaia/pipeline/run_20260223 \
        --rescore --max-solve-rounds 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("rejudge")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cases(results_dir: Path) -> list[dict]:
    outputs_dir = results_dir / "outputs"
    cases = []
    for subdir in sorted(outputs_dir.iterdir()):
        if not subdir.is_dir():
            continue
        meta_path = subdir / "meta.json"
        if not meta_path.exists():
            continue
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        output_path = subdir / "output.md"
        if output_path.exists():
            with open(output_path, encoding="utf-8") as f:
                meta["_model_output"] = f.read()
        else:
            meta["_model_output"] = ""
        meta["_subdir"] = subdir.name
        cases.append(meta)
    return cases


def _get_adapter(benchmark: str):
    from benchmark.iso_solve.eval.aalcr import AALCRAdapter
    from benchmark.iso_solve.eval.gaia import GAIAAdapter
    from benchmark.iso_solve.eval.gpqa import GPQAAdapter
    from benchmark.iso_solve.eval.hle import HLEAdapter
    from benchmark.iso_solve.eval.math import MathAdapter as MATHAdapter
    from benchmark.iso_solve.eval.aime25 import AIME25Adapter
    from benchmark.iso_solve.eval.livebench import LiveBenchAdapter
    from benchmark.iso_solve.eval.super_gpqa import SuperGPQAAdapter

    adapters = {
        "aalcr": AALCRAdapter,
        "gaia": GAIAAdapter,
        "gpqa": GPQAAdapter,
        "hle": HLEAdapter,
        "math": MATHAdapter,
        "aime25": AIME25Adapter,
        "livebench": LiveBenchAdapter,
        "super_gpqa": SuperGPQAAdapter,
    }
    cls = adapters.get(benchmark)
    if cls is None:
        raise ValueError(f"Unknown benchmark: {benchmark}. Available: {list(adapters)}")
    return cls()


def _detect_benchmark(cases: list[dict]) -> str | None:
    for c in cases:
        b = c.get("benchmark")
        if b:
            return b
    return None


def _detect_benchmark_from_path(results_dir: Path) -> str | None:
    """Infer benchmark name from results/{benchmark}/{mode}/..."""
    parts = results_dir.resolve().parts
    try:
        idx = parts.index("results")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    except ValueError:
        pass
    return None


def _load_eval_cfg() -> dict[str, Any]:
    import yaml
    cfg_path = Path("benchmark/iso_solve/config.yaml")
    if cfg_path.exists():
        with open(cfg_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _resolve_judge_model(cli_model: str | None) -> str:
    if cli_model:
        return cli_model
    try:
        cfg = _load_eval_cfg()
        m = cfg.get("evaluation", {}).get("judge_model")
        if m:
            return m
    except Exception:
        pass
    return os.getenv("LLM_MODEL", "qwen3.5-plus")


def _resolve_extract_model() -> str | None:
    try:
        cfg = _load_eval_cfg()
        return cfg.get("evaluation", {}).get("extract_model") or None
    except Exception:
        return None


def _resolve_temperatures() -> tuple[float | None, float | None]:
    try:
        cfg = _load_eval_cfg()
        ev = cfg.get("evaluation", {})
        ext = ev.get("extract_temperature")
        jdg = ev.get("judge_temperature")
        return (float(ext) if ext is not None else None,
                float(jdg) if jdg is not None else None)
    except Exception:
        return None, None


async def _rejudge_one(
    case: dict,
    judge_hint: str,
    judge_model: str | None,
    api_key: str | None,
    base_url: str | None,
    judge_max_tokens: int,
    judge_temperature: float | None = None,
) -> tuple[bool, str]:
    from benchmark.iso_solve.core.judge import judge_answer

    extracted = case.get("extracted_answer") or case.get("_model_output", "")
    correct, reasoning = await judge_answer(
        question=case["question"],
        predicted=extracted,
        ground_truth=case["ground_truth"],
        judge_hint=judge_hint,
        model=judge_model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=judge_max_tokens,
        temperature=judge_temperature,
    )
    return correct, reasoning


def _find_model_output(subdir: Path) -> str | None:
    """Find model output from solve_*/final_answer.md or standalone output.md."""
    for child in sorted(subdir.iterdir(), reverse=True):
        if child.is_dir() and child.name.startswith("solve_"):
            fa = child / "final_answer.md"
            if fa.exists():
                with open(fa, encoding="utf-8") as f:
                    content = f.read()
                if content.strip():
                    return content
    output_md = subdir / "output.md"
    if output_md.exists() and not (subdir / "meta.json").exists():
        with open(output_md, encoding="utf-8") as f:
            content = f.read()
        if content.strip():
            return content
    return None


def _detect_mode_from_path(results_dir: Path) -> str:
    parts = results_dir.resolve().parts
    try:
        idx = parts.index("results")
        if idx + 2 < len(parts):
            return parts[idx + 2]
    except ValueError:
        pass
    return "pipeline"


def _resolve_llm_runtime(bench_cfg: dict) -> dict[str, Any]:
    model_name = bench_cfg.get("llm", {}).get("model")
    api_key, base_url = None, None
    try:
        from src.services.llm.config import get_llm_config
        llm_cfg = get_llm_config()
        model_name = model_name or llm_cfg.model or "unknown"
        api_key = llm_cfg.api_key
        base_url = llm_cfg.base_url
    except Exception:
        model_name = model_name or os.getenv("LLM_MODEL", "unknown")
    return {"model_name": model_name or "unknown", "api_key": api_key, "base_url": base_url}


async def _solve_one(
    problem: Any,
    workspace: str,
    adapter: Any,
    mode: str,
    bench_cfg: dict,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
) -> str:
    """Run solver for a single problem. Returns model output text."""
    if mode == "pipeline":
        from benchmark.iso_solve.core.pipeline import run_solver_pipeline

        pipeline_cfg = bench_cfg.get("pipeline", {})
        llm_cfg = bench_cfg.get("llm", {})
        pipeline_model = pipeline_cfg.get("model") or model
        multimodal = llm_cfg.get("multimodal", True)
        max_tokens = pipeline_cfg.get("max_tokens") or llm_cfg.get("max_tokens")
        temperature = pipeline_cfg.get("temperature")
        if temperature is None:
            temperature = llm_cfg.get("temperature")

        req = adapter.build_pipeline_request(problem, multimodal=multimodal)
        result = await run_solver_pipeline(
            question=req.get("prompt", problem.question),
            workspace=workspace,
            language=pipeline_cfg.get("language", "en"),
            tools=pipeline_cfg.get("tools"),
            model=pipeline_model,
            image_url=req.get("image_url"),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return result.get("final_answer", "")
    else:
        from src.services.llm import complete

        llm_cfg = bench_cfg.get("llm", {})
        multimodal = llm_cfg.get("multimodal", True)
        req = adapter.build_direct_request(problem, multimodal=multimodal)
        kwargs: dict[str, Any] = {
            "temperature": llm_cfg.get("temperature", 0.0),
            "max_tokens": llm_cfg.get("max_tokens", 4096),
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


def _find_incomplete_indices(
    outputs_dir: Path,
    problems_by_index: dict[str, Any],
) -> list[str]:
    """Find indices of cases that have no usable solver output or had errors."""
    incomplete = []
    for idx_str in sorted(problems_by_index.keys()):
        subdir = outputs_dir / idx_str
        if not subdir.exists():
            incomplete.append(idx_str)
            continue
        meta_path = subdir / "meta.json"
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("error"):
                incomplete.append(idx_str)
            continue
        if _find_model_output(subdir) is not None:
            continue
        incomplete.append(idx_str)
    return incomplete


async def _retry_solve_incomplete(
    results_dir: Path,
    adapter: Any,
    problems_by_index: dict[str, Any],
    mode: str,
    bench_cfg: dict,
    max_rounds: int = 3,
) -> list[str]:
    """Retry solving for incomplete cases until all done or max_rounds hit."""
    outputs_dir = results_dir / "outputs"
    runtime = _resolve_llm_runtime(bench_cfg)
    model_name = runtime["model_name"]
    api_key = runtime["api_key"]
    base_url = runtime["base_url"]

    solve_concurrency = (
        bench_cfg.get("pipeline", {}).get("concurrency", 1)
        if mode == "pipeline"
        else bench_cfg.get("concurrency", 1)
    )

    for round_num in range(1, max_rounds + 1):
        incomplete = _find_incomplete_indices(outputs_dir, problems_by_index)
        if not incomplete:
            logger.info("[solve] All %d cases have output", len(problems_by_index))
            return []

        logger.info(
            "[solve] Round %d/%d: %d incomplete, retrying (concurrency=%d, model=%s)...",
            round_num, max_rounds, len(incomplete), solve_concurrency, model_name,
        )

        sem = asyncio.Semaphore(solve_concurrency)
        solved_count = 0

        async def _run_solve(idx_str: str) -> None:
            nonlocal solved_count
            prob = problems_by_index[idx_str]
            workspace = str(outputs_dir / idx_str)
            async with sem:
                try:
                    output = await _solve_one(
                        prob, workspace, adapter, mode, bench_cfg,
                        model_name, api_key, base_url,
                    )
                    if mode == "direct":
                        Path(workspace).mkdir(parents=True, exist_ok=True)
                        with open(Path(workspace) / "output.md", "w", encoding="utf-8") as f:
                            f.write(output)
                    solved_count += 1
                    logger.info("[solve] %s (%s): done", prob.id, idx_str)
                except Exception as exc:
                    logger.error("[solve] %s (%s): %s", prob.id, idx_str, exc)

        await asyncio.gather(*[_run_solve(idx) for idx in incomplete])
        logger.info("[solve] Round %d done: solved %d / %d", round_num, solved_count, len(incomplete))

    still_incomplete = _find_incomplete_indices(outputs_dir, problems_by_index)
    if still_incomplete:
        logger.warning(
            "[solve] %d cases still incomplete after %d rounds",
            len(still_incomplete), max_rounds,
        )
    return still_incomplete


def _infer_report_meta(results_dir: Path, benchmark: str) -> dict:
    """Infer mode / model / timestamp from directory path and name."""
    mode = ""
    parts = results_dir.resolve().parts
    try:
        idx = parts.index("results")
        if idx + 2 < len(parts):
            mode = parts[idx + 2]
    except ValueError:
        pass

    model, timestamp = "", ""
    m = re.match(r"(.+?)_(\d{8}_\d{6})", results_dir.name)
    if m:
        model = m.group(1)
        timestamp = m.group(2)

    return {
        "benchmark": benchmark,
        "mode": mode,
        "model": model,
        "timestamp": timestamp,
    }


def _build_report_dict(
    meta_info: dict,
    results: list[dict],
    breakdown_keys: list[str],
    incomplete_count: int,
) -> dict:
    correct_count = sum(1 for r in results if r["_new_correct"])
    errors = sum(1 for r in results if r.get("error"))
    total = len(results) + incomplete_count
    scored = len(results)

    acc = correct_count / scored if scored else 0.0
    acc_pct = round(100.0 * acc, 2)
    ci = round(1.96 * math.sqrt(acc_pct * (100 - acc_pct) / scored), 2) if scored else 0.0

    elapsed = sum(r.get("elapsed_sec", 0) or 0 for r in results)

    breakdowns: dict[str, dict[str, dict]] = {}
    for r in results:
        if r.get("error"):
            continue
        rmeta = r.get("metadata", {})
        for key in breakdown_keys:
            val = str(rmeta.get(key, ""))
            if not val:
                continue
            bucket_name = f"by_{key}"
            stats = breakdowns.setdefault(bucket_name, {}).setdefault(
                val, {"total": 0, "correct": 0}
            )
            stats["total"] += 1
            if r["_new_correct"]:
                stats["correct"] += 1
    for bucket in breakdowns.values():
        for s in bucket.values():
            s["accuracy"] = round(s["correct"] / s["total"], 4) if s["total"] else 0.0

    return {
        **meta_info,
        "overall": {
            "total": total,
            "scored": scored,
            "incomplete": incomplete_count,
            "correct": correct_count,
            "accuracy": round(acc, 4),
            "accuracy_pct": acc_pct,
            "confidence_interval": ci,
            "errors": errors,
            "elapsed_sec": round(elapsed, 2),
        },
        "breakdowns": breakdowns,
        "results": [
            {
                "id": r.get("id"),
                "question": r.get("question", "")[:300],
                "ground_truth": r.get("ground_truth", ""),
                "extracted_answer": r.get("extracted_answer"),
                "correct": r["_new_correct"],
                "score": 1.0 if r["_new_correct"] else 0.0,
                "judge_reasoning": r["_new_reasoning"][:400],
                "elapsed_sec": round(r.get("elapsed_sec", 0) or 0, 3),
                "error": r.get("error"),
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ],
    }


def _write_report_and_summary(results_dir: Path, report: dict) -> None:
    with open(results_dir / "report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    ov = report["overall"]
    scored = ov.get("scored", ov["total"])
    lines = [
        "=" * 70,
        f"{report.get('benchmark', '').upper()} Benchmark Report — {report.get('mode', '')} mode",
        f"Model: {report.get('model', '')}",
        f"Time:  {report.get('timestamp', '')}",
        "=" * 70,
        f"Overall: {ov['correct']}/{scored} = {ov['accuracy_pct']}% "
        f"+/- {ov['confidence_interval']}% (errors={ov['errors']})",
        f"Wall time: {ov.get('elapsed_sec', 0):.1f}s",
    ]
    if ov.get("incomplete", 0) > 0:
        lines.append(f"Incomplete: {ov['incomplete']} cases (not scored)")

    for bucket_name in sorted(report.get("breakdowns", {})):
        lines.append("")
        lines.append(f"--- {bucket_name} ---")
        for k in sorted(report["breakdowns"][bucket_name]):
            s = report["breakdowns"][bucket_name][k]
            a = s["correct"] / s["total"] if s["total"] else 0.0
            lines.append(f"  {k:30s} {s['correct']:4d}/{s['total']:4d} = {a:.3f}")
    lines.append("=" * 70)

    with open(results_dir / "summary.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _overwrite_meta(results_dir: Path, results: list[dict]) -> int:
    """Overwrite meta.json for flipped cases. Returns number of files written."""
    outputs_dir = results_dir / "outputs"
    written = 0
    for r in results:
        if r["_new_correct"] == r.get("correct", False):
            continue
        meta_path = outputs_dir / r["_subdir"] / "meta.json"
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        meta["correct"] = r["_new_correct"]
        meta["score"] = 1.0 if r["_new_correct"] else 0.0
        meta["judge_reasoning"] = r["_new_reasoning"]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        written += 1
    return written


def _rebuild_report(results_dir: Path, results: list[dict]) -> None:
    """Rebuild report.json and summary.txt from the current results."""
    report_path = results_dir / "report.json"
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    new_correct_total = 0
    new_errors = 0
    new_breakdowns: dict[str, dict[str, dict]] = {}

    for r in results:
        is_correct = r["_new_correct"]
        has_error = bool(r.get("error"))
        if has_error:
            new_errors += 1
        if is_correct:
            new_correct_total += 1
        meta = r.get("metadata", {})
        for bucket_name, bucket in report.get("breakdowns", {}).items():
            key_name = bucket_name.removeprefix("by_")
            bucket_value = str(meta.get(key_name, ""))
            if not bucket_value:
                continue
            stats = new_breakdowns.setdefault(bucket_name, {}).setdefault(
                bucket_value, {"total": 0, "correct": 0}
            )
            stats["total"] += 1
            if is_correct:
                stats["correct"] += 1

    total = report["overall"]["total"]
    acc = new_correct_total / total if total else 0.0
    acc_pct = round(100.0 * acc, 2)
    ci = round(1.96 * math.sqrt(acc_pct * (100 - acc_pct) / total), 2) if total else 0.0

    report["overall"]["correct"] = new_correct_total
    report["overall"]["accuracy"] = round(acc, 4)
    report["overall"]["accuracy_pct"] = acc_pct
    report["overall"]["confidence_interval"] = ci
    report["overall"]["errors"] = new_errors

    for bucket_name, bucket in new_breakdowns.items():
        for k, s in bucket.items():
            s["accuracy"] = round(s["correct"] / s["total"], 4) if s["total"] else 0.0
    report["breakdowns"] = new_breakdowns

    for item in report.get("results", []):
        match = next((r for r in results if r.get("id") == item.get("id")), None)
        if match:
            item["correct"] = match["_new_correct"]
            item["score"] = 1.0 if match["_new_correct"] else 0.0
            item["judge_reasoning"] = match["_new_reasoning"][:400]

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    bm = report.get("benchmark", "").upper()
    mode = report.get("mode", "")
    model = report.get("model", "")
    ts = report.get("timestamp", "")
    elapsed = report["overall"].get("elapsed_sec", 0.0)

    lines = [
        "=" * 70,
        f"{bm} Benchmark Report — {mode} mode",
        f"Model: {model}",
        f"Time:  {ts}",
        "=" * 70,
        f"Overall: {new_correct_total}/{total} = {acc_pct}% "
        f"+/- {ci}% (errors={new_errors})",
        f"Wall time: {elapsed:.1f}s",
    ]
    for bucket_name in sorted(new_breakdowns):
        lines.append("")
        lines.append(f"--- {bucket_name} ---")
        for k in sorted(new_breakdowns[bucket_name]):
            s = new_breakdowns[bucket_name][k]
            a = s["correct"] / s["total"] if s["total"] else 0.0
            lines.append(f"  {k:30s} {s['correct']:4d}/{s['total']:4d} = {a:.3f}")
    lines.append("=" * 70)

    summary_path = results_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    logger.info("Overwrote report.json and summary.txt")


def _load_problems_for_rescore(benchmark: str) -> list:
    """Load the full problem set for a benchmark (sequential, no limit)."""
    import yaml
    from benchmark.iso_solve.core.types import Problem  # noqa: F401

    cfg = _load_eval_cfg()
    bench_cfg = cfg.get(benchmark, {})
    adapter = _get_adapter(benchmark)

    class _FakeArgs:
        limit = None
        seed = 42
        sequential = True
        # benchmark-specific defaults
        gaia_config_name = None
        gaia_split = None
        gaia_levels = None
        gpqa_domains = None
        aime_parts = None
        livebench_categories = None
        aalcr_categories = None
        super_gpqa_disciplines = None
        super_gpqa_difficulties = None
        levels = None
        subjects = None
        dataroot = None

    args = _FakeArgs()
    problems = adapter.load_dataset(bench_cfg, args)
    problems = adapter.filter_problems(problems, bench_cfg, args)
    return problems


# ---------------------------------------------------------------------------
# Rescore mode
# ---------------------------------------------------------------------------

async def _rescore(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / "DeepTutor.env", override=False)
    load_dotenv(_PROJECT_ROOT / ".env", override=False)

    results_dir = Path(args.results_dir)
    outputs_dir = results_dir / "outputs"

    if not outputs_dir.exists():
        logger.error("No outputs directory at %s", outputs_dir)
        return

    all_subdirs = sorted([d for d in outputs_dir.iterdir() if d.is_dir()])
    if not all_subdirs:
        logger.error("No output subdirectories found")
        return

    # --- Detect benchmark and mode ---
    benchmark = _detect_benchmark_from_path(results_dir)
    mode = _detect_mode_from_path(results_dir)

    # Try meta.json for benchmark detection as fallback
    if not benchmark:
        for subdir in all_subdirs:
            mp = subdir / "meta.json"
            if mp.exists():
                with open(mp, encoding="utf-8") as f:
                    b = json.load(f).get("benchmark")
                if b:
                    benchmark = b
                    break
    if not benchmark:
        raise ValueError(
            "Cannot detect benchmark. Directory path does not contain "
            "'results/{benchmark}/...' and no meta.json files found."
        )

    adapter = _get_adapter(benchmark)
    cfg = _load_eval_cfg()
    bench_cfg = cfg.get(benchmark, {})

    # --- Phase 0: load dataset and retry incomplete solves ---
    logger.info("Loading %s dataset...", benchmark)
    problems = _load_problems_for_rescore(benchmark)
    problems_by_index: dict[str, Any] = {}
    for i, p in enumerate(problems):
        problems_by_index[f"{i:04d}"] = p
    logger.info("Loaded %d problems from dataset", len(problems))

    existing_indices = {d.name for d in all_subdirs}
    problems_by_index = {k: v for k, v in problems_by_index.items() if k in existing_indices}
    logger.info("Scoped to %d existing output directories", len(problems_by_index))

    max_rounds = getattr(args, "max_solve_rounds", 3)
    pre_incomplete = _find_incomplete_indices(outputs_dir, problems_by_index)

    if pre_incomplete:
        logger.info(
            "%d cases have no solver output — entering retry-solve phase (mode=%s, max_rounds=%d)",
            len(pre_incomplete), mode, max_rounds,
        )
        still_incomplete = await _retry_solve_incomplete(
            results_dir, adapter, problems_by_index, mode, bench_cfg, max_rounds,
        )
    else:
        logger.info("All cases already have solver output, skipping retry-solve phase")
        still_incomplete = []

    # --- Phase 1: scan and categorise ---
    all_subdirs = sorted([d for d in outputs_dir.iterdir() if d.is_dir()])
    meta_cases: list[dict] = []
    unscored: list[tuple[str, str]] = []
    incomplete: list[str] = []

    for subdir in all_subdirs:
        meta_path = subdir / "meta.json"
        if meta_path.exists():
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            if meta.get("error"):
                new_output = _find_model_output(subdir)
                if new_output is not None:
                    unscored.append((subdir.name, new_output))
                else:
                    incomplete.append(subdir.name)
                continue
            output_path = subdir / "output.md"
            if output_path.exists():
                with open(output_path, encoding="utf-8") as f:
                    meta["_model_output"] = f.read()
            else:
                meta["_model_output"] = ""
            meta["_subdir"] = subdir.name
            meta_cases.append(meta)
        else:
            model_output = _find_model_output(subdir)
            if model_output is not None:
                unscored.append((subdir.name, model_output))
            else:
                incomplete.append(subdir.name)

    logger.info(
        "Scan: %d with meta, %d unscored (have solve output), %d incomplete",
        len(meta_cases), len(unscored), len(incomplete),
    )

    # --- Phase 2: build unified case list ---
    all_cases: list[dict] = list(meta_cases)

    for subdir_name, model_output in unscored:
        prob = problems_by_index.get(subdir_name)
        if prob is None:
            logger.warning(
                "No dataset problem for index %s (dataset has %d entries), marking incomplete",
                subdir_name, len(problems_by_index),
            )
            incomplete.append(subdir_name)
            continue
        all_cases.append({
            "id": prob.id,
            "benchmark": prob.benchmark,
            "question": prob.question,
            "ground_truth": prob.ground_truth,
            "metadata": prob.metadata,
            "_model_output": model_output,
            "_subdir": subdir_name,
            "_needs_extract": True,
        })

    all_cases.sort(key=lambda c: c["_subdir"])

    if not all_cases:
        print("No scorable cases found.")
        if incomplete:
            print(f"\nIncomplete: {len(incomplete)} cases")
        return

    # --- Phase 4: resolve models ---
    judge_model = _resolve_judge_model(args.judge_model)
    extract_model = _resolve_extract_model()
    extract_temperature, judge_temperature = _resolve_temperatures()
    skip_extract = adapter.skip_extract
    extract_hint = adapter.extract_hint
    judge_hint = adapter.judge_hint

    logger.info(
        "Rescore: %d cases | judge=%s | extract=%s | concurrency=%d",
        len(all_cases), judge_model, extract_model or "(default)", args.concurrency,
    )

    # --- Phase 5: extract + judge ---
    sem = asyncio.Semaphore(args.concurrency)
    completed = 0
    total = len(all_cases)

    async def _score_one(case: dict) -> dict:
        nonlocal completed
        async with sem:
            if not skip_extract:
                from benchmark.iso_solve.core.extractor import extract_answer
                extracted = await extract_answer(
                    question=case["question"],
                    model_output=case["_model_output"],
                    extract_hint=extract_hint,
                    model=extract_model,
                    max_tokens=16384,
                    temperature=extract_temperature,
                )
                if extracted is None:
                    extracted = adapter.extract_fallback(case["_model_output"])
                case["extracted_answer"] = extracted
            elif skip_extract and case.get("_needs_extract", False):
                case["extracted_answer"] = case["_model_output"]

            correct, reasoning = await _rejudge_one(
                case, judge_hint, judge_model, None, None, args.judge_max_tokens,
                judge_temperature=judge_temperature,
            )

            completed += 1
            old_correct = case.get("correct")
            tag = ""
            if old_correct is not None and correct != old_correct:
                tag = " ** FLIPPED **"
            elif old_correct is None:
                tag = " (new)"
            logger.info(
                "[%d/%d] %s: %s%s",
                completed, total, case.get("id"),
                "OK" if correct else "WRONG", tag,
            )

            return {**case, "_new_correct": correct, "_new_reasoning": reasoning}

    results = await asyncio.gather(*[_score_one(c) for c in all_cases])

    # --- Phase 6: write ALL meta.json + output.md ---
    for r in results:
        subdir_path = outputs_dir / r["_subdir"]
        subdir_path.mkdir(parents=True, exist_ok=True)

        meta = {
            "id": r.get("id"),
            "benchmark": r.get("benchmark", benchmark),
            "question": r.get("question", ""),
            "ground_truth": r.get("ground_truth", ""),
            "metadata": r.get("metadata", {}),
            "extracted_answer": r.get("extracted_answer"),
            "correct": r["_new_correct"],
            "score": 1.0 if r["_new_correct"] else 0.0,
            "confidence": r.get("confidence", 100),
            "judge_reasoning": r["_new_reasoning"],
            "elapsed_sec": round(r.get("elapsed_sec", 0) or 0, 3),
            "error": r.get("error"),
        }
        with open(subdir_path / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        output_md = subdir_path / "output.md"
        if not output_md.exists() and r.get("_model_output"):
            with open(output_md, "w", encoding="utf-8") as f:
                f.write(r["_model_output"])

    # --- Phase 7: build and write report ---
    meta_info = _infer_report_meta(results_dir, benchmark)
    report = _build_report_dict(meta_info, results, adapter.breakdown_keys, len(incomplete))
    _write_report_and_summary(results_dir, report)

    # --- Phase 8: print summary ---
    correct_count = sum(1 for r in results if r["_new_correct"])
    scored = len(results)
    acc_pct = round(100.0 * correct_count / scored, 1) if scored else 0
    ci_val = round(1.96 * math.sqrt(acc_pct * (100 - acc_pct) / scored), 2) if scored else 0

    print()
    print("=" * 70)
    print(f"Rescored: {correct_count}/{scored} = {acc_pct}% +/- {ci_val}%")
    if incomplete:
        print(f"Incomplete: {len(incomplete)} cases (not scored)")
    print(f"Wrote: {scored} meta.json + report.json + summary.txt")
    print("=" * 70)

    if incomplete:
        print(f"\nIncomplete cases ({len(incomplete)}):")
        for s in sorted(incomplete):
            print(f"  {s}")


# ---------------------------------------------------------------------------
# Default rejudge mode
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser(description="Re-judge / re-score benchmark results")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--judge-max-tokens", type=int, default=16384)
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Overwrite meta.json / report.json / summary.txt in-place for flipped cases",
    )
    parser.add_argument(
        "--rescore", action="store_true",
        help="Full re-score: retry incomplete solves, extract+judge ALL cases, rebuild report",
    )
    parser.add_argument(
        "--max-solve-rounds", type=int, default=3,
        help="(rescore) Max retry rounds for incomplete solver cases (default: 3)",
    )
    args = parser.parse_args()

    if args.rescore:
        await _rescore(args)
        return

    results_dir = Path(args.results_dir)
    cases = _load_cases(results_dir)
    logger.info("Loaded %d cases from %s", len(cases), results_dir)

    benchmark = _detect_benchmark(cases)
    if not benchmark:
        raise ValueError("Cannot detect benchmark from meta.json files")
    adapter = _get_adapter(benchmark)
    judge_hint = adapter.judge_hint
    logger.info("Benchmark: %s | judge_hint: %s", benchmark, judge_hint[:80])

    judge_model = _resolve_judge_model(args.judge_model)
    _, judge_temperature = _resolve_temperatures()

    logger.info("Judge model: %s | concurrency: %d | overwrite: %s",
                judge_model, args.concurrency, args.overwrite)

    sem = asyncio.Semaphore(args.concurrency)
    completed = 0
    total = len(cases)

    async def _run(case: dict) -> dict:
        nonlocal completed
        async with sem:
            new_correct, reasoning = await _rejudge_one(
                case, judge_hint, judge_model, None, None, args.judge_max_tokens,
                judge_temperature=judge_temperature,
            )
            completed += 1
            old_correct = case.get("correct", False)
            if new_correct != old_correct:
                logger.info(
                    "[%d/%d] %s: %s -> %s ** FLIPPED **",
                    completed, total, case.get("id"),
                    "OK" if old_correct else "WRONG",
                    "OK" if new_correct else "WRONG",
                )
            return {**case, "_new_correct": new_correct, "_new_reasoning": reasoning}

    results = await asyncio.gather(*[_run(c) for c in cases])

    old_correct = sum(1 for r in results if r.get("correct", False))
    new_correct = sum(1 for r in results if r["_new_correct"])
    flipped = [r for r in results if r["_new_correct"] != r.get("correct", False)]

    acc = lambda c, n: round(c / n * 100, 1) if n else 0
    ci = lambda a, n: round(1.96 * math.sqrt(a * (100 - a) / n), 2) if n else 0

    print()
    print("=" * 70)
    print(f"Old:  {old_correct}/{total} = {acc(old_correct, total)}% +/- {ci(acc(old_correct, total), total)}%")
    print(f"New:  {new_correct}/{total} = {acc(new_correct, total)}% +/- {ci(acc(new_correct, total), total)}%")
    print(f"Diff: {new_correct - old_correct:+d}")
    print("=" * 70)

    if not flipped:
        print("\nNo flipped verdicts.")
        if args.overwrite:
            print("Nothing to overwrite.")
        return

    print(f"\nFlipped verdicts: {len(flipped)}")
    print("-" * 70)
    for f in flipped:
        old = "CORRECT" if f.get("correct") else "INCORRECT"
        new = "CORRECT" if f["_new_correct"] else "INCORRECT"
        print(f"\n  [{f['_subdir']}] {f.get('id')}: {old} -> {new}")
        print(f"    GT:        {f.get('ground_truth', '')[:150]}")
        print(f"    Reasoning: {f.get('_new_reasoning', '')[:150]}")
        extracted = f.get("extracted_answer", "") or ""
        print(f"    Answer:    {extracted[:150]}...")
    print("=" * 70)

    if args.overwrite:
        written = _overwrite_meta(results_dir, results)
        logger.info("Overwrote %d meta.json files", written)
        _rebuild_report(results_dir, results)
        print(f"\n[overwrite] Updated {written} meta.json + report.json + summary.txt")


if __name__ == "__main__":
    asyncio.run(main())
