"""Identity repository: field fidelity against the Phase 2 JSON record."""

from __future__ import annotations

import pytest

from deeptutor.db.connection import Database
from deeptutor.db.repositories.identity import (
    RECORD_FIELDS,
    IdentityRepository,
    IdentityRepositoryError,
    canonicalize_record,
    record_from_row,
)

PHONE = "989121234567"


def make_user(username: str = PHONE, **overrides):
    record = {
        "id": f"u_{username}",
        "hash": "pbkdf2_sha256$600000$salt$digest",
        "role": "student",
        "created_at": "2026-11-01T10:00:00+00:00",
        "disabled": False,
        "avatar": "",
        "preset": "standard",
        "must_change_password": False,
        "token_version": 0,
    }
    record.update(overrides)
    return record


class TestRoundTrip:
    @pytest.mark.parametrize("field", RECORD_FIELDS)
    def test_every_record_field_survives_a_write_and_read(self, db: Database, field):
        """The regression that matters most.

        Phase 2 shipped two bugs where a field was dropped on a
        canonicalise-write round trip: ``token_version`` (revocation silently
        stopped working) and ``phone`` (registration lost the identity). This
        test names every field and fails if any of them is lost, so a new field
        added to one side and not the other cannot pass unnoticed.
        """
        repo = IdentityRepository(db)
        record = make_user(
            phone=PHONE,
            username=PHONE,
            book_permission={"mode": "all"},
            learner_profile={"grade": 10},
        )
        repo.save(PHONE, record)
        loaded = repo.get(PHONE)
        assert loaded is not None, f"{field} test could not load the record"
        assert field in loaded, f"{field} was dropped by the round trip"

    def test_values_are_preserved_exactly(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE, token_version=7, disabled=True))
        loaded = repo.get(PHONE)
        assert loaded is not None
        assert loaded["token_version"] == 7
        assert loaded["disabled"] is True
        assert loaded["role"] == "student"
        assert loaded["created_at"] == "2026-11-01T10:00:00+00:00"

    def test_nested_json_payloads_round_trip(self, db: Database):
        repo = IdentityRepository(db)
        profile = {"grade": 11, "major": "riazi", "interests": ["math", "physics"]}
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE, learner_profile=profile))
        loaded = repo.get(PHONE)
        assert loaded is not None
        assert loaded["learner_profile"] == profile

    def test_missing_optional_fields_are_absent_not_none(self, db: Database):
        repo = IdentityRepository(db)
        repo.save("admin", make_user(id="u_admin", role="admin"))
        loaded = repo.get("admin")
        assert loaded is not None
        assert "phone" not in loaded
        assert "book_permission" not in loaded
        assert "learner_profile" not in loaded


class TestCanonicalize:
    def test_string_value_becomes_a_hashed_record(self):
        record = canonicalize_record("someone", "already-hashed")
        assert record is not None
        assert record["hash"] == "already-hashed"
        assert record["token_version"] == 0
        assert record["disabled"] is False

    def test_record_without_hash_is_rejected(self):
        assert canonicalize_record("x", {"role": "admin"}) is None

    def test_non_dict_is_rejected(self):
        assert canonicalize_record("x", 42) is None

    def test_unknown_role_falls_back(self):
        record = canonicalize_record("x", {"hash": "h", "role": "superuser"}, default_role="user")
        assert record is not None
        assert record["role"] == "user"

    def test_unknown_preset_falls_back(self):
        record = canonicalize_record("x", {"hash": "h", "preset": "weird"})
        assert record is not None
        assert record["preset"] == "standard"

    def test_string_booleans_are_coerced(self):
        record = canonicalize_record("x", {"hash": "h", "disabled": "true"})
        assert record is not None
        assert record["disabled"] is True

    def test_zero_token_version_is_not_lost_to_falsiness(self):
        """``int(value.get("token_version") or 0)`` — make sure 0 stays 0 and is absent from the dict."""
        record = canonicalize_record("x", {"hash": "h", "token_version": 0})
        assert record is not None
        assert record["token_version"] == 0


