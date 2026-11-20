"""Database-level guards for the media tables.

Why these are triggers installed at runtime rather than constraints in a
migration
--------------------------------------------------------------------------
The licence rule ("a row that claims a source must claim its terms") belongs in
the database, not only in the service layer: the next writer can bypass a
Python check, and a provenance record that is only *usually* honest is not a
provenance record.

But SQLite cannot `ALTER TABLE ... ADD CONSTRAINT`, and rebuilding
`media_assets` to attach a CHECK would mean copying every row and every index --
a lot of risk for a guarantee a trigger gives just as completely. Triggers do
need `BEGIN ... END`, which this project's migration splitter cannot express
(it splits on top-level semicolons and does not track compound statements).

So the guard is installed by :func:`ensure_guards`, called once per process
after migrations. That placement has one property worth stating: it either
installs or raises. There is no code path where the tables exist and the
invariant silently does not.

Why the guard also rejects on UPDATE
------------------------------------
An asset could be moved onto a source afterwards, which would bypass an
insert-only trigger and leave the same dishonest row. The update trigger fires
on exactly the two columns that decide the question.
"""

from __future__ import annotations

import logging

from deeptutor.db.connection import Database, DatabaseError

logger = logging.getLogger(__name__)

_INSTALLED: set[int] = set()

#: The invariant, in SQL. Kept as named constants so a test can assert against
#: the same text the installer uses rather than a copy that can drift.
LICENCE_MESSAGE = "media_assets: a source requires a licence_code"

_INSERT_GUARD = f"""
CREATE TRIGGER IF NOT EXISTS trg_media_assets_licence_required
BEFORE INSERT ON media_assets
FOR EACH ROW
WHEN NEW.source_id IS NOT NULL
 AND TRIM(NEW.source_id) <> ''
 AND (NEW.licence_code IS NULL OR TRIM(NEW.licence_code) = '')
BEGIN
    SELECT RAISE(ABORT, '{LICENCE_MESSAGE}');
END
"""

_UPDATE_GUARD = f"""
CREATE TRIGGER IF NOT EXISTS trg_media_assets_licence_required_update
BEFORE UPDATE OF source_id, licence_code ON media_assets
FOR EACH ROW
WHEN NEW.source_id IS NOT NULL
 AND TRIM(NEW.source_id) <> ''
 AND (NEW.licence_code IS NULL OR TRIM(NEW.licence_code) = '')
BEGIN
    SELECT RAISE(ABORT, '{LICENCE_MESSAGE}');
END
"""

_STATEMENTS = (_INSERT_GUARD, _UPDATE_GUARD)


def _tables_present(db: Database) -> bool:
    """Are the media tables here yet?

    A process may start before migrations have run (the CLI does this on a
    fresh install). Installing a trigger on a table that does not exist is an
    error, and swallowing it would hide the real problem, so this asks first
    and returns False rather than pretending success.
    """
    with db.read() as conn:
        row = conn.scalar(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'media_assets'"
        )
    return int(row or 0) > 0


def ensure_guards(db: Database) -> bool:
    """Install the guards if the tables exist. Returns whether they are in place.

    Idempotent, and memoised per database file so a long-running worker does not
    re-run DDL on every job. The memo is keyed by the settings URL rather than
    the object identity so two ``Database`` handles for the same file share it.
    """
    key = hash(getattr(db.settings, "app_url", "") or id(db))
    if key in _INSTALLED:
        return True
    if not _tables_present(db):
        logger.warning("media tables are not migrated yet; integrity guards not installed")
        return False

    # The connection wrapper executes one statement per call and would choke on
    # a compound trigger body, so the driver handle is used directly. This is
    # the only place in the studio that touches the raw connection, and it is
    # exactly why the guards live here instead of in a migration.
    with db.transaction() as conn:
        raw = getattr(conn, "_raw", None)
        if raw is None:  # pragma: no cover - defensive
            raise DatabaseError("cannot install integrity guards: no raw connection")
        for statement in _STATEMENTS:
            try:
                raw.execute(statement)
            except Exception as exc:  # noqa: BLE001 - re-raised with context
                raise DatabaseError(
                    f"cannot install media licence guard: {exc}"
                ) from exc
        raw.commit()

    _INSTALLED.add(key)
    return True


def guards_present(db: Database) -> dict[str, bool]:
    """Which guards exist. Used by tests and by the admin health view."""
    with db.read() as conn:
        rows = list(
            conn.query(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND name LIKE 'trg_media_assets_licence%'"
            )
        )
    present = {row["name"] for row in rows}
    return {
        "insert": "trg_media_assets_licence_required" in present,
        "update": "trg_media_assets_licence_required_update" in present,
    }


def reset_memo() -> None:
    """Forget which databases have been guarded. Tests use this."""
    _INSTALLED.clear()


__all__ = [
    "LICENCE_MESSAGE",
    "ensure_guards",
    "guards_present",
    "reset_memo",
]
