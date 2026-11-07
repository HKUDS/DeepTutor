"""Multi-round LLM scoring for existing benchmark results.

Runs N rounds (default 5) of extract + judge on an existing results folder,
producing a per-round detailed report and an averaged final summary.

For benchmarks with breakdown keys (e.g. GAIA by level), per-group averages
are also reported.

Usage:
    # Single directory
    python -m benchmark.iso_solve.get_llm_score \
        --results-dir benchmark/iso_solve/report_trace/gaia/direct/google_gemini-3-flash-preview_nitro_20260223_235651

    # Batch mode — score all dirs listed in a YAML file
    python -m benchmark.iso_solve.get_llm_score \
        --jobs benchmark/iso_solve/score_jobs.yaml

    # Custom rounds & concurrency
    python -m benchmark.iso_solve.get_llm_score \
        --results-dir benchmark/iso_solve/report_trace/hle/direct/anthropic_claude-sonnet-4.5_20260224_133043 \
        --rounds 3 --concurrency 30

    # Override judge model
    python -m benchmark.iso_solve.get_llm_score \
        --results-dir benchmark/iso_solve/report_trace/aalcr/direct/openai_gpt-5-mini_20260223_185720-paper \
        --judge-model openai/gpt-5.2:nitro
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
logger = logging.getLogger("get_llm_score")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_RESULTS_DIR_MARKERS = ("results", "report_trace")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cases(results_dir: Path) -> list[dict]:
    """Load all cases from outputs/ directory."""
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
    from benchmark.iso_solve.eval import ADAPTER_REGISTRY

    cls = ADAPTER_REGISTRY.get(benchmark)
    if cls is None:
        raise ValueError(f"Unknown benchmark: {benchmark}. Available: {list(ADAPTER_REGISTRY)}")
    return cls()


def _find_marker_index(parts: tuple[str, ...]) -> int | None:
    """Find the index of 'results' or 'report_trace' in path parts."""
    for marker in _RESULTS_DIR_MARKERS:
        try:
            return parts.index(marker)
        except ValueError:
            continue
    return None


def _detect_benchmark_from_path(results_dir: Path) -> str | None:
    parts = results_dir.resolve().parts
    idx = _find_marker_index(parts)
    if idx is not None and idx + 1 < len(parts):
        return parts[idx + 1]
    return None


def _detect_benchmark_from_cases(cases: list[dict]) -> str | None:
    for c in cases:
        b = c.get("benchmark")
        if b:
            return b
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


def _resolve_extract_max_tokens() -> int:
    try:
        cfg = _load_eval_cfg()
        return cfg.get("evaluation", {}).get("extract_max_tokens", 16384)
    except Exception:
        return 16384


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


def _infer_report_meta(results_dir: Path, benchmark: str) -> dict:
    mode = ""
    parts = results_dir.resolve().parts
    idx = _find_marker_index(parts)
    if idx is not None and idx + 2 < len(parts):
        mode = parts[idx + 2]

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


# ---------------------------------------------------------------------------
# Single-round scoring
# ---------------------------------------------------------------------------

async def _score_one_case(
    case: dict,
    *,
    skip_extract: bool,
    extract_hint: str,
    judge_hint: str,
    extract_model: str | None,
    judge_model: str | None,
    extract_max_tokens: int,
    judge_max_tokens: int,
    extract_temperature: float | None,
    judge_temperature: float | None,
    adapter: Any,
) -> dict:
    """Run extract + judge on a single case. Returns case dict with _new_* fields."""
    from benchmark.iso_solve.core.extractor import extract_answer
    from benchmark.iso_solve.core.judge import judge_answer

    extracted = case.get("extracted_answer")
    if not skip_extract:
        extracted = await extract_answer(
            question=case["question"],
            model_output=case["_model_output"],
            extract_hint=extract_hint,
            model=extract_model,
            max_tokens=extract_max_tokens,
            temperature=extract_temperature,
        )
        if extracted is None:
            extracted = adapter.extract_fallback(case["_model_output"])
    elif extracted is None:
        extracted = case["_model_output"]

    correct, reasoning = await judge_answer(
        question=case["question"],
        predicted=extracted,
        ground_truth=case["ground_truth"],
        judge_hint=judge_hint,
        model=judge_model,
        max_tokens=judge_max_tokens,
        temperature=judge_temperature,
    )

    return {
        **case,
        "_new_extracted": extracted,
        "_new_correct": correct,
        "_new_reasoning": reasoning,
    }


async def _run_one_round(
    cases: list[dict],
    *,
    round_num: int,
    total_rounds: int,
    concurrency: int,
    skip_extract: bool,
    extract_hint: str,
    judge_hint: str,
    extract_model: str | None,
    judge_model: str | None,
    extract_max_tokens: int,
    judge_max_tokens: int,
    extract_temperature: float | None,
    judge_temperature: float | None,
    adapter: Any,
) -> list[dict]:
    """Run one round of extract+judge on all cases."""
    sem = asyncio.Semaphore(concurrency)
    completed = 0
    total = len(cases)

    async def _run(case: dict) -> dict:
        nonlocal completed
        async with sem:
            result = await _score_one_case(
                case,
                skip_extract=skip_extract,
                extract_hint=extract_hint,
                judge_hint=judge_hint,
                extract_model=extract_model,
                judge_model=judge_model,
                extract_max_tokens=extract_max_tokens,
                judge_max_tokens=judge_max_tokens,
                extract_temperature=extract_temperature,
                judge_temperature=judge_temperature,
                adapter=adapter,
            )
            completed += 1
            status = "OK" if result["_new_correct"] else "WRONG"
            if completed % 50 == 0 or completed == total:
                logger.info(
                    "  Round %d/%d [%d/%d] %s %s",
                    round_num, total_rounds, completed, total,
                    result.get("_subdir", ""), status,
                )
            return result

    results = await asyncio.gather(*[_run(c) for c in cases])
    return list(results)


# ---------------------------------------------------------------------------
# Report building
# ---------------------------------------------------------------------------

def _build_round_report(
    results: list[dict],
    breakdown_keys: list[str],
    meta_info: dict,
    round_num: int,
) -> dict:
    """Build a per-round report dict."""
    correct_count = sum(1 for r in results if r["_new_correct"])
    errors = sum(1 for r in results if r.get("error"))
    total = len(results)

    acc = correct_count / total if total else 0.0
    acc_pct = round(100.0 * acc, 2)
    ci = round(1.96 * math.sqrt(acc_pct * (100 - acc_pct) / total), 2) if total else 0.0

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
        "round": round_num,
        "overall": {
            "total": total,
            "correct": correct_count,
            "accuracy": round(acc, 4),
            "accuracy_pct": acc_pct,
            "confidence_interval": ci,
            "errors": errors,
        },
        "breakdowns": breakdowns,
        "results": [
            {
                "id": r.get("id"),
                "question": r.get("question", "")[:300],
                "ground_truth": r.get("ground_truth", ""),
                "extracted_answer": r.get("_new_extracted"),
                "correct": r["_new_correct"],
                "score": 1.0 if r["_new_correct"] else 0.0,
                "judge_reasoning": r["_new_reasoning"][:400],
                "error": r.get("error"),
                "metadata": r.get("metadata", {}),
            }
            for r in results
        ],
    }


def _compute_averages(
    round_reports: list[dict],
    breakdown_keys: list[str],
) -> dict:
    """Compute averaged scores across all rounds."""
    n_rounds = len(round_reports)

    overall_accs = [rr["overall"]["accuracy_pct"] for rr in round_reports]
    mean_acc = sum(overall_accs) / n_rounds
    std_acc = math.sqrt(sum((a - mean_acc) ** 2 for a in overall_accs) / n_rounds) if n_rounds > 1 else 0.0

    avg_correct = sum(rr["overall"]["correct"] for rr in round_reports) / n_rounds
    total = round_reports[0]["overall"]["total"]

    breakdown_avgs: dict[str, dict[str, dict]] = {}
    for rr in round_reports:
        for bucket_name, bucket in rr.get("breakdowns", {}).items():
            for val, stats in bucket.items():
                entry = breakdown_avgs.setdefault(bucket_name, {}).setdefault(
                    val, {"total": stats["total"], "accs": []}
                )
                acc_val = stats["correct"] / stats["total"] * 100 if stats["total"] else 0.0
                entry["accs"].append(acc_val)

    breakdown_summary: dict[str, dict[str, dict]] = {}
    for bucket_name, bucket in breakdown_avgs.items():
        for val, entry in bucket.items():
            accs = entry["accs"]
            mean = sum(accs) / len(accs) if accs else 0.0
            std = math.sqrt(sum((a - mean) ** 2 for a in accs) / len(accs)) if len(accs) > 1 else 0.0
            breakdown_summary.setdefault(bucket_name, {})[val] = {
                "total": entry["total"],
                "mean_accuracy_pct": round(mean, 2),
                "std_accuracy_pct": round(std, 2),
                "per_round_accuracy_pct": [round(a, 2) for a in accs],
            }

    per_question: dict[str, dict] = {}
    for rr in round_reports:
        for item in rr["results"]:
            qid = item["id"]
            entry = per_question.setdefault(qid, {
                "id": qid,
                "question": item["question"],
                "ground_truth": item["ground_truth"],
                "metadata": item["metadata"],
                "rounds": [],
            })
            entry["rounds"].append({
                "round": rr["round"],
                "extracted_answer": item["extracted_answer"],
                "correct": item["correct"],
                "judge_reasoning": item["judge_reasoning"],
            })

    for entry in per_question.values():
        correct_rounds = sum(1 for rd in entry["rounds"] if rd["correct"])
        entry["correct_rate"] = round(correct_rounds / n_rounds, 4)
        entry["correct_count"] = correct_rounds

    return {
        "n_rounds": n_rounds,
        "total_questions": total,
        "mean_correct": round(avg_correct, 2),
        "mean_accuracy_pct": round(mean_acc, 2),
        "std_accuracy_pct": round(std_acc, 2),
        "per_round_accuracy_pct": [round(a, 2) for a in overall_accs],
        "breakdowns": breakdown_summary,
        "per_question": list(per_question.values()),
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def _format_summary(meta_info: dict, averages: dict) -> str:
    lines = [
        "=" * 70,
        f"{meta_info['benchmark'].upper()} LLM Score — {averages['n_rounds']}-round average",
        f"Model: {meta_info['model']}",
        f"Mode:  {meta_info['mode']}",
        "=" * 70,
        "",
        f"Overall: {averages['mean_accuracy_pct']}% (+/- std {averages['std_accuracy_pct']}%)",
        f"  Total questions: {averages['total_questions']}",
        f"  Mean correct:    {averages['mean_correct']}",
        "",
        "Per-round accuracy:",
    ]
    for i, acc in enumerate(averages["per_round_accuracy_pct"], 1):
        lines.append(f"  Round {i}: {acc}%")

    for bucket_name in sorted(averages.get("breakdowns", {})):
        lines.append("")
        lines.append(f"--- {bucket_name} ---")
        bucket = averages["breakdowns"][bucket_name]
        for val in sorted(bucket):
            s = bucket[val]
            lines.append(
                f"  {val:30s}  n={s['total']:4d}  "
                f"mean={s['mean_accuracy_pct']:6.2f}%  std={s['std_accuracy_pct']:5.2f}%  "
                f"rounds={s['per_round_accuracy_pct']}"
            )

    lines.append("")
    lines.append("=" * 70)

    unstable = [
        q for q in averages["per_question"]
        if 0 < q["correct_count"] < averages["n_rounds"]
    ]
    if unstable:
        unstable.sort(key=lambda q: q["correct_rate"])
        lines.append("")
        lines.append(f"Unstable questions ({len(unstable)} / {averages['total_questions']}):")
        lines.append("-" * 70)
        for q in unstable:
            verdicts = " ".join(
                "OK" if rd["correct"] else "XX" for rd in q["rounds"]
            )
            lines.append(
                f"  {q['id'][:40]:40s}  {q['correct_count']}/{averages['n_rounds']}  [{verdicts}]"
            )
        lines.append("=" * 70)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core: score a single results directory
# ---------------------------------------------------------------------------

async def score_one_dir(
    results_dir: Path,
    *,
    rounds: int = 5,
    concurrency: int = 20,
    judge_model_override: str | None = None,
    judge_max_tokens: int = 16384,
    output_dir: Path | None = None,
) -> dict:
    """Score a single results directory. Returns the averages dict."""
    cases = _load_cases(results_dir)
    if not cases:
        logger.error("No cases found in %s/outputs/ — skipping", results_dir)
        return {}

    benchmark = (
        _detect_benchmark_from_path(results_dir)
        or _detect_benchmark_from_cases(cases)
    )
    if not benchmark:
        logger.error("Cannot detect benchmark for %s — skipping", results_dir)
        return {}

    adapter = _get_adapter(benchmark)
    meta_info = _infer_report_meta(results_dir, benchmark)

    judge_model = _resolve_judge_model(judge_model_override)
    extract_model = _resolve_extract_model()
    extract_max_tokens = _resolve_extract_max_tokens()
    extract_temperature, judge_temperature = _resolve_temperatures()

    label = f"{meta_info['benchmark']}/{meta_info['mode']}/{meta_info['model']}"
    logger.info(
        "[%s] Cases: %d | Rounds: %d | Judge: %s | Extract: %s | Concurrency: %d",
        label, len(cases), rounds, judge_model,
        extract_model or "(default)", concurrency,
    )

    if output_dir:
        out_dir = output_dir
    else:
        # Default: benchmark/iso_solve/report_trace/{benchmark}/{mode}/{run_name}/llm_score/
        trace_base = Path("benchmark/iso_solve/report_trace")
        run_name = results_dir.name
        if meta_info["benchmark"] and meta_info["mode"]:
            out_dir = trace_base / meta_info["benchmark"] / meta_info["mode"] / run_name / "llm_score"
        else:
            out_dir = results_dir / "llm_score"
    out_dir.mkdir(parents=True, exist_ok=True)

    round_reports: list[dict] = []

    for round_num in range(1, rounds + 1):
        logger.info("[%s] Round %d / %d", label, round_num, rounds)

        results = await _run_one_round(
            cases,
            round_num=round_num,
            total_rounds=rounds,
            concurrency=concurrency,
            skip_extract=adapter.skip_extract,
            extract_hint=adapter.extract_hint,
            judge_hint=adapter.judge_hint,
            extract_model=extract_model,
            judge_model=judge_model,
            extract_max_tokens=extract_max_tokens,
            judge_max_tokens=judge_max_tokens,
            extract_temperature=extract_temperature,
            judge_temperature=judge_temperature,
            adapter=adapter,
        )

        report = _build_round_report(
            results, adapter.breakdown_keys, meta_info, round_num,
        )
        round_reports.append(report)

        correct = report["overall"]["correct"]
        total = report["overall"]["total"]
        acc = report["overall"]["accuracy_pct"]
        logger.info(
            "[%s] Round %d result: %d/%d = %.2f%%", label, round_num, correct, total, acc,
        )

        round_path = out_dir / f"round_{round_num}.json"
        with open(round_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

    averages = _compute_averages(round_reports, adapter.breakdown_keys)

    avg_path = out_dir / "average.json"
    with open(avg_path, "w", encoding="utf-8") as f:
        json.dump({**meta_info, "averages": averages}, f, ensure_ascii=False, indent=2)

    summary_text = _format_summary(meta_info, averages)

    summary_path = out_dir / "summary.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary_text)

    print()
    print(summary_text)

    return {**meta_info, "averages": averages}


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def _load_jobs(jobs_path: Path) -> tuple[dict, list[dict]]:
    """Load score_jobs.yaml. Returns (defaults, jobs)."""
    import yaml

    with open(jobs_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    defaults = data.get("defaults", {})
    jobs = data.get("jobs", [])
    if not jobs:
        raise ValueError(f"No jobs defined in {jobs_path}")
    return defaults, jobs


async def _run_batch(
    jobs_path: Path,
    *,
    cli_rounds: int | None,
    cli_concurrency: int | None,
    cli_judge_model: str | None,
    cli_judge_max_tokens: int,
) -> None:
    """Run all jobs from a YAML file sequentially."""
    defaults, jobs = _load_jobs(jobs_path)

    total_jobs = len(jobs)
    logger.info("Loaded %d jobs from %s", total_jobs, jobs_path)

    all_summaries: list[str] = []

    for i, job in enumerate(jobs, 1):
        results_dir = Path(job["results_dir"])
        if not results_dir.exists():
            logger.error("[%d/%d] Directory not found: %s — skipping", i, total_jobs, results_dir)
            continue

        rounds = cli_rounds or job.get("rounds") or defaults.get("rounds", 5)
        concurrency = cli_concurrency or job.get("concurrency") or defaults.get("concurrency", 20)
        judge_model = cli_judge_model or job.get("judge_model")
        judge_max_tokens = job.get("judge_max_tokens", cli_judge_max_tokens)
        output_dir = Path(job["output"]) if job.get("output") else None

        logger.info(
            "=" * 70 + "\n" +
            f"  Job {i}/{total_jobs}: {results_dir}\n" +
            f"  rounds={rounds}  concurrency={concurrency}\n" +
            "=" * 70,
        )

        result = await score_one_dir(
            results_dir,
            rounds=rounds,
            concurrency=concurrency,
            judge_model_override=judge_model,
            judge_max_tokens=judge_max_tokens,
            output_dir=output_dir,
        )

        if result and "averages" in result:
            avg = result["averages"]
            bm = result.get("benchmark", "?")
            mode = result.get("mode", "?")
            model = result.get("model", "?")
            all_summaries.append(
                f"  {bm:12s} {mode:10s} {model:50s}  "
                f"{avg['mean_accuracy_pct']:6.2f}% +/- {avg['std_accuracy_pct']:.2f}%"
            )

    if all_summaries:
        print()
        print("=" * 70)
        print("  BATCH SUMMARY")
        print("=" * 70)
        print(f"  {'Benchmark':12s} {'Mode':10s} {'Model':50s}  {'Score':>14s}")
        print("-" * 70)
        for line in all_summaries:
            print(line)
        print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / "DeepTutor.env", override=False)
    load_dotenv(_PROJECT_ROOT / ".env", override=False)

    parser = argparse.ArgumentParser(
        description="Multi-round LLM scoring for existing benchmark results",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--results-dir", help="Path to a single results folder")
    group.add_argument("--jobs", help="Path to score_jobs.yaml for batch scoring")

    parser.add_argument("--rounds", type=int, default=None, help="Number of extract+judge rounds (default: 5)")
    parser.add_argument("--concurrency", type=int, default=None, help="Parallel LLM requests per round")
    parser.add_argument("--judge-model", default=None, help="Override judge model")
    parser.add_argument("--judge-max-tokens", type=int, default=16384, help="Max tokens for judge")
    parser.add_argument("--output", default=None, help="Output directory (default: <results-dir>/llm_score/)")
    args = parser.parse_args()

    if args.jobs:
        await _run_batch(
            Path(args.jobs),
            cli_rounds=args.rounds,
            cli_concurrency=args.concurrency,
            cli_judge_model=args.judge_model,
            cli_judge_max_tokens=args.judge_max_tokens,
        )
    else:
        results_dir = Path(args.results_dir)
        if not results_dir.exists():
            logger.error("Results directory not found: %s", results_dir)
            sys.exit(1)

        await score_one_dir(
            results_dir,
            rounds=args.rounds or 5,
            concurrency=args.concurrency or 20,
            judge_model_override=args.judge_model,
            judge_max_tokens=args.judge_max_tokens,
            output_dir=Path(args.output) if args.output else None,
        )


if __name__ == "__main__":
    asyncio.run(main())
