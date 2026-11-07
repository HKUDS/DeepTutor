#!/usr/bin/env python
"""
Data Generation Pipeline

Orchestrates the full benchmark data generation from existing knowledge bases:

  Existing KBs (per-subtopic)
       │
       ▼  Stage 1: Discover KBs
       │
       ▼  Stage 2: Query each KB → generate knowledge scope (saved separately)
       │
       ▼  Stage 3: Generate student profiles (beginner/intermediate/advanced)
       │
       ▼  Stage 4: Generate knowledge gaps per profile
       │
       ▼  Stage 5: Generate one task per gap → one benchmark entry per (profile, gap, task)
       │
       ▼  Stage 6: Output benchmark entries (JSONL, no scope duplication)

Output structure:
  benchmark/data/generated/
  ├── knowledge_scopes/
  │   └── {kb_name}.json           # knowledge scope per KB
  └── benchmark_{timestamp}.jsonl  # evaluation entries (profile + gap + task)
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import yaml

from benchmark.data_generation.content_loader import load_page_content_for_profile
from benchmark.data_generation.gap_generator import (
    generate_gaps,
    generate_gaps_for_profiles,
    generate_gaps_for_profiles_with_pages,
    generate_gaps_from_pages,
)
from benchmark.data_generation.profile_generator import generate_profiles_for_kb
from benchmark.data_generation.scope_generator import generate_knowledge_scope
from benchmark.data_generation.task_generator import (
    MIN_GAPS_PER_TASK,
    generate_tasks_with_partition,
    generate_tasks_with_partition_and_rejection,
)

logger = logging.getLogger("benchmark.pipeline")

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class DataGenerationPipeline:
    """
    Full data generation pipeline: KB → evaluation data.

    Assumes subtopics have already been split and each topic has its own
    RAG knowledge base ready to query.

    Output:
        - knowledge_scopes/{kb_name}.json  — scope reference (not used in evaluation)
        - benchmark_{timestamp}.jsonl      — one entry per (profile, gap, task) triple

    Usage:
        pipeline = DataGenerationPipeline()
        entries = await pipeline.run()
    """

    def __init__(self, config_path: str | Path | None = None):
        """
        Initialize the pipeline.

        Args:
            config_path: Path to benchmark_config.yaml.
                         If None, uses benchmark/config/benchmark_config.yaml.
        """
        if config_path is None:
            config_path = PROJECT_ROOT / "benchmark" / "config" / "benchmark_config.yaml"
        else:
            config_path = Path(config_path)
            if not config_path.is_absolute():
                config_path = PROJECT_ROOT / config_path

        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        # Output directory
        self.output_dir = Path(self.config["output"]["output_dir"])
        if not self.output_dir.is_absolute():
            self.output_dir = PROJECT_ROOT / self.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Knowledge scopes directory (separate from entries)
        self.scopes_dir = self.output_dir / "knowledge_scopes"
        self.scopes_dir.mkdir(parents=True, exist_ok=True)

        # KB base directory
        kb_cfg = self.config.get("knowledge_bases", {})
        self.kb_base_dir = kb_cfg.get("base_dir", "./data/knowledge_bases")
        if not Path(self.kb_base_dir).is_absolute():
            self.kb_base_dir = str(PROJECT_ROOT / self.kb_base_dir)

        # Pipeline state
        self.kb_names: list[str] = []
        self.knowledge_scopes: dict[str, dict] = {}       # kb_name → scope
        self.profiles: dict[str, list[dict]] = {}          # kb_name → [profile]
        self.gaps: dict[str, dict[str, list[dict]]] = {}   # kb_name → {pid → [gap]}
        self.benchmark_entries: list[dict] = []

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )

    async def run(self, kb_names: list[str] | None = None) -> list[dict]:
        """
        Run the complete data generation pipeline.

        Args:
            kb_names: Explicit list of KB names to process.
                      If None, uses config or auto-discovers.

        Returns:
            List of benchmark entries
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.info("=" * 60)
        logger.info("Starting Benchmark Data Generation Pipeline")
        logger.info("=" * 60)

        # Stage 1: Discover KBs
        await self._stage_discover_kbs(kb_names)

        # Stages 2-5: Process each KB
        for kb_name in self.kb_names:
            await self._process_single_kb(kb_name)

        # Stage 6: Output
        await self._stage_output(timestamp)

        logger.info("=" * 60)
        logger.info(f"Pipeline complete! Generated {len(self.benchmark_entries)} benchmark entries")
        logger.info("=" * 60)

        return self.benchmark_entries

    # =========================================================================
    # Pipeline Stages
    # =========================================================================

    async def _stage_discover_kbs(self, kb_names: list[str] | None = None):
        """Stage 1: Discover which knowledge bases to process."""
        logger.info("[Stage 1] Discovering knowledge bases...")

        if kb_names:
            self.kb_names = kb_names
        else:
            configured = self.config.get("knowledge_bases", {}).get("kb_names", [])
            if configured:
                self.kb_names = configured
            else:
                # Auto-discover from KB manager
                from src.knowledge.manager import KnowledgeBaseManager

                manager = KnowledgeBaseManager(self.kb_base_dir)
                self.kb_names = manager.list_knowledge_bases()

        logger.info(f"Will process {len(self.kb_names)} knowledge bases: {self.kb_names}")

    async def _process_single_kb(self, kb_name: str):
        """Stages 2-5 for a single knowledge base."""
        logger.info(f"\n{'='*50}")
        logger.info(f"Processing KB: {kb_name}")
        logger.info(f"{'='*50}")

        # Stage 2: Generate knowledge scope → saved to separate file
        logger.info(f"[Stage 2] Generating knowledge scope for '{kb_name}'...")
        rag_cfg = self.config.get("rag_query", {})
        try:
            scope = await generate_knowledge_scope(
                kb_name=kb_name,
                seed_queries=rag_cfg.get("seed_queries"),
                mode=rag_cfg.get("mode", "naive"),
                kb_base_dir=self.kb_base_dir,
            )
            self.knowledge_scopes[kb_name] = scope

            # Save scope to its own file (reference only, not used in evaluation)
            scope_file = self.scopes_dir / f"{kb_name}.json"
            with open(scope_file, "w", encoding="utf-8") as f:
                json.dump(scope, f, ensure_ascii=False, indent=2)
            logger.info(f"  Knowledge scope saved → {scope_file}")

        except Exception as e:
            logger.error(f"Failed to generate scope for '{kb_name}': {e}")
            return

        # Stage 3: Generate profiles
        logger.info(f"[Stage 3] Generating student profiles for '{kb_name}'...")
        profile_cfg = self.config.get("profile_generation", {})
        profiles = await generate_profiles_for_kb(
            knowledge_scope=scope,
            background_types=profile_cfg.get(
                "background_types", ["beginner", "intermediate", "advanced"]
            ),
            profiles_per_kb=profile_cfg.get("profiles_per_subtopic", 3),
        )
        self.profiles[kb_name] = profiles

        # Stage 4 & 5: Generate gaps and tasks per profile, looping until min_tasks is satisfied
        gap_cfg = self.config.get("gap_generation", {})
        task_cfg = self.config.get("task_generation", {})
        logger.info(f"[Stage 4-5] Generating gaps and tasks for '{kb_name}' (min {task_cfg.get('min_tasks_per_profile', 3)} tasks/profile)...")
        min_tasks = task_cfg.get("min_tasks_per_profile", 3)
        gaps_per_batch_cfg = task_cfg.get("gaps_per_batch", 3)
        gaps_per_batch = max(gaps_per_batch_cfg, MIN_GAPS_PER_TASK)
        if gaps_per_batch_cfg < MIN_GAPS_PER_TASK:
            logger.warning(
                "task_generation.gaps_per_batch=%d is too small; bumping to %d "
                "to enforce >=%d gaps per task",
                gaps_per_batch_cfg,
                gaps_per_batch,
                MIN_GAPS_PER_TASK,
            )
        severity_weights = {}
        for level in gap_cfg.get("severity_levels", []):
            severity_weights[level["name"]] = level["weight"]

        use_content_list = gap_cfg.get("use_content_list", False)
        rejection_sampling = use_content_list and gap_cfg.get("rejection_sampling", False)
        page_content_by_profile: dict[str, tuple[dict[int, str], list[int]]] = {}

        if use_content_list:
            num_pages = gap_cfg.get("pages_per_profile", 10)
            for profile in profiles:
                profile_id = profile.get("profile_id", "unknown")
                result = load_page_content_for_profile(
                    kb_base_dir=self.kb_base_dir,
                    kb_name=kb_name,
                    num_pages=num_pages,
                    profile_id=profile_id,
                )
                if result:
                    page_content_by_profile[profile_id] = result
            if not page_content_by_profile:
                logger.warning("  No content_list found, falling back to scope-based gaps")
                use_content_list = False

        profile_gaps: dict[str, list[dict]] = {p.get("profile_id", "?"): [] for p in profiles}

        for profile in profiles:
            profile_id = profile.get("profile_id", "unknown")
            page_content, _ = page_content_by_profile.get(profile_id, (None, []))
            all_gaps: list[dict] = []
            all_tasks: list[dict] = []
            task_index_offset = 0

            max_batches = 10
            batch_num = 0
            while len(all_tasks) < min_tasks and batch_num < max_batches:
                batch_num += 1
                batch_size = gaps_per_batch
                try:
                    if use_content_list and page_content:
                        new_gaps = await generate_gaps_from_pages(
                            page_content=page_content,
                            student_profile=profile,
                            num_gaps=batch_size,
                            severity_weights=severity_weights or None,
                            gap_id_offset=len(all_gaps),
                        )
                    else:
                        new_gaps = await generate_gaps(
                            knowledge_scope=scope,
                            student_profile=profile,
                            num_gaps=batch_size,
                            severity_weights=severity_weights or None,
                            gap_id_offset=len(all_gaps),
                        )

                    if not new_gaps:
                        logger.warning(f"  No new gaps for {profile_id}, stopping")
                        break

                    all_gaps.extend(new_gaps)

                    if rejection_sampling and page_content:
                        tasks = await generate_tasks_with_partition_and_rejection(
                            knowledge_scope=scope,
                            student_profile=profile,
                            knowledge_gaps=new_gaps,
                            page_content=page_content,
                            task_index_offset=task_index_offset,
                        )
                    else:
                        tasks = await generate_tasks_with_partition(
                            knowledge_scope=scope,
                            student_profile=profile,
                            knowledge_gaps=new_gaps,
                            task_index_offset=task_index_offset,
                        )

                    all_tasks.extend(tasks)
                    task_index_offset += len(tasks)

                    if len(all_tasks) >= min_tasks:
                        logger.info(f"  {profile_id}: {len(all_tasks)} tasks (threshold met)")
                        break
                    logger.info(f"  {profile_id}: {len(all_tasks)}/{min_tasks} tasks, generating more gaps...")

                except Exception as e:
                    logger.error(f"Failed for {profile_id}: {e}")
                    break

            profile_gaps[profile_id] = all_gaps
            gap_by_id = {g["gap_id"]: g for g in all_gaps if "gap_id" in g}

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
                self.benchmark_entries.append(entry)

        self.gaps[kb_name] = profile_gaps

        # Save intermediate per-KB result (includes scope for debugging)
        if self.config["output"].get("save_intermediate", True):
            self._save_intermediate(
                f"kb_{kb_name}.json",
                {
                    "kb_name": kb_name,
                    "knowledge_scope": scope,
                    "profiles": profiles,
                    "gaps": profile_gaps,
                    "num_entries": sum(
                        1
                        for e in self.benchmark_entries
                        if e.get("kb_name") == kb_name
                    ),
                },
            )

        kb_entries = sum(1 for e in self.benchmark_entries if e["kb_name"] == kb_name)
        logger.info(f"Completed KB '{kb_name}': {len(profiles)} profiles, {kb_entries} entries")

    async def _stage_output(self, timestamp: str):
        """Stage 6: Save final output — organized by KB, each with its own _all_entries.jsonl."""
        logger.info("[Stage 6] Saving benchmark dataset...")

        run_dir = self.output_dir / f"benchmark_{timestamp}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Group entries by KB
        entries_by_kb: dict[str, list[dict]] = {}
        for entry in self.benchmark_entries:
            kb = entry.get("kb_name", "unknown")
            entries_by_kb.setdefault(kb, []).append(entry)

        # Write per-KB directories
        for kb_name, kb_entries in entries_by_kb.items():
            kb_dir = run_dir / kb_name
            kb_dir.mkdir(parents=True, exist_ok=True)

            seen_entry_ids: dict[str, int] = {}
            for entry in kb_entries:
                base_entry_id = str(entry.get("entry_id", "unknown"))
                dup_count = seen_entry_ids.get(base_entry_id, 0)
                seen_entry_ids[base_entry_id] = dup_count + 1

                if dup_count == 0:
                    entry_id = base_entry_id
                else:
                    entry_id = f"{base_entry_id}__dup{dup_count + 1:02d}"
                    logger.warning(
                        "Duplicate entry_id detected: %s -> renamed to %s",
                        base_entry_id, entry_id,
                    )
                    entry["entry_id"] = entry_id

                entry_file = kb_dir / f"{entry_id}.json"
                with open(entry_file, "w", encoding="utf-8") as f:
                    json.dump(entry, f, ensure_ascii=False, indent=2)

            kb_jsonl = kb_dir / "_all_entries.jsonl"
            with open(kb_jsonl, "w", encoding="utf-8") as f:
                for entry in kb_entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

            logger.info(f"  {kb_name}: {len(kb_entries)} entries → {kb_dir}/")

        # Also write a combined JSONL at the run level
        combined_file = run_dir / "_all_entries.jsonl"
        with open(combined_file, "w", encoding="utf-8") as f:
            for entry in self.benchmark_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"Combined JSONL → {combined_file}")

        # Summary
        summary = {
            "timestamp": timestamp,
            "statistics": {
                "total_entries": len(self.benchmark_entries),
                "num_kbs": len(self.kb_names),
                "num_profiles": sum(len(p) for p in self.profiles.values()),
                "per_kb": [
                    {
                        "kb_name": kb,
                        "num_profiles": len(self.profiles.get(kb, [])),
                        "num_entries": len(entries_by_kb.get(kb, [])),
                    }
                    for kb in self.kb_names
                ],
            },
            "entries_dir": str(run_dir),
            "knowledge_scopes_dir": str(self.scopes_dir),
        }

        summary_file = run_dir / "_summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info(f"Summary → {summary_file}")

    # =========================================================================
    # Utilities
    # =========================================================================

    def _save_intermediate(self, filename: str, data):
        """Save intermediate results to output directory."""
        intermediate_dir = self.output_dir / "intermediate"
        intermediate_dir.mkdir(exist_ok=True)
        filepath = intermediate_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.debug(f"Saved intermediate: {filepath}")


# =============================================================================
# CLI Entry Point
# =============================================================================


async def main():
    """CLI entry point for running the data generation pipeline."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Benchmark Data Generation: KB → Evaluation Data"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to benchmark config file (default: benchmark/config/benchmark_config.yaml)",
    )
    parser.add_argument(
        "--kb-names",
        nargs="+",
        default=None,
        help="Explicit list of KB names to process (overrides config)",
    )

    args = parser.parse_args()

    pipeline = DataGenerationPipeline(args.config)
    await pipeline.run(kb_names=args.kb_names)


if __name__ == "__main__":
    asyncio.run(main())
