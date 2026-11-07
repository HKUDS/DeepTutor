#!/usr/bin/env python3
"""
Initialize one KB per PDF from ../documents, then generate profiles.

Flow per PDF:
  1) Create KB (name derived from PDF filename)
  2) Process document into RAG KB
  3) Generate knowledge scope
  4) Generate student profiles
  5) Save outputs under benchmark/data/generated/profiles_from_documents_<timestamp>/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

# Ensure project root is importable when script is executed directly.
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT_FOR_IMPORT = _THIS_FILE.parents[2]
if str(_PROJECT_ROOT_FOR_IMPORT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT_FOR_IMPORT))

from benchmark.data_generation.profile_generator import generate_profiles_for_kb
from benchmark.data_generation.scope_generator import generate_knowledge_scope
from src.knowledge.initializer import KnowledgeBaseInitializer

logger = logging.getLogger("benchmark.init_kbs_profiles")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "benchmark" / "config" / "benchmark_config.yaml"
DEFAULT_DOCS_DIR = PROJECT_ROOT.parent / "documents"
MAX_CONCURRENCY = 4


class PipelineAbortError(RuntimeError):
    """Abort all processing when any single PDF pipeline fails."""


def _runtime_status(message: str) -> None:
    """Print concise runtime scheduler status."""
    print(message, flush=True)


class _LightRAGProgressHandler(logging.Handler):
    """Direct handler for LightRAG chunk progress.

    NOT a StreamHandler subclass, so LightRAGLogContext won't remove it.
    """

    _formatter = logging.Formatter("%(asctime)s [lightrag] %(levelname)s: %(message)s")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            print(self._formatter.format(record), flush=True)
        except Exception:
            self.handleError(record)


def _configure_logging() -> None:
    """Configure default logging (INFO)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    lightrag_logger = logging.getLogger("lightrag")
    lightrag_logger.setLevel(logging.INFO)
    handler = _LightRAGProgressHandler()
    handler.setLevel(logging.INFO)
    lightrag_logger.addHandler(handler)


def _sanitize_kb_name(name: str) -> str:
    """Convert filename stem into a valid kb_name."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s or "kb"


def _unique_name(base: str, used: set[str]) -> str:
    """Make KB name unique in current run."""
    if base not in used:
        used.add(base)
        return base
    i = 2
    while f"{base}_{i}" in used:
        i += 1
    name = f"{base}_{i}"
    used.add(name)
    return name


def _load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _cleanup_failed_kb_data(kb_base_dir: Path, kb_name: str, output_dir: Path) -> None:
    """Remove artifacts for a failed PDF pipeline."""
    kb_dir = kb_base_dir / kb_name
    output_json = output_dir / f"{kb_name}.json"

    if output_json.exists():
        try:
            output_json.unlink()
            logger.info("Removed failed output file: %s", output_json)
        except Exception as e:
            logger.warning("Failed to remove output file %s: %s", output_json, e)

    if kb_dir.exists():
        try:
            shutil.rmtree(kb_dir)
            logger.info("Removed failed KB directory: %s", kb_dir)
        except Exception as e:
            logger.warning("Failed to remove KB directory %s: %s", kb_dir, e)


def _parse_gpu_ids(raw: str) -> list[str]:
    ids = [p.strip() for p in raw.split(",") if p.strip()]
    return ids or ["0"]


_RAG_CRITICAL_FILES = [
    "kv_store_text_chunks.json",
    "kv_store_full_docs.json",
    "kv_store_full_entities.json",
    "kv_store_full_relations.json",
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
    "graph_chunk_entity_relation.graphml",
]


def _is_kb_rag_complete(kb_base_dir: Path, kb_name: str) -> bool:
    """Check if a KB's RAG storage is fully built (all critical files present and non-empty)."""
    rag_dir = kb_base_dir / kb_name / "rag_storage"
    if not rag_dir.is_dir():
        return False
    for fname in _RAG_CRITICAL_FILES:
        fpath = rag_dir / fname
        if not fpath.exists() or fpath.stat().st_size == 0:
            return False
    # Check doc_status: all documents should be 'processed'
    status_path = rag_dir / "kv_store_doc_status.json"
    if status_path.exists():
        try:
            with open(status_path, encoding="utf-8") as f:
                doc_status = json.load(f)
            for doc in doc_status.values():
                if isinstance(doc, dict) and doc.get("status") not in ("processed",):
                    return False
        except Exception:
            return False
    return True


