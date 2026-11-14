"""Bounded, reviewed strategy evolution for one mastery path (Hermes-style).

Three layers feed the teaching adaptation. Layer 1 is deterministic evidence
(question kinds, reply likes, teaching observations). Layer 2 is the per-turn
judgement the tutor already makes. This module is Layer 3 — the slow loop that
turns accumulated evidence into a durable, learner-visible strategy note.

It borrows Hermes' curator invariants:

- **Evidence-gated.** A proposal needs at least a minimum number of independent
  signals; one hard turn never changes the strategy.
- **Independently reviewed.** A separate call accepts or rejects before anything
  is written, and a rejection is a normal outcome.
- **Bounded.** At most one note change per run, a small cap on notes, a short
  body. The pass never edits prompts, the playbook, or tools.
- **Reversible.** Writes go through the versioned note store, which already
  supports history and rollback.
- **Learner-owned.** Automation never touches a learner-authored or pinned note.

The proposal and review are the only model calls; everything that decides
*whether* to run, and every hard rule about what may be written, is
deterministic and testable without a model.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable

from deeptutor.learning.storage import LearningStore
from deeptutor.learning.teaching import strategy_outcomes

logger = logging.getLogger(__name__)

#: A proposal needs this many decisive results (helped/not_helped), or one plus
#: a like. Likes alone never drive a strategy note.
MIN_DECISIVE_SIGNALS = 2
#: How many agent-authored notes one path may hold. Small on purpose: a wall of
#: strategy notes is a strategy nobody reads.
MAX_STRATEGY_NOTES = 6
MAX_NOTE_BODY = 400

LLMCall = Callable[[str, str], Awaitable[str]]


async def _default_llm(prompt: str, system_prompt: str) -> str:
    from deeptutor.services.llm import get_llm_client

    return await get_llm_client().complete(prompt, system_prompt=system_prompt)


def _extract_json(text: str) -> dict[str, Any]:
    """Read one JSON object out of a model reply, tolerating prose and repairs."""
    if not text:
        return {}
    start = text.find("{")
    end = text.rfind("}")
    candidate = text[start : end + 1] if start != -1 and end != -1 else text
    try:
        import json_repair

        data = json_repair.loads(candidate)
    except Exception:  # noqa: BLE001 - a malformed reply is a rejection, not a crash
        return {}
    return data if isinstance(data, dict) else {}


def strategy_evidence(
    profile: Any,
    feedback: dict[str, Any] | None,
    notes: list[dict[str, Any]],
) -> dict[str, Any]:
    """The deterministic evidence bundle a proposal is allowed to cite.

    Only recorded results count: an ``unknown`` attempt is a hypothesis, not
    evidence, and a like is a weaker signal than a helped/not_helped result.
    """
    outcomes = strategy_outcomes(profile) if profile is not None else {"total": 0, "strategies": []}
    strategies = [row for row in outcomes.get("strategies", []) if row.get("total", 0) >= 1]
    decisive = sum(int(row.get("total") or 0) for row in strategies)
    likes = int((feedback or {}).get("count") or 0)
    gate_met = decisive >= MIN_DECISIVE_SIGNALS or (decisive >= 1 and likes >= 1)
    return {
        "strategies": strategies,
        "likes": {
            "count": likes,
            "per_knowledge_point": (feedback or {}).get("per_knowledge_point") or {},
            "recent": [
                {"knowledge_point_id": item.get("knowledge_point_id", ""), "excerpt": item.get("excerpt", "")}
                for item in (feedback or {}).get("recent", [])[:5]
            ],
        },
        "notes": [
            {
                "note_id": note.get("note_id", ""),
                "body": note.get("body", ""),
                "created_by": note.get("created_by", "agent"),
                "pinned": bool(note.get("pinned")),
            }
            for note in notes
        ],
        "gate": {
            "met": gate_met,
            "decisive_signals": decisive,
            "likes": likes,
            "requirement": f"{MIN_DECISIVE_SIGNALS} recorded results, or 1 result plus a like",
        },
    }


def _evidence_names(evidence: dict[str, Any]) -> set[str]:
    return {str(row.get("strategy") or "") for row in evidence.get("strategies", [])}


def _proposal_cites_real_evidence(proposal: dict[str, Any], evidence: dict[str, Any]) -> bool:
    cited = proposal.get("strategies")
    if cited is None:
        return True
    if not isinstance(cited, list):
        return False
    known = _evidence_names(evidence)
    return all(str(name) in known for name in cited)


def _valid_proposal(proposal: dict[str, Any], evidence: dict[str, Any]) -> tuple[bool, str]:
    """The deterministic half of the review: rules no model gets to override."""
    action = str(proposal.get("action") or "none")
    if action == "none":
        return True, ""
    if action not in {"create", "update"}:
        return False, f"unknown action {action!r}"
    body = str(proposal.get("body") or "").strip()
    if not body:
        return False, "the note body is empty"
    if len(body) > MAX_NOTE_BODY:
        return False, "the note body is too long"
    if not _proposal_cites_real_evidence(proposal, evidence):
        return False, "the proposal cites evidence that is not in the bundle"
    if action == "update":
        target = next(
            (note for note in evidence.get("notes", []) if note.get("note_id") == proposal.get("note_id")),
            None,
        )
        if target is None:
            return False, "the note to update does not exist"
        if target.get("created_by") != "agent":
            return False, "a learner-authored note is never changed by automation"
        if target.get("pinned"):
            return False, "a pinned note is not changed by automation"
    return True, ""


_PROPOSER_SYSTEM = (
    "You maintain a short, learner-visible list of teaching-strategy notes for one "
    "mastery path. A note says how THIS learner is best taught, backed by evidence. "
    "You are given the evidence and the current notes. Propose AT MOST ONE change: "
    "create a new note, update an existing agent-authored note, or do nothing. "
    "Cite only strategies that appear in the evidence. Keep a note to one or two "
    "short sentences. Never propose touching a learner-authored or pinned note. "
    "If the evidence is thin or contradictory, choose \"none\". "
    'Reply with one JSON object: {"action": "none"|"create"|"update", "note_id": "", '
    '"body": "", "strategies": ["..."], "reason": "..."}.'
)

_REVIEWER_SYSTEM = (
    "You are an independent reviewer of a proposed teaching-strategy note. You did "
    "not write the proposal and you have no stake in it. Accept only if: it cites "
    "evidence that is actually present; it does not contradict a learner-authored or "
    "pinned note; it is concrete and short; and the evidence genuinely supports it. "
    "Reject if the evidence is absent, thin, contradictory, or the note merely "
    "restates a note that already exists. A rejection is a normal, expected outcome. "
    'Reply with one JSON object: {"decision": "accept"|"reject", "reason": "..."}.'
)


def _render_evidence(evidence: dict[str, Any]) -> str:
    return json.dumps(evidence, ensure_ascii=False, indent=2)


async def propose_strategy_note(
    evidence: dict[str, Any], *, llm: LLMCall, language: str = "zh"
) -> dict[str, Any]:
    prompt = (
        f"Learner's language for the note body: {language}.\n"
        f"Evidence:\n{_render_evidence(evidence)}\n\n"
        "Propose at most one change as the specified JSON object."
    )
    raw = await llm(prompt, _PROPOSER_SYSTEM)
    return _extract_json(raw)


async def review_strategy_proposal(
    proposal: dict[str, Any], evidence: dict[str, Any], *, llm: LLMCall
) -> dict[str, Any]:
    prompt = (
        f"Proposed change:\n{json.dumps(proposal, ensure_ascii=False, indent=2)}\n\n"
        f"Evidence:\n{_render_evidence(evidence)}\n\n"
        "Accept or reject as the specified JSON object."
    )
    raw = await llm(prompt, _REVIEWER_SYSTEM)
    return _extract_json(raw)


def _apply_proposal(
    store: LearningStore, path_id: str, proposal: dict[str, Any], *, actor: str
) -> dict[str, Any]:
    action = str(proposal.get("action") or "none")
    body = str(proposal.get("body") or "").strip()
    strategies = [str(name) for name in (proposal.get("strategies") or [])]
    evidence = [{"kind": "strategy", "name": name} for name in strategies]
    note_id = str(proposal.get("note_id") or "") if action == "update" else ""
    return store.save_strategy_note(
        path_id,
        note_id,
        body,
        created_by="agent",
        evidence=evidence,
        actor=actor,
    )


async def evolve_strategy(
    path_id: str,
    *,
    store: LearningStore | None = None,
    llm: LLMCall | None = None,
    actor: str = "learner",
    language: str = "zh",
) -> dict[str, Any]:
    """Run one evidence-gated, independently-reviewed strategy-note change.

    Returns a receipt whose ``status`` is one of: ``no_path``, ``gated`` (not
    enough evidence), ``capped`` (too many notes), ``no_change``, ``rejected``
    (the reviewer or the deterministic rules refused), or ``applied``.
    """
    store = store or LearningStore()
    llm = llm or _default_llm

    progress = store.load(path_id)
    if progress is None:
        return {"status": "no_path", "path_id": path_id}

    notes = store.list_strategy_notes(path_id)
    feedback = store.reply_feedback_summary(path_id)
    evidence = strategy_evidence(getattr(progress, "learner_profile", None), feedback, notes)

    if not evidence["gate"]["met"]:
        return {
            "status": "gated",
            "path_id": path_id,
            "evidence": evidence,
            "message": "Not enough recorded evidence to propose a strategy note yet.",
        }

    agent_notes = [note for note in notes if note.get("created_by") == "agent"]
    if len(agent_notes) >= MAX_STRATEGY_NOTES:
        return {
            "status": "capped",
            "path_id": path_id,
            "evidence": evidence,
            "message": f"This path already holds {MAX_STRATEGY_NOTES} tutor notes.",
        }

    proposal = await propose_strategy_note(evidence, llm=llm, language=language)
    if str(proposal.get("action") or "none") == "none":
        return {"status": "no_change", "path_id": path_id, "proposal": proposal, "evidence": evidence}

    ok, reason = _valid_proposal(proposal, evidence)
    if not ok:
        return {
            "status": "rejected",
            "path_id": path_id,
            "proposal": proposal,
            "review": {"decision": "reject", "reason": reason},
            "evidence": evidence,
        }

    review = await review_strategy_proposal(proposal, evidence, llm=llm)
    if str(review.get("decision") or "").lower() != "accept":
        return {
            "status": "rejected",
            "path_id": path_id,
            "proposal": proposal,
            "review": review,
            "evidence": evidence,
        }

    try:
        note = _apply_proposal(store, path_id, proposal, actor=f"evolve:{actor}")
    except ValueError as exc:
        return {
            "status": "rejected",
            "path_id": path_id,
            "proposal": proposal,
            "review": {"decision": "reject", "reason": str(exc)},
            "evidence": evidence,
        }
    return {
        "status": "applied",
        "path_id": path_id,
        "note": note,
        "proposal": proposal,
        "review": review,
        "evidence": evidence,
    }
