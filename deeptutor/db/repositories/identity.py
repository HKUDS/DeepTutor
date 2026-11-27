"""User identity persistence, shaped exactly like the Phase 2 users.json.

What must survive the move
--------------------------
The Phase 2 store is a dict keyed by *username*, where each record holds::

    id, hash, role, created_at, disabled, avatar, preset,
    must_change_password, token_version, (phone), book_permission, learner_profile

Two of those fields are security-critical and were each silently dropped once
already (see ``_canonical_record`` in ``deeptutor/multi_user/identity.py``):

* ``token_version`` — bumping it is how "log out everywhere" works. Drop it and
  revocation silently does nothing.
* ``disabled``      — dropping it re-enables a banned account on the next write.

So this repository's read path returns **every** field, and
:func:`record_from_row` / :func:`row_from_record` are the single translation
point, covered by a round-trip test that fails if a field is added to one side
and not the other.

Username versus phone
---------------------
Phase 2 identifies a user by ``username``; D-005 says registration is by phone,
so for real accounts ``username == phone_number``. The local admin account has
a username and no phone. Both live in ``users``; ``uq_users_username`` and
``uq_users_phone_number`` are each unique but nullable, so the two identities
cannot collide and an account can exist with only one of them.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Iterable

from deeptutor.db.connection import Database, DatabaseError

logger = logging.getLogger(__name__)

VALID_ROLES = frozenset({"admin", "teacher", "student", "user"})
VALID_PRESETS = frozenset({"standard", "learner", "custom"})

#: Columns that make up the Phase 2 record shape. Kept as a module constant so
#: the round-trip test can assert against it rather than a hand-copied list.
RECORD_FIELDS = (
    "id",
    "hash",
    "role",
    "created_at",
    "disabled",
    "avatar",
    "preset",
    "must_change_password",
    "token_version",
    "phone",
    "username",
)


class IdentityRepositoryError(RuntimeError):
    """A write violated an identity invariant."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any) -> bool:
    """SQLite stores booleans as 0/1, Postgres as real booleans."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes"}
    return bool(value)


def record_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Row -> the dict shape ``identity.load_users()`` returns."""
    record: dict[str, Any] = {
        "id": str(row["id"]),
        "hash": str(row["password_hash"]),
        "role": str(row["role"]),
        "created_at": str(row["created_at"]),
        "disabled": _as_bool(row["disabled"]),
        "avatar": str(row.get("avatar") or ""),
        "preset": str(row.get("preset") or "standard"),
        "must_change_password": _as_bool(row["must_change_password"]),
        "token_version": int(row.get("token_version") or 0),
    }
    if row.get("phone_number"):
        record["phone"] = str(row["phone_number"])
    if row.get("username"):
        record["username"] = str(row["username"])
    for extra, column in (
        ("book_permission", "book_permission"),
        ("learner_profile", "learner_profile"),
    ):
        raw = row.get(column)
        if raw:
            try:
                record[extra] = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning("ignoring unparseable %s for user %s", column, row["id"])
    return record


def canonicalize_record(
    username: str,
    value: Any,
    *,
    default_role: str = "user",
) -> dict[str, Any] | None:
    """Normalise an inbound record, mirroring ``identity._canonical_record``.

    Returns ``None`` when the value cannot be a user (no hash). Unknown fields
    are preserved rather than dropped — the Phase 2 bug was dropping *known*
    fields, and silently discarding unknown ones makes the same mistake harder
    to notice.
    """
    if isinstance(value, str):
        return {
            "id": f"u_{username}",
            "hash": value,
            "role": default_role,
            "created_at": _now(),
            "disabled": False,
            "avatar": "",
            "preset": "standard",
            "must_change_password": False,
            "token_version": 0,
        }
    if not isinstance(value, dict):
        return None
    hashed = str(value.get("hash") or value.get("password_hash") or "")
    if not hashed:
        return None
    role = str(value.get("role") or default_role)
    if role not in VALID_ROLES:
        role = default_role if default_role in VALID_ROLES else "user"
    preset = str(value.get("preset") or "standard")
    if preset not in VALID_PRESETS:
        preset = "standard"
    record: dict[str, Any] = {
        "id": str(value.get("id") or username),
        "hash": hashed,
        "role": role,
        "created_at": str(value.get("created_at") or _now()),
        "disabled": _as_bool(value.get("disabled", False)),
        "avatar": str(value.get("avatar") or ""),
        "preset": preset,
        "must_change_password": _as_bool(value.get("must_change_password", False)),
        "token_version": int(value.get("token_version") or 0),
    }
    if value.get("phone"):
        record["phone"] = str(value["phone"])
    if "book_permission" in value:
        record["book_permission"] = value["book_permission"]
    if "learner_profile" in value:
        record["learner_profile"] = value["learner_profile"]
    return record


