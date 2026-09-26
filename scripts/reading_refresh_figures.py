#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Refresh embedded figures for already-ingested reading materials (PDF only).

Usage — always run with the project venv's python. The system python has none
of the ``deeptutor`` dependencies installed, so it fails at import time:

    cd /d/DeepTutor
    ./venv/Scripts/python.exe scripts/reading_refresh_figures.py --dry-run --all
    ./venv/Scripts/python.exe scripts/reading_refresh_figures.py --dry-run --material 66ca25db46bf8a41
    ./venv/Scripts/python.exe scripts/reading_refresh_figures.py --all --yes
    ./venv/Scripts/python.exe scripts/reading_refresh_figures.py --material 66ca25db46bf8a41 --caption --yes
    ./venv/Scripts/python.exe scripts/reading_refresh_figures.py --material 66ca25db46bf8a41 --no-caption --yes

For each PDF material whose manifest says ``extractor == "pymupdf"`` and whose
original bytes are still on disk, this re-extracts the document **in place**
(``ReadingStore.refresh_document``) so embedded images land in ``media/`` and
``media.json``; annotations, bookmarks and reading position are preserved. With
captioning enabled, each stored image is captioned through the configured model.

This is a destructive in-place rewrite of ``data/user/workspace/reading``. Back
that directory up before a non-dry run if the annotations there matter to you.
Without ``--yes`` a non-dry run asks for interactive confirmation, and refuses
to run at all in a non-interactive shell.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from deeptutor.reading.refresh import pdf_materials, refresh_materials  # noqa: E402
from deeptutor.reading.store import ReadingStore  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-extract embedded figures for ingested PDF materials.",
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--material",
        action="append",
        metavar="ID",
        help="material id to refresh (repeatable)",
    )
    target.add_argument(
        "--all",
        action="store_true",
        help="refresh every eligible PDF material",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read-only: print what would be refreshed, write nothing",
    )
    captions = parser.add_mutually_exclusive_group()
    captions.add_argument(
        "--caption", action="store_true", help="caption stored images (explicit on)"
    )
    captions.add_argument(
        "--no-caption", action="store_true", help="skip captioning (explicit off)"
    )
    parser.add_argument(
        "--force-caption",
        action="store_true",
        help="caption even if a stored caption already exists (implies --caption)",
    )
    parser.add_argument("--limit", type=int, metavar="N", help="process at most N materials")
    parser.add_argument("--yes", action="store_true", help="skip the interactive confirmation")
    return parser


def _captions_enabled() -> bool:
    """Config default for captioning, tolerating the module not existing yet."""
    try:
        from deeptutor.reading.captions import captions_enabled
    except ImportError:
        print(
            "note: captioning module unavailable; defaulting to --no-caption",
            file=sys.stderr,
        )
        return False
    try:
        return bool(captions_enabled())
    except Exception as exc:  # noqa: BLE001 - a bad config must not block dry runs
        print(f"note: captions_enabled() failed ({exc}); defaulting to off", file=sys.stderr)
        return False


def _print_table(summary: dict) -> None:
    rows = summary["rows"]
    print()
    print("mode:", "dry-run" if summary["dry_run"] else "refresh")
    header = ("material id", "filename", "old media", "new media", "captions")
    table = [header]
    for row in rows:
        table.append(
            (
                str(row["material_id"]),
                str(row["filename"]),
                str(row["old_media"]),
                "-" if row["new_media"] is None else str(row["new_media"]),
                "-" if row["captions"] is None else str(row["captions"]),
            )
        )
    if len(table) > 1:
        widths = [max(len(line[col]) for line in table) for col in range(len(header))]
        for line in table:
            print("  ".join(cell.ljust(widths[col]) for col, cell in enumerate(line)).rstrip())
    print(
        f"processed={summary['processed']} skipped={summary['skipped']} "
        f"media_added={summary['media_added']} captions={summary['captions']} "
        f"failures={len(summary['failures'])}"
    )
    for failure in summary["failures"]:
        print(
            f"  FAILED {failure['material_id']}: {failure['error']}",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.material and not args.all:
        parser.error("choose one of --material <id> (repeatable) or --all")
    if args.no_caption and args.force_caption:
        parser.error("--no-caption conflicts with --force-caption")

    if args.no_caption:
        caption = False
    elif args.caption or args.force_caption:
        caption = True
    else:
        caption = _captions_enabled()

    material_ids = args.material if args.material else None
    store = ReadingStore()

    if not args.dry_run and not args.yes:
        eligible = pdf_materials(store, material_ids=material_ids)
        if args.limit is not None:
            eligible = eligible[: max(0, args.limit)]
        if not eligible:
            print("nothing to refresh")
            return 0
        if not sys.stdin.isatty():
            print(
                "refusing to run a non-dry refresh without --yes in a non-interactive shell",
                file=sys.stderr,
            )
            return 2
        print(f"about to re-extract {len(eligible)} material(s) in place under {store.root}:")
        for material_id, filename, old_media in eligible:
            print(f"  {material_id}  {filename}  (media={old_media})")
        print(f"captioning: {'on' if caption else 'off'}")
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except EOFError:
            answer = ""
        if answer not in ("y", "yes"):
            print("aborted")
            return 2

    summary = asyncio.run(
        refresh_materials(
            store,
            material_ids,
            dry_run=args.dry_run,
            caption=caption,
            caption_force=args.force_caption,
            limit=args.limit,
        )
    )
    _print_table(summary)
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
