"""Pure Deep Research recovery contracts: gates, safe checkpoints and retry lineage."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

BLOCK_EVIDENCE_MIN_CHARS = 80
REPORT_BODY_MIN_CHARS = 200
_FALLBACK_RE = re.compile(r"(?:^|\n)\s*(?:⚠|warning:|error:|\[fallback[^\]]*\]).*", re.I)
_RESEARCH_CONFIG_KEYS = frozenset({
    "confirmed_outline", "initial_subtopics", "language", "persona",
    "research_depth", "max_iterations", "reasoning_effort",
})


def evidence_text(value: str) -> str:
    return re.sub(r"\s+", "", _FALLBACK_RE.sub("", value or ""))


def block_is_substantive(value: str) -> bool:
    return len(evidence_text(value)) >= BLOCK_EVIDENCE_MIN_CHARS


def report_is_substantive(value: str) -> bool:
    lines = (value or "").splitlines()
    body: list[str] = []
    in_references = False
    for line in lines:
        plain = re.sub(r"<[^>]+>", "", line).strip()
        if re.match(r"^#{1,6}\s*(references|citations|sources|bibliography)\s*$", plain, re.I):
            in_references = True
            continue
        if in_references or line.lstrip().startswith("#"):
            continue
        # Citation-only Markdown and HTML reference-list rows are evidence
        # metadata, not a report body.
        if re.match(r"^(?:[-*+]\s*)?(?:\[\^?[^\]]+\]|\[\d+\])(?:\s*[,.;])?\s*$", plain):
            continue
        if re.match(r"^\s*<li[^>]*>.*</li>\s*$", line, re.I):
            continue
        body.append(line)
    return len(evidence_text("\n".join(body))) >= REPORT_BODY_MIN_CHARS


def checkpoint_hash(checkpoint: dict[str, Any]) -> str:
    payload = dict(checkpoint)
    payload.pop("checkpoint_hash", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def seal_checkpoint(checkpoint: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(checkpoint)
    sealed["checkpoint_hash"] = checkpoint_hash(sealed)
    return sealed


def verify_checkpoint(checkpoint: dict[str, Any]) -> bool:
    return checkpoint.get("schema_version") == 1 and checkpoint.get("checkpoint_hash") == checkpoint_hash(checkpoint)


def new_attempt_id() -> str:
    return "attempt_" + uuid.uuid4().hex


def retry_parameters_hash(
    *,
    parent_attempt_id: str,
    strategy: str,
    llm_selection: dict[str, Any] | None,
) -> str:
    """Canonical, secret-free identity for an idempotent retry request."""
    selection = llm_selection or {}
    payload = {
        "parent_attempt_id": str(parent_attempt_id),
        "strategy": str(strategy),
        "llm_selection": {
            "profile_id": str(selection.get("profile_id") or ""),
            "model_id": str(selection.get("model_id") or ""),
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def safe_research_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Persist only declared, JSON-safe research controls.

    Runtime/private carriers (notably ``_research_retry``) and provider
    credentials must never become part of a checkpoint or retry payload.
    This is deliberately shallow: nested objects are not recursively copied.
    """
    if not isinstance(config, dict):
        return {}
    return {
        key: value for key, value in config.items()
        if key in _RESEARCH_CONFIG_KEYS and not key.startswith("_")
        and isinstance(value, (str, int, float, bool, type(None), list))
    }


class ResearchTerminalError(RuntimeError):
    """A public research result has been emitted and the turn must fail once."""

    def __init__(self, result: dict[str, Any], checkpoint: dict[str, Any]):
        failure = result.get("metadata", {}).get("failure") or {}
        super().__init__(str(failure.get("summary") or "Research failed."))
        self.result = result
        self.checkpoint = checkpoint
        self.failure = failure


def retry_budget(current: int, limit: int | None) -> int | None:
    """One permitted output-budget escalation; None means no legal retry."""
    ceiling = int(limit or 0)
    if ceiling <= current:
        return None
    return min(current * 2, ceiling)


def backoff_delays(attempts: int = 2) -> tuple[float, ...]:
    """Bounded deterministic delays; callers inject sleep in tests."""
    return tuple(min(2.0**index, 4.0) for index in range(max(0, min(attempts, 3))))


__all__ = ["BLOCK_EVIDENCE_MIN_CHARS", "REPORT_BODY_MIN_CHARS", "block_is_substantive", "report_is_substantive", "seal_checkpoint", "verify_checkpoint", "new_attempt_id", "retry_parameters_hash", "safe_research_config", "ResearchTerminalError", "retry_budget", "backoff_delays"]