class IdentityRepository:
    """CRUD for users, keyed by the Phase 2 ``username``."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- read ---------------------------------------------------------------

    def load_users(self) -> dict[str, dict[str, Any]]:
        """Every user as ``{username: record}``.

        ``username`` is the natural key for an account whose username is unset
        (a phone-only account created outside D-005) we fall back to the phone
        number, then the id, so a row can never become invisible to the loader
        that enumerates users.
        """
        with self._db.read() as conn:
            rows = conn.query("SELECT * FROM users ORDER BY created_at ASC").rows
        users: dict[str, dict[str, Any]] = {}
        for row in rows:
            record = record_from_row(row)
            key = record.get("username") or record.get("phone") or record["id"]
            users[str(key)] = record
        return users

    def get(self, username: str) -> dict[str, Any] | None:
        with self._db.read() as conn:
            return self._get_conn(conn, username)

    def get_by_id(self, user_id: str) -> tuple[str, dict[str, Any]] | None:
        with self._db.read() as conn:
            row = conn.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        if row is None:
            return None
        record = record_from_row(row)
        key = record.get("username") or record.get("phone") or record["id"]
        return str(key), record

    def get_by_phone(self, phone: str) -> tuple[str, dict[str, Any]] | None:
        with self._db.read() as conn:
            row = conn.query_one("SELECT * FROM users WHERE phone_number = ?", (phone,))
        if row is None:
            return None
        record = record_from_row(row)
        key = record.get("username") or record.get("phone") or record["id"]
        return str(key), record

    def get_phone(self, username: str) -> str:
        record = self.get(username)
        return str(record.get("phone") or "") if record else ""

    def count(self) -> int:
        with self._db.read() as conn:
            return int(conn.scalar("SELECT COUNT(*) AS n FROM users") or 0)

    def is_first_user(self) -> bool:
        return self.count() == 0

    def list_public(self) -> list[dict[str, Any]]:
        """Records minus the password hash, for admin listings."""
        out = []
        for key, record in self.load_users().items():
            public = {k: v for k, v in record.items() if k != "hash"}
            public["username"] = key
            out.append(public)
        return out

    @staticmethod
    def _get_conn(conn: Any, username: str) -> dict[str, Any] | None:
        row = conn.query_one(
            "SELECT * FROM users WHERE username = ? OR phone_number = ? OR id = ?",
            (username, username, username),
        )
        return record_from_row(row) if row else None

    # -- write --------------------------------------------------------------

    def _upsert(self, conn: Any, username: str, record: dict[str, Any]) -> None:
        existing = conn.query_one(
            "SELECT id FROM users WHERE username = ? OR id = ?",
            (username, record["id"]),
        )
        phone = record.get("phone") or (username if _looks_like_phone(username) else None)
        payload = (
            record["hash"],
            record["role"],
            1 if record["disabled"] else 0,
            1 if record["must_change_password"] else 0,
            str(record.get("avatar") or ""),
            str(record.get("preset") or "standard"),
            int(record.get("token_version") or 0),
            str(record["created_at"]),
            _now(),
            phone,
            json.dumps(record["book_permission"], ensure_ascii=False)
            if record.get("book_permission")
            else None,
            json.dumps(record["learner_profile"], ensure_ascii=False)
            if record.get("learner_profile")
            else None,
        )
        if existing is not None:
            conn.execute(
                "UPDATE users SET password_hash = ?, role = ?, disabled = ?, "
                "must_change_password = ?, avatar = ?, preset = ?, token_version = ?, "
                "created_at = ?, updated_at = ?, phone_number = ?, "
                "book_permission = ?, learner_profile = ? WHERE id = ?",
                (*payload, str(existing["id"])),
            )
            return
        try:
            conn.execute(
                "INSERT INTO users (password_hash, role, disabled, must_change_password, "
                "avatar, preset, token_version, created_at, updated_at, phone_number, "
                "book_permission, learner_profile, id, username) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*payload, record["id"], username),
            )
        except DatabaseError as exc:
            raise IdentityRepositoryError(f"cannot create user {username!r}: {exc}") from exc

    def save(self, username: str, record: dict[str, Any]) -> None:
        canonical = canonicalize_record(username, record)
        if canonical is None:
            raise IdentityRepositoryError(f"refusing to save invalid record for {username!r}")
        with self._db.transaction() as conn:
            self._upsert(conn, username, canonical)

    def replace_all(self, users: dict[str, dict[str, Any]], *, prune: bool = False) -> int:
        """Bulk write, used by the backfill and by admin bulk operations.

        ``prune=True`` deletes users not present in *users*. Off by default: a
        partial dict should never be able to delete accounts.
        """
        written = 0
        with self._db.transaction() as conn:
            for username, record in users.items():
                canonical = canonicalize_record(username, record)
                if canonical is None:
                    logger.warning("skipping invalid record for %r", username)
                    continue
                self._upsert(conn, username, canonical)
                written += 1
            if prune:
                keep = [
                    str(r["id"]) for r in (canonicalize_record(u, v) for u, v in users.items()) if r
                ]
                if not keep:
                    conn.execute("DELETE FROM users")
                else:
                    placeholders = ", ".join("?" for _ in keep)
                    conn.execute(f"DELETE FROM users WHERE id NOT IN ({placeholders})", tuple(keep))
        return written

    def delete(self, username: str) -> bool:
        with self._db.transaction() as conn:
            row = conn.query_one(
                "SELECT id FROM users WHERE username = ? OR phone_number = ? OR id = ?",
                (username, username, username),
            )
            if row is None:
                return False
            conn.execute("DELETE FROM users WHERE id = ?", (str(row["id"]),))
        return True

    def set_password(self, username: str, hashed: str) -> bool:
        return self._patch(username, {"password_hash": hashed})

    def set_role(self, username: str, role: str) -> bool:
        if role not in VALID_ROLES:
            raise IdentityRepositoryError(f"invalid role {role!r}")
        return self._patch(username, {"role": role})

    def set_disabled(self, username: str, disabled: bool) -> bool:
        return self._patch(username, {"disabled": 1 if disabled else 0})

    def set_avatar(self, username: str, avatar: str) -> bool:
        return self._patch(username, {"avatar": avatar})

    def set_preset(self, username: str, preset: str) -> bool:
        if preset not in VALID_PRESETS:
            raise IdentityRepositoryError(f"invalid preset {preset!r}")
        return self._patch(username, {"preset": preset})

    def set_must_change_password(self, username: str, required: bool) -> bool:
        return self._patch(username, {"must_change_password": 1 if required else 0})

    def set_phone(self, username: str, phone: str) -> bool:
        """Attach a phone. Raises when the number already belongs to someone."""
        try:
            return self._patch(username, {"phone_number": phone})
        except DatabaseError as exc:
            raise IdentityRepositoryError(f"phone {phone!r} is already registered") from exc

    def set_learner_profile(
        self, username: str, profile: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        payload = json.dumps(profile, ensure_ascii=False) if profile else None
        if not self._patch(username, {"learner_profile": payload}):
            return None
        return profile

    def set_book_permission(self, username: str, permission: Any) -> bool:
        payload = json.dumps(permission, ensure_ascii=False) if permission else None
        return self._patch(username, {"book_permission": payload})

    def bump_token_version(self, username: str) -> bool:
        """Invalidate every outstanding token for this account.

        A single atomic ``token_version = token_version + 1``. Doing this as
        read-modify-write would lose one of two concurrent revocation requests,
        which is precisely when it matters (an attacker holding a session while
        the owner clicks "log out everywhere").
        """
        with self._db.transaction() as conn:
            return (
                conn.execute(
                    "UPDATE users SET token_version = token_version + 1, updated_at = ? "
                    "WHERE username = ? OR phone_number = ? OR id = ?",
                    (_now(), username, username, username),
                )
                == 1
            )

    def token_version_of(self, username: str) -> int:
        record = self.get(username)
        return int(record.get("token_version") or 0) if record else 0

    def mark_login(self, username: str) -> None:
        self._patch(username, {"last_login_at": _now()})

    def _patch(self, username: str, changes: dict[str, Any]) -> bool:
        if not changes:
            return False
        assignments = ", ".join(f"{column} = ?" for column in changes)
        params = list(changes.values()) + [_now(), username, username, username]
        with self._db.transaction() as conn:
            return (
                conn.execute(
                    f"UPDATE users SET {assignments}, updated_at = ? "
                    "WHERE username = ? OR phone_number = ? OR id = ?",
                    tuple(params),
                )
                == 1
            )

    # -- backfill -----------------------------------------------------------

    def backfill(self, users: Iterable[tuple[str, dict[str, Any]]]) -> dict[str, int]:
        """Copy a Phase 2 ``users.json`` into the table.

        Idempotent: re-running updates existing rows rather than inserting
        duplicates, and never deletes. That is the requirement for a backfill
        that can be run twice after a failed deploy.
        """
        written = skipped = 0
        with self._db.transaction() as conn:
            for username, record in users:
                canonical = canonicalize_record(str(username), record)
                if canonical is None:
                    skipped += 1
                    continue
                self._upsert(conn, str(username), canonical)
                written += 1
        return {"written": written, "skipped": skipped}


def _looks_like_phone(value: str) -> bool:
    """E.164 digits, as stored. Mirrors ``deeptutor.multi_user.phone``."""
    return value.isdigit() and 10 <= len(value) <= 15
