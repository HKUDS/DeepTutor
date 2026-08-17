#!/usr/bin/env python3
"""Migrate a nested immersive-reading data tree without destructive writes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _copy_file_preserving_conflict(
    source: Path,
    destination: Path,
    *,
    run_id: str,
    actions: list[dict[str, str]],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(source, destination)
        actions.append({"action": "copy", "source": str(source), "target": str(destination)})
        return
    if destination.is_dir() or source.is_file():
        conflict = destination.with_name(f"{destination.name}.nested-{run_id}")
        shutil.copy2(source, conflict)
        actions.append(
            {
                "action": "conflict-copy",
                "source": str(source),
                "target": str(conflict),
                "existing": str(destination),
            }
        )
        return
    actions.append({"action": "skip-directory", "source": str(source), "target": str(destination)})


def _copy_tree(
    source: Path,
    destination: Path,
    *,
    run_id: str,
    actions: list[dict[str, str]],
) -> None:
    if source.is_file():
        _copy_file_preserving_conflict(
            source,
            destination,
            run_id=run_id,
            actions=actions,
        )
        return
    if not destination.exists():
        shutil.copytree(source, destination)
        actions.append({"action": "copy-tree", "source": str(source), "target": str(destination)})
        return
    for item in source.iterdir():
        _copy_tree(item, destination / item.name, run_id=run_id, actions=actions)


def _plan_and_migrate(
    source: Path,
    destination: Path,
    *,
    backup_root: Path,
    requested_ids: set[str],
    dry_run: bool = False,
) -> dict[str, Any]:
    if not source.is_dir():
        raise SystemExit(f"Nested data tree does not exist: {source}")
    destination.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    source_settings = source / "settings"
    source_immersive = source / "workspace" / "immersive_reading"
    target_settings = destination / "settings"
    target_immersive = destination / "workspace" / "immersive_reading"

    source_documents = sorted(source_immersive.glob("document_*"))
    source_pairings = sorted((source_immersive / "bilingual").glob("pairing_*"))
    target_pairings = sorted((target_immersive / "bilingual").glob("pairing_*"))
    target_document_ids = {path.name for path in target_immersive.glob("document_*")}
    target_pairs = {
        (
            str(_read_json(path / "pairing.json").get("en_document_id", "")),
            str(_read_json(path / "pairing.json").get("zh_document_id", "")),
        )
        for path in target_pairings
    }

    inventory = {
        "source": str(source),
        "destination": str(destination),
        "documents": [path.name for path in source_documents],
        "pairings": [path.name for path in source_pairings],
        "requested_ids": sorted(requested_ids),
        "requested_ids_found": sorted(
            requested_ids
            & (
                {path.name.removeprefix("document_") for path in source_documents}
                | {path.name.removeprefix("pairing_") for path in source_pairings}
                | target_document_ids
                | {
                    path.name.removeprefix("document_")
                    for path in target_immersive.glob("document_*")
                }
                | {path.name.removeprefix("pairing_") for path in target_pairings}
            )
        ),
    }
    actions: list[dict[str, str]] = []

    settings_files = (
        sorted(path for path in source_settings.iterdir() if path.is_file())
        if source_settings.is_dir()
        else []
    )
    for path in settings_files:
        target = target_settings / path.name
        if target.exists():
            actions.append(
                {"action": "skip-existing-setting", "source": str(path), "target": str(target)}
            )
        else:
            actions.append({"action": "copy-setting", "source": str(path), "target": str(target)})

    for path in source_documents:
        if path.name in target_document_ids:
            actions.append(
                {
                    "action": "merge-existing-document",
                    "source": str(path),
                    "target": str(target_immersive / path.name),
                }
            )
        else:
            actions.append(
                {
                    "action": "copy-document",
                    "source": str(path),
                    "target": str(target_immersive / path.name),
                }
            )

    for path in source_pairings:
        pairing = _read_json(path / "pairing.json")
        pair = (str(pairing.get("en_document_id", "")), str(pairing.get("zh_document_id", "")))
        if pair in target_pairs:
            actions.append(
                {"action": "skip-duplicate-pairing", "source": str(path), "pair": "/".join(pair)}
            )
        else:
            actions.append(
                {
                    "action": "copy-pairing",
                    "source": str(path),
                    "target": str(target_immersive / "bilingual" / path.name),
                }
            )

    report = {
        **inventory,
        "backup_root": str(backup_root),
        "dry_run": dry_run,
        "planned_actions": actions,
        "executed_actions": [],
    }
    if dry_run:
        return report

    backup_root.mkdir(parents=True, exist_ok=True)
    preflight = backup_root / "preflight-manifest.json"
    preflight.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    backup_source = backup_root / "source"
    if not backup_source.exists():
        shutil.copytree(source, backup_source)

    executed: list[dict[str, str]] = []
    for path in settings_files:
        target = target_settings / path.name
        if target.exists():
            executed.append(
                {"action": "skip-existing-setting", "source": str(path), "target": str(target)}
            )
        else:
            shutil.copy2(path, target)
            executed.append({"action": "copy-setting", "source": str(path), "target": str(target)})

    for path in source_documents:
        if path.name in target_document_ids:
            before = len(executed)
            _copy_tree(path, target_immersive / path.name, run_id=run_id, actions=executed)
            if len(executed) == before:
                executed.append({"action": "skip-identical-existing-document", "source": str(path)})
        else:
            shutil.copytree(path, target_immersive / path.name)
            executed.append(
                {
                    "action": "copy-document",
                    "source": str(path),
                    "target": str(target_immersive / path.name),
                }
            )

    target_pairs = {
        (
            str(_read_json(path / "pairing.json").get("en_document_id", "")),
            str(_read_json(path / "pairing.json").get("zh_document_id", "")),
        )
        for path in target_pairings
    }
    for path in source_pairings:
        pairing = _read_json(path / "pairing.json")
        pair = (str(pairing.get("en_document_id", "")), str(pairing.get("zh_document_id", "")))
        if pair in target_pairs:
            executed.append(
                {"action": "skip-duplicate-pairing", "source": str(path), "pair": "/".join(pair)}
            )
        else:
            shutil.copytree(path, target_immersive / "bilingual" / path.name)
            executed.append(
                {
                    "action": "copy-pairing",
                    "source": str(path),
                    "target": str(target_immersive / "bilingual" / path.name),
                }
            )
            target_pairs.add(pair)

    report["executed_actions"] = executed
    (backup_root / "migration-manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=project_root / "data/user/data/user")
    parser.add_argument("--destination", type=Path, default=project_root / "data/user")
    parser.add_argument("--backup-root", type=Path, default=None)
    parser.add_argument("--find-id", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    backup_root = args.backup_root or args.destination / "backups" / "nested-runtime"
    if args.dry_run:
        backup_root = args.destination / "backups" / "nested-runtime-dry-runs"
    backup_root = backup_root / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    report = _plan_and_migrate(
        args.source.resolve(),
        args.destination.resolve(),
        backup_root=backup_root.resolve(),
        requested_ids=set(args.find_id),
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
