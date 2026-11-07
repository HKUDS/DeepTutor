#!/usr/bin/env python3
"""
Fix kb_config.json status for KBs whose RAG storage is actually complete.

Scans all KB directories, checks if RAG files are intact, and updates
kb_config.json entries from "processing"/"error" to "ready" when appropriate.

Usage:
    python3 -m benchmark.tools.fix_kb_config [--kb-dir data/knowledge_bases] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

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

ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_RED = "\033[91m"
ANSI_DIM = "\033[2m"
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"


def _is_rag_healthy(kb_dir: Path) -> tuple[bool, str]:
    """Check if a KB's RAG storage is complete and healthy.

    Returns (healthy, reason).
    """
    rag_dir = kb_dir / "rag_storage"
    if not rag_dir.is_dir():
        return False, "rag_storage/ missing"

    for fname in CRITICAL_RAG_FILES:
        fpath = rag_dir / fname
        if not fpath.exists():
            return False, f"{fname} missing"
        if fpath.stat().st_size == 0:
            return False, f"{fname} empty"

    status_path = rag_dir / "kv_store_doc_status.json"
    if status_path.exists():
        try:
            with open(status_path, encoding="utf-8") as f:
                doc_status = json.load(f)
            for doc_id, doc in doc_status.items():
                if isinstance(doc, dict) and doc.get("status") == "failed":
                    return False, f"doc '{doc_id[:40]}' status=failed"
        except Exception as e:
            return False, f"doc_status unreadable: {e}"

    chunks_path = rag_dir / "kv_store_text_chunks.json"
    try:
        with open(chunks_path, encoding="utf-8") as f:
            chunks = json.load(f)
        if isinstance(chunks, dict) and len(chunks) == 0:
            return False, "text_chunks empty (0 entries)"
    except Exception:
        return False, "text_chunks unreadable"

    meta_path = kb_dir / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path, encoding="utf-8") as f:
                meta = json.load(f)
            if not meta.get("rag_provider"):
                return False, "metadata.json: rag_provider is null"
        except Exception:
            pass

    return True, "ok"


def main():
    parser = argparse.ArgumentParser(
        description="Fix kb_config.json status for KBs with healthy RAG storage"
    )
    parser.add_argument(
        "--kb-dir",
        default="data/knowledge_bases",
        help="Path to knowledge_bases directory (default: data/knowledge_bases)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without actually writing changes.",
    )
    args = parser.parse_args()

    kb_base = Path(args.kb_dir)
    if not kb_base.is_absolute():
        kb_base = (_PROJECT_ROOT / kb_base).resolve()

    if not kb_base.is_dir():
        print(f"Error: {kb_base} is not a directory", file=sys.stderr)
        sys.exit(1)

    config_path = kb_base / "kb_config.json"
    if not config_path.exists():
        print(f"Error: {config_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    kbs = config.get("knowledge_bases", {})
    if not kbs:
        print("No knowledge bases in config.")
        sys.exit(0)

    kb_dirs = sorted(
        d for d in kb_base.iterdir()
        if d.is_dir() and (d / "rag_storage").is_dir()
    )

    fixed: list[str] = []
    skipped_ok: list[str] = []
    skipped_bad: list[str] = []
    registered: list[str] = []

    for kb_dir in kb_dirs:
        name = kb_dir.name
        entry = kbs.get(name)
        status = entry.get("status") if entry else None

        if status == "ready":
            skipped_ok.append(name)
            continue

        healthy, reason = _is_rag_healthy(kb_dir)

        if not healthy:
            label = f"status={status}" if status else "not in config"
            print(f"  {ANSI_RED}✗{ANSI_RESET} {name}  {ANSI_DIM}({label}, unhealthy: {reason}){ANSI_RESET}")
            skipped_bad.append(name)
            continue

        if not entry:
            now = datetime.now().isoformat()
            kbs[name] = {
                "path": name,
                "description": f"Knowledge base: {name}",
                "status": "ready",
                "updated_at": now,
                "progress": {
                    "stage": "completed",
                    "message": "Fixed by fix_kb_config",
                    "percent": 100,
                    "current": 1,
                    "total": 1,
                    "file_name": "",
                    "error": None,
                    "timestamp": now,
                },
            }
            action = "REGISTER + FIX"
            registered.append(name)
        else:
            old_status = entry.get("status", "?")
            entry["status"] = "ready"
            entry["updated_at"] = datetime.now().isoformat()
            entry.setdefault("progress", {})["stage"] = "completed"
            entry["progress"]["message"] = f"Fixed by fix_kb_config (was: {old_status})"
            entry["progress"]["error"] = None
            action = f"{old_status} → ready"

        print(f"  {ANSI_GREEN}✓{ANSI_RESET} {name}  {ANSI_BOLD}{action}{ANSI_RESET}")
        fixed.append(name)

    print(f"\n{'=' * 60}")
    print(
        f"Result: "
        f"{ANSI_GREEN}{len(fixed)} fixed{ANSI_RESET} | "
        f"{len(skipped_ok)} already ready | "
        f"{ANSI_RED}{len(skipped_bad)} unhealthy (skipped){ANSI_RESET}"
    )

    if fixed:
        print(f"\n{ANSI_GREEN}{ANSI_BOLD}Fixed ({len(fixed)}):{ANSI_RESET}")
        for name in fixed:
            print(f"  {ANSI_GREEN}✓{ANSI_RESET} {name}")

    if skipped_bad:
        print(f"\n{ANSI_RED}Unhealthy — not fixed ({len(skipped_bad)}):{ANSI_RESET}")
        for name in skipped_bad:
            print(f"  {ANSI_RED}✗{ANSI_RESET} {name}")

    if not fixed:
        print("\nNothing to fix.")
        sys.exit(0)

    if args.dry_run:
        print(f"\n{ANSI_YELLOW}[DRY RUN] No changes written.{ANSI_RESET}")
    else:
        config["knowledge_bases"] = kbs
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"\n{ANSI_GREEN}Saved: {config_path}{ANSI_RESET}")


if __name__ == "__main__":
    main()
