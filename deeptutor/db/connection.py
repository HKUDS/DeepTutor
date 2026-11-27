"""Portable connection wrapper over PostgreSQL and SQLite.

Why not an ORM
--------------
The repository already ships ``aiosqlite`` and hand-written SQL (see
``deeptutor/services/storage/file_library.py``). Adding SQLAlchemy would mean a
second, competing data-access idiom for the same tables and an import-time cost
on a CLI that must stay fast. :class:`Connection` is a ~200-line adapter that
gives repositories one spelling for the four things that actually differ
between the engines:

* **placeholders** — ``%s`` (psycopg) vs ``?`` (sqlite3)
* **row access** — ``dict`` for both, but Postgres returns ``datetime`` objects
  natively while SQLite returns strings unless a converter is registered
* **transactions** — psycopg's implicit transaction on first statement vs
  sqlite3's ``isolation_level=None`` explicit ``BEGIN``
* **upserts** — ``ON CONFLICT`` exists in both but SQLite needs 3.24+ and does
  not support ``ON CONFLICT ... DO UPDATE`` with a ``WHERE`` exclusion the same
  way, so repositories call :meth:`Connection.upsert` instead of hand-writing it

Everything else (``CREATE TABLE``, ``SELECT``, indexes) is written in the
portable subset and covered by the same test suite against both engines.

PostgreSQL is optional: ``psycopg`` is imported inside :func:`_connect_postgres`
so a deployment without the driver never pays for it at import time.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
import logging
import re
import sqlite3
import threading
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit

from deeptutor.db.config import DatabaseSettings

logger = logging.getLogger(__name__)

_PARAM_RE = re.compile(r"%s")


class DatabaseUnavailable(RuntimeError):
    """A database operation was attempted but no database is configured.

    Call-sites that must work without a database (the default deployment)
    catch this and fall back to their file store.
    """


class DatabaseError(RuntimeError):
    """Engine-neutral error, raised instead of leaking driver exceptions."""


@dataclass
class _Result:
    rows: list[dict[str, Any]]

    def first(self) -> dict[str, Any] | None:
        return self.rows[0] if self.rows else None

    def scalar(self) -> Any:
        if not self.rows:
            return None
        return next(iter(self.rows[0].values()))

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.rows)

    def __len__(self) -> int:
        return len(self.rows)


def normalize_value(value: Any) -> Any:
    """Render a driver-native value the way the JSON file stores did.

    Phase 2 wrote every timestamp as an ISO-8601 string
    (``datetime.now(timezone.utc).isoformat()``). Repositories must return the
    *same shape* after the move to Postgres, or every caller that does
    ``record["created_at"][:10]`` or compares two records breaks in a way no
    type checker catches. So the adapter, not the caller, converts:

    * ``datetime`` -> ISO-8601 with a ``+00:00`` offset, in UTC
    * ``date``     -> ``YYYY-MM-DD``
    * everything else unchanged (``Decimal`` is converted to ``int``/``float``
      because every numeric column in this schema is an integer)
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, decimal_type()):
        return int(value) if value == int(value) else float(value)
    return value


def decimal_type() -> type:
    """Lazy ``decimal.Decimal`` lookup so the import stays cheap."""
    from decimal import Decimal

    return Decimal


def _normalize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: normalize_value(value) for key, value in row.items()}


#: Strict ISO-8601 instant *with* an offset, e.g. ``2026-11-17T20:45:00+00:00``.
#: Deliberately anchored and offset-required: a bare date or a local time must
#: not be reinterpreted as an instant, because guessing the offset silently
#: shifts data by hours.
_ISO_INSTANT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)


def coerce_param(value: Any, backend: str) -> Any:
    """Adapt one bound parameter to the active engine.

    The repositories produce timestamps the way the Phase 2 JSON store did: as
    ISO-8601 strings (``datetime.now(timezone.utc).isoformat()``). That is the
    right internal representation — it is what every caller compares and slices
    — but Postgres' ``timestamptz`` columns reject a text parameter
    (``column "created_at" is of type timestamp with time zone but expression is
    of type text``).

    Rather than sprinkle ``.isoformat()`` vs ``datetime`` decisions through ~30
    call-sites (where one miss is a production 500), the conversion happens once
    here, on the boundary, keyed on the value being a *complete instant with an
    offset*. Anything else — an id, a name, a truncated error message, a JSON
    blob — passes through untouched.

    SQLite stores timestamps as TEXT, so it needs no conversion at all, and the
    two engines end up accepting identical repository code.
    """
    if backend != "postgres" or not isinstance(value, str):
        return value
    if not _ISO_INSTANT_RE.match(value):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:  # pragma: no cover - the regex already gates the shape
        return value


