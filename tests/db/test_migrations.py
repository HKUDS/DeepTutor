"""Migration engine: discovery, idempotency, drift detection, rollback."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.db.config import DatabaseSettings
from deeptutor.db.connection import Database
from deeptutor.db.migrate import (
    MigrationError,
    applied_migrations,
    apply_pending,
    discover_migrations,
    rollback_to,
    split_statements,
)


class TestDiscovery:
    def test_finds_all_shipped_migrations_in_order(self):
        migrations = discover_migrations()
        assert [m.version for m in migrations] == sorted(m.version for m in migrations)
        assert [m.name for m in migrations] == [
            "product_core",
            "billing_and_storage",
            "jobs_and_idempotency",
            "reconcile_legacy_supabase",
            "ensure_unique_indexes",
        ]

    def test_every_migration_has_both_directions(self):
        for migration in discover_migrations():
            assert split_statements(migration.up), f"{migration.name} UP is empty"
            assert split_statements(migration.down), f"{migration.name} DOWN is empty"

    def test_checksum_is_stable_across_reads(self):
        first = discover_migrations()
        second = discover_migrations()
        assert [m.checksum for m in first] == [m.checksum for m in second]

    def test_rejects_bad_filename(self, tmp_path: Path):
        (tmp_path / "0001_bad.sql").write_text("-- @@ UP @@\nSELECT 1;\n-- @@ DOWN @@\nSELECT 1;")
        with pytest.raises(MigrationError, match="unrecognised migration file"):
            discover_migrations(tmp_path)

    def test_rejects_missing_down_section(self, tmp_path: Path):
        (tmp_path / "V0001__broken.sql").write_text("-- @@ UP @@\nSELECT 1;")
        with pytest.raises(MigrationError, match="must contain"):
            discover_migrations(tmp_path)

    def test_rejects_empty_up(self, tmp_path: Path):
        (tmp_path / "V0001__broken.sql").write_text(
            "-- @@ UP @@\n-- only a comment\n-- @@ DOWN @@\nSELECT 1;"
        )
        with pytest.raises(MigrationError, match="empty UP"):
            discover_migrations(tmp_path)

    def test_rejects_duplicate_versions(self, tmp_path: Path):
        for name in ("V0001__one.sql", "V0001__two.sql"):
            (tmp_path / name).write_text("-- @@ UP @@\nSELECT 1;\n-- @@ DOWN @@\nSELECT 1;")
        with pytest.raises(MigrationError, match="duplicate"):
            discover_migrations(tmp_path)

    def test_rejects_uppercase_name(self, tmp_path: Path):
        (tmp_path / "V0001__BadName.sql").write_text(
            "-- @@ UP @@\nSELECT 1;\n-- @@ DOWN @@\nSELECT 1;"
        )
        with pytest.raises(MigrationError, match="unrecognised migration file"):
            discover_migrations(tmp_path)


class TestSplitStatements:
    def test_splits_on_top_level_semicolons(self):
        assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]

    def test_ignores_semicolon_in_string_literal(self):
        sql = "INSERT INTO t VALUES ('a;b');"
        assert split_statements(sql) == ["INSERT INTO t VALUES ('a;b')"]

    def test_ignores_semicolon_in_line_comment(self):
        sql = "-- a; b\nSELECT 1;"
        assert split_statements(sql) == ["SELECT 1"]

    def test_handles_escaped_quote(self):
        sql = "INSERT INTO t VALUES ('it''s; fine');"
        assert len(split_statements(sql)) == 1

    def test_trailing_statement_without_semicolon(self):
        assert split_statements("SELECT 1") == ["SELECT 1"]

    def test_comment_only_input_is_empty(self):
        assert split_statements("-- nothing here\n") == []

    def test_empty_input(self):
        assert split_statements("") == []


class TestApply:
    def test_applies_everything_to_empty_database(self, sqlite_db: Database):
        with sqlite_db.read() as conn:
            applied = applied_migrations(conn)
        assert [int(r["version"]) for r in applied] == [1, 2, 3]

    def test_creates_the_expected_tables(self, sqlite_db: Database):
        with sqlite_db.read() as conn:
            names = {
                r["name"]
                for r in conn.query(
                    "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
                )
            }
        assert {
            "users",
            "otp_codes",
            "user_sessions",
            "audit_events",
            "plans",
            "billing_settings",
            "user_wallets",
            "payment_transactions",
            "token_usage_logs",
            "user_files",
            "jobs",
            "job_events",
        } <= names

    def test_second_run_is_a_no_op(self, sqlite_db: Database):
        assert apply_pending(sqlite_db) == []

    def test_records_checksums(self, sqlite_db: Database):
        with sqlite_db.read() as conn:
            rows = applied_migrations(conn)
        expected = {m.version: m.checksum for m in discover_migrations()}
        for row in rows:
            assert row["checksum"] == expected[int(row["version"])]

    def test_dry_run_reports_without_writing(self, tmp_path: Path):
        path = tmp_path / "fresh.db"
        db = Database(DatabaseSettings(app_url=f"sqlite:///{path}", backend="sqlite"))
        try:
            pending = apply_pending(db, dry_run=True)
            assert [m.version for m in pending] == [1, 2, 3]
            with db.read() as conn:
                assert applied_migrations(conn) == []
        finally:
            db.close()

    def test_target_version_stops_early(self, tmp_path: Path):
        path = tmp_path / "partial.db"
        db = Database(DatabaseSettings(app_url=f"sqlite:///{path}", backend="sqlite"))
        try:
            applied = apply_pending(db, target_version=2)
            assert [m.version for m in applied] == [1, 2]
            with db.read() as conn:
                assert [int(r["version"]) for r in applied_migrations(conn)] == [1, 2]
        finally:
            db.close()

    def test_resumes_from_partial_state(self, tmp_path: Path):
        path = tmp_path / "resume.db"
        db = Database(DatabaseSettings(app_url=f"sqlite:///{path}", backend="sqlite"))
        try:
            apply_pending(db, target_version=1)
            second = apply_pending(db)
            assert [m.version for m in second] == [2, 3]
        finally:
            db.close()


class TestDriftDetection:
    def test_refuses_edited_migration(self, tmp_path: Path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        target = migrations_dir / "V0001__thing.sql"
        target.write_text("-- @@ UP @@\nCREATE TABLE t (id TEXT);\n-- @@ DOWN @@\nDROP TABLE t;")
        db = Database(DatabaseSettings(app_url=f"sqlite:///{tmp_path / 'd.db'}", backend="sqlite"))
        try:
            apply_pending(db, directory=migrations_dir)
            target.write_text(
                "-- @@ UP @@\nCREATE TABLE t (id TEXT, extra TEXT);\n-- @@ DOWN @@\nDROP TABLE t;"
            )
            with pytest.raises(MigrationError, match="edited after being applied"):
                apply_pending(db, directory=migrations_dir)
        finally:
            db.close()

    def test_refuses_database_newer_than_source(self, tmp_path: Path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        (migrations_dir / "V0001__a.sql").write_text(
            "-- @@ UP @@\nCREATE TABLE a (id TEXT);\n-- @@ DOWN @@\nDROP TABLE a;"
        )
        (migrations_dir / "V0002__b.sql").write_text(
            "-- @@ UP @@\nCREATE TABLE b (id TEXT);\n-- @@ DOWN @@\nDROP TABLE b;"
        )
        db = Database(DatabaseSettings(app_url=f"sqlite:///{tmp_path / 'd.db'}", backend="sqlite"))
        try:
            apply_pending(db, directory=migrations_dir)
            (migrations_dir / "V0002__b.sql").unlink()
            with pytest.raises(MigrationError, match="not in the source tree"):
                apply_pending(db, directory=migrations_dir)
        finally:
            db.close()


class TestRollback:
    def test_rolls_back_to_zero(self, sqlite_db: Database):
        rolled = rollback_to(sqlite_db, 0)
        assert [m.version for m in rolled] == [3, 2, 1]
        with sqlite_db.read() as conn:
            names = {
                r["name"] for r in conn.query("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        # Only the bookkeeping table survives: it is the runner's own state.
        assert names == {"deeptutor_schema_migrations"}

    def test_rolls_back_partially(self, sqlite_db: Database):
        rollback_to(sqlite_db, 2)
        with sqlite_db.read() as conn:
            assert [int(r["version"]) for r in applied_migrations(conn)] == [1, 2]
            names = {
                r["name"] for r in conn.query("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        assert "jobs" not in names
        assert "users" in names

    def test_rollback_then_reapply_restores_schema(self, sqlite_db: Database):
        rollback_to(sqlite_db, 1)
        apply_pending(sqlite_db)
        with sqlite_db.read() as conn:
            assert [int(r["version"]) for r in applied_migrations(conn)] == [1, 2, 3]
            assert (
                conn.scalar("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='jobs'")
                == 1
            )

    def test_rollback_refuses_when_file_missing(self, tmp_path: Path):
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        f = migrations_dir / "V0001__a.sql"
        f.write_text("-- @@ UP @@\nCREATE TABLE a (id TEXT);\n-- @@ DOWN @@\nDROP TABLE a;")
        db = Database(DatabaseSettings(app_url=f"sqlite:///{tmp_path / 'd.db'}", backend="sqlite"))
        try:
            apply_pending(db, directory=migrations_dir)
            f.unlink()
            with pytest.raises(MigrationError, match="migration file is missing"):
                rollback_to(db, 0, directory=migrations_dir)
        finally:
            db.close()

    def test_dry_run_rollback_changes_nothing(self, sqlite_db: Database):
        rolled = rollback_to(sqlite_db, 0, dry_run=True)
        assert [m.version for m in rolled] == [3, 2, 1]
        with sqlite_db.read() as conn:
            assert [int(r["version"]) for r in applied_migrations(conn)] == [1, 2, 3]