def _is_profile_complete(output_dir: Path, kb_name: str) -> bool:
    """Check if profile output already exists with valid content."""
    out_path = output_dir / f"{kb_name}.json"
    if not out_path.exists():
        return False
    try:
        with open(out_path, encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("profiles")) and bool(data.get("knowledge_scope"))
    except Exception:
        return False


async def _process_pdf(
    *,
    pdf_path: Path,
    kb_name: str,
    kb_base_dir: Path,
    profile_cfg: dict,
    rag_cfg: dict,
    output_dir: Path,
    skip_processing: bool,
    skip_extract: bool,
    use_mineru_api: bool,
    mineru_api_token: str | None,
    mineru_model_version: str,
    force: bool = False,
    kb_only: bool = False,
) -> dict | None:
    """Initialize KB from one PDF and generate profiles."""
    if not kb_only and not force and _is_profile_complete(output_dir, kb_name):
        logger.info("SKIP (complete): %s — profile already exists", kb_name)
        return None

    logger.info("=" * 70)
    logger.info("PDF: %s", pdf_path.name)
    logger.info("KB : %s", kb_name)
    logger.info("=" * 70)

    if not skip_processing:
        if not force and _is_kb_rag_complete(kb_base_dir, kb_name):
            logger.info("SKIP RAG build (complete): %s — rag_storage already built", kb_name)
        else:
            initializer = KnowledgeBaseInitializer(
                kb_name=kb_name,
                base_dir=str(kb_base_dir),
            )
            initializer.create_directory_structure()
            copied = initializer.copy_documents([str(pdf_path)])
            if not copied:
                raise RuntimeError(f"Failed to copy PDF: {pdf_path}")

            await initializer.process_documents(
                use_mineru_api=use_mineru_api,
                mineru_api_token=mineru_api_token,
                mineru_model_version=mineru_model_version,
            )

    return await _run_post_gpu_stage(
        pdf_path=pdf_path,
        kb_name=kb_name,
        kb_base_dir=kb_base_dir,
        profile_cfg=profile_cfg,
        rag_cfg=rag_cfg,
        output_dir=output_dir,
        skip_extract=skip_extract,
        kb_only=kb_only,
    )


async def _run_gpu_stage_only(
    *,
    pdf_path: Path,
    kb_name: str,
    kb_base_dir: Path,
    use_mineru_api: bool,
    mineru_api_token: str | None,
    mineru_model_version: str,
    force: bool = False,
) -> None:
    """Run only GPU-heavy stage: create/copy/process documents."""
    if not force and _is_kb_rag_complete(kb_base_dir, kb_name):
        logger.info("SKIP GPU stage (complete): %s — rag_storage already built", kb_name)
        return
    try:
        logger.info("=" * 70)
        logger.info("GPU stage start | PDF: %s | KB: %s", pdf_path.name, kb_name)
        logger.info("=" * 70)
        initializer = KnowledgeBaseInitializer(kb_name=kb_name, base_dir=str(kb_base_dir))
        initializer.create_directory_structure()
        copied = initializer.copy_documents([str(pdf_path)])
        if not copied:
            raise RuntimeError(f"Failed to copy PDF: {pdf_path}")
        await initializer.process_documents(
            use_mineru_api=use_mineru_api,
            mineru_api_token=mineru_api_token,
            mineru_model_version=mineru_model_version,
        )
    except Exception as e:
        logger.exception("Failed on %s -> %s: %s", pdf_path.name, kb_name, e)
        raise PipelineAbortError(
            f"GPU stage failed for {pdf_path.name} (kb={kb_name}). Program terminated."
        ) from e


