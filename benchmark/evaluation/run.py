#!/usr/bin/env python
"""
CLI for benchmark evaluation.

Current evaluator uses independent metrics:
1) source_faithfulness (LLM, per turn, 1-5)
2) teaching_quality (LLM, per turn, 1-5 on four dimensions)
3) turn_count (non-LLM, raw iter source)
"""

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from benchmark.evaluation.evaluator import evaluate_transcript

logger = logging.getLogger("benchmark.evaluation")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_EVAL_DIR = PROJECT_ROOT / "benchmark" / "data" / "evaluations"


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )


async def _run_single(transcript_path: Path, skip_turns: bool, temperature: float) -> dict:
    """Evaluate a single transcript."""
    return await evaluate_transcript(
        transcript_path=transcript_path,
        skip_turns=skip_turns,
        temperature=temperature,
    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate tutor transcripts from benchmark conversations"
    )
    parser.add_argument(
        "--transcript",
        help="Path to a single transcript JSON file",
    )
    parser.add_argument(
        "--transcript-dir",
        help="Path to directory of transcript JSON files (evaluates all)",
    )
    parser.add_argument(
        "--dialog-only",
        action="store_true",
        help="Skip per-turn LLM metrics (faithfulness/teaching_quality), keep turn_count only",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output path for results JSON (default: benchmark/data/evaluations/<stem>_eval_<timestamp>.json)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="LLM temperature for evaluation (default: 0.2)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    _setup_logging(args.verbose)

    if args.transcript and args.transcript_dir:
        parser.error("Use either --transcript or --transcript-dir, not both")
    if not args.transcript and not args.transcript_dir:
        parser.error("Provide --transcript or --transcript-dir")

    paths: list[Path] = []
    if args.transcript:
        p = Path(args.transcript)
        if not p.exists():
            # Try relative to project root (handles /benchmark/... typo)
            alt = PROJECT_ROOT / args.transcript.lstrip("/")
            if alt.exists():
                p = alt
            else:
                parser.error(f"Transcript not found: {p}")
        paths = [p]
    else:
        d = Path(args.transcript_dir)
        if not d.is_dir():
            alt = PROJECT_ROOT / args.transcript_dir.lstrip("/")
            if alt.is_dir():
                d = alt
            else:
                parser.error(f"Directory not found: {d}")
        paths = sorted(d.glob("*.json"))

    if not paths:
        parser.error("No transcript files found")

    results = []
    for path in paths:
        logger.info("Evaluating %s", path)
        try:
            result = await _run_single(
                transcript_path=path,
                skip_turns=args.dialog_only,
                temperature=args.temperature,
            )
            results.append(result)

            # Print summary
            print(f"\n--- {path.name} ---")
            if "error" in result:
                print(f"Error: {result['error']}")
            elif "sessions" in result:
                print(f"Profile: {result.get('profile_id', '?')} ({result.get('num_sessions', 0)} sessions)")
                for i, s in enumerate(result.get("sessions", []), 1):
                    metrics = s.get("metrics", {})
                    faith = metrics.get("source_faithfulness", {})
                    tq = metrics.get("teaching_quality", {})
                    turns = metrics.get("turn_count", {})
                    print(
                        f"  Session {i} ({s.get('entry_id', '?')}): "
                        f"paired_turns={turns.get('paired_turns', 0)}, "
                        f"faith_avg={faith.get('avg_score', 'N/A')}, "
                        f"personalization_avg={tq.get('personalization', {}).get('avg', 'N/A')}"
                    )
                agg = result.get("aggregate", {})
                agg_turn = agg.get("turn_count", {})
                agg_faith = agg.get("source_faithfulness", {})
                print(f"Total paired turns: {agg_turn.get('paired_turns_total', 0)}")
                print(f"Faithfulness overall avg: {agg_faith.get('avg_score_overall', 'N/A')}")
            else:
                print(f"Entry: {result.get('entry_id', '?')}")
                metrics = result.get("metrics", {})
                faith = metrics.get("source_faithfulness", {})
                tq = metrics.get("teaching_quality", {})
                turns = metrics.get("turn_count", {})
                print(f"Paired turns: {turns.get('paired_turns', 0)}")
                print(
                    "Source faithfulness (1-5): "
                    f"avg={faith.get('avg_score', 'N/A')}, "
                    f"min={faith.get('min_score', 'N/A')}, "
                    f"max={faith.get('max_score', 'N/A')}, "
                    f"scored_turns={faith.get('num_scored_turns', 0)}"
                )
                print(
                    "Teaching quality (1-5): "
                    f"personalization={tq.get('personalization', {}).get('avg', 'N/A')}, "
                    f"applicability={tq.get('applicability', {}).get('avg', 'N/A')}, "
                    f"vividness={tq.get('vividness', {}).get('avg', 'N/A')}, "
                    f"logical_depth={tq.get('logical_depth', {}).get('avg', 'N/A')}"
                )
        except Exception as e:
            logger.exception("Failed to evaluate %s", path)
            results.append({"transcript_path": str(path), "error": str(e)})

    # Single file: result is the first (and only) item
    output_data = results[0] if len(results) == 1 else {"evaluations": results}

    # Always save to file; default path when --output not specified
    if args.output:
        out_path = Path(args.output)
    else:
        DEFAULT_EVAL_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if len(paths) == 1:
            stem = paths[0].stem
            out_path = DEFAULT_EVAL_DIR / f"{stem}_eval_{timestamp}.json"
        else:
            out_path = DEFAULT_EVAL_DIR / f"eval_{timestamp}.json"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
