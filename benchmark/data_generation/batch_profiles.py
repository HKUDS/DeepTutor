#!/usr/bin/env python3
"""
Batch Profile Generator — generate profiles for all healthy knowledge bases.

Discovers usable KBs, generates knowledge scope + student profiles in parallel.

Usage:
    python3 -m benchmark.data_generation.batch_profiles
    python3 -m benchmark.data_generation.batch_profiles --kb-dir data/knowledge_bases --concurrency 8
    python3 -m benchmark.data_generation.batch_profiles --kb-names kb1,kb2,kb3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

_THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = _THIS_FILE.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from benchmark.data_generation.profile_generator import generate_profiles_for_kb
from benchmark.data_generation.scope_generator import generate_knowledge_scope

logger = logging.getLogger("benchmark.batch_profiles")

DEFAULT_CONFIG = PROJECT_ROOT / "benchmark" / "config" / "benchmark_config.yaml"

CRITICAL_RAG_FILES = [
    "kv_store_text_chunks.json",
    "kv_store_full_docs.json",
    "kv_store_full_entities.json",
    "kv_store_full_relations.json",
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
    "graph_chunk_entity_relation.graphml",
]


def _discover_healthy_kbs(kb_base_dir: Path) -> list[str]:
    """Return names of KBs whose RAG storage is complete."""
    healthy = []
    for d in sorted(kb_base_dir.iterdir()):
        if not d.is_dir():
            continue
        rag_dir = d / "rag_storage"
        if not rag_dir.is_dir():
            continue
        ok = True
        for fname in CRITICAL_RAG_FILES:
            fpath = rag_dir / fname
            if not fpath.exists() or fpath.stat().st_size == 0:
                ok = False
                break
        if ok:
            healthy.append(d.name)
    return healthy


async def _process_one_kb(
    kb_name: str,
    kb_base_dir: str,
    profile_cfg: dict,
    rag_cfg: dict,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """Generate scope + profiles for a single KB."""
    out_path = output_dir / f"{kb_name}.json"
    if out_path.exists():
        try:
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("profiles") and existing.get("knowledge_scope"):
                logger.info("SKIP (complete): %s", kb_name)
                return existing
        except Exception:
            pass

    async with semaphore:
        logger.info("Processing: %s", kb_name)
        try:
            scope = await generate_knowledge_scope(
                kb_name=kb_name,
                seed_queries=rag_cfg.get("seed_queries"),
                mode=rag_cfg.get("mode", "naive"),
                kb_base_dir=kb_base_dir,
            )
            profiles = await generate_profiles_for_kb(
                knowledge_scope=scope,
                background_types=profile_cfg.get(
                    "background_types", ["beginner", "intermediate", "advanced"]
                ),
                profiles_per_kb=profile_cfg.get("profiles_per_subtopic", 3),
            )

            out = {
                "kb_name": kb_name,
                "knowledge_scope": scope,
                "profiles": profiles,
                "num_profiles": len(profiles),
            }
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            logger.info("Done: %s -> %d profiles", kb_name, len(profiles))
            return out
        except Exception as e:
            logger.error("FAILED: %s — %s", kb_name, e)
            return None


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Batch generate profiles for all healthy knowledge bases"
    )
    parser.add_argument(
        "--kb-dir",
        default="data/knowledge_bases",
        help="Path to knowledge_bases directory (default: data/knowledge_bases)",
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Benchmark config path (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory. If omitted, creates a new timestamped dir.",
    )
    parser.add_argument(
        "--kb-names",
        default=None,
        help="Comma-separated KB names to process (default: auto-discover all healthy KBs).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Max parallel KB processing (default: 6)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force regeneration even if output already exists.",
    )
    args = parser.parse_args()

    kb_base_dir = Path(args.kb_dir)
    if not kb_base_dir.is_absolute():
        kb_base_dir = (PROJECT_ROOT / kb_base_dir).resolve()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = (PROJECT_ROOT / cfg_path).resolve()
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    profile_cfg = cfg.get("profile_generation", {})
    rag_cfg = cfg.get("rag_query", {})

    if args.kb_names:
        kb_names = [n.strip() for n in args.kb_names.split(",") if n.strip()]
    else:
        kb_names = _discover_healthy_kbs(kb_base_dir)

    if not kb_names:
        print("No healthy knowledge bases found.")
        sys.exit(0)

    if args.output_dir:
        output_dir = Path(args.output_dir)
        if not output_dir.is_absolute():
            output_dir = (PROJECT_ROOT / output_dir).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "benchmark" / "data" / "generated" / f"profiles_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"KBs: {len(kb_names)} | Concurrency: {args.concurrency} | Output: {output_dir}")
    for name in kb_names:
        print(f"  - {name}")

    semaphore = asyncio.Semaphore(args.concurrency)
    tasks = [
        _process_one_kb(
            kb_name=name,
            kb_base_dir=str(kb_base_dir),
            profile_cfg=profile_cfg,
            rag_cfg=rag_cfg,
            output_dir=output_dir,
            semaphore=semaphore,
        )
        for name in kb_names
    ]
    results = await asyncio.gather(*tasks)

    success = [r for r in results if r is not None]
    failed = len(results) - len(success)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "kb_base_dir": str(kb_base_dir),
        "num_kbs": len(kb_names),
        "num_success": len(success),
        "num_failed": failed,
        "results": [
            {"kb_name": r["kb_name"], "num_profiles": r["num_profiles"]}
            for r in success
        ],
    }
    summary_path = output_dir / "_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Success: {len(success)}/{len(kb_names)} | Failed: {failed}")
    print(f"Output: {output_dir}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    asyncio.run(main())
