"""Transactional help receipts attached to the account's current Reading quiz."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Literal


class QuizHelpConflict(ValueError):
    """The question or idempotent help request is no longer usable."""


def update_help(
    conn: sqlite3.Connection,
    material_id: str,
    locator: int,
    question_id: str,
    request_id: str,
    fingerprint: str,
    token: str,
    operation: Literal["claim", "complete", "abort"],
    result: dict[str, Any] | None,
    lease_seconds: float,
    help_kind: str,
) -> dict[str, Any] | None:
    """Serialize across processes; never replace sibling questions or old attempts.

    Receipts live only as long as the pending quiz. A crashed request can be
    retried after its lease; the old worker cannot finish a replacement claim.
    """
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT question_json FROM reading_quiz_pending "
        "WHERE material_id = ? AND locator = ? AND question_id = ?",
        (material_id, locator, question_id),
    ).fetchone()
    if row is None:
        if operation == "abort":
            return None
        raise QuizHelpConflict("This reading quiz has expired.")
    question = json.loads(row["question_json"])
    receipts = question.setdefault("_help_requests", {})
    receipt = receipts.get(request_id)
    now = time.time()
    if operation == "claim":
        if receipt is not None:
            if receipt["fingerprint"] != fingerprint:
                raise QuizHelpConflict("This help request was already used for different content.")
            if receipt["state"] == "complete":
                return receipt["result"]
            if receipt["state"] == "pending" and receipt["expires_at"] > now:
                raise QuizHelpConflict("This help request is still running. Retry shortly.")
        elif len(receipts) >= 50:
            raise QuizHelpConflict("This question has reached its help request limit.")
        receipts[request_id] = {
            "fingerprint": fingerprint,
            "help_kind": help_kind,
            "token": token,
            "state": "pending",
            "expires_at": now + lease_seconds,
        }
    elif operation == "complete":
        if (
            receipt is None
            or receipt["token"] != token
            or receipt["state"] != "pending"
            or receipt["expires_at"] <= now
        ):
            raise QuizHelpConflict("This help request has expired. Retry the request.")
        if result is None:
            raise ValueError("A completed help request requires a result.")
        # Bound durable per-question receipts, including unusually large plugins.
        if len(json.dumps(result).encode("utf-8")) > 262_144:
            raise ValueError("The help result is too large to record.")
        question["_help_count"] = int(question.get("_help_count", 0)) + 1
        result = {
            **result,
            "quiz_help": {
                "question_id": question_id,
                "hints_used": question["_help_count"],
            },
        }
        receipt.update(state="complete", result=result)
        # Keep evidence even if the learner regenerates before answering. The
        # compact event excludes answer keys, selections and model responses.
        conn.execute(
            "INSERT INTO reading_quiz_help_events "
            "(material_id, locator, question_id, request_id, help_kind, question, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                material_id,
                locator,
                question_id,
                request_id,
                receipt["help_kind"],
                str(question.get("prompt") or "")[:10000],
                now,
            ),
        )
    elif operation == "abort":
        if receipt is None or receipt["token"] != token or receipt["state"] != "pending":
            return None
        receipt["state"] = "failed"
    else:
        raise ValueError("Unknown help operation.")
    conn.execute(
        "UPDATE reading_quiz_pending SET question_json = ? "
        "WHERE material_id = ? AND locator = ? AND question_id = ?",
        (json.dumps(question, ensure_ascii=False), material_id, locator, question_id),
    )
    conn.commit()
    return result if operation == "complete" else None
