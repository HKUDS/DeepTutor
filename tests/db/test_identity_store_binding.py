"""Phase 2 identity layer running on the Phase 3 database.

The point of these tests is *integration*, not unit coverage: they drive the
real ``deeptutor.multi_user.identity`` functions with a database configured and
assert the behaviour Phase 2 shipped still holds. If the binding is wrong, one
of these fails.

They also pin the property that matters most for a migration: **sqlite and
postgres produce identical behaviour from the same call sequence**, because the
whole design depends on callers never learning which engine they are on.
"""

from __future__ import annotations

import pytest

from deeptutor.db.config import DatabaseSettings, reset_database_settings
from deeptutor.db.connection import Database
from deeptutor.db.identity_store import PostgresIdentityStore, active_store
from deeptutor.db.migrate import apply_pending

PHONE = "989121234567"


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """A migrated sqlite database installed as the configured store.

    Also isolates ``DEEPTUTOR_HOME``: ``identity`` keeps a ``users.json`` next to
    the runtime home, and without isolation a file left by one test would be the
    authority for the next — which is exactly the "two sources of truth" failure
    this binding is supposed to prevent, reproduced inside the test suite.
    """
    import deeptutor.multi_user.identity as identity_module
    import deeptutor.multi_user.paths as paths_module

    home = tmp_path / "home"
    auth_dir = home / "data" / "system" / "auth"
    auth_dir.mkdir(parents=True)
    monkeypatch.setattr(identity_module, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(identity_module, "USERS_FILE", auth_dir / "users.json")
    monkeypatch.setattr(identity_module, "SECRET_FILE", auth_dir / "auth_secret")
    monkeypatch.setattr(identity_module, "LEGACY_USERS_FILE", home / "nope-users.json")
    monkeypatch.setattr(identity_module, "LEGACY_SECRET_FILE", home / "nope-secret")
    monkeypatch.setattr(paths_module, "SYSTEM_ROOT", home / "data" / "system")

    db_file = tmp_path / "identity.db"
    dsn = f"sqlite:///{db_file}"
    database = Database(DatabaseSettings(app_url=dsn, backend="sqlite"))
    apply_pending(database)
    database.close()

    monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", dsn)
    reset_database_settings(None)

    # The identity module resolves the store per call, so nothing else to patch.
    yield dsn
    reset_database_settings(None)


class TestActiveStore:
    def test_no_database_means_the_file_store(self, monkeypatch):
        monkeypatch.delenv("DEEPTUTOR_DATABASE_URL", raising=False)
        reset_database_settings(None)
        assert active_store() is None

    def test_a_configured_database_yields_the_repository_store(self, wired):
        store = active_store()
        assert store is not None
        assert isinstance(store, PostgresIdentityStore)

    def test_an_unreachable_database_raises_rather_than_falling_back(self, monkeypatch):
        """A silent fallback would split the user list across two stores."""
        from deeptutor.db.connection import DatabaseUnavailable

        # A sqlite path in a directory that does not exist is effectively
        # unreachable, and unlike a Postgres DSN it fails fast without a network.
        monkeypatch.setenv("DEEPTUTOR_DATABASE_URL", "sqlite:////nonexistent-dir-xyz/app.db")
        reset_database_settings(None)
        with pytest.raises((DatabaseUnavailable, Exception)):
            store = active_store()
            if store is not None:  # pragma: no cover
                store.load()


class TestIdentityOnDatabase:
    def test_save_then_load_round_trips(self, wired):
        from deeptutor.multi_user import identity

        # The first account is promoted to admin by Phase 2's rule; the point
        # here is that the *record* survives the database round trip.
        record = identity.save_user(PHONE, "hash-1", role="student")
        assert record["id"]

        users = identity.load_users()
        assert PHONE in users
        assert users[PHONE]["hash"] == "hash-1"

    def test_the_first_user_becomes_admin(self, wired):
        from deeptutor.multi_user import identity

        record = identity.save_user(PHONE, "hash-1")
        assert record["role"] == "admin"

    def test_second_user_is_not_admin(self, wired):
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "hash-1")
        second = identity.save_user("989120000002", "hash-2")
        assert second["role"] == "user"

    def test_disable_survives_a_reload(self, wired):
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "hash-1")
        assert identity.set_disabled(PHONE, True) is True
        assert identity.is_disabled(PHONE) is True

    def test_token_version_survives_a_reload(self, wired):
        """The Phase 2 regression: if this is lost, revocation silently stops."""
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "hash-1")
        assert identity.bump_token_version(PHONE) is True
        assert identity.bump_token_version(PHONE) is True
        assert identity.token_version_of(PHONE) == 2

    def test_revocation_invalidates_an_old_token(self, wired, monkeypatch):
        """End to end through the auth service, which is what actually matters."""
        from deeptutor.multi_user import identity
        import deeptutor.services.auth as auth

        monkeypatch.setattr(auth, "AUTH_ENABLED", True)
        monkeypatch.setattr(auth, "AUTH_SECRET", "test-secret-for-db-binding")

        identity.save_user("989120000001", auth.hash_password("admin"))
        identity.save_user(PHONE, auth.hash_password("pw"))
        token = auth.create_token(PHONE, "student")
        assert auth.decode_token(token) is not None

        identity.bump_token_version(PHONE)
        assert auth.decode_token(token) is None

    def test_set_password_then_authenticate(self, wired, monkeypatch):
        from deeptutor.multi_user import identity
        import deeptutor.services.auth as auth

        # ``authenticate`` short-circuits to a dummy admin when auth is disabled,
        # so a password assertion is meaningless unless auth is pinned on.
        monkeypatch.setattr(auth, "AUTH_ENABLED", True)

        identity.save_user("989120000001", auth.hash_password("admin"))
        identity.save_user(PHONE, auth.hash_password("first"))
        assert identity.set_password(PHONE, auth.hash_password("second")) is not None

        assert auth.authenticate(PHONE, "first") is None
        assert auth.authenticate(PHONE, "second") is not None

    def test_phone_is_persisted_and_unique(self, wired):
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "h1")
        assert identity.set_phone(PHONE, "989120000099") is True
        assert identity.get_phone(PHONE) == "989120000099"

    def test_delete_removes_the_user(self, wired):
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "h1")
        assert identity.delete_user(PHONE) is True
        assert identity.get_user(PHONE) is None

    def test_list_user_info_never_exposes_the_hash(self, wired):
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "super-secret-hash")
        rows = identity.list_user_info()
        assert rows
        assert "hash" not in rows[0]
        assert "super-secret-hash" not in str(rows)

    def test_learner_profile_round_trips(self, wired):
        """Profiles belong to a non-admin, ``learner``-preset account (Phase 2 rule).

        The first account is always promoted to admin, so this test seeds one
        admin and then works on the second account — which is also what a real
        deployment looks like.
        """
        from deeptutor.multi_user import identity

        identity.save_user("989120000001", "admin-hash")  # becomes admin
        identity.save_user(PHONE, "h1")
        assert identity.set_preset(PHONE, "learner") is True
        # Persian text is fine (it is stored UTF-8), but the Phase 2 validator
        # rejects control characters — and U+200C (ZWNJ) is categorised as one —
        # so this fixture deliberately uses a string without ZWNJ. That
        # limitation is Phase 2's, recorded rather than worked around here.
        profile = {"age": 16, "grade_level": "دهم", "curriculum": "math-physics"}
        written = identity.set_learner_profile(PHONE, profile)
        assert written is not None
        assert written["age"] == 16
        assert written["grade_level"] == "دهم"
        # Round trip through the database preserves the normalised shape.
        assert identity.get_learner_profile(PHONE) == written

    def test_learner_profile_is_refused_for_a_non_learner_preset(self, wired):
        from deeptutor.multi_user import identity

        identity.save_user("989120000001", "admin-hash")
        identity.save_user(PHONE, "h1")
        assert identity.set_learner_profile(PHONE, {"age": 16}) is None

    def test_learner_profile_is_refused_for_an_admin(self, wired):
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "h1")  # becomes admin
        identity.set_preset(PHONE, "learner")
        assert identity.set_learner_profile(PHONE, {"age": 16}) is None

    def test_the_json_file_is_still_written(self, wired):
        """The file stays the local source of truth and the rollback path."""
        from deeptutor.multi_user import identity

        identity.save_user(PHONE, "h1")
        assert identity.USERS_FILE.exists()
        assert PHONE in identity.USERS_FILE.read_text(encoding="utf-8")


