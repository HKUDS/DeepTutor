"""Migration CLI and statement exporter.

Usage
-----
::

    python -m deeptutor.db.migrations status
    python -m deeptutor.db.migrations up [--target N] [--dry-run]
    python -m deeptutor.db.migrations down --target N
    python -m deeptutor.db.migrations verify
    python -m deeptutor.db.migrations export --direction up [--version N]

``up`` / ``down`` / ``verify`` need ``DEEPTUTOR_DATABASE_URL``.

``export`` does not touch a database at all — it prints the exact statements of
a migration to stdout, one per ``-- statement N --`` banner. That exists because
in some environments (this sandbox) the only route to the production database is
an API, and the alternative to exporting the real statements is retyping them by
hand, where a typo between the file and the database is invisible and permanent.
Exporting makes the file the single source of truth for what was executed.
"""

from __future__ import annotations

import argparse
import json
import sys

from deeptutor.db.config import DatabaseSettings, load_database_settings, redact_dsn
from deeptutor.db.connection import Database
from deeptutor.db.migrate import (
    MigrationError,
    applied_migrations,
    apply_pending,
    discover_migrations,
    rollback_to,
    split_statements,
)
from deeptutor.db.schema_check import describe_schema, verify_schema


def _database(settings: DatabaseSettings) -> Database:
    if not settings.enabled:
        print(
            "error: DEEPTUTOR_DATABASE_URL is not set; nothing to do",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return Database(settings)


def cmd_status(settings: DatabaseSettings) -> int:
    migrations = discover_migrations()
    db = _database(settings)
    try:
        with db.read() as conn:
            applied = {int(r["version"]) for r in applied_migrations(conn)}
    finally:
        db.close()
    print(f"target: {settings.safe_app_dsn}  ({settings.backend})")
    for migration in migrations:
        mark = "applied" if migration.version in applied else "pending"
        if not migration.applies_to(settings.backend):
            mark = "n/a (dialect)"
        print(f"  V{migration.version:04d} {migration.name:<32} {mark}")
    return 0


def cmd_up(settings: DatabaseSettings, target: int | None, dry_run: bool) -> int:
    db = _database(settings)
    try:
        applied = apply_pending(db, target_version=target, dry_run=dry_run)
        if dry_run:
            print("would apply: " + (", ".join(m.name for m in applied) or "nothing"))
        else:
            print("applied: " + (", ".join(m.name for m in applied) or "nothing"))
        return 0
    except MigrationError as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_down(settings: DatabaseSettings, target: int) -> int:
    db = _database(settings)
    try:
        rolled = rollback_to(db, target)
        print("rolled back: " + (", ".join(m.name for m in rolled) or "nothing"))
        return 0
    except MigrationError as exc:
        print(f"rollback refused: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_verify(settings: DatabaseSettings) -> int:
    db = _database(settings)
    try:
        try:
            verify_schema(db)
        except Exception as exc:  # noqa: BLE001 - report, do not traceback
            print(f"schema mismatch: {exc}", file=sys.stderr)
            return 1
        print("schema OK")
        if "--verbose" in sys.argv:
            print(json.dumps(describe_schema(db), indent=2, ensure_ascii=False))
        return 0
    finally:
        db.close()


def cmd_export(direction: str, version: int | None) -> int:
    """Print a migration's statements for out-of-band execution."""
    migrations = discover_migrations()
    if version is None:
        selected = migrations
    else:
        selected = [m for m in migrations if m.version == version]
        if not selected:
            print(f"error: no migration with version {version}", file=sys.stderr)
            return 2
    for migration in selected:
        body = migration.up if direction == "up" else migration.down
        print(f"-- ===== V{migration.version:04d} {migration.name} ({direction}) =====")
        print(f"-- dialect: {migration.dialect}")
        print(f"-- checksum: {migration.checksum}")
        for index, statement in enumerate(split_statements(body), start=1):
            print(f"\n-- statement {index} --")
            print(f"{statement};")
        print()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m deeptutor.db.migrations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    up = sub.add_parser("up")
    up.add_argument("--target", type=int, default=None)
    up.add_argument("--dry-run", action="store_true")
    down = sub.add_parser("down")
    down.add_argument("--target", type=int, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--verbose", action="store_true")
    export = sub.add_parser("export")
    export.add_argument("--direction", choices=["up", "down"], default="up")
    export.add_argument("--version", type=int, default=None)

    args = parser.parse_args(argv)

    if args.command == "export":
        return cmd_export(args.direction, args.version)

    settings = load_database_settings()
    print(f"-- database: {redact_dsn(settings.app_url) or '(unset)'}", file=sys.stderr)

    if args.command == "status":
        return cmd_status(settings)
    if args.command == "up":
        return cmd_up(settings, args.target, args.dry_run)
    if args.command == "down":
        return cmd_down(settings, args.target)
    if args.command == "verify":
        return cmd_verify(settings)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