async def _run_post_gpu_stage(
    *,
    pdf_path: Path,
    kb_name: str,
    kb_base_dir: Path,
    profile_cfg: dict,
    rag_cfg: dict,
    output_dir: Path,
    skip_extract: bool,
    kb_only: bool = False,
) -> dict:
    """Run non-GPU stage after documents are processed."""
    initializer = KnowledgeBaseInitializer(kb_name=kb_name, base_dir=str(kb_base_dir))
    if not skip_extract:
        await asyncio.to_thread(initializer.extract_numbered_items)

    if kb_only:
        logger.info("KB-only mode: skipping profile generation for %s", kb_name)
        return {"pdf_file": str(pdf_path), "kb_name": kb_name, "knowledge_scope": {}, "profiles": [], "num_profiles": 0}

    scope = await generate_knowledge_scope(
        kb_name=kb_name,
        seed_queries=rag_cfg.get("seed_queries"),
        mode=rag_cfg.get("mode", "naive"),
        kb_base_dir=str(kb_base_dir),
    )
    profiles = await generate_profiles_for_kb(
        knowledge_scope=scope,
        background_types=profile_cfg.get(
            "background_types", ["beginner", "intermediate", "advanced"]
        ),
        profiles_per_kb=profile_cfg.get("profiles_per_subtopic", 3),
    )

    out = {
        "pdf_file": str(pdf_path),
        "kb_name": kb_name,
        "knowledge_scope": scope,
        "profiles": profiles,
        "num_profiles": len(profiles),
    }
    out_path = output_dir / f"{kb_name}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    logger.info("Saved: %s", out_path)
    return out


