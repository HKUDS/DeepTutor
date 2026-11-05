#!/usr/bin/env python3
"""Preview old LlamaIndex snapshots; deletion is an explicit offline operation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deeptutor.services.rag.version_retention import obsolete_versions, prune_versions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kb_dirs", nargs="+", type=Path, help="Exact knowledge-base directories")
    parser.add_argument(
        "--keep", type=int, default=2, help="Published versions per signature (min 2)"
    )
    parser.add_argument(
        "--protect-version", action="append", default=[], help="Keep a pinned version name"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Delete the previewed obsolete snapshots"
    )
    parser.add_argument(
        "--offline", action="store_true", help="Confirm all workers/indexers are stopped"
    )
    args = parser.parse_args()
    if args.keep < 2 or (args.apply and not args.offline):
        parser.error("--keep must be >= 2; --apply also requires --offline")
    protected = frozenset(args.protect_version)
    # Validate all requested roots before performing any deletion.
    roots = list(dict.fromkeys(path.expanduser().resolve(strict=True) for path in args.kb_dirs))
    if not all(root.is_dir() for root in roots):
        parser.error("Every kb_dir must be a directory")
    report = []
    for root in roots:
        candidates = obsolete_versions(root, keep=args.keep, protected=protected)
        size = sum(
            p.stat().st_size
            for v in candidates
            for p in v.rglob("*")
            if p.is_file() and not p.is_symlink()
        )
        row = {"kb_dir": str(root), "versions": [p.name for p in candidates], "bytes": size}
        if args.apply:
            row["removed"] = prune_versions(root, keep=args.keep, protected=protected, offline=True)
        report.append(row)
    print(json.dumps({"applied": args.apply, "knowledge_bases": report}, indent=2))


if __name__ == "__main__":
    main()