def _sqlite_path(dsn: str) -> str:
    parts = urlsplit(dsn)
    # sqlite:///relative.db  -> path "/relative.db" -> strip the leading slash
    # sqlite:////abs/path.db -> path "//abs/path.db" -> keep one slash
    path = parts.path
    if path.startswith("//"):
        return path[1:]
    if path.startswith("/"):
        return path[1:] or ":memory:"
    return path or dsn.split("://", 1)[-1]


class Connection:
    """One logical database connection.

    Not thread-safe: acquire one per unit of work. Use
    :meth:`Database.transaction` for the common case.

    ``placeholder`` is ``%s`` for Postgres and ``?`` for SQLite; repositories
    always write ``?`` and :meth:`_adapt` rewrites it for Postgres, so SQL in
    this codebase has exactly one spelling.
    """

    def __init__(self, raw: Any, *, backend: str) -> None:
        self._raw = raw
        self.backend = backend
        self._closed = False

    # -- statement adaptation ------------------------------------------------

    @property
    def placeholder(self) -> str:
        return "%s" if self.backend == "postgres" else "?"

    def _adapt(self, sql: str) -> str:
        if self.backend != "postgres":
            return sql
        # Two rewrites, both required for psycopg:
        #
        # 1. ``?`` outside a quoted literal becomes ``%s`` — repositories write
        #    exactly one placeholder spelling.
        # 2. *Every* literal ``%`` becomes ``%%``, including inside string
        #    literals. psycopg interpolates on ``%`` before the server ever sees
        #    the statement, so ``WHERE name LIKE '100%'`` raises
        #    "unsupported format character" unless the percent is doubled.
        #
        # Order matters: the ``%`` from step 1 must not be re-escaped, so the
        # placeholder is emitted as a unit and percent-doubling only applies to
        # characters from the original SQL.
        out: list[str] = []
        in_single = False
        index = 0
        length = len(sql)
        while index < length:
            ch = sql[index]
            if ch == "'":
                # Handle the doubled-quote escape ('' inside a literal).
                out.append(ch)
                if in_single and index + 1 < length and sql[index + 1] == "'":
                    out.append("'")
                    index += 2
                    continue
                in_single = not in_single
                index += 1
                continue
            if ch == "?" and not in_single:
                out.append("%s")
                index += 1
                continue
            if ch == "%":
                out.append("%%")
                index += 1
                continue
            out.append(ch)
            index += 1
        return "".join(out)

    @contextmanager
    def _cursor(self) -> Iterator[Any]:
        if self.backend == "postgres":
            from psycopg.rows import dict_row

            raw = self._raw.cursor(row_factory=dict_row)
        else:
            raw = self._raw.cursor()
        try:
            yield raw
        finally:
            try:
                raw.close()
            except Exception:  # noqa: BLE001 - closing must never mask the real error
                pass

    # -- query API ----------------------------------------------------------

    def _params(self, params: Sequence[Any] | Mapping[str, Any]) -> Any:
        if isinstance(params, Mapping):
            return {key: coerce_param(value, self.backend) for key, value in params.items()}
        if not isinstance(params, (list, tuple)):
            return params
        return tuple(coerce_param(value, self.backend) for value in params)

    def execute(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> int:
        """Run a statement, return the affected row count."""
        try:
            with self._cursor() as cur:
                cur.execute(self._adapt(sql), self._params(params))
                return cur.rowcount if cur.rowcount is not None else 0
        except Exception as exc:  # noqa: BLE001 - normalised below
            raise DatabaseError(f"execute failed: {exc}") from exc

    def query(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> _Result:
        """Run a ``SELECT``, return rows as dicts."""
        try:
            with self._cursor() as cur:
                cur.execute(self._adapt(sql), self._params(params))
                if cur.description is None:
                    return _Result([])
                if self.backend == "postgres":
                    return _Result([_normalize_row(dict(row)) for row in cur.fetchall()])
                columns = [c[0] for c in cur.description]
                return _Result([_normalize_row(dict(zip(columns, row))) for row in cur.fetchall()])
        except Exception as exc:  # noqa: BLE001
            raise DatabaseError(f"query failed: {exc}") from exc

    def query_one(
        self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()
    ) -> dict[str, Any] | None:
        return self.query(sql, params).first()

    def scalar(self, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> Any:
        return self.query(sql, params).scalar()

    def insert_returning_id(self, sql: str, params: Sequence[Any] = ()) -> Any:
        """Insert a row and return its generated id.

        Postgres uses ``RETURNING``; SQLite uses ``lastrowid``. Callers pass the
        statement *with* ``RETURNING id`` for clarity and it is stripped for
        SQLite.
        """
        if self.backend == "postgres":
            return self.query(sql, params).scalar()
        stripped = re.sub(r"\s+RETURNING\s+\w+\s*;?\s*$", "", sql, flags=re.IGNORECASE)
        self.execute(stripped, params)
        return self._raw.cursor().lastrowid

    # -- transaction control ------------------------------------------------

    def begin(self) -> None:
        if self.backend == "sqlite" and not self._raw.in_transaction:
            self._raw.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        if not self._closed:
            self._raw.rollback()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._raw.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("connection close failed: %s", exc)

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class Database:
    """Engine-agnostic handle.

    A Postgres :class:`Database` wraps a psycopg connection pool; a SQLite one
    opens a fresh connection per unit of work. Repositories never see which.
    """

    def __init__(self, settings: DatabaseSettings) -> None:
        self.settings = settings
        self.backend = settings.backend
        self._pool: Any = None
        self._sqlite_lock = threading.Lock()

    # -- lifecycle ----------------------------------------------------------

    def connect(self) -> Connection:
        if self.backend == "postgres":
            return self._connect_postgres()
        return self._connect_sqlite()

    def _connect_postgres(self) -> Connection:
        if self._pool is None:
            try:
                from psycopg_pool import ConnectionPool
            except ImportError as exc:  # pragma: no cover - driver optional
                raise DatabaseUnavailable(
                    "PostgreSQL configured but psycopg/psycopg_pool is not installed; "
                    "install the 'db' extra"
                ) from exc
            self._pool = ConnectionPool(
                conninfo=self.settings.app_url,
                min_size=1,
                max_size=self.settings.pool_size,
                open=True,
                kwargs={"row_factory": None},
            )
        raw = self._pool.getconn()
        self._apply_session_settings(raw)
        return Connection(raw, backend="postgres")

    def _apply_session_settings(self, raw: Any) -> None:
        try:
            with raw.cursor() as cur:
                cur.execute(
                    "SET statement_timeout = %s",
                    (self.settings.statement_timeout_ms,),
                )
            raw.commit()
        except Exception as exc:  # noqa: BLE001 - non-fatal
            logger.debug("could not set statement_timeout: %s", exc)
            raw.rollback()

    def _connect_sqlite(self) -> Connection:
        path = _sqlite_path(self.settings.app_url)
        try:
            raw = sqlite3.connect(
                path,
                timeout=30.0,
                isolation_level=None,  # explicit BEGIN, see Connection.begin
                check_same_thread=False,
            )
        except sqlite3.Error as exc:
            raise DatabaseUnavailable(f"cannot open sqlite database: {exc}") from exc
        raw.row_factory = None
        raw.execute("PRAGMA foreign_keys = ON")
        raw.execute("PRAGMA journal_mode = WAL")
        return Connection(raw, backend="sqlite")

    def release(self, conn: Connection) -> None:
        """Return *conn* to the pool (Postgres) or close it (SQLite)."""
        if self.backend == "postgres" and self._pool is not None:
            try:
                self._pool.putconn(conn._raw)  # noqa: SLF001 - intentional
            except Exception as exc:  # noqa: BLE001
                logger.debug("pool return failed: %s", exc)
            return
        conn.close()

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """One unit of work: commit on success, roll back on any exception."""
        conn = self.connect()
        try:
            conn.begin()
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self.release(conn)

    @contextmanager
    def read(self) -> Iterator[Connection]:
        """Read-only unit of work. Never commits user data."""
        conn = self.connect()
        try:
            yield conn
        finally:
            if self.backend == "sqlite":
                conn.rollback()
            self.release(conn)

    # -- observability ------------------------------------------------------

    def ping(self) -> tuple[bool, str]:
        """Cheap liveness probe: ``(ok, detail)``. Never raises."""
        try:
            conn = self.connect()
            try:
                value = conn.scalar("SELECT 1 AS ok")
                return (value == 1, "ok")
            finally:
                self.release(conn)
        except Exception as exc:  # noqa: BLE001 - probe must not raise
            return (False, type(exc).__name__)

    def close(self) -> None:
        if self._pool is not None:
            try:
                self._pool.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("pool close failed: %s", exc)
            finally:
                self._pool = None


def open_database(settings: DatabaseSettings | None = None) -> Database | None:
    """Return a :class:`Database`, or ``None`` when the layer is disabled."""
    from deeptutor.db.config import get_database_settings

    resolved = settings if settings is not None else get_database_settings()
    if not resolved.enabled:
        return None
    return Database(resolved)
