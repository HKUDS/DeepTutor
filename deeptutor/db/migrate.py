"""Versioned, checksummed SQL migrations.

Conventions
-----------
Migrations are plain ``.sql`` files in :mod:`deeptutor.db.migrations`, named::

    V0001__create_product_core.sql
    V0002__add_wallet_constraints.sql

Each migration owns exactly one file and is split into two halves by a marker
line::

    -- @@ UP @@
    ... forward statements ...
    -- @@ DOWN @@
    ... rollback statements ...

The runner applies ``UP`` in order and ``DOWN`` in reverse order, recording
``(version, name, checksum, applied_at)`` in ``deeptutor_schema_migrations``.
Because the checksum covers the file content, editing an *already applied*
migration is detected and refused — the same guarantee Alembic gives, without
the dependency.

Statements are split on ``;`` at line ends by :func:`split_statements`, which
understands ``--`` comments and single-quoted literals but deliberately does
**not** try to parse ``$$``-quoted PL/pgSQL bodies. A migration that needs a
function body must put it in its own file section and keep the body free of
top-level semicolons, or run it through ``execute_query`` out of band. This is a
documented limitation, not a bug: the alternative is a parsing dialect that
breaks in subtle ways.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import logging
from pathlib import Path
import re
from typing import Iterable

from deeptutor.db.connection import Connection, Database

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).with_name("migrations")
UP_MARKER = "-- @@ UP @@"
DOWN_MARKER = "-- @@ DOWN @@"
NAME = r"V(\d{4})__([a-z0-9_]+)\.sql"
_NAME_RE = re.compile(rf"^{NAME}$")
_DIALECT_RE = re.compile(r"^--\s*@@\s*DIALECT:\s*(\w+)\s*@@\s*$", re.MULTILINE)
_CHECKSUM_RE = re.compile(r"[\s;]+$")


class MigrationError(RuntimeError):
    """A migration is malformed, out of order, or drifted."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    up: str
    down: str
    #: ``"any"`` (portable, runs on SQLite too) or ``"postgres"`` (uses
    #: Postgres-only DDL such as ``ADD COLUMN IF NOT EXISTS``). A postgres-only
    #: migration is *skipped* on SQLite rather than failing the whole run, which
    #: keeps the CI harness meaningful: the portable migrations, which carry the
    #: real logic, still execute and are still tested.
    dialect: str = "any"

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.up.encode("utf-8")).hexdigest()[:32]

    def applies_to(self, backend: str) -> bool:
        return self.dialect in ("any", backend)


