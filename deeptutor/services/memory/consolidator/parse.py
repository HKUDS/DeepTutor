"""Tolerant JSON parsers shared across the consolidator.

Two shapes are supported:

* :func:`parse_action` — one-action-per-turn envelope used by the
  agentic loop driver. Returns ``None`` on failure so the loop can
  surface a retry hint instead of crashing.
* :func:`_parse_ops_response` — legacy ``{"ops": [...]}`` shape, kept
  because the workbench's preview → apply flow round-trips ops
  through this parser (see :mod:`deeptutor.services.memory.store`).

Both strip code fences and tolerate prose framing so the model can
think out loud without invalidating the run.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

from deeptutor.services.memory.ops import AddOp, DeleteOp, EditOp, Op

logger = logging.getLogger(__name__)


# ── Loop-mode action envelope ────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedAction:
    name: str
    args: dict[str, Any]
    thought: str = ""

    def arg(self, key: str, default: Any = None) -> Any:
        return self.args.get(key, default)


def parse_action(raw: str) -> ParsedAction | None:
    """Parse one ``{"thought","action","args"}`` envelope from LLM text.

    Returns ``None`` on any malformed input; the loop driver renders a
    correction hint to the next turn so the model can self-recover.
    """
    snippet = _extract_json_object(raw)
    if snippet is None:
        return None
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    name_raw = data.get("action")
    if not isinstance(name_raw, str) or not name_raw.strip():
        return None
    args_raw = data.get("args")
    args: dict[str, Any] = args_raw if isinstance(args_raw, dict) else {}
    thought_raw = data.get("thought")
    thought = thought_raw.strip() if isinstance(thought_raw, str) else ""
    return ParsedAction(name=name_raw.strip(), args=args, thought=thought)


# ── Legacy ops-array shape (kept for apply_ops_payload) ──────────────────


def _parse_ops_response(raw: str) -> list[Op]:
    """Tolerant parse of a legacy ``{"ops":[...]}`` envelope into ``Op``."""
    snippet = _extract_json_object(raw)
    if snippet is None:
        logger.warning("memory consolidate: no JSON object in payload")
        return []
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError:
        logger.warning("memory consolidate: malformed JSON in payload")
        return []
    if not isinstance(data, dict):
        return []
    ops_raw = data.get("ops")
    if not isinstance(ops_raw, list):
        return []

    ops: list[Op] = []
    for raw_op in ops_raw:
        op = _parse_one_op(raw_op)
        if op is not None:
            ops.append(op)
    return ops


def _parse_one_op(raw_op: Any) -> Op | None:
    if not isinstance(raw_op, dict):
        return None
    kind = raw_op.get("op")
    try:
        if kind == "add":
            return AddOp(
                section=str(raw_op.get("section", "")).strip(),
                text=str(raw_op.get("text", "")).strip(),
                refs=[str(r) for r in raw_op.get("refs", []) if r],
            )
        if kind == "edit":
            return EditOp(
                target_id=str(raw_op.get("target_id", "")).strip(),
                new_text=str(raw_op.get("new_text", "")).strip(),
                new_refs=[str(r) for r in raw_op.get("new_refs", []) if r],
            )
        if kind == "delete":
            return DeleteOp(
                target_id=str(raw_op.get("target_id", "")).strip(),
                reason=str(raw_op.get("reason", "stale")).strip(),
            )
    except Exception:  # noqa: BLE001 — be permissive at the parse layer
        return None
    return None


# ── Shared text extraction ───────────────────────────────────────────────


def _extract_json_object(raw: str) -> str | None:
    """Strip code fences and pull out the first top-level JSON object."""
    text = raw.strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