class TestReadPaths:
    def test_load_users_keys_by_username(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        repo.save("admin", make_user(id="u_admin", role="admin"))
        users = repo.load_users()
        assert set(users) == {PHONE, "admin"}
        assert users[PHONE]["role"] == "student"
        assert users["admin"]["role"] == "admin"

    def test_get_by_username_phone_or_id(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        for key in (PHONE, f"u_{PHONE}"):
            assert repo.get(key) is not None, key

    def test_get_by_phone(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        found = repo.get_by_phone(PHONE)
        assert found is not None
        assert found[0] == PHONE

    def test_get_returns_none_for_unknown(self, db: Database):
        assert IdentityRepository(db).get("nobody") is None

    def test_is_first_user(self, db: Database):
        repo = IdentityRepository(db)
        assert repo.is_first_user() is True
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        assert repo.is_first_user() is False

    def test_list_public_hides_the_hash(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        public = repo.list_public()
        assert public
        assert all("hash" not in entry for entry in public)
        assert public[0]["username"] == PHONE


class TestWrites:
    def test_save_then_save_again_updates(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE, role="teacher"))
        assert repo.count() == 1
        loaded = repo.get(PHONE)
        assert loaded is not None
        assert loaded["role"] == "teacher"

    def test_set_disabled_is_visible_immediately(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        assert repo.set_disabled(PHONE, True) is True
        assert repo.get(PHONE)["disabled"] is True  # type: ignore[index]
        assert repo.set_disabled(PHONE, False) is True
        assert repo.get(PHONE)["disabled"] is False  # type: ignore[index]

    def test_set_disabled_unknown_user_returns_false(self, db: Database):
        assert IdentityRepository(db).set_disabled("ghost", True) is False

    def test_bump_token_version_increments_atomically(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        assert repo.bump_token_version(PHONE) is True
        assert repo.bump_token_version(PHONE) is True
        assert repo.token_version_of(PHONE) == 2

    def test_bump_token_version_unknown_user_returns_false(self, db: Database):
        assert IdentityRepository(db).bump_token_version("ghost") is False

    def test_set_role_rejects_invalid_role(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        with pytest.raises(IdentityRepositoryError, match="invalid role"):
            repo.set_role(PHONE, "god")

    def test_set_preset_rejects_invalid_preset(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        with pytest.raises(IdentityRepositoryError, match="invalid preset"):
            repo.set_preset(PHONE, "fancy")

    def test_phone_must_be_unique(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        repo.save("other", make_user(id="u_other"))
        with pytest.raises(IdentityRepositoryError, match="already registered"):
            repo.set_phone("other", PHONE)

    def test_delete_removes_the_user(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        assert repo.delete(PHONE) is True
        assert repo.get(PHONE) is None
        assert repo.delete("ghost") is False

    def test_mark_login_sets_last_login(self, db: Database):
        repo = IdentityRepository(db)
        repo.save(PHONE, make_user(phone=PHONE, username=PHONE))
        repo.mark_login(PHONE)
        with db.read() as conn:
            row = conn.query_one("SELECT last_login_at FROM users WHERE phone_number = ?", (PHONE,))
        assert row is not None and row["last_login_at"]


class TestBackfill:
    def test_backfill_writes_every_valid_user(self, db: Database):
        repo = IdentityRepository(db)
        users = {
            PHONE: make_user(phone=PHONE, username=PHONE),
            "admin": make_user(id="u_admin", role="admin"),
        }
        result = repo.backfill(users.items())
        assert result == {"written": 2, "skipped": 0}
        assert repo.count() == 2

    def test_backfill_is_idempotent(self, db: Database):
        repo = IdentityRepository(db)
        users = {PHONE: make_user(phone=PHONE, username=PHONE)}
        repo.backfill(users.items())
        repo.backfill(users.items())
        assert repo.count() == 1

    def test_backfill_skips_invalid_records_without_aborting(self, db: Database):
        repo = IdentityRepository(db)
        users = {
            PHONE: make_user(phone=PHONE, username=PHONE),
            "broken": {"role": "admin"},  # no hash
        }
        result = repo.backfill(users.items())
        assert result == {"written": 1, "skipped": 1}
        assert repo.count() == 1

    def test_backfill_preserves_security_state(self, db: Database):
        repo = IdentityRepository(db)
        users = {
            PHONE: make_user(
                phone=PHONE,
                username=PHONE,
                token_version=9,
                disabled=True,
                must_change_password=True,
            )
        }
        repo.backfill(users.items())
        loaded = repo.get(PHONE)
        assert loaded is not None
        assert loaded["token_version"] == 9
        assert loaded["disabled"] is True
        assert loaded["must_change_password"] is True


class TestRecordFromRow:
    def test_handles_postgres_style_booleans(self):
        row = {
            "id": "u_1",
            "username": "a",
            "phone_number": None,
            "password_hash": "h",
            "role": "user",
            "disabled": True,
            "must_change_password": False,
            "avatar": "",
            "preset": "standard",
            "token_version": 3,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        record = record_from_row(row)
        assert record["disabled"] is True
        assert record["must_change_password"] is False

    def test_handles_sqlite_integer_booleans(self):
        row = {
            "id": "u_1",
            "username": "a",
            "phone_number": None,
            "password_hash": "h",
            "role": "user",
            "disabled": 1,
            "must_change_password": 0,
            "avatar": "",
            "preset": "standard",
            "token_version": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        record = record_from_row(row)
        assert record["disabled"] is True
        assert record["must_change_password"] is False

    def test_tolerates_unparseable_json_columns(self):
        row = {
            "id": "u_1",
            "username": "a",
            "phone_number": None,
            "password_hash": "h",
            "role": "user",
            "disabled": 0,
            "must_change_password": 0,
            "avatar": "",
            "preset": "standard",
            "token_version": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
            "book_permission": "{not json",
        }
        record = record_from_row(row)
        assert "book_permission" not in record