async def _run_jobs_with_gpu_pipeline(
    *,
    jobs: list[tuple[Path, str]],
    gpu_ids: list[str],
    config_path: Path,
    kb_base_dir: Path,
    profile_cfg: dict,
    rag_cfg: dict,
    output_dir: Path,
    skip_extract: bool,
    use_mineru_api: bool,
    mineru_api_token: str | None,
    mineru_model_version: str,
    force: bool = False,
    kb_only: bool = False,
) -> list[dict]:
    """Run jobs with GPU-stage sharding and immediate refill."""
    if not kb_only and not force:
        original_count = len(jobs)
        jobs = [
            (pdf, kb) for pdf, kb in jobs
            if not _is_profile_complete(output_dir, kb)
        ]
        skipped = original_count - len(jobs)
        if skipped:
            logger.info("Resume: skipping %d already-complete jobs", skipped)
        if not jobs:
            logger.info("All jobs already complete — nothing to do.")
            return []

    available_gpus = list(gpu_ids)
    running: list[dict] = []
    waiting_jobs = list(jobs)
    results: list[dict] = []
    post_tasks: set[asyncio.Task] = set()

    async def _start_one(pdf_path: Path, kb_name: str, gpu_id: str) -> dict:
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--single-gpu-stage",
            str(pdf_path),
            "--single-kb-name",
            kb_name,
            "--config",
            str(config_path),
            "--mineru-model-version",
            mineru_model_version,
            "--gpu-ids",
            gpu_id,
        ]
        if skip_extract:
            cmd.append("--skip-extract")
        if use_mineru_api:
            cmd.append("--use-mineru-api")
        else:
            cmd.append("--no-use-mineru-api")
        if mineru_api_token:
            cmd.extend(["--mineru-api-token", mineru_api_token])
        if force:
            cmd.append("--force")

        env = os.environ.copy()
        env["CUDA_VISIBLE_DEVICES"] = gpu_id
        remaining_after_dispatch = len(waiting_jobs)
        _runtime_status(
            f"[GPU {gpu_id}] running {pdf_path.name} | queue remaining: {remaining_after_dispatch}"
        )
        proc = await asyncio.create_subprocess_exec(*cmd, env=env)
        wait_task = asyncio.create_task(proc.wait())
        return {
            "pdf_path": pdf_path,
            "kb_name": kb_name,
            "gpu_id": gpu_id,
            "proc": proc,
            "wait_task": wait_task,
        }

    while waiting_jobs or running or post_tasks:
        while waiting_jobs and available_gpus:
            pdf_path, kb_name = waiting_jobs.pop(0)
            gpu_id = available_gpus.pop(0)
            running.append(await _start_one(pdf_path, kb_name, gpu_id))

        if not running and not post_tasks:
            break

        wait_targets = [r["wait_task"] for r in running] + list(post_tasks)
        if not wait_targets:
            break
        done, _ = await asyncio.wait(wait_targets, return_when=asyncio.FIRST_COMPLETED)

        finished_entries = [r for r in running if r["wait_task"] in done]
        for entry in finished_entries:
            running.remove(entry)
            available_gpus.append(entry["gpu_id"])

            exit_code = entry["wait_task"].result()
            if exit_code != 0:
                logger.error(
                    "Job failed: %s (pdf=%s) on GPU %s, exit_code=%s",
                    entry["kb_name"],
                    entry["pdf_path"].name,
                    entry["gpu_id"],
                    exit_code,
                )
                for other in running:
                    other["proc"].terminate()
                await asyncio.gather(*[r["wait_task"] for r in running], return_exceptions=True)
                for task in post_tasks:
                    task.cancel()
                await asyncio.gather(*post_tasks, return_exceptions=True)
                _cleanup_failed_kb_data(
                    kb_base_dir=kb_base_dir, kb_name=entry["kb_name"], output_dir=output_dir
                )
                raise PipelineAbortError(
                    f"Pipeline failed for {entry['pdf_path'].name} (kb={entry['kb_name']})."
                )

            # GPU stage done -> immediately schedule non-GPU stage.
            post_task = asyncio.create_task(
                _run_post_gpu_stage(
                    pdf_path=entry["pdf_path"],
                    kb_name=entry["kb_name"],
                    kb_base_dir=kb_base_dir,
                    profile_cfg=profile_cfg,
                    rag_cfg=rag_cfg,
                    output_dir=output_dir,
                    skip_extract=skip_extract,
                    kb_only=kb_only,
                )
            )
            post_tasks.add(post_task)

        finished_post = [t for t in post_tasks if t in done]
        for task in finished_post:
            post_tasks.remove(task)
            exc = task.exception()
            if exc is not None:
                for other in running:
                    other["proc"].terminate()
                await asyncio.gather(*[r["wait_task"] for r in running], return_exceptions=True)
                for t in post_tasks:
                    t.cancel()
                await asyncio.gather(*post_tasks, return_exceptions=True)
                raise PipelineAbortError(str(exc))
            results.append(task.result())

    return results


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialize one KB per PDF in ../documents, then generate profiles."
    )
    parser.add_argument(
        "--docs-dir",
        default=str(DEFAULT_DOCS_DIR),
        help=f"Directory containing PDF files (default: {DEFAULT_DOCS_DIR})",
    )
    parser.add_argument(
        "--docs-folder",
        default=None,
        help=(
            "Folder name under project parent directory. "
            "Example: --docs-folder documents_alt -> ../documents_alt"
        ),
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"Benchmark config path (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip numbered items extraction for faster initialization",
    )
    parser.add_argument(
        "--skip-processing",
        action="store_true",
        help="Skip document parsing/processing and reuse existing KB content_list/rag_storage.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process first N PDFs (0 = all)",
    )
    parser.add_argument(
        "--use-mineru-api",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use MinerU cloud API for parsing (default: True). Use --no-use-mineru-api for local parser.",
    )
    parser.add_argument(
        "--mineru-api-token",
        default=None,
        help="MinerU API token (falls back to MINERU_API_TOKEN env var if omitted).",
    )
    parser.add_argument(
        "--mineru-model-version",
        default="vlm",
        help='MinerU API model version (default: "vlm").',
    )
    parser.add_argument(
        "--gpu-ids",
        default="0,1,2,3",
        help='GPU ids for sharding workloads, comma-separated (default: "0,1,2,3").',
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Run in serial mode (default is parallel GPU pipeline mode).",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Resume into an existing output directory instead of creating a new one.",
    )
    parser.add_argument(
        "--kb-only",
        action="store_true",
        help="Only build knowledge bases, skip profile generation.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-processing of all KBs, ignoring existing results.",
    )
    parser.add_argument("--single-gpu-stage", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--single-kb-name", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    _configure_logging()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = (PROJECT_ROOT / cfg_path).resolve()
    cfg = _load_config(cfg_path)

    kb_base_dir = Path(
        cfg.get("knowledge_bases", {}).get("base_dir", "./data/knowledge_bases")
    )
    if not kb_base_dir.is_absolute():
        kb_base_dir = (PROJECT_ROOT / kb_base_dir).resolve()

    profile_cfg = cfg.get("profile_generation", {})
    rag_cfg = cfg.get("rag_query", {})

    if args.single_gpu_stage:
        if not args.single_kb_name:
            raise ValueError("--single-gpu-stage mode requires --single-kb-name")
        pdf_path = Path(args.single_gpu_stage).resolve()
        await _run_gpu_stage_only(
            pdf_path=pdf_path,
            kb_name=args.single_kb_name,
            kb_base_dir=kb_base_dir,
            use_mineru_api=args.use_mineru_api,
            mineru_api_token=args.mineru_api_token,
            mineru_model_version=args.mineru_model_version,
            force=args.force,
        )
        return

    if args.docs_folder:
        docs_dir = (PROJECT_ROOT.parent / args.docs_folder).resolve()
    else:
        docs_dir = Path(args.docs_dir)
    if not docs_dir.is_absolute():
        docs_dir = (PROJECT_ROOT / docs_dir).resolve()
    if not docs_dir.exists():
        raise FileNotFoundError(f"Documents dir not found: {docs_dir}")

    if args.output_dir:
        output_dir = Path(args.output_dir)
        if not output_dir.is_absolute():
            output_dir = (PROJECT_ROOT / output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = output_dir.name.replace("profiles_from_documents_", "")
        logger.info("Resuming into existing output dir: %s", output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = PROJECT_ROOT / "benchmark" / "data" / "generated" / f"profiles_from_documents_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(docs_dir.glob("*.pdf"))
    if args.limit and args.limit > 0:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        raise ValueError(f"No PDF files found in: {docs_dir}")

    used_names: set[str] = set()
    jobs = []
    for pdf in pdfs:
        kb_name = _unique_name(_sanitize_kb_name(pdf.stem), used_names)
        jobs.append((pdf, kb_name))

    gpu_ids = _parse_gpu_ids(args.gpu_ids)
    if args.skip_processing:
        _runtime_status(
            f"Start reuse-existing run | mode=skip_processing | total_pdfs={len(jobs)}"
        )
        results = []
        for idx, (pdf_path, kb_name) in enumerate(jobs, start=1):
            if not args.force and _is_profile_complete(output_dir, kb_name):
                logger.info("SKIP (complete) [%d/%d]: %s", idx, len(jobs), kb_name)
                continue
            logger.info(
                "Running reuse-existing pipeline [%d/%d]: %s -> %s",
                idx,
                len(jobs),
                pdf_path.name,
                kb_name,
            )
            try:
                result = await _run_post_gpu_stage(
                    pdf_path=pdf_path,
                    kb_name=kb_name,
                    kb_base_dir=kb_base_dir,
                    profile_cfg=profile_cfg,
                    rag_cfg=rag_cfg,
                    output_dir=output_dir,
                    skip_extract=args.skip_extract,
                    kb_only=args.kb_only,
                )
                results.append(result)
            except Exception as e:
                logger.exception(
                    "Reuse-existing pipeline failed on %s -> %s: %s",
                    pdf_path.name,
                    kb_name,
                    e,
                )
                raise SystemExit(1)
    elif args.serial:
        _runtime_status(
            f"Start serial run | gpus={','.join(gpu_ids[:MAX_CONCURRENCY])} | "
            f"mode={'mineru_api' if args.use_mineru_api else 'local'} | total_pdfs={len(jobs)}"
        )
        results = []
        for idx, (pdf_path, kb_name) in enumerate(jobs, start=1):
            logger.info(
                "Running serial pipeline [%d/%d]: %s -> %s",
                idx,
                len(jobs),
                pdf_path.name,
                kb_name,
            )
            try:
                result = await _process_pdf(
                    pdf_path=pdf_path,
                    kb_name=kb_name,
                    kb_base_dir=kb_base_dir,
                    profile_cfg=profile_cfg,
                    rag_cfg=rag_cfg,
                    output_dir=output_dir,
                    skip_processing=args.skip_processing,
                    skip_extract=args.skip_extract,
                    use_mineru_api=args.use_mineru_api,
                    mineru_api_token=args.mineru_api_token,
                    mineru_model_version=args.mineru_model_version,
                    force=args.force,
                    kb_only=args.kb_only,
                )
                if result is not None:
                    results.append(result)
            except Exception as e:
                logger.exception("Pipeline failed on %s -> %s: %s", pdf_path.name, kb_name, e)
                _cleanup_failed_kb_data(
                    kb_base_dir=kb_base_dir, kb_name=kb_name, output_dir=output_dir
                )
                raise SystemExit(1)
    else:
        _runtime_status(
            f"Start parallel run | gpus={','.join(gpu_ids[:MAX_CONCURRENCY])} | "
            f"mode={'mineru_api' if args.use_mineru_api else 'local'} | total_pdfs={len(jobs)}"
        )
        try:
            results = await _run_jobs_with_gpu_pipeline(
                jobs=jobs,
                gpu_ids=gpu_ids[:MAX_CONCURRENCY],
                config_path=cfg_path,
                kb_base_dir=kb_base_dir,
                profile_cfg=profile_cfg,
                rag_cfg=rag_cfg,
                output_dir=output_dir,
                skip_extract=args.skip_extract,
                use_mineru_api=args.use_mineru_api,
                mineru_api_token=args.mineru_api_token,
                mineru_model_version=args.mineru_model_version,
                force=args.force,
                kb_only=args.kb_only,
            )
        except PipelineAbortError as e:
            logger.error("%s", e)
            raise SystemExit(1)

    all_profiles = sorted(output_dir.glob("*.json"))
    all_profiles = [p for p in all_profiles if p.name != "_summary.json"]
    total_complete = len(all_profiles)

    summary = {
        "timestamp": timestamp,
        "docs_dir": str(docs_dir),
        "kb_base_dir": str(kb_base_dir),
        "num_pdfs": len(pdfs),
        "num_new": len(results),
        "num_total_complete": total_complete,
        "results": [
            {
                "pdf_file": r["pdf_file"],
                "kb_name": r["kb_name"],
                "num_profiles": r["num_profiles"],
            }
            for r in results
        ],
    }
    summary_path = output_dir / "_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\nDone.")
    print(f"Output dir: {output_dir}")
    print(f"Summary: {summary_path}")
    print(f"This run: {len(results)} new | Total complete: {total_complete}/{len(pdfs)} PDFs")


if __name__ == "__main__":
    asyncio.run(main())
