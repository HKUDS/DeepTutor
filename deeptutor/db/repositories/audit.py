"""Append-only audit trail.

``deeptutor.multi_user.audit`` already writes an append-only JSON file. This
table is the durable replacement, with one property the file store cannot give:
deletion is not offered by the interface, and the table has no ``DELETE`` path
in any repository. An auditor can therefore rely on absence of a route meaning
absence of a capability, rather than absence of a *current* code path.

The Phase 2 rule "no raw secret in DB/log/trace" applies here more than
anywhere: :func:`redact` is applied to ``detail`` on the way in, so an OTP code
or a password accidentally passed as audit detail cannot become a permanent
record.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any
import uuid

from deeptutor.db.connection import Database

logger = logging.getLogger(__name__)

#: Field names whose values must never be persisted, matched case-insensitively.
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "password_hash",
        "hash",
        "code",
        "otp",
        "otp_code",
        "token",
        "access_token",
        "refresh_token",
        "secret",
        "authorization",
        "cookie",
        "api_key",
        "phone",
        "phone_number",
    }
)

_PHONE_RE = re.compile(r"\b(\d{4})\d{4,9}(\d{2})\b")
_REDACTED = "***"


def redact(detail: Any) -> Any:
    """Strip secrets and mask phone numbers from an audit detail payload."""
    if detail is None:
        return None
    if isinstance(detail, str):
        return _PHONE_RE.sub(r"\1***\2", detail)
    if isinstance(detail, dict):
        return {
            key: (_REDACTED if str(key).lower() in SENSITIVE_KEYS else redact(value))
            for key, value in detail.items()
        }
    if isinstance(detail, (list, tuple)):
        return [redact(item) for item in detail]
    return detail


class AuditRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        action: str,
        *,
        actor_id: str | None = None,
        actor_label: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        outcome: str = "ok",
        detail: Any = None,
        ip_address: str | None = None,
    ) -> str:
        event_id = f"aud_{uuid.uuid4().hex}"
        payload = redact(detail)
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_events (id, actor_id, actor_label, action, target_type, "
                "target_id, outcome, detail, ip_address, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    actor_id,
                    actor_label,
                    action,
                    target_type,
                    target_id,
                    outcome,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    ip_address,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return event_id

    def list_events(
        self,
        *,
        action: str | None = None,
        actor_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if action:
            clauses.append("action = ?")
            params.append(action)
        if actor_id:
            clauses.append("actor_id = ?")
            params.append(actor_id)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        params.extend([limit, offset])
        with self._db.read() as conn:
            rows = conn.query(
                f"SELECT * FROM audit_events {where}ORDER BY created_at DESC LIMIT ? OFFSET ?",
                tuple(params),
            ).rows
        for row in rows:
            if row.get("detail"):
                try:
                    row["detail"] = json.loads(row["detail"])
                except (TypeError, ValueError):
                    pass
        return rows

    def count(self) -> int:
        with self._db.read() as conn:
            return int(conn.scalar("SELECT COUNT(*) AS n FROM audit_events") or 0)
