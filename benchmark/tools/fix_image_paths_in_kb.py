#!/usr/bin/env python3
"""
Repair stale image paths inside KB JSON artifacts.

Typical issue:
  - Old paths point to content_list/.../auto/images/*.jpg (or docling/images)
  - Files were migrated to kb/images/*.jpg, old parser dirs were cleaned
  - Retrieval/evaluation logs: "Image file not found: .../content_list/.../auto/images/..."

This script rewrites stale image paths in:
  - content_list/*.json
  - rag_storage/*.json

Usage:
  python -m benchmark.tools.fix_image_paths_in_kb --kb-dir data/knowledge_bases --dry-run
  python -m benchmark.tools.fix_image_paths_in_kb --kb-dir data/knowledge_bases --kb-name my_kb
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

ANSI_GREEN = "\033[92m"
ANSI_YELLOW = "\033[93m"
ANSI_RED = "\033[91m"
ANSI_DIM = "\033[2m"
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"

TARGET_SUBDIRS = ("auto/images", "docling/images", "content_list")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
_TARGET_HINTS_LOWER = tuple(x.lower() for x in TARGET_SUBDIRS)
_STALE_IMAGE_PATH_RE = re.compile(
    r'([^\s"\'<>]*?(?:content_list|auto/images|docling/images)[^\s"\'<>]*?'
    r'(?:\.png|\.jpg|\.jpeg|\.webp|\.gif|\.bmp))',
    flags=re.IGNORECASE,
)


@dataclass
class FileFixResult:
    path: Path
    scanned_strings: int = 0
    replaced_strings: int = 0
    changed: bool = False
    error: str | None = None


def _load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _looks_like_stale_path(value: str) -> bool:
    v = value.replace("\\", "/")
    return any(token in v for token in TARGET_SUBDIRS)


def _rewrite_embedded_paths(value: str, images_dir: Path, stats: dict[str, int]) -> str:
    """
    Rewrite stale image paths embedded inside longer strings.

    Example:
      "Image Path: /.../content_list/.../auto/images/abc.jpg"
      -> "Image Path: /.../knowledge_bases/<kb>/images/abc.jpg"
    """
    # Fast-path: skip regex for most strings.
    lower = value.lower()
    if not any(h in lower for h in _TARGET_HINTS_LOWER):
        return value

    def _replace(match: re.Match[str]) -> str:
        old = match.group(1)
        basename = Path(old).name
        if not basename:
            return old
        candidate = images_dir / basename
        if candidate.exists():
            stats["replaced"] += 1
            return str(candidate.resolve())
        return old

    return _STALE_IMAGE_PATH_RE.sub(_replace, value)


def _maybe_rewrite_path(value: str, images_dir: Path, stats: dict[str, int]) -> str:
    """Return rewritten path if stale and basename exists in kb/images."""
    if not isinstance(value, str):
        return value

    # 1) Embedded path inside longer text
    rewritten = _rewrite_embedded_paths(value, images_dir, stats)
    if rewritten != value:
        return rewritten

    # 2) Whole-string path rewrite
    if _looks_like_stale_path(value):
        basename = Path(value).name
        if basename:
            candidate = images_dir / basename
            if candidate.exists():
                stats["replaced"] += 1
                return str(candidate.resolve())
    return value


def _rewrite_obj(obj: Any, images_dir: Path, stats: dict[str, int]) -> Any:
    if isinstance(obj, dict):
        return {k: _rewrite_obj(v, images_dir, stats) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_rewrite_obj(x, images_dir, stats) for x in obj]
    if isinstance(obj, str):
        stats["scanned"] += 1
        return _maybe_rewrite_path(obj, images_dir, stats)
    return obj


def _backup_file(path: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, backup)
    return backup


def _fix_one_json(path: Path, images_dir: Path, dry_run: bool, backup: bool) -> FileFixResult:
    result = FileFixResult(path=path)
    try:
        original = _load_json(path)
        stats = {"scanned": 0, "replaced": 0}
        updated = _rewrite_obj(original, images_dir, stats)
        result.scanned_strings = stats["scanned"]
        result.replaced_strings = stats["replaced"]
        result.changed = stats["replaced"] > 0

        if result.changed and not dry_run:
            if backup:
                _backup_file(path)
            _dump_json(path, updated)
        return result
    except Exception as e:
        result.error = str(e)
        return result


def _collect_target_jsons(kb_dir: Path) -> list[Path]:
    targets: list[Path] = []
    cl_dir = kb_dir / "content_list"
    rag_dir = kb_dir / "rag_storage"
    if cl_dir.is_dir():
        targets.extend(sorted(cl_dir.glob("**/*.json")))
    if rag_dir.is_dir():
        targets.extend(sorted(rag_dir.glob("**/*.json")))
    # Deduplicate while preserving order
    seen = set()
    unique_targets: list[Path] = []
    for p in targets:
        sp = str(p.resolve())
        if sp in seen:
            continue
        seen.add(sp)
        unique_targets.append(p)
    return unique_targets


def _iter_kb_dirs(base: Path, kb_filter: set[str] | None) -> list[Path]:
    dirs = [d for d in sorted(base.iterdir()) if d.is_dir() and d.name != "manifests"]
    if kb_filter:
        dirs = [d for d in dirs if d.name in kb_filter]
    return dirs


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix stale image paths in KB JSON artifacts.")
    parser.add_argument(
        "--kb-dir",
        default="data/knowledge_bases",
        help="Path to knowledge_bases directory (default: data/knowledge_bases)",
    )
    parser.add_argument(
        "--kb-name",
        default="",
        help="Optional comma-separated KB names to process (default: all).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .bak timestamped backups before writing.",
    )
    parser.add_argument(
        "--clear-llm-cache",
        action="store_true",
        help="Also clear rag_storage/kv_store_llm_response_cache.json after rewriting.",
    )
    args = parser.parse_args()

    kb_base = Path(args.kb_dir)
    if not kb_base.is_absolute():
        kb_base = (_PROJECT_ROOT / kb_base).resolve()
    if not kb_base.is_dir():
        print(f"{ANSI_RED}Error: {kb_base} is not a directory{ANSI_RESET}", file=sys.stderr)
        sys.exit(1)

    kb_filter = {x.strip() for x in args.kb_name.split(",") if x.strip()} or None
    kb_dirs = _iter_kb_dirs(kb_base, kb_filter)
    if not kb_dirs:
        print(f"{ANSI_YELLOW}No KB directories found to process.{ANSI_RESET}")
        sys.exit(0)

    print(f"KB dir: {kb_base}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}")
    print(f"Backup: {not args.no_backup}")
    print(f"KB count: {len(kb_dirs)}\n")

    total_files = total_changed = total_replaced = total_errors = 0

    for kb_dir in kb_dirs:
        images_dir = kb_dir / "images"
        targets = _collect_target_jsons(kb_dir)
        print(f"{ANSI_BOLD}{kb_dir.name}{ANSI_RESET}  ({len(targets)} json files)")
        if not images_dir.is_dir():
            print(f"  {ANSI_YELLOW}⚠ images/ missing, skipping{ANSI_RESET}")
            continue

        kb_changed = kb_replaced = kb_errors = 0
        for idx, path in enumerate(targets, start=1):
            print(f"  {ANSI_DIM}→ [{idx}/{len(targets)}] scanning {path.name}{ANSI_RESET}")
            started = time.time()
            r = _fix_one_json(
                path=path,
                images_dir=images_dir,
                dry_run=args.dry_run,
                backup=not args.no_backup,
            )
            elapsed = time.time() - started
            total_files += 1
            if r.error:
                kb_errors += 1
                total_errors += 1
                print(f"  {ANSI_RED}✗{ANSI_RESET} {path.name}: {r.error} ({elapsed:.1f}s)")
                continue
            if r.changed:
                kb_changed += 1
                kb_replaced += r.replaced_strings
                total_changed += 1
                total_replaced += r.replaced_strings
                print(
                    f"  {ANSI_GREEN}✓{ANSI_RESET} {path.name}: replaced {r.replaced_strings}"
                    f" {ANSI_DIM}(scanned={r.scanned_strings}, {elapsed:.1f}s){ANSI_RESET}"
                )
            else:
                print(f"  {ANSI_DIM}- {path.name}: no change ({elapsed:.1f}s){ANSI_RESET}")

        if kb_changed == 0 and kb_errors == 0:
            print(f"  {ANSI_DIM}- no stale paths rewritten{ANSI_RESET}")
        else:
            msg = (
                f"  changed_files={kb_changed}, replaced_paths={kb_replaced}, errors={kb_errors}"
            )
            print(f"  {msg}")

        if args.clear_llm_cache:
            cache_path = kb_dir / "rag_storage" / "kv_store_llm_response_cache.json"
            if cache_path.exists():
                if args.dry_run:
                    print(f"  {ANSI_YELLOW}~{ANSI_RESET} would clear cache: {cache_path.name}")
                else:
                    try:
                        if not args.no_backup:
                            _backup_file(cache_path)
                        _dump_json(cache_path, {})
                        print(f"  {ANSI_GREEN}✓{ANSI_RESET} cleared cache: {cache_path.name}")
                    except Exception as e:
                        total_errors += 1
                        print(f"  {ANSI_RED}✗{ANSI_RESET} clear cache failed: {e}")
        print()

    print("=" * 72)
    print(
        f"Scanned files: {total_files} | Changed files: {total_changed} | "
        f"Replaced paths: {total_replaced} | Errors: {total_errors}"
    )
    if args.dry_run:
        print(f"{ANSI_YELLOW}[DRY-RUN] No files were modified.{ANSI_RESET}")
    elif total_changed > 0:
        print(f"{ANSI_GREEN}Done. Rewrites applied.{ANSI_RESET}")
    else:
        print("Done. Nothing to rewrite.")


if __name__ == "__main__":
    main()

