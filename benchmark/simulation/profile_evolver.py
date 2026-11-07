"""
Profile Evolver - Update student profile after a session

When a session completes, the addressed gaps are considered "resolved".
This module updates the profile for the next session:
- Moves resolved concepts from unknown/partially_known to known_well
- Removes resolved gaps from the gaps list (for beliefs)
"""

import copy
import logging
from typing import Any

logger = logging.getLogger("benchmark.profile_evolver")


def evolve_profile(profile: dict, resolved_gaps: list[dict]) -> dict:
    """
    Create an updated profile after resolving the given gaps.

    For each resolved gap:
    - Add target_concept (or correct_understanding summary) to known_well
    - Remove from unknown and partially_known if present

    Args:
        profile: Original profile dict (will be deep-copied)
        resolved_gaps: List of gap dicts that were addressed in the session

    Returns:
        New profile dict with updated knowledge_state
    """
    if not resolved_gaps:
        return copy.deepcopy(profile)

    new_profile = copy.deepcopy(profile)
    ks = new_profile.get("knowledge_state", {})
    known_well = list(ks.get("known_well", []))
    partially_known = list(ks.get("partially_known", []))
    unknown = list(ks.get("unknown", []))

    for gap in resolved_gaps:
        concept = gap.get("target_concept", "")
        if not concept:
            continue

        # Add to known_well (student learned this)
        if concept not in known_well:
            known_well.append(concept)

        # Remove from partially_known and unknown
        if concept in partially_known:
            partially_known.remove(concept)
        if concept in unknown:
            unknown.remove(concept)

    new_profile["knowledge_state"] = {
        "known_well": known_well,
        "partially_known": partially_known,
        "unknown": unknown,
    }

    logger.debug(
        "Evolved profile: +%d known_well, resolved %d gaps",
        len(known_well) - len(ks.get("known_well", [])),
        len(resolved_gaps),
    )
    return new_profile


def evolve_entry(
    entry: dict,
    resolved_gaps: list[dict],
    prior_sessions_summary: str | None = None,
) -> dict:
    """
    Create an entry for the next session with evolved profile and remaining gaps.

    Args:
        entry: Base entry (from previous session or template)
        resolved_gaps: Gaps addressed in the completed session
        prior_sessions_summary: Optional summary of prior sessions for context

    Returns:
        New entry with evolved profile; gaps exclude resolved ones
    """
    new_entry = copy.deepcopy(entry)
    resolved_ids = {g.get("gap_id") for g in resolved_gaps}

    # Evolve profile
    new_entry["profile"] = evolve_profile(
        entry.get("profile", {}),
        resolved_gaps,
    )

    # Remove resolved gaps from entry's gaps list
    remaining_gaps = [g for g in entry.get("gaps", []) if g.get("gap_id") not in resolved_ids]
    new_entry["gaps"] = remaining_gaps

    if prior_sessions_summary:
        new_entry["prior_sessions_summary"] = prior_sessions_summary

    return new_entry
