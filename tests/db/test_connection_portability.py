"""Engine adapters: the translations that make one SQL dialect work on two engines.

Every function here exists because SQLite and PostgreSQL disagree about
something. Each test pins one disagreement, so a refactor that "simplifies" the
adapter fails here rather than in production.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from deeptutor.db.config import DatabaseConfigError, load_database_settings, redact_dsn
from deeptutor.db.connection import DatabaseSettings, coerce_param, normalize_value


class TestRedactDsn:
    def test_removes_the_password(self):
        dsn = "postgresql://app:sup3rs3cret@db.example.com:5432/postgres"
        redacted = redact_dsn(dsn)
        assert "sup3rs3cret" not in redacted
        assert "***" in redacted
        assert "db.example.com" in redacted

    def test_leaves_a_passwordless_dsn_alone(self):
        dsn = "postgresql://db.example.com/postgres"
        assert redact_dsn(dsn) == dsn

    def test_handles_empty(self):
        assert redact_dsn("") == ""

    def test_decodes_nothing_it_should_not(self):
        """A password with punctuation must still be fully removed."""
        dsn = "postgresql://app:p%40ss%2Fw0rd@host:5432/db"
        assert "p%40ss" not in redact_dsn(dsn)


class TestLoadSettings:
    def test_disabled_without_a_url(self):
        settings = load_database_settings({})
        assert settings.enabled is False
        assert settings.backend == "sqlite"  # the neutral default label

    def test_parses_a_postgres_url(self):
        settings = load_database_settings({"DEEPTUTOR_DATABASE_URL": "postgresql://h/db"})
        assert settings.enabled is True
        assert settings.is_postgres is True

    def test_migration_url_falls_back_to_the_app_url(self):
        settings = load_database_settings({"DEEPTUTOR_DATABASE_URL": "postgresql://h/db"})
        assert settings.migration_url == settings.app_url

    def test_migration_url_can_differ(self):
        settings = load_database_settings(
            {
                "DEEPTUTOR_DATABASE_URL": "postgresql://app@h/db",
                "DEEPTUTOR_MIGRATION_DATABASE_URL": "postgresql://owner@h/db",
            }
        )
        assert settings.migration_url == "postgresql://owner@h/db"

    def test_rejects_an_unknown_scheme(self):
        with pytest.raises(DatabaseConfigError, match="unsupported database scheme"):
            load_database_settings({"DEEPTUTOR_DATABASE_URL": "mysql://h/db"})

    def test_rejects_a_mismatched_migration_backend(self):
        with pytest.raises(DatabaseConfigError, match="does not match"):
            load_database_settings(
                {
                    "DEEPTUTOR_DATABASE_URL": "postgresql://h/db",
                    "DEEPTUTOR_MIGRATION_DATABASE_URL": "sqlite:///x.db",
                }
            )

    def test_pool_size_must_be_numeric(self):
        with pytest.raises(DatabaseConfigError, match="must be an integer"):
            load_database_settings(
                {
                    "DEEPTUTOR_DATABASE_URL": "postgresql://h/db",
                    "DEEPTUTOR_DATABASE_POOL_SIZE": "lots",
                }
            )

    def test_pool_size_must_be_positive(self):
        with pytest.raises(DatabaseConfigError, match="must be positive"):
            load_database_settings(
                {"DEEPTUTOR_DATABASE_URL": "postgresql://h/db", "DEEPTUTOR_DATABASE_POOL_SIZE": "0"}
            )

    def test_describe_never_leaks_the_password(self):
        settings = load_database_settings(
            {"DEEPTUTOR_DATABASE_URL": "postgresql://app:secret@db.host:5432/postgres"}
        )
        described = str(settings.describe())
        assert "secret" not in described
        assert "db.host" in described


class TestNormalizeValue:
    def test_datetime_becomes_iso_utc(self):
        moment = datetime(2026, 11, 17, 20, 45, tzinfo=timezone.utc)
        assert normalize_value(moment) == "2026-11-17T20:45:00+00:00"

    def test_naive_datetime_is_assumed_utc(self):
        """Postgres ``timestamptz`` can hand back a naive value in some configs."""
        moment = datetime(2026, 11, 17, 20, 45)
        assert normalize_value(moment) == "2026-11-17T20:45:00+00:00"

    def test_non_utc_offset_is_converted(self):
        from datetime import timedelta

        moment = datetime(2026, 11, 17, 23, 15, tzinfo=timezone(timedelta(hours=2, minutes=30)))
        assert normalize_value(moment) == "2026-11-17T20:45:00+00:00"

    def test_scalars_pass_through(self):
        assert normalize_value(42) == 42
        assert normalize_value("text") == "text"
        assert normalize_value(None) is None
        assert normalize_value(True) is True

    def test_decimal_becomes_a_number(self):
        from decimal import Decimal

        assert normalize_value(Decimal("15")) == 15
        assert normalize_value(Decimal("1.5")) == 1.5


class TestCoerceParam:
    @pytest.mark.parametrize(
        "value",
        [
            "2026-11-17T20:45:00+00:00",
            "2026-11-17T20:45:00Z",
            "2026-11-17T20:45:00.123456+00:00",
            "2026-11-17T20:45:00-05:00",
        ],
    )
    def test_iso_instants_become_datetimes_on_postgres(self, value):
        coerced = coerce_param(value, "postgres")
        assert isinstance(coerced, datetime)

    @pytest.mark.parametrize(
        "value",
        [
            "u_abc123",  # an id
            "989121234567",  # a phone
            "2026-11-17",  # a date, not an instant
            "2026-11-17T20:45:00",  # no offset: ambiguous
            "not a date at all",
            "Error: disk on fire",
            '{"a": 1}',
            "",
        ],
    )
    def test_everything_else_passes_through_on_postgres(self, value):
        assert coerce_param(value, "postgres") == value

    def test_sqlite_never_converts(self):
        """SQLite stores timestamps as TEXT; converting would change the sort order."""
        value = "2026-11-17T20:45:00+00:00"
        assert coerce_param(value, "sqlite") == value

    def test_non_strings_are_untouched(self):
        assert coerce_param(42, "postgres") == 42
        assert coerce_param(None, "postgres") is None

    def test_round_trip_through_normalize_is_stable(self):
        """coerce then normalize must return the original string.

        This is what makes the repositories engine-agnostic: a value read from
        Postgres is written back in the identical representation.
        """
        original = "2026-11-17T20:45:00+00:00"
        assert normalize_value(coerce_param(original, "postgres")) == original


class TestPlaceholderAdaptation:
    def test_question_marks_become_percent_s_on_postgres(self):
        from deeptutor.db.connection import Connection

        conn = Connection.__new__(Connection)
        conn.backend = "postgres"
        assert conn._adapt("SELECT * FROM t WHERE a = ? AND b = ?") == (
            "SELECT * FROM t WHERE a = %s AND b = %s"
        )

    def test_sqlite_keeps_question_marks(self):
        from deeptutor.db.connection import Connection

        conn = Connection.__new__(Connection)
        conn.backend = "sqlite"
        assert conn._adapt("SELECT ? ") == "SELECT ? "

    def test_a_literal_question_mark_in_a_string_is_not_a_placeholder(self):
        from deeptutor.db.connection import Connection

        conn = Connection.__new__(Connection)
        conn.backend = "postgres"
        assert conn._adapt("SELECT 'what?' AS q WHERE id = ?") == (
            "SELECT 'what?' AS q WHERE id = %s"
        )

    def test_a_literal_percent_is_escaped_for_psycopg(self):
        """psycopg uses ``%`` for its own interpolation, so a literal needs doubling."""
        from deeptutor.db.connection import Connection

        conn = Connection.__new__(Connection)
        conn.backend = "postgres"
        assert conn._adapt("SELECT '100%' AS p WHERE id = ?") == (
            "SELECT '100%%' AS p WHERE id = %s"
        )