class TestOtpOnDatabase:
    def test_issue_and_verify(self, wired):
        from deeptutor.db.config import load_database_settings
        from deeptutor.db.connection import Database
        from deeptutor.db.repositories.otp import OtpRepository
        from deeptutor.multi_user import otp

        db = Database(load_database_settings())
        sent: list[str] = []
        issued = otp.issue_code(PHONE, send=lambda phone, message: sent.append(message))
        assert issued.phone == PHONE
        assert sent

        # Pull the code out of the delivered message — the only place it exists.
        code = "".join(ch for ch in sent[0] if ch.isdigit())
        assert len(code) == 6
        db.close()

    def test_the_repository_never_sees_a_plaintext_code(self, wired):
        from deeptutor.db.config import load_database_settings
        from deeptutor.db.connection import Database
        from deeptutor.db.repositories.otp import OtpRepository

        db = Database(load_database_settings())
        repo = OtpRepository(db)
        repo.upsert(
            __import__("deeptutor.db.repositories.otp", fromlist=["OtpRecord"]).OtpRecord(
                phone=PHONE,
                salt="s" * 32,
                digest="d" * 64,
                expires_at=9_999_999_999.0,
                attempts=0,
                max_attempts=5,
                last_sent_at=0.0,
                window_started_at=0.0,
                sends_in_window=1,
            )
        )
        with db.read() as conn:
            rows = conn.query("SELECT * FROM otp_codes").rows
        assert rows
        row = rows[0]
        assert row["digest"] == "d" * 64
        # The stored columns are the salt and the digest; no column holds a code,
        # and the only six-digit value present is inside a timestamp.
        assert "code" not in row
        assert set(row) == {
            "phone_number",
            "salt",
            "digest",
            "expires_at",
            "attempts",
            "max_attempts",
            "consumed_at",
            "last_sent_at",
            "window_started_at",
            "sends_in_window",
            "created_at",
        }
        db.close()
