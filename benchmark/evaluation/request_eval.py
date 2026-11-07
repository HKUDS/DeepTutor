#!/usr/bin/env python3
"""
Request-based evaluation runner.

Evaluate request dataset records with:
  1) baseline model (direct LLM completion)
  2) DeepTutor tools (solve_question / generate_questions)

Each record contains:
  - solve_request.query
  - question_request.query

For each system and each task type (solve/question), this script:
  - generates output
  - runs LLM-as-judge scoring
  - stores detailed per-record result and aggregate summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure project root is importable when executed directly.
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT_FOR_IMPORT = _THIS_FILE.parents[2]
if str(_PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_FOR_IMPORT))

from benchmark.data_generation.llm_utils import call_llm_json
from src.services.llm import factory

logger = logging.getLogger("benchmark.request_eval")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_GENERATED_DIR = PROJECT_ROOT / "benchmark" / "data" / "generated"
DEFAULT_EVAL_DIR = PROJECT_ROOT / "benchmark" / "data" / "evaluations"
DEFAULT_WORKSPACE_DIR = PROJECT_ROOT / "benchmark" / "data" / "request_eval_workspaces"


def _normalize_space(text: str) -> str:
    return " ".join((text or "").strip().split())


def _discover_latest_dir(prefix: str, base_dir: Path) -> Path:
    candidates = [p for p in base_dir.glob(f"{prefix}_*") if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No {prefix}_* directories found under: {base_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _load_request_records(requests_dir: Path, limit: int = 0) -> list[dict[str, Any]]:
    files = sorted(p for p in requests_dir.glob("*.json") if not p.name.startswith("_"))
    if limit > 0:
        files = files[:limit]
    if not files:
        raise ValueError(f"No request records found in: {requests_dir}")

    records: list[dict[str, Any]] = []
    for fp in files:
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "solve_request" in data and "question_request" in data:
            records.append(data)
        else:
            logger.warning("Skip invalid request file: %s", fp)
    return records


def _load_profile_context_map(benchmark_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """
    Load minimal profile context from benchmark entries keyed by (kb_name, profile_id).
    """
    ctx_map: dict[tuple[str, str], dict[str, Any]] = {}
    files = sorted(p for p in benchmark_dir.glob("*.json") if not p.name.startswith("_"))
    for fp in files:
        try:
            with open(fp, encoding="utf-8") as f:
                entry = json.load(f)
        except Exception:
            continue

        if not isinstance(entry, dict):
            continue
        kb_name = str(entry.get("kb_name", ""))
        profile = entry.get("profile", {}) or {}
        profile_id = str(profile.get("profile_id", ""))
        if not kb_name or not profile_id:
            continue

        key = (kb_name, profile_id)
        task = entry.get("task", {}) or {}
        title = _normalize_space(str(task.get("title", "")))
        if key not in ctx_map:
            ctx_map[key] = {
                "profile": profile,
                "task_titles": [title] if title else [],
            }
        elif title and title not in ctx_map[key]["task_titles"]:
            ctx_map[key]["task_titles"].append(title)
    return ctx_map


def _format_profile_context(profile: dict[str, Any], task_titles: list[str]) -> str:
    ks = profile.get("knowledge_state", {}) or {}
    parts = [
        f"profile_id: {profile.get('profile_id', '')}",
        f"learning_purpose: {_normalize_space(str(profile.get('learning_purpose', '')))}",
        f"task_topics: {task_titles[:3]}",
        f"known_well: {ks.get('known_well', [])[:4]}",
        f"partially_known: {ks.get('partially_known', [])[:4]}",
        f"unknown: {ks.get('unknown', [])[:4]}",
    ]
    return "\n".join(parts)


def _format_question_from_deeptutor(result: dict[str, Any]) -> str:
    qs = result.get("questions", []) or []
    if not qs:
        return "(No question generated.)"
    q = qs[0] or {}
    stem = _normalize_space(str(q.get("question", "")))
    options = q.get("options", {})
    lines = [stem] if stem else ["(Empty question)"]
    if isinstance(options, dict):
        for k, v in options.items():
            lines.append(f"{k}. {v}")
    return "\n".join(lines)


async def _generate_with_baseline(query: str, task_type: str) -> str:
    if task_type == "solve":
        system_prompt = (
            "You are a helpful tutor. Solve the user's requested problem clearly "
            "with concise step-by-step reasoning."
        )
    else:
        system_prompt = (
            "You are a tutor creating practice problems. Generate exactly one practice question "
            "only. Do not include solution or hints."
        )
    text = await factory.complete(
        prompt=query,
        system_prompt=system_prompt,
        temperature=0.3,
        max_tokens=800,
    )
    return (text or "").strip()


async def _generate_with_deeptutor(
    *,
    task_type: str,
    kb_name: str,
    query: str,
    workspace: str,
    language: str,
) -> str:
    from benchmark.iso_solve.core.pipeline import run_solver_pipeline
    from benchmark.simulation.tools import generate_questions

    if task_type == "solve":
        solve_tools = ["code_execute", "reason"]
        result = await run_solver_pipeline(
            question=query,
            workspace=workspace,
            language=language,
            tools=solve_tools,
        )
        return (result.get("final_answer") or "").strip() or "(No answer generated.)"

    # iso_solve-style gating: if rag is disabled for question generation,
    # don't pass a KB name to avoid any accidental KB-side initialization.
    q_tools = {"rag": False, "web": False}
    q_kb_name = kb_name if q_tools["rag"] else ""
    q_result = await generate_questions(
        workspace=workspace,
        kb_name=q_kb_name,
        topic=query,
        num_questions=1,
        language=language,
        enable_memory=False,
        enable_rag=q_tools["rag"],
        enable_web=q_tools["web"],
    )
    return _format_question_from_deeptutor(q_result)


async def _judge_solve(
    *,
    query: str,
    output_text: str,
    profile_context: str,
) -> dict[str, Any]:
    system_prompt = (
        "You are a strict evaluator. Return valid JSON only."
    )
    user_prompt = (
        "Evaluate the quality of a tutoring solve response.\n\n"
        f"Request:\n{query}\n\n"
        f"Student context:\n{profile_context}\n\n"
        f"System output:\n{output_text}\n\n"
        "Return JSON only with keys:\n"
        "{\n"
        '  "relevance": 1-5,\n'
        '  "clarity": 1-5,\n'
        '  "helpfulness": 1-5,\n'
        '  "overall": 1-5,\n'
        '  "rationale": "short reason"\n'
        "}"
    )
    try:
        data = await call_llm_json(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=600,
        )
    except Exception as e:
        return {
            "relevance": None,
            "clarity": None,
            "helpfulness": None,
            "overall": None,
            "rationale": f"judge_failed: {e}",
            "error": str(e),
        }

    def _clamp(x: Any) -> int | None:
        try:
            v = int(x)
            return max(1, min(5, v))
        except Exception:
            return None

    return {
        "relevance": _clamp(data.get("relevance")),
        "clarity": _clamp(data.get("clarity")),
        "helpfulness": _clamp(data.get("helpfulness")),
        "overall": _clamp(data.get("overall")),
        "rationale": data.get("rationale", ""),
    }


async def _judge_question(
    *,
    query: str,
    output_text: str,
    profile_context: str,
) -> dict[str, Any]:
    system_prompt = "You are a strict evaluator. Return valid JSON only."
    user_prompt = (
        "Evaluate a generated practice question.\n\n"
        f"Request:\n{query}\n\n"
        f"Student context:\n{profile_context}\n\n"
        f"Generated output:\n{output_text}\n\n"
        "Return JSON only with keys:\n"
        "{\n"
        '  "request_following": 1-5,\n'
        '  "topic_relevance": 1-5,\n'
        '  "difficulty_fit": 1-5,\n'
        '  "clarity": 1-5,\n'
        '  "overall": 1-5,\n'
        '  "rationale": "short reason"\n'
        "}"
    )
    try:
        data = await call_llm_json(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=600,
        )
    except Exception as e:
        return {
            "request_following": None,
            "topic_relevance": None,
            "difficulty_fit": None,
            "clarity": None,
            "overall": None,
            "rationale": f"judge_failed: {e}",
            "error": str(e),
        }

    def _clamp(x: Any) -> int | None:
        try:
            v = int(x)
            return max(1, min(5, v))
        except Exception:
            return None

    return {
        "request_following": _clamp(data.get("request_following")),
        "topic_relevance": _clamp(data.get("topic_relevance")),
        "difficulty_fit": _clamp(data.get("difficulty_fit")),
        "clarity": _clamp(data.get("clarity")),
        "overall": _clamp(data.get("overall")),
        "rationale": data.get("rationale", ""),
    }


def _avg(nums: list[float]) -> float | None:
    return round(sum(nums) / len(nums), 4) if nums else None


def _build_summary(results: list[dict[str, Any]], systems: list[str]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for system in systems:
        solve_scores: list[float] = []
        question_scores: list[float] = []
        failures = 0
        for r in results:
            sr = (r.get("systems", {}).get(system, {}).get("solve", {}) or {})
            qr = (r.get("systems", {}).get(system, {}).get("question", {}) or {})
            s_overall = sr.get("judge", {}).get("overall")
            q_overall = qr.get("judge", {}).get("overall")
            if isinstance(s_overall, (int, float)):
                solve_scores.append(float(s_overall))
            if isinstance(q_overall, (int, float)):
                question_scores.append(float(q_overall))
            if sr.get("error") or qr.get("error"):
                failures += 1
        combined = [*solve_scores, *question_scores]
        summary[system] = {
            "num_records": len(results),
            "num_failures": failures,
            "solve_overall_avg": _avg(solve_scores),
            "question_overall_avg": _avg(question_scores),
            "combined_overall_avg": _avg(combined),
        }
    return summary


async def _eval_one_record(
    record: dict[str, Any],
    systems: list[str],
    profile_context_map: dict[tuple[str, str], dict[str, Any]],
    deeptutor_language: str,
    record_index: int = 0,
    total_records: int = 0,
) -> dict[str, Any]:
    kb_name = str(record.get("kb_name", ""))
    profile_id = str(record.get("profile_id", ""))
    profile_entry_id = str(record.get("profile_entry_id", f"{kb_name}_{profile_id}"))

    solve_query = ((record.get("solve_request") or {}).get("query") or "").strip()
    question_query = ((record.get("question_request") or {}).get("query") or "").strip()

    ctx = profile_context_map.get((kb_name, profile_id), {})
    profile = ctx.get("profile", {}) or {}
    task_titles = ctx.get("task_titles", []) or []
    profile_context = _format_profile_context(profile, task_titles)

    output = {
        "profile_entry_id": profile_entry_id,
        "kb_name": kb_name,
        "profile_id": profile_id,
        "topic": record.get("topic", ""),
        "systems": {},
    }
    prefix = f"[record {record_index}/{total_records} {profile_entry_id}]"
    logger.info("%s start", prefix)

    for system in systems:
        system_out: dict[str, Any] = {}
        logger.info("%s [%s] start", prefix, system)

        # solve
        t0 = time.perf_counter()
        solve_text = ""
        solve_error = None
        logger.info("%s [%s] solve.generate start", prefix, system)
        try:
            if system == "baseline":
                solve_text = await _generate_with_baseline(solve_query, "solve")
            else:
                ws = str(DEFAULT_WORKSPACE_DIR / profile_entry_id / "deeptutor")
                solve_text = await _generate_with_deeptutor(
                    task_type="solve",
                    kb_name=kb_name,
                    query=solve_query,
                    workspace=ws,
                    language=deeptutor_language,
                )
        except Exception as e:
            solve_error = str(e)
            solve_text = ""
        logger.info(
            "%s [%s] solve.generate done in %.2fs%s",
            prefix,
            system,
            time.perf_counter() - t0,
            f" (error: {solve_error})" if solve_error else "",
        )
        logger.info("%s [%s] solve.judge start", prefix, system)
        solve_judge = await _judge_solve(
            query=solve_query,
            output_text=solve_text,
            profile_context=profile_context,
        )
        logger.info(
            "%s [%s] solve.judge done (overall=%s)",
            prefix,
            system,
            solve_judge.get("overall"),
        )
        system_out["solve"] = {
            "query": solve_query,
            "output": solve_text,
            "judge": solve_judge,
            "elapsed_sec": round(time.perf_counter() - t0, 3),
            "error": solve_error,
        }

        # question
        t1 = time.perf_counter()
        question_text = ""
        question_error = None
        logger.info("%s [%s] question.generate start", prefix, system)
        try:
            if system == "baseline":
                question_text = await _generate_with_baseline(question_query, "question")
            else:
                ws = str(DEFAULT_WORKSPACE_DIR / profile_entry_id / "deeptutor")
                question_text = await _generate_with_deeptutor(
                    task_type="question",
                    kb_name=kb_name,
                    query=question_query,
                    workspace=ws,
                    language=deeptutor_language,
                )
        except Exception as e:
            question_error = str(e)
            question_text = ""
        logger.info(
            "%s [%s] question.generate done in %.2fs%s",
            prefix,
            system,
            time.perf_counter() - t1,
            f" (error: {question_error})" if question_error else "",
        )
        logger.info("%s [%s] question.judge start", prefix, system)
        question_judge = await _judge_question(
            query=question_query,
            output_text=question_text,
            profile_context=profile_context,
        )
        logger.info(
            "%s [%s] question.judge done (overall=%s)",
            prefix,
            system,
            question_judge.get("overall"),
        )
        system_out["question"] = {
            "query": question_query,
            "output": question_text,
            "judge": question_judge,
            "elapsed_sec": round(time.perf_counter() - t1, 3),
            "error": question_error,
        }

        output["systems"][system] = system_out
        logger.info(
            "%s [%s] done (solve=%.2fs question=%.2fs)",
            prefix,
            system,
            system_out["solve"]["elapsed_sec"],
            system_out["question"]["elapsed_sec"],
        )
    logger.info("%s complete", prefix)
    return output


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate request dataset with baseline and DeepTutor.")
    parser.add_argument(
        "--requests-dir",
        default=None,
        help="Request dataset directory (requests_YYYYMMDD_HHMMSS). Default: latest.",
    )
    parser.add_argument(
        "--benchmark-dir",
        default=None,
        help="Benchmark entries directory for profile context (benchmark_...). Default: latest.",
    )
    parser.add_argument(
        "--system",
        choices=["baseline", "deeptutor", "both"],
        default="both",
        help="Which system to evaluate (default: both).",
    )
    parser.add_argument(
        "--deeptutor-language",
        default="en",
        help="Language used by DeepTutor tools (default: en).",
    )
    parser.add_argument("--limit", type=int, default=0, help="Only evaluate first N records.")
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=2,
        help="Max concurrent records to evaluate (default: 2).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (default: benchmark/data/evaluations/request_eval_<timestamp>.json).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.requests_dir:
        requests_dir = Path(args.requests_dir)
        if not requests_dir.is_absolute():
            requests_dir = (PROJECT_ROOT / requests_dir).resolve()
    else:
        requests_dir = _discover_latest_dir("requests", DEFAULT_GENERATED_DIR)

    if args.benchmark_dir:
        benchmark_dir = Path(args.benchmark_dir)
        if not benchmark_dir.is_absolute():
            benchmark_dir = (PROJECT_ROOT / benchmark_dir).resolve()
    else:
        benchmark_dir = _discover_latest_dir("benchmark", DEFAULT_GENERATED_DIR)

    records = _load_request_records(requests_dir, args.limit)
    profile_context_map = _load_profile_context_map(benchmark_dir)
    systems = ["baseline", "deeptutor"] if args.system == "both" else [args.system]

    logger.info("Requests dir: %s", requests_dir)
    logger.info("Benchmark dir: %s", benchmark_dir)
    logger.info("Records: %d | Systems: %s", len(records), systems)

    sem = asyncio.Semaphore(max(1, args.max_concurrency))

    async def _run_with_sem(i: int, rec: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            t_rec = time.perf_counter()
            return await _eval_one_record(
                record=rec,
                systems=systems,
                profile_context_map=profile_context_map,
                deeptutor_language=args.deeptutor_language,
                record_index=i + 1,
                total_records=len(records),
            )

    results = await asyncio.gather(*[_run_with_sem(i, r) for i, r in enumerate(records)])
    summary = _build_summary(results, systems)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        out_path = Path(args.output)
        if not out_path.is_absolute():
            out_path = (PROJECT_ROOT / out_path).resolve()
    else:
        DEFAULT_EVAL_DIR.mkdir(parents=True, exist_ok=True)
        out_path = DEFAULT_EVAL_DIR / f"request_eval_{timestamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "timestamp": timestamp,
        "requests_dir": str(requests_dir),
        "benchmark_dir": str(benchmark_dir),
        "systems": systems,
        "num_records": len(results),
        "summary": summary,
        "results": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\nDone.")
    print(f"Output: {out_path}")
    for system in systems:
        s = summary.get(system, {})
        print(
            f"[{system}] solve_avg={s.get('solve_overall_avg')} | "
            f"question_avg={s.get('question_overall_avg')} | "
            f"combined_avg={s.get('combined_overall_avg')} | "
            f"failures={s.get('num_failures')}"
        )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()