def split_statements(sql: str) -> list[str]:
    """Split *sql* into individual statements on top-level semicolons.

    Line comments (``--``) and single-quoted strings are respected so a
    semicolon inside a default value or a comment cannot split a statement.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_single = False
    in_line_comment = False
    i = 0
    length = len(sql)
    while i < length:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < length else ""
        if in_line_comment:
            buffer.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_single:
            buffer.append(ch)
            if ch == "'":
                if nxt == "'":  # escaped quote inside the literal
                    buffer.append(nxt)
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_line_comment = True
            buffer.append(ch)
            i += 1
            continue
        if ch == "'":
            in_single = True
            buffer.append(ch)
            i += 1
            continue
        if ch == ";":
            candidate = "".join(buffer).strip()
            if _has_sql(candidate):
                statements.append(_strip_leading_comments(candidate))
            buffer = []
            i += 1
            continue
        buffer.append(ch)
        i += 1
    tail = "".join(buffer).strip()
    if _has_sql(tail):
        statements.append(_strip_leading_comments(tail))
    return statements


def _strip_leading_comments(fragment: str) -> str:
    """Drop whole-line ``--`` comments from the head of a statement.

    A migration file reads far better with a comment above each statement, but
    the comment must not become part of the SQL sent to the driver: a driver
    that cannot take a leading comment (or a test that compares against the
    bare statement) would otherwise see noise. Inline trailing comments are
    preserved because they are part of the same line as real SQL.
    """
    lines = fragment.splitlines()
    while lines and (not lines[0].strip() or lines[0].strip().startswith("--")):
        lines.pop(0)
    return "\n".join(lines).strip()


def _has_sql(fragment: str) -> bool:
    """True when *fragment* contains anything but whitespace and comments."""
    for line in fragment.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return True
    return False


def _parse(path: Path) -> Migration:
    match = _NAME_RE.match(path.name)
    if not match:
        raise MigrationError(
            f"migration filename {path.name!r} must match V0001__lowercase_name.sql"
        )
    body = path.read_text(encoding="utf-8")
    if UP_MARKER not in body or DOWN_MARKER not in body:
        raise MigrationError(f"{path.name} must contain {UP_MARKER} and {DOWN_MARKER}")
    dialect_match = _DIALECT_RE.search(body)
    dialect = dialect_match.group(1).lower() if dialect_match else "any"
    if dialect not in {"any", "postgres", "sqlite"}:
        raise MigrationError(
            f"{path.name} declares unsupported dialect {dialect!r}; "
            "expected any, postgres or sqlite"
        )
    head, rest = body.split(UP_MARKER, 1)
    up, down = rest.split(DOWN_MARKER, 1)
    if not split_statements(up):
        raise MigrationError(f"{path.name} has an empty UP section")
    if not split_statements(down):
        raise MigrationError(f"{path.name} has an empty DOWN section")
    return Migration(
        version=int(match.group(1)),
        name=match.group(2),
        path=path,
        up=up.strip(),
        down=down.strip(),
        dialect=dialect,
    )


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    """All migrations, ordered by version. Duplicate versions are an error.

    A ``.sql`` file that does not match the ``V####__name.sql`` convention is an
    error, not something to skip. Silently ignoring a misfiled migration is the
    worst possible behaviour here: it looks like the migration ran because the
    deploy succeeded, and the schema is wrong only at runtime.
    """
    root = directory or MIGRATIONS_DIR
    if not root.is_dir():
        return []
    stray = sorted(p.name for p in root.glob("*.sql") if not _NAME_RE.match(p.name))
    if stray:
        raise MigrationError(
            "unrecognised migration file(s): "
            + ", ".join(stray)
            + " — expected V0001__lowercase_name.sql"
        )
    migrations = [_parse(p) for p in sorted(root.glob("V*.sql"))]
    seen: dict[int, str] = {}
    for mig in migrations:
        if mig.version in seen:
            raise MigrationError(
                f"duplicate migration version {mig.version}: {seen[mig.version]} and {mig.name}"
            )
        seen[mig.version] = mig.name
    return migrations


_CREATE_LOG = """
CREATE TABLE IF NOT EXISTS deeptutor_schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    checksum VARCHAR(64) NOT NULL,
    applied_at VARCHAR(40) NOT NULL
)
"""


def _ensure_log_table(conn: Connection) -> None:
    conn.execute(_CREATE_LOG)


def applied_migrations(conn: Connection) -> list[dict[str, object]]:
    _ensure_log_table(conn)
    return conn.query(
        "SELECT version, name, checksum, applied_at "
        "FROM deeptutor_schema_migrations ORDER BY version"
    ).rows


def _verify_no_drift(conn: Connection, migrations: Iterable[Migration]) -> None:
    by_version = {m.version: m for m in migrations}
    for row in applied_migrations(conn):
        version = int(row["version"])  # type: ignore[arg-type]
        known = by_version.get(version)
        if known is None:
            raise MigrationError(
                f"database has migration {version} ({row['name']}) which is not in the "
                "source tree — refusing to continue"
            )
        if known.checksum != row["checksum"]:
            raise MigrationError(
                f"migration {version} ({known.name}) was edited after being applied; "
                "add a new migration instead of changing history"
            )


def apply_pending(
    db: Database,
    *,
    directory: Path | None = None,
    target_version: int | None = None,
    dry_run: bool = False,
) -> list[Migration]:
    """Apply every migration newer than the database's current version.

    Returns the migrations that were (or would be) applied. Raises
    :class:`MigrationError` on drift, and lets :class:`DatabaseError` propagate
    so a failed migration aborts its own transaction.
    """
    migrations = discover_migrations(directory)
    if not migrations:
        return []
    applied_versions: list[int] = []
    with db.transaction() as conn:
        _verify_no_drift(conn, migrations)
        applied_versions = [
            int(r["version"])  # type: ignore[arg-type]
            for r in applied_migrations(conn)
        ]
        pending = [
            m
            for m in migrations
            if m.version not in applied_versions
            and (target_version is None or m.version <= target_version)
            # A dialect this engine cannot run is recorded as not-applicable
            # rather than applied, so switching engines later still runs it.
            and m.applies_to(db.backend)
        ]
        if dry_run:
            return pending
        for mig in pending:
            logger.info("applying migration %s (%s)", mig.version, mig.name)
            for statement in split_statements(mig.up):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO deeptutor_schema_migrations (version, name, checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (mig.version, mig.name, mig.checksum, _now_iso()),
            )
    if not dry_run and pending:
        # Verify *after* the transaction commits, so a mismatch is reported
        # against the state the application will actually see. A migration that
        # silently accepted a pre-existing table with the wrong columns would
        # otherwise pass here and fail in a request instead.
        from deeptutor.db.schema_check import verify_schema

        verify_schema(db)
    return pending


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def rollback_to(
    db: Database,
    target_version: int,
    *,
    directory: Path | None = None,
    dry_run: bool = False,
) -> list[Migration]:
    """Roll the schema *down* to *target_version* (exclusive).

    ``target_version=0`` undoes everything. Each migration's ``DOWN`` runs in
    reverse order inside the same transaction as its own bookkeeping delete, so
    a failure leaves the recorded version matching the actual schema.
    """
    migrations = {m.version: m for m in discover_migrations(directory)}
    rolled_back: list[Migration] = []
    with db.transaction() as conn:
        _ensure_log_table(conn)
        current = [
            int(r["version"])  # type: ignore[arg-type]
            for r in applied_migrations(conn)
        ]
        to_undo = sorted((v for v in current if v > target_version), reverse=True)
        for version in to_undo:
            mig = migrations.get(version)
            if mig is None:
                raise MigrationError(
                    f"cannot roll back version {version}: migration file is missing"
                )
            if dry_run:
                rolled_back.append(mig)
                continue
            logger.info("rolling back migration %s (%s)", mig.version, mig.name)
            for statement in split_statements(mig.down):
                conn.execute(statement)
            conn.execute("DELETE FROM deeptutor_schema_migrations WHERE version = ?", (version,))
            rolled_back.append(mig)
    return rolled_back
