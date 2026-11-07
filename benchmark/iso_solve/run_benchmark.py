# -*- coding: utf-8 -*-
"""Unified benchmark entrypoint for iso_solve."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(_PROJECT_ROOT / "DeepTutor.env", override=False)
load_dotenv(_PROJECT_ROOT / ".env", override=False)

from benchmark.iso_solve.core import BenchmarkRunner, extract_answer, judge_answer
from benchmark.iso_solve.eval import ADAPTER_REGISTRY

logger = logging.getLogger("benchmark_runner")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark Runner — unified iso_solve evaluator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--benchmark",
        choices=["math", "gaia", "hle", "gpqa", "aime25", "livebench", "aalcr", "super_gpqa"],
        default="math",
    )
    parser.add_argument("--mode", choices=["direct", "pipeline"], default="direct")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sequential", action="store_true",
                        help="Take the first N problems in dataset order instead of random sampling")
    parser.add_argument("--output", type=str, default=None)
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--tools", nargs="+", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")

    math_group = parser.add_argument_group("MATH")
    math_group.add_argument("--dataroot", type=str, default=None)
    math_group.add_argument("--subjects", nargs="+", default=None)
    math_group.add_argument("--levels", nargs="+", type=int, default=None)

    gaia_group = parser.add_argument_group("GAIA")
    gaia_group.add_argument("--gaia-config-name", type=str, default=None)
    gaia_group.add_argument("--gaia-split", type=str, default=None)
    gaia_group.add_argument("--gaia-levels", nargs="+", type=int, default=None)

    gpqa_group = parser.add_argument_group("GPQA")
    gpqa_group.add_argument("--gpqa-domains", nargs="+", default=None)

    aime_group = parser.add_argument_group("AIME")
    aime_group.add_argument("--aime-parts", nargs="+", type=int, default=None)

    livebench_group = parser.add_argument_group("LiveBench")
    livebench_group.add_argument("--livebench-categories", nargs="+", default=None)

    aalcr_group = parser.add_argument_group("AA-LCR")
    aalcr_group.add_argument("--aalcr-categories", nargs="+", default=None)

    super_gpqa_group = parser.add_argument_group("SuperGPQA")
    super_gpqa_group.add_argument("--super-gpqa-disciplines", nargs="+", default=None)
    super_gpqa_group.add_argument("--super-gpqa-difficulties", nargs="+", default=None)

    return parser


def _load_cfg(path: str | None) -> dict:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        logger.warning("Config file does not exist: %s", path)
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = _load_cfg(args.config)
    adapter_cls = ADAPTER_REGISTRY[args.benchmark]
    adapter = adapter_cls()
    runner = BenchmarkRunner(adapter, extract_answer, judge_answer)
    report = asyncio.run(runner.run(args, cfg))
    for line in report.summary_lines():
        print(line)


if __name__ == "__main__":
    main()
