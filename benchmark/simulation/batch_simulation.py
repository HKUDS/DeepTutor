#!/usr/bin/env python3
"""
Batch Simulation & Evaluation — end-to-end pipeline.

Given a profile directory (from batch_profiles.py), for every profile:
1. Generate benchmark entries (gaps + tasks)
2. Run simulation with mock tutor and/or DeepTutor
3. Evaluate both transcripts
4. Output comparison summary

Usage:
    python -m benchmark.simulation.batch_simulation \
        --profiles-dir benchmark/data/generated/profiles_20260304_161506

    python -m benchmark.simulation.batch_simulation \
        --profiles-dir benchmark/data/generated/profiles_20260304_161506 \
        --concurrency 6 --max-turns 15 --backends mock,deep_tutor
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# Locks for entry generation to avoid race conditions between backends for the same profile
_entry_gen_locks: dict[str, asyncio.Lock] = {}

_THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = _THIS_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(PROJECT_ROOT / ".env", override=False)

import yaml

logger = logging.getLogger("benchmark.batch_sim")

DEFAULT_CONFIG = PROJECT_ROOT / "benchmark" / "config" / "benchmark_config.yaml"


# ======================================================================
# Stage 1: Entry generation (gaps + tasks per profile)
# ======================================================================


async def _generate_entries_for_profile(
    kb_name: str,
    profile: dict,
    knowledge_scope: dict,
    cfg: dict,
    kb_base_dir: str,
) -> list[dict]:
    """Generate benchmark entries (gaps + tasks) for a single profile.

    Mirrors pipeline.py stages 4-5 for one profile.
    """
    from benchmark.data_generation.content_loader import load_page_content_for_profile
    from benchmark.data_generation.gap_generator import (
        generate_gaps,
        generate_gaps_from_pages,
    )
    from benchmark.data_generation.task_generator import (
        MIN_GAPS_PER_TASK,
        generate_tasks_with_partition,
    )

    gap_cfg = cfg.get("gap_generation", {})
    task_cfg = cfg.get("task_generation", {})
    profile_id = profile.get("profile_id", "unknown")

    severity_weights: dict[str, float] = {}
    for level in gap_cfg.get("severity_levels", []):
        severity_weights[level["name"]] = level["weight"]

    min_tasks = task_cfg.get("min_tasks_per_profile", 3)
    gaps_per_batch = max(task_cfg.get("gaps_per_batch", 3), MIN_GAPS_PER_TASK)
    llm_retry_attempts = max(1, int(task_cfg.get("llm_retry_attempts", 3)))
    llm_retry_delay_sec = max(0.0, float(task_cfg.get("llm_retry_delay_sec", 1.5)))

    use_content_list = gap_cfg.get("use_content_list", False)
    page_content: dict[int, str] | None = None
    if use_content_list:
        num_pages = gap_cfg.get("pages_per_profile", 10)
        result = load_page_content_for_profile(
            kb_base_dir=kb_base_dir,
            kb_name=kb_name,
            num_pages=num_pages,
            profile_id=profile_id,
        )
        if result:
            page_content, _ = result
        else:
            logger.warning(
                "  No content_list for %s, falling back to scope-based gaps",
                kb_name,
            )

    all_gaps: list[dict] = []
    all_tasks: list[dict] = []
    task_index_offset = 0
    max_batches = 10

    async def _run_with_retry(op_name: str, batch_num: int, coro_factory):
        last_error: Exception | None = None
        for attempt in range(1, llm_retry_attempts + 1):
            try:
                return await coro_factory()
            except Exception as e:
                last_error = e
                if attempt >= llm_retry_attempts:
                    raise
                wait_sec = llm_retry_delay_sec * attempt
                logger.warning(
                    "  %s batch %d %s failed (%d/%d): %s; retrying in %.1fs",
                    profile_id,
                    batch_num,
                    op_name,
                    attempt,
                    llm_retry_attempts,
                    e,
                    wait_sec,
                )
                if wait_sec > 0:
                    await asyncio.sleep(wait_sec)
        if last_error is not None:
            raise last_error

    for batch_num in range(1, max_batches + 1):
        if len(all_tasks) >= min_tasks:
            break

        try:
            if page_content:
                async def _gen_gaps():
                    return await generate_gaps_from_pages(
                        page_content=page_content,
                        student_profile=profile,
                        num_gaps=gaps_per_batch,
                        severity_weights=severity_weights or None,
                        gap_id_offset=len(all_gaps),
                    )
            else:
                async def _gen_gaps():
                    return await generate_gaps(
                        knowledge_scope=knowledge_scope,
                        student_profile=profile,
                        num_gaps=gaps_per_batch,
                        severity_weights=severity_weights or None,
                        gap_id_offset=len(all_gaps),
                    )

            new_gaps = await _run_with_retry("gap_generation", batch_num, _gen_gaps)

            if not new_gaps:
                logger.warning("  No new gaps for %s, stopping", profile_id)
                break

            async def _gen_tasks():
                return await generate_tasks_with_partition(
                    knowledge_scope=knowledge_scope,
                    student_profile=profile,
                    knowledge_gaps=new_gaps,
                    task_index_offset=task_index_offset,
                )

            tasks = await _run_with_retry("task_generation", batch_num, _gen_tasks)

            # Only commit this batch's gaps/tasks after both generation steps succeed.
            all_gaps.extend(new_gaps)
            all_tasks.extend(tasks)
            task_index_offset += len(tasks)

            logger.info(
                "  %s: batch %d → %d/%d tasks",
                profile_id,
                batch_num,
                len(all_tasks),
                min_tasks,
            )
        except Exception as e:
            logger.error("  Entry generation failed for %s batch %d: %s", profile_id, batch_num, e)
            continue

    gap_by_id = {g["gap_id"]: g for g in all_gaps if "gap_id" in g}
    entries: list[dict] = []
    for task in all_tasks:
        task_id = task.get("task_id", "unknown")
        target_gap_ids = task.get("target_gaps", [])
        target_gaps = [gap_by_id[gid] for gid in target_gap_ids if gid in gap_by_id]

        entry = {
            "entry_id": f"{kb_name}_{profile_id}_{task_id}",
            "kb_name": kb_name,
            "profile": profile,
            "gaps": target_gaps,
            "task": task,
        }
        if page_content is not None:
            entry["source_content"] = page_content
        entries.append(entry)

    logger.info(
        "  %s: generated %d entries (%d gaps, %d tasks)",
        profile_id,
        len(entries),
        len(all_gaps),
        len(all_tasks),
    )
    return entries


def _save_entries(entries: list[dict], entries_dir: Path) -> list[str]:
    """Save entries as individual JSON files + JSONL. Returns list of file paths."""
    entries_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for entry in entries:
        entry_id = entry.get("entry_id", "unknown")
        path = entries_dir / f"{entry_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        paths.append(str(path))

    jsonl_path = entries_dir / "_all_entries.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return paths


def _load_entries(entries_dir: Path) -> list[dict]:
    """Load entries from a JSONL file."""
    jsonl_path = entries_dir / "_all_entries.jsonl"
    entries: list[dict] = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


# ======================================================================
# Stage 2: Simulation (multi-session per profile per backend)
# ======================================================================


async def _simulate_profile(
    profile_id: str,
    entries: list[dict],
    backend: Literal["deep_tutor", "mock"],
    output_dir: Path,
    max_turns: int,
    language: str,
    evolve_profile: bool,
    verbose: bool = False,
) -> dict:
    """Run multi-session simulation for one profile with one backend.

    Replicates the logic of run_multi_session but saves to our controlled paths.
    Returns the combined multi-session result dict.
    """
    from benchmark.simulation.conversation import (
        _run_single_session,
        _summarize_session,
    )
    from benchmark.simulation.profile_evolver import evolve_profile as evolve_profile_fn

    workspace = str(output_dir / "workspaces" / backend / profile_id)

    prior_sessions_summary: list[str] = []
    current_profile = entries[0].get("profile", {})
    sessions_results: list[dict] = []

    for i, base_entry in enumerate(entries):
        session_num = i + 1
        entry = dict(base_entry)

        if evolve_profile and i > 0:
            prev_profile = entries[i - 1].get("profile", {})
            resolved = entries[i - 1].get("gaps", [])
            current_profile = evolve_profile_fn(prev_profile, resolved)
        entry["profile"] = current_profile

        prior_ctx = "\n".join(prior_sessions_summary) if prior_sessions_summary else None

        logger.info(
            "[%s] %s session %d/%d: %s",
            backend,
            profile_id,
            session_num,
            len(entries),
            entry.get("entry_id", "?"),
        )

        try:
            if verbose:
                result = await _run_single_session(
                    entry=entry,
                    max_turns=max_turns,
                    auto=True,
                    use_editor=False,
                    auto_backend=backend,
                    deeptutor_workspace=workspace,
                    deeptutor_language=language,
                    prior_sessions_summary=prior_ctx,
                )
            else:
                with contextlib.redirect_stdout(io.StringIO()):
                    result = await _run_single_session(
                        entry=entry,
                        max_turns=max_turns,
                        auto=True,
                        use_editor=False,
                        auto_backend=backend,
                        deeptutor_workspace=workspace,
                        deeptutor_language=language,
                        prior_sessions_summary=prior_ctx,
                    )

            logger.info(
                "  [%s] %s session %d done: %d turns",
                backend,
                profile_id,
                session_num,
                result.get("actual_turns", 0),
            )
        except Exception as e:
            logger.error(
                "  [%s] %s session %d failed: %s",
                backend,
                profile_id,
                session_num,
                e,
            )
            result = {
                "entry_id": entry.get("entry_id", f"session_{session_num}"),
                "transcript": [],
                "entry": entry,
                "actual_turns": 0,
                "practice_questions": [],
                "error": str(e),
            }

        task = entry.get("task", {})
        summary = _summarize_session(result.get("transcript", []), task, session_num)
        prior_sessions_summary.append(summary)
        sessions_results.append(result)

    combined = {
        "profile_id": profile_id,
        "backend": backend,
        "timestamp": datetime.now().isoformat(),
        "mode": "auto",
        "evolve_profile": evolve_profile,
        "num_sessions": len(sessions_results),
        "sessions": [
            {
                "entry_id": r["entry_id"],
                "actual_turns": r["actual_turns"],
                "transcript": r.get("transcript", []),
                "entry": r["entry"],
                "practice_questions": r.get("practice_questions", []),
            }
            for r in sessions_results
        ],
    }

    transcript_dir = output_dir / "transcripts" / backend
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript_dir / f"{profile_id}.json"
    with open(transcript_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    logger.info("  Transcript saved → %s", transcript_path)
    return combined


# ======================================================================
# Stage 3: Evaluation
# ======================================================================


async def _evaluate_profile_transcript(
    transcript_path: Path,
    eval_output_dir: Path,
    temperature: float = 0.2,
) -> dict:
    """Evaluate a profile's transcript and save results."""
    from benchmark.evaluation.evaluator import evaluate_transcript

    eval_output_dir.mkdir(parents=True, exist_ok=True)

    result = await evaluate_transcript(
        transcript_path=transcript_path,
        temperature=temperature,
    )

    eval_path = eval_output_dir / f"{transcript_path.stem}_eval.json"
    with open(eval_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("  Evaluation saved → %s", eval_path)
    return result


def _extract_eval_summary(eval_result: dict) -> dict:
    """Extract key metrics from full evaluation result for the summary."""
    if "error" in eval_result:
        return {"error": eval_result["error"]}

    agg = eval_result.get("aggregate", {})
    return {
        "num_sessions": eval_result.get("num_sessions", 0),
        "turn_count": agg.get("turn_count", {}),
        "source_faithfulness": agg.get("source_faithfulness", {}),
        "teaching_quality": agg.get("teaching_quality", {}),
        "practice_questions": agg.get("practice_questions", {}),
    }


# ======================================================================
# Orchestration: one profile at a time (backends serial)
# ======================================================================


async def _process_one_profile(
    kb_name: str,
    profile: dict,
    scope: dict,
    cfg: dict,
    kb_base_dir: str,
    backends: list[str],
    output_dir: Path,
    semaphore: asyncio.Semaphore,
    max_turns: int,
    language: str,
    evolve_profile: bool,
    eval_temperature: float,
    skip_eval: bool,
    verbose: bool,
) -> dict:
    """Process one profile: generate entries, then run backends serially."""
    async with semaphore:
        profile_id = profile.get("profile_id", "unknown")
        profile_result: dict[str, Any] = {
            "profile_id": profile_id,
            "kb_name": kb_name,
            "num_entries": 0,
            "simulations": {},
            "evaluations": {},
        }

        # ----------------------------------------------------------
        # Step 1: Generate entries (shared across backends — lock to avoid race)
        # ----------------------------------------------------------
        entries_dir = output_dir / "entries" / kb_name / profile_id
        lock_key = f"{kb_name}/{profile_id}"
        if lock_key not in _entry_gen_locks:
            _entry_gen_locks[lock_key] = asyncio.Lock()

        async with _entry_gen_locks[lock_key]:
            if (entries_dir / "_all_entries.jsonl").exists():
                logger.info("SKIP entry generation (exists): %s", profile_id)
                entries = _load_entries(entries_dir)
            else:
                try:
                    entries = await _generate_entries_for_profile(
                        kb_name=kb_name,
                        profile=profile,
                        knowledge_scope=scope,
                        cfg=cfg,
                        kb_base_dir=kb_base_dir,
                    )
                    _save_entries(entries, entries_dir)
                except Exception as e:
                    logger.error(
                        "Entry generation failed for %s: %s", profile_id, e
                    )
                    return profile_result

        if not entries:
            logger.warning("No entries for %s, skipping simulation", profile_id)
            return profile_result

        profile_result["num_entries"] = len(entries)

        # ----------------------------------------------------------
        # Step 2 & 3: Simulate + Evaluate each backend serially
        # ----------------------------------------------------------
        for backend in backends:
            transcript_path = output_dir / "transcripts" / backend / f"{profile_id}.json"

            if transcript_path.exists():
                logger.info("SKIP simulation (exists): %s / %s", profile_id, backend)
                sim_result = json.loads(transcript_path.read_text("utf-8"))
            else:
                try:
                    sim_result = await _simulate_profile(
                        profile_id=profile_id,
                        entries=entries,
                        backend=backend,
                        output_dir=output_dir,
                        max_turns=max_turns,
                        language=language,
                        evolve_profile=evolve_profile,
                        verbose=verbose,
                    )
                except Exception as e:
                    logger.error(
                        "Simulation failed for %s / %s: %s",
                        profile_id,
                        backend,
                        e,
                    )
                    sim_result = {"error": str(e)}

            profile_result["simulations"][backend] = {
                "num_sessions": sim_result.get("num_sessions", 0),
                "transcript_path": str(transcript_path),
            }

            if (
                not skip_eval
                and transcript_path.exists()
                and "error" not in sim_result
            ):
                eval_dir = output_dir / "evaluations" / backend
                eval_path = eval_dir / f"{profile_id}_eval.json"
                if eval_path.exists():
                    logger.info(
                        "SKIP evaluation (exists): %s / %s", profile_id, backend
                    )
                    eval_result = json.loads(eval_path.read_text("utf-8"))
                else:
                    try:
                        eval_result = await _evaluate_profile_transcript(
                            transcript_path=transcript_path,
                            eval_output_dir=eval_dir,
                            temperature=eval_temperature,
                        )
                    except Exception as e:
                        logger.error(
                            "Evaluation failed for %s / %s: %s",
                            profile_id,
                            backend,
                            e,
                        )
                        eval_result = {"error": str(e)}

                profile_result["evaluations"][backend] = _extract_eval_summary(eval_result)

        return profile_result


# ======================================================================
# Summary
# ======================================================================


def _build_and_print_summary(
    all_kb_results: list[dict],
    backends: list[str],
    output_dir: Path,
) -> dict:
    """Build aggregate summary across all KBs and print comparison table."""
    summary_by_backend: dict[str, dict[str, Any]] = {}

    for backend in backends:
        total_profiles = 0
        total_sessions = 0
        faith_scores: list[float] = []
        personalization_scores: list[float] = []
        applicability_scores: list[float] = []
        vividness_scores: list[float] = []
        logical_depth_scores: list[float] = []
        pq_scores: list[float] = []
        total_turns = 0

        for kb_res in all_kb_results:
            for profile_res in kb_res.get("profiles", []):
                sim = profile_res.get("simulations", {}).get(backend, {})
                n_sess = sim.get("num_sessions", 0)
                if n_sess == 0:
                    continue
                total_profiles += 1
                total_sessions += n_sess

                ev = profile_res.get("evaluations", {}).get(backend, {})
                tc = ev.get("turn_count", {})
                total_turns += tc.get("paired_turns_total", 0)

                sf = ev.get("source_faithfulness", {})
                avg = sf.get("avg_score_overall")
                if isinstance(avg, (int, float)):
                    faith_scores.append(float(avg))

                tq = ev.get("teaching_quality", {})
                for key, bucket in [
                    ("avg_personalization_overall", personalization_scores),
                    ("avg_applicability_overall", applicability_scores),
                    ("avg_vividness_overall", vividness_scores),
                    ("avg_logical_depth_overall", logical_depth_scores),
                ]:
                    v = tq.get(key)
                    if isinstance(v, (int, float)):
                        bucket.append(float(v))

                pq = ev.get("practice_questions", {})
                metric_vals = []
                for key in [
                    "avg_fitness",
                    "avg_groundedness",
                    "avg_diversity",
                    "avg_answer_quality",
                    "avg_cross_concept",
                ]:
                    v = pq.get(key)
                    if isinstance(v, (int, float)):
                        metric_vals.append(float(v))
                if metric_vals:
                    pq_scores.append(sum(metric_vals) / len(metric_vals))

        summary_by_backend[backend] = {
            "total_profiles": total_profiles,
            "total_sessions": total_sessions,
            "total_paired_turns": total_turns,
            "avg_faithfulness": (
                round(sum(faith_scores) / len(faith_scores), 4)
                if faith_scores
                else None
            ),
            "avg_personalization": round(sum(personalization_scores) / len(personalization_scores), 4) if personalization_scores else None,
            "avg_applicability": round(sum(applicability_scores) / len(applicability_scores), 4) if applicability_scores else None,
            "avg_vividness": round(sum(vividness_scores) / len(vividness_scores), 4) if vividness_scores else None,
            "avg_logical_depth": round(sum(logical_depth_scores) / len(logical_depth_scores), 4) if logical_depth_scores else None,
            "avg_practice_quality": round(sum(pq_scores) / len(pq_scores), 4) if pq_scores else None,
        }

    # Print comparison
    print("\n" + "=" * 70)
    print("BATCH SIMULATION & EVALUATION SUMMARY")
    print("=" * 70)

    for backend, stats in summary_by_backend.items():
        print(f"\n--- {backend.upper()} ---")
        print(f"  Profiles evaluated    : {stats['total_profiles']}")
        print(f"  Total sessions        : {stats['total_sessions']}")
        print(f"  Total paired turns    : {stats['total_paired_turns']}")
        faith = stats["avg_faithfulness"]
        print(f"  Avg faithfulness (1-5): {faith if faith is not None else 'N/A'}")
        print(f"  Avg personalization   : {stats['avg_personalization'] if stats['avg_personalization'] is not None else 'N/A'}")
        print(f"  Avg applicability     : {stats['avg_applicability'] if stats['avg_applicability'] is not None else 'N/A'}")
        print(f"  Avg vividness         : {stats['avg_vividness'] if stats['avg_vividness'] is not None else 'N/A'}")
        print(f"  Avg logical depth     : {stats['avg_logical_depth'] if stats['avg_logical_depth'] is not None else 'N/A'}")
        print(f"  Avg practice quality  : {stats['avg_practice_quality'] if stats['avg_practice_quality'] is not None else 'N/A'}")

    print("\n" + "=" * 70)

    full_summary = {
        "timestamp": datetime.now().isoformat(),
        "output_dir": str(output_dir),
        "backends": backends,
        "aggregate": summary_by_backend,
        "per_kb": all_kb_results,
    }

    summary_path = output_dir / "_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(full_summary, f, ensure_ascii=False, indent=2)
    print(f"\nFull summary → {summary_path}")

    return full_summary


# ======================================================================
# CLI
# ======================================================================


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Batch simulation & evaluation for all profiles"
    )
    parser.add_argument(
        "--profiles-dir",
        required=True,
        help="Directory containing profile JSON files (from batch_profiles.py)",
    )
    parser.add_argument(
        "--kb-dir",
        default="data/knowledge_bases",
        help="Knowledge bases directory (default: data/knowledge_bases)",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Benchmark config path (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: benchmark/data/batch_sim_{timestamp})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Max parallel profile tasks (default: 6)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=30,
        help="Max student turns per session (default: 30)",
    )
    parser.add_argument(
        "--backends",
        default="mock,deep_tutor",
        help="Comma-separated backends to test (default: mock,deep_tutor)",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="DeepTutor language (default: en)",
    )
    parser.add_argument(
        "--no-evolve",
        action="store_true",
        help="Disable profile evolution between sessions",
    )
    parser.add_argument(
        "--skip-eval",
        action="store_true",
        help="Skip transcript evaluation (simulation only)",
    )
    parser.add_argument(
        "--skip-sim",
        action="store_true",
        help="Skip simulation (entry generation only)",
    )
    parser.add_argument(
        "--eval-temperature",
        type=float,
        default=0.2,
        help="LLM temperature for evaluation (default: 0.2)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show per-turn conversation output (noisy with parallel KBs)",
    )

    args = parser.parse_args()

    # Suppress noisy logs from RAG/LLM internals during auto simulation
    from benchmark.simulation.conversation import _suppress_noisy_auto_logs

    _suppress_noisy_auto_logs()
    # Re-enable our own loggers after global suppression
    logging.getLogger("benchmark.batch_sim").setLevel(logging.INFO)
    logging.getLogger("benchmark.conversation").setLevel(logging.INFO)
    logging.getLogger("benchmark.evaluation").setLevel(logging.INFO)
    logging.getLogger("benchmark.pipeline").setLevel(logging.INFO)
    logging.getLogger("benchmark.gap_generator").setLevel(logging.INFO)
    logging.getLogger("benchmark.task_generator").setLevel(logging.INFO)

    # Resolve paths
    profiles_dir = Path(args.profiles_dir)
    if not profiles_dir.is_absolute():
        profiles_dir = (PROJECT_ROOT / profiles_dir).resolve()

    kb_base_dir = Path(args.kb_dir)
    if not kb_base_dir.is_absolute():
        kb_base_dir = (PROJECT_ROOT / kb_base_dir).resolve()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = (PROJECT_ROOT / cfg_path).resolve()
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    backends = [b.strip() for b in args.backends.split(",") if b.strip()]

    if args.output_dir:
        output_dir = Path(args.output_dir)
        if not output_dir.is_absolute():
            output_dir = (PROJECT_ROOT / output_dir).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = (
            PROJECT_ROOT / "benchmark" / "data" / f"batch_sim_{timestamp}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load profile data
    profile_files = sorted(profiles_dir.glob("*.json"))
    profile_files = [f for f in profile_files if not f.name.startswith("_")]
    if not profile_files:
        print(f"No profile files found in {profiles_dir}")
        sys.exit(1)

    all_kb_data: list[dict] = []
    for pf in profile_files:
        try:
            with open(pf, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("profiles") and data.get("knowledge_scope"):
                all_kb_data.append(data)
        except Exception as e:
            logger.warning("Skip %s: %s", pf.name, e)

    if not all_kb_data:
        print("No valid profile files found (need 'profiles' and 'knowledge_scope' keys)")
        sys.exit(1)

    total_profiles = sum(len(d["profiles"]) for d in all_kb_data)
    print(f"KBs: {len(all_kb_data)} | Profiles: {total_profiles} | "
          f"Backends: {backends} | Concurrency: {args.concurrency}")
    print(f"Output: {output_dir}")
    for d in all_kb_data:
        print(f"  - {d['kb_name']}: {len(d['profiles'])} profiles")
    print()

    if args.skip_sim:
        backends_for_sim: list[str] = []
        logger.info("--skip-sim: will only generate entries, no simulation/evaluation")
    else:
        backends_for_sim = backends

    semaphore = asyncio.Semaphore(args.concurrency)

    if not backends_for_sim:
        # --skip-sim: only generate entries, one task per unique profile
        async def _gen_entries_only(kb_data: dict, profile: dict) -> None:
            async with semaphore:
                kb_name = kb_data["kb_name"]
                profile_id = profile.get("profile_id", "unknown")
                entries_dir = output_dir / "entries" / kb_name / profile_id
                if (entries_dir / "_all_entries.jsonl").exists():
                    logger.info("SKIP entry generation (exists): %s/%s", kb_name, profile_id)
                    return
                try:
                    entries = await _generate_entries_for_profile(
                        kb_name=kb_name,
                        profile=profile,
                        knowledge_scope=kb_data["knowledge_scope"],
                        cfg=cfg,
                        kb_base_dir=str(kb_base_dir),
                    )
                    _save_entries(entries, entries_dir)
                except Exception as e:
                    logger.error("Entry generation failed for %s/%s: %s", kb_name, profile_id, e)

        tasks = [
            _gen_entries_only(data, profile)
            for data in all_kb_data
            for profile in data["profiles"]
        ]
        logger.info("Launching %d entry-generation tasks (concurrency=%d)", len(tasks), args.concurrency)
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Entry generation complete. Output: %s", output_dir)
        return

    # Build tasks: one per profile (each task runs backends serially)
    tasks = []
    for data in all_kb_data:
        kb_name = data["kb_name"]
        scope = data["knowledge_scope"]
        for profile in data["profiles"]:
            tasks.append(
                _process_one_profile(
                    kb_name=kb_name,
                    profile=profile,
                    scope=scope,
                    cfg=cfg,
                    kb_base_dir=str(kb_base_dir),
                    backends=backends_for_sim,
                    output_dir=output_dir,
                    semaphore=semaphore,
                    max_turns=args.max_turns,
                    language=args.language,
                    evolve_profile=not args.no_evolve,
                    eval_temperature=args.eval_temperature,
                    skip_eval=args.skip_eval,
                    verbose=args.verbose,
                )
            )

    total_tasks = len(tasks)
    logger.info("Launching %d parallel tasks (concurrency=%d)", total_tasks, args.concurrency)
    all_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results (filter out exceptions)
    good_results: list[dict] = []
    for i, result in enumerate(all_results):
        if isinstance(result, Exception):
            logger.error("Task %d failed: %s", i, result)
        else:
            good_results.append(result)

    # Group per-profile results by KB for summary
    by_kb: dict[str, list[dict]] = {d["kb_name"]: [] for d in all_kb_data}
    for r in good_results:
        by_kb.setdefault(r.get("kb_name", "unknown"), []).append(r)
    kb_results = [
        {"kb_name": d["kb_name"], "profiles": by_kb.get(d["kb_name"], [])}
        for d in all_kb_data
    ]

    # Summary
    _build_and_print_summary(kb_results, backends_for_sim, output_dir)


if __name__ == "__main__":
    asyncio.run(main())
