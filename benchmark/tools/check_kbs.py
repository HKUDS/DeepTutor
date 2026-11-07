#!/usr/bin/env python3
"""
Diagnose health of all knowledge bases.

Usage:
    python3 -m benchmark.tools.check_kbs [--kb-dir data/knowledge_bases]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

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

OPTIONAL_RAG_FILES = [
    "kv_store_doc_status.json",
    "kv_store_llm_response_cache.json",
    "kv_store_parse_cache.json",
]

ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_RED = "\033[91m"
ANSI_DIM = "\033[2m"
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"


def _size_str(path: Path) -> str:
    if not path.exists():
        return "missing"
    size = path.stat().st_size
    if size == 0:
        return f"{ANSI_RED}0 B (EMPTY){ANSI_RESET}"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _load_json(path: Path) -> dict | list | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _check_doc_status(rag_dir: Path) -> tuple[int, int, int, list[str]]:
    """Return (total, processed, failed, problem_docs)."""
    status_file = rag_dir / "kv_store_doc_status.json"
    data = _load_json(status_file)
    if not data:
        return 0, 0, 0, ["doc_status file missing or unreadable"]

    total = processed = failed = 0
    problems: list[str] = []
    for doc_id, doc in data.items():
        if not isinstance(doc, dict):
            continue
        total += 1
        status = doc.get("status")
        if status == "processed":
            processed += 1
        elif status == "failed":
            failed += 1
            err = doc.get("error", "unknown error")
            summary = doc.get("content_summary", doc_id)[:60]
            problems.append(f"FAILED: {summary} — {err}")
        elif status in ("processing", "pending"):
            problems.append(f"{status.upper()}: {doc.get('content_summary', doc_id)[:60]}")
    return total, processed, failed, problems


def _count_json_entries(path: Path) -> int | None:
    data = _load_json(path)
    if isinstance(data, dict):
        return len(data)
    if isinstance(data, list):
        return len(data)
    return None


def check_kb(kb_dir: Path, kb_config_entry: dict | None) -> dict:
    """Check a single KB and return a report dict."""
    report: dict = {"name": kb_dir.name, "issues": [], "warnings": [], "stats": {}}
    issues = report["issues"]
    warnings = report["warnings"]
    stats = report["stats"]

    # --- metadata.json ---
    meta_path = kb_dir / "metadata.json"
    meta = _load_json(meta_path)
    if not meta:
        issues.append("metadata.json missing or unreadable")
    else:
        if not meta.get("rag_provider"):
            issues.append("metadata.json: rag_provider is null (processing incomplete)")
        if not meta.get("file_hashes"):
            warnings.append("metadata.json: no file_hashes recorded")
        stats["rag_provider"] = meta.get("rag_provider")
        stats["created_at"] = meta.get("created_at")

    # --- kb_config status ---
    if kb_config_entry:
        cfg_status = kb_config_entry.get("status")
        stats["config_status"] = cfg_status
        progress = kb_config_entry.get("progress", {})
        stats["config_stage"] = progress.get("stage")
        if cfg_status == "error":
            issues.append(f"kb_config status=error: {progress.get('error', '?')}")
        elif cfg_status == "processing":
            warnings.append(f"kb_config status=processing (stage={progress.get('stage')})")
    else:
        warnings.append("not registered in kb_config.json")

    # --- rag_storage directory ---
    rag_dir = kb_dir / "rag_storage"
    if not rag_dir.is_dir():
        issues.append("rag_storage/ directory missing")
        return report

    # Critical files
    for fname in CRITICAL_RAG_FILES:
        fpath = rag_dir / fname
        if not fpath.exists():
            issues.append(f"rag_storage/{fname} MISSING")
        elif fpath.stat().st_size == 0:
            issues.append(f"rag_storage/{fname} is EMPTY (0 bytes)")
        else:
            stats[fname] = _size_str(fpath)

    # doc_status
    total, processed, failed, doc_problems = _check_doc_status(rag_dir)
    stats["docs_total"] = total
    stats["docs_processed"] = processed
    stats["docs_failed"] = failed
    if failed > 0:
        issues.append(f"{failed}/{total} document(s) FAILED")
    if total > 0 and processed < total and failed == 0:
        pending = total - processed
        warnings.append(f"{pending}/{total} document(s) still pending/processing")
    for p in doc_problems:
        if p.startswith("FAILED"):
            issues.append(p)
        else:
            warnings.append(p)

    # Entity / relation / chunk counts
    entities_count = _count_json_entries(rag_dir / "kv_store_full_entities.json")
    relations_count = _count_json_entries(rag_dir / "kv_store_full_relations.json")
    chunks_count = _count_json_entries(rag_dir / "kv_store_text_chunks.json")
    stats["entities"] = entities_count
    stats["relations"] = relations_count
    stats["chunks"] = chunks_count

    if chunks_count is not None and chunks_count == 0:
        issues.append("text_chunks is empty — no searchable content")
    if entities_count is not None and entities_count == 0:
        warnings.append("no entities extracted (knowledge graph empty)")

    # --- content_list ---
    cl_dir = kb_dir / "content_list"
    if cl_dir.is_dir():
        cl_files = list(cl_dir.glob("*.json"))
        stats["content_list_files"] = len(cl_files)
    else:
        warnings.append("content_list/ directory missing")

    # --- numbered_items ---
    ni_path = kb_dir / "numbered_items.json"
    if ni_path.exists():
        ni_data = _load_json(ni_path)
        stats["numbered_items"] = len(ni_data) if isinstance(ni_data, list) else "?"
    else:
        stats["numbered_items"] = None

    # --- raw documents ---
    raw_dir = kb_dir / "raw"
    if raw_dir.is_dir():
        raw_files = [f for f in raw_dir.iterdir() if f.is_file()]
        stats["raw_files"] = len(raw_files)
    else:
        warnings.append("raw/ directory missing")

    return report


def print_report(report: dict) -> str:
    """Print a single KB report. Returns 'ok' | 'warn' | 'error'."""
    name = report["name"]
    issues = report["issues"]
    warnings = report["warnings"]
    stats = report["stats"]

    if issues:
        icon = f"{ANSI_RED}✗{ANSI_RESET}"
        status = "ERROR"
    elif warnings:
        icon = f"{ANSI_YELLOW}⚠{ANSI_RESET}"
        status = "WARN"
    else:
        icon = f"{ANSI_GREEN}✓{ANSI_RESET}"
        status = "OK"

    print(f"\n{icon} {ANSI_BOLD}{name}{ANSI_RESET}")

    # Stats line
    parts = []
    if stats.get("docs_total") is not None:
        parts.append(f"docs={stats['docs_processed']}/{stats['docs_total']}")
    if stats.get("chunks") is not None:
        parts.append(f"chunks={stats['chunks']}")
    if stats.get("entities") is not None:
        parts.append(f"entities={stats['entities']}")
    if stats.get("relations") is not None:
        parts.append(f"relations={stats['relations']}")
    if stats.get("numbered_items") is not None:
        parts.append(f"numbered_items={stats['numbered_items']}")
    elif stats.get("numbered_items") is None:
        parts.append(f"numbered_items={ANSI_DIM}N/A{ANSI_RESET}")
    if stats.get("config_status"):
        parts.append(f"config={stats['config_status']}")
    if parts:
        print(f"  {' | '.join(parts)}")

    # File sizes
    rag_files_shown = [f for f in CRITICAL_RAG_FILES if f in stats]
    if rag_files_shown:
        sizes = [f"{f.replace('kv_store_', '').replace('.json', '').replace('.graphml', '')}={stats[f]}" for f in rag_files_shown]
        print(f"  {ANSI_DIM}{' | '.join(sizes)}{ANSI_RESET}")

    for w in warnings:
        print(f"  {ANSI_YELLOW}⚠ {w}{ANSI_RESET}")
    for i in issues:
        print(f"  {ANSI_RED}✗ {i}{ANSI_RESET}")

    return "error" if issues else ("warn" if warnings else "ok")


_RAG_TOOL_SCRIPT = _PROJECT_ROOT / "src" / "tools" / "rag_tool.py"


async def _test_rag_query(kb_name: str, kb_base_dir: str, timeout: float = 60.0) -> tuple[bool, str]:
    """Run rag_tool.py as a subprocess to test if a KB is queryable.

    Returns (success, message).
    """
    cmd = [
        sys.executable,
        str(_RAG_TOOL_SCRIPT),
        "--kb-name", kb_name,
        "--kb-base-dir", kb_base_dir,
        "--query", "What is the main topic of this document?",
        "--mode", "naive",
    ]
    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(_PROJECT_ROOT),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        elapsed = time.monotonic() - t0

        if proc.returncode != 0:
            err_line = (stderr or stdout or b"").decode(errors="replace").strip().split("\n")[-1][:120]
            return False, f"exit code {proc.returncode} ({elapsed:.1f}s): {err_line}"

        output = stdout.decode(errors="replace")
        answer_lines: list[str] = []
        capturing = False
        for line in output.splitlines():
            if line.startswith("Answer:"):
                capturing = True
                first = line[len("Answer:"):].strip()
                if first:
                    answer_lines.append(first)
            elif capturing:
                answer_lines.append(line)

        if capturing:
            answer = "\n".join(answer_lines).strip()
            if not answer:
                return False, f"empty answer ({elapsed:.1f}s)"
            return True, f"ok ({elapsed:.1f}s)\n{answer}"

        return False, f"no Answer line in output ({elapsed:.1f}s)"
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, f"timeout (>{timeout:.0f}s)"
    except Exception as e:
        msg = str(e).split("\n")[0][:120]
        return False, f"error: {msg}"


async def main():
    import logging

    parser = argparse.ArgumentParser(description="Check health of all knowledge bases")
    parser.add_argument(
        "--kb-dir",
        default="data/knowledge_bases",
        help="Path to knowledge_bases directory (default: data/knowledge_bases)",
    )
    parser.add_argument(
        "--no-rag",
        action="store_true",
        help="Skip live RAG query test (only run static checks).",
    )
    parser.add_argument(
        "--rag-timeout",
        type=float,
        default=60.0,
        help="Timeout in seconds for each RAG test query (default: 60).",
    )
    args = parser.parse_args()

    kb_base = Path(args.kb_dir)
    if not kb_base.is_absolute():
        kb_base = (_PROJECT_ROOT / kb_base).resolve()

    if not kb_base.is_dir():
        print(f"Error: {kb_base} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Load kb_config.json
    kb_config_path = kb_base / "kb_config.json"
    kb_config: dict = {}
    if kb_config_path.exists():
        data = _load_json(kb_config_path)
        if isinstance(data, dict):
            kb_config = data.get("knowledge_bases", {})

    # Find all KB directories (has metadata.json OR rag_storage/)
    kb_dirs = sorted(
        d
        for d in kb_base.iterdir()
        if d.is_dir()
        and (
            (d / "metadata.json").exists()
            or (d / "rag_storage").is_dir()
            or d.name in kb_config
        )
    )

    if not kb_dirs:
        print("No knowledge bases found.")
        sys.exit(0)

    print(f"{ANSI_BOLD}Knowledge Base Health Check{ANSI_RESET}")
    print(f"Directory: {kb_base}")
    print(f"Found {len(kb_dirs)} KB(s), {len(kb_config)} registered in kb_config.json")

    # --- Phase 1: Static checks ---
    print(f"\n{'=' * 60}")
    print(f"{ANSI_BOLD}Phase 1: Static checks{ANSI_RESET}")
    print(f"{'=' * 60}")

    groups: dict[str, list[str]] = {"ok": [], "warn": [], "error": []}
    for kb_dir in kb_dirs:
        cfg_entry = kb_config.get(kb_dir.name)
        report = check_kb(kb_dir, cfg_entry)
        result = print_report(report)
        groups[result].append(kb_dir.name)

    for cfg_name in kb_config:
        if not (kb_base / cfg_name).is_dir():
            print(f"\n{ANSI_RED}✗ {ANSI_BOLD}{cfg_name}{ANSI_RESET}")
            print(f"  {ANSI_RED}✗ registered in kb_config.json but directory missing{ANSI_RESET}")
            groups["error"].append(cfg_name)

    print(f"\n{'=' * 60}")
    print(
        f"Static: "
        f"{ANSI_GREEN}{len(groups['ok'])} OK{ANSI_RESET} | "
        f"{ANSI_YELLOW}{len(groups['warn'])} WARN{ANSI_RESET} | "
        f"{ANSI_RED}{len(groups['error'])} ERROR{ANSI_RESET}"
    )

    # --- Phase 2: Live RAG tests (all KBs, parallel) ---
    all_kb_names = [d.name for d in kb_dirs]
    if args.no_rag or not all_kb_names:
        _print_final_summary(groups, rag_results=None)
        sys.exit(1 if groups["error"] else 0)

    logging.disable(logging.CRITICAL)

    print(f"\n{'=' * 60}")
    print(
        f"{ANSI_BOLD}Phase 2: Live RAG query test{ANSI_RESET} "
        f"({len(all_kb_names)} KBs, parallel, timeout={args.rag_timeout:.0f}s each)"
    )
    print(f"{'=' * 60}")

    async def _test_one(kb_name: str) -> tuple[str, bool, str]:
        ok, msg = await _test_rag_query(kb_name, str(kb_base), timeout=args.rag_timeout)
        return kb_name, ok, msg

    results = await asyncio.gather(*[_test_one(name) for name in all_kb_names])

    rag_pass: list[str] = []
    rag_fail: list[str] = []
    for kb_name, ok, msg in sorted(results, key=lambda r: r[0]):
        if ok:
            header, _, body = msg.partition("\n")
            print(f"  {ANSI_GREEN}✓{ANSI_RESET} {kb_name}  {ANSI_DIM}{header}{ANSI_RESET}")
            if body:
                for line in body.splitlines():
                    print(f"    {ANSI_DIM}{line}{ANSI_RESET}")
            rag_pass.append(kb_name)
        else:
            print(f"  {ANSI_RED}✗{ANSI_RESET} {kb_name}  {msg}")
            rag_fail.append(kb_name)

    logging.disable(logging.NOTSET)

    print(f"\n{'=' * 60}")
    print(
        f"RAG test: "
        f"{ANSI_GREEN}{len(rag_pass)} PASS{ANSI_RESET} | "
        f"{ANSI_RED}{len(rag_fail)} FAIL{ANSI_RESET}"
    )

    _print_final_summary(groups, rag_results={"pass": rag_pass, "fail": rag_fail})
    sys.exit(1 if groups["error"] else 0)


def _print_final_summary(
    groups: dict[str, list[str]],
    rag_results: dict[str, list[str]] | None,
) -> None:
    """Print the combined final summary."""
    print(f"\n{'=' * 60}")
    total_ok = len(groups["ok"])
    total_warn = len(groups["warn"])
    total_err = len(groups["error"])
    print(
        f"{ANSI_BOLD}Final:{ANSI_RESET} "
        f"{ANSI_GREEN}{total_ok} OK{ANSI_RESET} | "
        f"{ANSI_YELLOW}{total_warn} WARN{ANSI_RESET} | "
        f"{ANSI_RED}{total_err} ERROR{ANSI_RESET}"
    )

    if rag_results:
        rp = sorted(rag_results.get("pass", []))
        rf = sorted(rag_results.get("fail", []))
        if rp:
            print(f"\n{ANSI_GREEN}{ANSI_BOLD}RAG OK ({len(rp)}):{ANSI_RESET}")
            for name in rp:
                print(f"  {ANSI_GREEN}✓{ANSI_RESET} {name}")
        if rf:
            print(f"\n{ANSI_RED}{ANSI_BOLD}RAG FAIL ({len(rf)}):{ANSI_RESET}")
            for name in rf:
                print(f"  {ANSI_RED}✗{ANSI_RESET} {name}")

    if groups["ok"]:
        print(f"\n{ANSI_GREEN}Static OK ({len(groups['ok'])}):{ANSI_RESET}")
        for name in sorted(groups["ok"]):
            print(f"  {ANSI_GREEN}✓{ANSI_RESET} {name}")

    if groups["warn"]:
        print(f"\n{ANSI_YELLOW}Static WARN ({len(groups['warn'])}):{ANSI_RESET}")
        for name in sorted(groups["warn"]):
            print(f"  {ANSI_YELLOW}⚠{ANSI_RESET} {name}")

    if groups["error"]:
        print(f"\n{ANSI_RED}Static ERROR ({len(groups['error'])}):{ANSI_RESET}")
        for name in sorted(groups["error"]):
            print(f"  {ANSI_RED}✗{ANSI_RESET} {name}")


if __name__ == "__main__":
    asyncio.run(main())
