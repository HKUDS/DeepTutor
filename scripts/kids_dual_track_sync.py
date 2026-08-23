#!/usr/bin/env python3
"""Merge Kids data between the legacy app and the reward-extension worktree.

This is a switch-time sync, not a live shared database. Stop both frontends,
run it when switching the child between the two builds, then start only one
build. The legacy star fields remain authoritative and are restored into the
experimental tree so its Pydantic models can safely ignore them.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import filecmp
import json
import os
from pathlib import Path
import shutil
import sys
import time

STATE_VERSION = 1
STATE_NAME = "dual-track-sync-state.json"
LOCK_NAME = ".dual-track-sync.lock"
BACKUP_DIR = ".dual-track-backups"

READING_SCALARS = (
    "current_section_id",
    "current_section_index",
    "scroll_percent",
    "epub_cfi",
    "section_href",
)
INTERACTIVE_SCALARS = ("current_page_id", "current_page_order")
CUMULATIVE_READING = ("quiz_attempts", "quiz_best_score")
CUMULATIVE_TIME = "time_spent_seconds"


def read_json(path: Path, default=None):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def atomic_write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def kids_root(root: Path) -> Path:
    return root / "kids"


def progress_dir(root: Path) -> Path:
    return kids_root(root) / "progress"


def usage_dir(root: Path) -> Path:
    return kids_root(root) / "usage"


def progress_files(root: Path) -> dict[str, dict]:
    directory = progress_dir(root)
    if not directory.exists():
        return {}
    return {
        path.name: read_json(path)
        for path in sorted(directory.glob("*.json"))
        if read_json(path) is not None
    }


def usage_files(root: Path) -> dict[str, dict]:
    directory = usage_dir(root)
    if not directory.exists():
        return {}
    return {
        path.name: read_json(path)
        for path in sorted(directory.glob("*.json"))
        if read_json(path) is not None
    }


def merge_by_id(rows_a: list[dict], rows_b: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for source in (rows_a, rows_b):
        for row in source:
            key = str(row.get("id", ""))
            if not key:
                continue
            current = merged.get(key)
            if current is None or float(row.get("updated_at", 0)) > float(
                current.get("updated_at", 0)
            ):
                merged[key] = dict(row)
    return [merged[key] for key in sorted(merged)]


def merge_collection_rows(
    legacy: Path, experimental: Path, filename: str
) -> tuple[bool, list[dict] | None]:
    legacy_rows = read_json(legacy / filename, [])
    experimental_rows = read_json(experimental / filename, [])
    if not isinstance(legacy_rows, list) or not isinstance(experimental_rows, list):
        return False, None
    merged = merge_by_id(legacy_rows, experimental_rows)
    changed = merged != legacy_rows or merged != experimental_rows
    return changed, merged


def max_union(base: Mapping, legacy: Mapping, experimental: Mapping) -> dict:
    keys = set(base) | set(legacy) | set(experimental)
    return {
        key: max(base.get(key, 0), legacy.get(key, 0), experimental.get(key, 0))
        for key in keys
    }


def list_union(base: list, legacy: list, experimental: list) -> list:
    result: list[str] = []
    seen: set[str] = set()
    for value in [*base, *legacy, *experimental]:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def newer_position(base: Mapping, legacy: Mapping, experimental: Mapping) -> dict:
    candidates = [dict(base), dict(legacy), dict(experimental)]
    return max(candidates, key=lambda row: max(row.get("updated_at", 0), row.get("last_read_at", 0)))


def compatible_new_stars(kind: str, previous_scores: Mapping, current_scores: Mapping) -> dict[str, int]:
    """Conservatively seed legacy stars for quizzes taken in the extension build.

    Reading quizzes always present three questions, so only a perfect score earns
    three stars. Interactive totals live outside this JSON; award one star for a
    non-zero partial score and three for a perfect three, which the legacy app can
    upgrade on a later repeat attempt.
    """
    awards: dict[str, int] = {}
    for key, score in current_scores.items():
        previous = previous_scores.get(key, 0)
        if score <= previous:
            continue
        if kind == "reading":
            awards[key] = 3 if score >= 3 else 0
        else:
            awards[key] = 3 if score >= 3 else (1 if score > 0 else 0)
    return {key: value for key, value in awards.items() if value > 0}


def merge_progress(name: str, base: dict | None, legacy: dict | None, experimental: dict | None, *, bootstrap: bool) -> dict:
    kind = "interactive" if name.startswith("ib_") else "reading"
    if base is None:
        # Bootstrap prefers the legacy cumulative counters while unioning facts.
        primary = dict(legacy or experimental or {})
        secondary = dict(experimental or legacy or {})
        primary.setdefault("quiz_scores", {})
        primary.setdefault("quiz_stars_awarded", {})
        primary.setdefault("total_stars", 0)
        primary["quiz_scores"] = max_union({}, primary["quiz_scores"], secondary.get("quiz_scores", {}))
        completed_key = "completed_page_ids" if kind == "interactive" else "completed_section_ids"
        primary[completed_key] = list_union(
            [], primary.get(completed_key, []), secondary.get(completed_key, [])
        )
        if not bootstrap and secondary is not None:
            awards = compatible_new_stars(
                kind, legacy.get("quiz_scores", {}) if legacy else {}, secondary.get("quiz_scores", {})
            )
            previous_awards = primary["quiz_stars_awarded"]
            for key, stars in awards.items():
                previous = previous_awards.get(key, 0)
                if stars > previous:
                    previous_awards[key] = stars
                    primary["total_stars"] += stars - previous
        return primary

    merged = dict(base)
    legacy = legacy or {}
    experimental = experimental or {}
    position = newer_position(base, legacy, experimental)
    scalar_fields = INTERACTIVE_SCALARS if kind == "interactive" else READING_SCALARS
    for field in scalar_fields:
        merged[field] = position.get(field, base.get(field, 0 if field.endswith("index") or field.endswith("order") else ""))

    if kind == "reading":
        for field in CUMULATIVE_READING:
            merged[field] = int(base.get(field, 0))
            merged[field] += max(0, int(legacy.get(field, 0)) - int(base.get(field, 0)))
            merged[field] += max(0, int(experimental.get(field, 0)) - int(base.get(field, 0)))
        merged["quiz_best_score"] = max(
            int(base.get("quiz_best_score", 0)),
            int(legacy.get("quiz_best_score", 0)),
            int(experimental.get("quiz_best_score", 0)),
        )

    base_scores = dict(base.get("quiz_scores", {}))
    merged["quiz_scores"] = max_union(base_scores, legacy.get("quiz_scores", {}), experimental.get("quiz_scores", {}))

    completed_key = "completed_page_ids" if kind == "interactive" else "completed_section_ids"
    merged[completed_key] = list_union(
        base.get(completed_key, []),
        legacy.get(completed_key, []),
        experimental.get(completed_key, []),
    )
    merged[CUMULATIVE_TIME] = float(base.get(CUMULATIVE_TIME, 0))
    merged[CUMULATIVE_TIME] += max(0.0, float(legacy.get(CUMULATIVE_TIME, 0)) - float(base.get(CUMULATIVE_TIME, 0)))
    merged[CUMULATIVE_TIME] += max(0.0, float(experimental.get(CUMULATIVE_TIME, 0)) - float(base.get(CUMULATIVE_TIME, 0)))
    merged["last_read_at"] = max(
        float(base.get("last_read_at", 0)),
        float(legacy.get("last_read_at", 0)),
        float(experimental.get("last_read_at", 0)),
    )
    merged["updated_at"] = max(
        float(base.get("updated_at", 0)),
        float(legacy.get("updated_at", 0)),
        float(experimental.get("updated_at", 0)),
    )

    base_awards = dict(base.get("quiz_stars_awarded", {}))
    legacy_awards = legacy.get("quiz_stars_awarded", base_awards)
    experimental_awards = compatible_new_stars(kind, base_scores, experimental.get("quiz_scores", {}))
    merged_awards = max_union(base_awards, legacy_awards, experimental_awards)
    legacy_star_delta = max(0, int(legacy.get("total_stars", 0)) - int(base.get("total_stars", 0)))
    extension_star_delta = sum(
        max(0, int(merged_awards.get(key, 0)) - int(base_awards.get(key, 0)))
        for key in merged_awards
    )
    merged["quiz_stars_awarded"] = merged_awards
    merged["total_stars"] = int(base.get("total_stars", 0)) + legacy_star_delta + extension_star_delta
    return merged


def merge_usage(base: dict | None, legacy: dict | None, experimental: dict | None) -> dict:
    if base is None:
        chosen = legacy or experimental or {}
        return dict(chosen)
    legacy = legacy or {}
    experimental = experimental or {}
    merged = dict(base)
    for field in ("seconds", "bonus_seconds"):
        merged[field] = float(base.get(field, 0))
        merged[field] += max(0.0, float(legacy.get(field, 0)) - float(base.get(field, 0)))
        merged[field] += max(0.0, float(experimental.get(field, 0)) - float(base.get(field, 0)))
    merged["updated_at"] = max(
        float(base.get("updated_at", 0)),
        float(legacy.get("updated_at", 0)),
        float(experimental.get("updated_at", 0)),
    )
    return merged


def backup_files(legacy: Path, roots: list[Path], relative_files: list[Path]) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = legacy / BACKUP_DIR / stamp
    for root in roots:
        for relative in relative_files:
            source = root / relative
            if source.is_file():
                destination = backup_root / root.parent.name / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
    return backup_root


def sync_content_files(legacy: Path, experimental: Path) -> tuple[int, int, int]:
    """Union immutable document/cache files, preferring the newer byte stream."""
    copied_to_legacy = 0
    copied_to_experimental = 0
    unchanged = 0
    relatives: set[Path] = set()
    for root in (legacy, experimental):
        for path in root.rglob("*"):
            if not path.is_file() or is_kids_or_internal(path.relative_to(root)):
                continue
            relatives.add(path.relative_to(root))
    for relative in sorted(relatives):
        old_path = legacy / relative
        new_path = experimental / relative
        if not old_path.is_file():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(new_path, old_path)
            copied_to_legacy += 1
        elif not new_path.is_file():
            old_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old_path, new_path)
            copied_to_experimental += 1
        elif filecmp.cmp(old_path, new_path, shallow=False):
            unchanged += 1
        elif old_path.stat().st_mtime_ns > new_path.stat().st_mtime_ns:
            shutil.copy2(old_path, new_path)
            copied_to_experimental += 1
        else:
            shutil.copy2(new_path, old_path)
            copied_to_legacy += 1
    return copied_to_legacy, copied_to_experimental, unchanged


def sync_bookengine_books(
    legacy: Path, experimental: Path, assignments: list[dict]
) -> tuple[int, int, int]:
    """Union BookEngine content referenced by active interactive assignments."""
    book_ids = {
        str(row.get("book_id", ""))
        for row in assignments
        if row.get("status", "active") == "active"
        and row.get("content_type") == "interactive_book"
        and str(row.get("book_id", "")).strip()
    }
    copied_to_legacy = 0
    copied_to_experimental = 0
    unchanged = 0

    for book_id in sorted(book_ids):
        legacy_book = legacy.parent / "book" / f"book_{book_id}"
        experimental_book = experimental.parent / "book" / f"book_{book_id}"
        if not legacy_book.is_dir() and not experimental_book.is_dir():
            continue

        relatives: set[Path] = set()
        for root in (legacy_book, experimental_book):
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                relative = path.relative_to(root)
                # Kids progress lives in immersive_reading; keep BookEngine's
                # own mutable reading state local to each build.
                if (
                    relative.parts[0].startswith(".")
                    or relative == Path("progress.json")
                    or relative == Path("log.md")
                ):
                    continue
                relatives.add(relative)

        for relative in sorted(relatives):
            old_path = legacy_book / relative
            new_path = experimental_book / relative
            if not old_path.is_file():
                old_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(new_path, old_path)
                copied_to_legacy += 1
            elif not new_path.is_file():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(old_path, new_path)
                copied_to_experimental += 1
            elif filecmp.cmp(old_path, new_path, shallow=False):
                unchanged += 1
            elif old_path.stat().st_mtime_ns > new_path.stat().st_mtime_ns:
                shutil.copy2(old_path, new_path)
                copied_to_experimental += 1
            else:
                shutil.copy2(new_path, old_path)
                copied_to_legacy += 1

    return copied_to_legacy, copied_to_experimental, unchanged


def is_kids_or_internal(relative: Path) -> bool:
    return relative.parts[0] == "kids" or relative.parts[0].startswith(".")


def run(legacy_root: Path, experimental_root: Path, *, apply: bool) -> int:
    legacy_root = legacy_root.expanduser().resolve()
    experimental_root = experimental_root.expanduser().resolve()
    if not legacy_root.is_dir() or not experimental_root.is_dir():
        raise SystemExit("Both immersive_reading roots must exist.")
    if legacy_root == experimental_root:
        raise SystemExit("Legacy and experimental roots must be different.")

    old_kids, new_kids = kids_root(legacy_root), kids_root(experimental_root)
    lock_path = old_kids / LOCK_NAME
    old_kids.mkdir(parents=True, exist_ok=True)

    # The lock is advisory. Stop both UIs before syncing; do not let a child use
    # either build while files are being replaced.
    with lock_path.open("a+", encoding="utf-8") as lock:
        if os.name == "posix":
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        state = read_json(old_kids / STATE_NAME)
        bootstrap = state is None
        if bootstrap:
            state = {"version": STATE_VERSION, "progress": {}, "usage": {}}
        if int(state.get("version", 0)) != STATE_VERSION:
            raise SystemExit(f"Unsupported sync state version: {state.get('version')}")

        old_progress = progress_files(legacy_root)
        new_progress = progress_files(experimental_root)
        old_usage = usage_files(legacy_root)
        new_usage = usage_files(experimental_root)

        merged_progress: dict[str, dict] = {}
        for name in sorted(set(old_progress) | set(new_progress) | set(state.get("progress", {}))):
            merged_progress[name] = merge_progress(
                name,
                state.get("progress", {}).get(name),
                old_progress.get(name),
                new_progress.get(name),
                bootstrap=bootstrap,
            )

        merged_usage: dict[str, dict] = {}
        for name in sorted(set(old_usage) | set(new_usage) | set(state.get("usage", {}))):
            merged_usage[name] = merge_usage(
                state.get("usage", {}).get(name), old_usage.get(name), new_usage.get(name)
            )

        profiles_changed, merged_profiles = merge_collection_rows(old_kids, new_kids, "profiles.json")
        assignments_changed, merged_assignments = merge_collection_rows(
            old_kids, new_kids, "assignments.json"
        )
        if merged_profiles is None or merged_assignments is None:
            raise SystemExit("profiles.json and assignments.json must both contain arrays.")

        progress_changed = any(
            merged_progress[name] != old_progress.get(name)
            or merged_progress[name] != new_progress.get(name)
            for name in merged_progress
        )
        usage_changed = any(
            merged_usage[name] != old_usage.get(name)
            or merged_usage[name] != new_usage.get(name)
            for name in merged_usage
        )

        print(f"mode: {'apply' if apply else 'dry-run'}")
        print(f"bootstrap: {bootstrap}")
        print(f"profiles: {len(merged_profiles)}")
        print(f"assignments: {len(merged_assignments)}")
        print(f"progress files: {len(merged_progress)} changed={progress_changed}")
        print(f"usage files: {len(merged_usage)} changed={usage_changed}")

        if not apply:
            return 0

        changed_kids: list[Path] = [Path("kids") / STATE_NAME]
        for filename, rows, changed in (
            ("profiles.json", merged_profiles, profiles_changed),
            ("assignments.json", merged_assignments, assignments_changed),
        ):
            if changed:
                changed_kids.append(Path("kids") / filename)
        for name, value in merged_progress.items():
            changed_kids.append(Path("kids") / "progress" / name)
        for name, value in merged_usage.items():
            changed_kids.append(Path("kids") / "usage" / name)
        backup = backup_files(legacy_root, [legacy_root, experimental_root], changed_kids)

        atomic_write_json(old_kids / "profiles.json", merged_profiles)
        atomic_write_json(old_kids / "assignments.json", merged_assignments)
        atomic_write_json(new_kids / "profiles.json", merged_profiles)
        atomic_write_json(new_kids / "assignments.json", merged_assignments)
        old_progress_dir, old_usage_dir = progress_dir(legacy_root), usage_dir(legacy_root)
        new_progress_dir, new_usage_dir = progress_dir(experimental_root), usage_dir(experimental_root)
        for directory in (old_progress_dir, new_progress_dir, old_usage_dir, new_usage_dir):
            directory.mkdir(parents=True, exist_ok=True)
        for name, value in merged_progress.items():
            atomic_write_json(old_progress_dir / name, value)
            atomic_write_json(new_progress_dir / name, value)
        for name, value in merged_usage.items():
            atomic_write_json(old_usage_dir / name, value)
            atomic_write_json(new_usage_dir / name, value)

        state = {
            "version": STATE_VERSION,
            "progress": merged_progress,
            "usage": merged_usage,
        }
        atomic_write_json(old_kids / STATE_NAME, state)
        atomic_write_json(new_kids / STATE_NAME, state)

        book_to_legacy, book_to_experimental, book_unchanged = sync_bookengine_books(
            legacy_root, experimental_root, merged_assignments
        )
        to_legacy, to_experimental, unchanged = sync_content_files(legacy_root, experimental_root)
        print(f"bookengine copied legacy<-experimental: {book_to_legacy}")
        print(f"bookengine copied experimental<-legacy: {book_to_experimental}")
        print(f"bookengine unchanged: {book_unchanged}")
        print(f"backup: {backup}")
        print(f"content copied legacy<-experimental: {to_legacy}")
        print(f"content copied experimental<-legacy: {to_experimental}")
        print(f"content unchanged: {unchanged}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-root",
        type=Path,
        default=Path("/Users/Shared/DeepTutor/data/user/workspace/immersive_reading"),
        help="Legacy immersive_reading directory",
    )
    parser.add_argument(
        "--experimental-root",
        type=Path,
        default=Path(
            "/tmp/DeepTutor-kids-dual-home/data/user/workspace/immersive_reading"
        ),
        help="Experimental immersive_reading directory",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    return run(args.legacy_root, args.experimental_root, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
