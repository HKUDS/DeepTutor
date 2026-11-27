"""Health, readiness and backup evidence.

The properties that matter:
* liveness never touches a dependency (a database outage must not restart a
  healthy process)
* readiness *does* fail when the database is broken, and says 503
* backup evidence is a comparable snapshot with no user data in it
"""

from __future__ import annotations

import pytest

from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.health import backup_evidence, liveness, readiness


class TestLiveness:
    def test_is_ok_without_any_dependency(self, monkeypatch):
        monkeypatch.delenv("DEEPTUTOR_DATABASE_URL", raising=False)
        reset_database_settings(None)
        payload = liveness()
        assert payload["status"] == "ok"
        assert "checked_at" in payload

    def test_stays_ok_when_the_database_is_unreachable(self, monkeypatch):
        """The whole point: a broken database must not look like a dead process."""
        monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
        reset_database_settings(None)
        assert liveness()["status"] == "ok"


class TestReadiness:
    def test_ok_without_a_database(self, monkeypatch):
        monkeypatch.delenv("DEEPTUTOR_DATABASE_URL", raising=False)
        reset_database_settings(None)
        payload = readiness()
        assert payload["status"] == "ok"
        assert payload["database"]["enabled"] is False

    def test_ok_with_a_migrated_sqlite_database(self, monkeypatch, tmp_path):
        from deeptutor.db.connection import Database
        from deeptutor.db.migrate import apply_pending

        db_file = tmp_path / "ready.db"
        db = Database(DatabaseSettings(app_url=f"sqlite:///{db_file}", backend="sqlite"))
        apply_pending(db)
        try:
            payload = readiness(db)
        finally:
            db.close()
        assert payload["status"] == "ok"
        assert payload["schema"]["ok"] is True

    def test_degraded_when_a_required_column_is_missing(self, monkeypatch, tmp_path):
        from deeptutor.db.connection import Database
        from deeptutor.db.migrate import apply_pending

        db_file = tmp_path / "broken.db"
        db = Database(DatabaseSettings(app_url=f"sqlite:///{db_file}", backend="sqlite"))
        apply_pending(db)
        # Simulate drift: drop a column the code depends on.
        with db.transaction() as conn:
            conn.execute("ALTER TABLE users DROP COLUMN must_change_password")
        try:
            payload = readiness(db)
        finally:
            db.close()
        assert payload["status"] == "degraded"
        assert payload["schema"]["ok"] is False
        assert "must_change_password" in payload["schema"]["reason"]

    def test_never_raises_on_a_broken_dsn(self, monkeypatch):
        monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")
        reset_database_settings(None)
        payload = readiness()
        assert payload["status"] == "degraded"
        assert payload["database"]["ok"] is False


class TestBackupEvidence:
    def test_reports_no_database_as_a_note(self, monkeypatch):
        monkeypatch.delenv("DEEPTUTOR_DATABASE_URL", raising=False)
        reset_database_settings(None)
        evidence = backup_evidence()
        assert "no database configured" in evidence["note"]
        assert evidence["tables"] == {}

    def test_reports_the_migration_ledger(self, tmp_path):
        from deeptutor.db.connection import Database
        from deeptutor.db.migrate import apply_pending

        db = Database(DatabaseSettings(app_url=f"sqlite:///{tmp_path / 'ev.db'}", backend="sqlite"))
        apply_pending(db)
        try:
            evidence = backup_evidence(db)
        finally:
            db.close()
        from deeptutor.db.migrate import discover_migrations

        versions = [m["version"] for m in evidence["migrations"]]
        # Compared against what is shipped, not a literal: a literal turns every
        # new migration into a red test whose obvious fix is to edit the list.
        # Postgres-only migrations are skipped on SQLite, so the ledger holds
        # what applies to this backend.
        expected = [m.version for m in discover_migrations() if m.applies_to("sqlite")]
        assert versions == expected
        assert all(m["known_to_source"] for m in evidence["migrations"])
        assert evidence["schema_ok"] is True

    def test_row_counts_cover_every_table(self, tmp_path):
        from deeptutor.db.connection import Database
        from deeptutor.db.migrate import apply_pending

        db = Database(DatabaseSettings(app_url=f"sqlite:///{tmp_path / 'rc.db'}", backend="sqlite"))
        apply_pending(db)
        try:
            evidence = backup_evidence(db)
        finally:
            db.close()
        from deeptutor.db.migrate import discover_migrations

        assert evidence["tables"]["users"] == 0
        assert evidence["tables"]["deeptutor_schema_migrations"] == len(
            [m for m in discover_migrations() if m.applies_to("sqlite")]
        )
        # Phase 4 tables are counted too, so a backup artefact stays complete as
        # the schema grows.
        assert evidence["tables"]["catalog_sources"] == 0
        assert evidence["tables"]["curriculum_grades"] == 0

    def test_contains_no_user_data(self, tmp_path):
        """A backup artefact that leaks emails is a liability."""
        from deeptutor.db.connection import Database
        from deeptutor.db.migrate import apply_pending
        from deeptutor.db.repositories.identity import IdentityRepository

        db = Database(DatabaseSettings(app_url=f"sqlite:///{tmp_path / 'nu.db'}", backend="sqlite"))
        apply_pending(db)
        IdentityRepository(db).save(
            "989120000123",
            {
                "id": "u_x",
                "hash": "secret-hash",
                "role": "student",
                "created_at": "2026-01-01T00:00:00+00:00",
                "disabled": False,
                "avatar": "",
                "preset": "standard",
                "must_change_password": False,
                "token_version": 0,
                "phone": "989120000123",
                "username": "989120000123",
            },
        )
        try:
            evidence = backup_evidence(db)
        finally:
            db.close()
        blob = str(evidence)
        assert "secret-hash" not in blob
        assert "989120000123" not in blob
        assert evidence["tables"]["users"] == 1

    def test_flags_a_migration_the_source_does_not_know(self, tmp_path):
        from deeptutor.db.connection import Database
        from deeptutor.db.migrate import apply_pending

        db = Database(DatabaseSettings(app_url=f"sqlite:///{tmp_path / 'uk.db'}", backend="sqlite"))
        apply_pending(db)
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO deeptutor_schema_migrations (version, name, checksum, applied_at) "
                "VALUES (99, 'ghost', 'x', '2026-01-01')"
            )
        try:
            evidence = backup_evidence(db)
        finally:
            db.close()
        ghost = [m for m in evidence["migrations"] if m["version"] == 99]
        assert ghost and ghost[0]["known_to_source"] is False
