#!/usr/bin/env python
"""
Gap Generator - Generate knowledge gaps for student profiles

Creates realistic knowledge gaps (misconceptions, incomplete understanding,
missing knowledge) tailored to each student's profile and the subtopic's
knowledge scope.

Supports two modes:
- Scope-based: uses knowledge_scope (RAG query result)
- Page-grounded: uses content_list page content; each gap has source_pages
"""

import json
import logging

from benchmark.data_generation.llm_utils import call_llm_json, load_prompt, render_prompt

logger = logging.getLogger("benchmark.gap_generator")


async def generate_gaps(
    knowledge_scope: dict,
    student_profile: dict,
    num_gaps: int = 3,
    severity_weights: dict[str, float] | None = None,
    gap_id_offset: int = 0,
) -> list[dict]:
    """
    Generate knowledge gaps for a specific (scope, profile) pair.

    Args:
        knowledge_scope: Knowledge scope dictionary
        student_profile: Student profile dictionary
        num_gaps: Number of gaps to generate
        severity_weights: Distribution of gap types, e.g.:
            {"misconception": 0.3, "incomplete": 0.4, "missing": 0.3}

    Returns:
        List of knowledge gap dictionaries
    """
    if severity_weights is None:
        severity_weights = {"misconception": 0.3, "incomplete": 0.4, "missing": 0.3}

    profile_id = student_profile.get("profile_id", "unknown")
    logger.info(f"Generating {num_gaps} gaps for profile '{profile_id}'")

    prompt = load_prompt("generate_gaps")

    scope_text = json.dumps(knowledge_scope, ensure_ascii=False, indent=2)
    profile_text = json.dumps(student_profile, ensure_ascii=False, indent=2)

    user_prompt = render_prompt(
        prompt["user_template"],
        knowledge_scope=scope_text,
        student_profile=profile_text,
        num_gaps=num_gaps,
        misconception_weight=severity_weights.get("misconception", 0.3),
        incomplete_weight=severity_weights.get("incomplete", 0.4),
        missing_weight=severity_weights.get("missing", 0.3),
    )

    result = await call_llm_json(
        user_prompt=user_prompt,
        system_prompt=prompt["system"],
        temperature=0.7,
        max_tokens=4096,
    )

    gaps = result.get("gaps", [])

    # Ensure gap IDs are unique
    for i, gap in enumerate(gaps):
        if "gap_id" not in gap:
            gap["gap_id"] = f"gap_{profile_id}_{i + gap_id_offset:02d}"

    logger.info(f"  Generated {len(gaps)} gaps: {[g.get('type', '?') for g in gaps]}")
    return gaps


async def generate_gaps_for_profiles(
    knowledge_scope: dict,
    profiles: list[dict],
    gaps_per_profile: int = 3,
    severity_weights: dict[str, float] | None = None,
) -> dict[str, list[dict]]:
    """
    Generate gaps for multiple profiles under the same knowledge scope.

    Args:
        knowledge_scope: Knowledge scope dictionary
        profiles: List of student profile dictionaries
        gaps_per_profile: Number of gaps per profile
        severity_weights: Distribution of gap types

    Returns:
        Dictionary mapping profile_id -> list of gaps
    """
    all_gaps: dict[str, list[dict]] = {}

    for profile in profiles:
        profile_id = profile.get("profile_id", "unknown")

        try:
            gaps = await generate_gaps(
                knowledge_scope=knowledge_scope,
                student_profile=profile,
                num_gaps=gaps_per_profile,
                severity_weights=severity_weights,
            )
            all_gaps[profile_id] = gaps
        except Exception as e:
            logger.error(f"Failed to generate gaps for profile {profile_id}: {e}")
            all_gaps[profile_id] = []

    return all_gaps


def _format_page_content(page_content: dict[int, str]) -> str:
    """Format page_content dict for prompt."""
    lines = []
    for page_idx in sorted(page_content.keys()):
        text = page_content[page_idx]
        if text:
            lines.append(f"### Page {page_idx}\n{text[:3000]}{'...' if len(text) > 3000 else ''}")
    return "\n\n".join(lines) if lines else "(no content)"


async def generate_gaps_from_pages(
    page_content: dict[int, str],
    student_profile: dict,
    num_gaps: int = 3,
    severity_weights: dict[str, float] | None = None,
    gap_id_offset: int = 0,
) -> list[dict]:
    """
    Generate knowledge gaps grounded in specific page content.

    Each gap will have source_pages (list of page indices).

    Args:
        page_content: Dict mapping page_idx -> text content
        student_profile: Student profile dictionary
        num_gaps: Number of gaps to generate
        severity_weights: Distribution of gap types

    Returns:
        List of gap dicts with source_pages field
    """
    if severity_weights is None:
        severity_weights = {"misconception": 0.3, "incomplete": 0.4, "missing": 0.3}

    profile_id = student_profile.get("profile_id", "unknown")
    logger.info(f"Generating {num_gaps} page-grounded gaps for profile '{profile_id}'")

    prompt = load_prompt("generate_gaps_page")
    page_text = _format_page_content(page_content)
    profile_text = json.dumps(student_profile, ensure_ascii=False, indent=2)

    user_prompt = render_prompt(
        prompt["user_template"],
        page_content=page_text,
        student_profile=profile_text,
        num_gaps=num_gaps,
        misconception_weight=severity_weights.get("misconception", 0.3),
        incomplete_weight=severity_weights.get("incomplete", 0.4),
        missing_weight=severity_weights.get("missing", 0.3),
    )

    result = await call_llm_json(
        user_prompt=user_prompt,
        system_prompt=prompt["system"],
        temperature=0.7,
        max_tokens=4096,
    )

    gaps = result.get("gaps", [])

    for i, gap in enumerate(gaps):
        if "gap_id" not in gap:
            gap["gap_id"] = f"gap_{profile_id}_{i + gap_id_offset:02d}"
        if "source_pages" not in gap or not isinstance(gap["source_pages"], list):
            gap["source_pages"] = list(page_content.keys())[:1] if page_content else []

    logger.info(
        f"  Generated {len(gaps)} gaps: {[g.get('type', '?') for g in gaps]}, "
        f"source_pages={[g.get('source_pages', []) for g in gaps]}"
    )
    return gaps


async def generate_gaps_for_profiles_with_pages(
    page_content_by_profile: dict[str, tuple[dict[int, str], list[int]]],
    profiles: list[dict],
    gaps_per_profile: int = 3,
    severity_weights: dict[str, float] | None = None,
) -> dict[str, list[dict]]:
    """
    Generate page-grounded gaps for multiple profiles.

    Args:
        page_content_by_profile: profile_id -> (page_content dict, selected_page_indices)
        profiles: List of student profiles
        gaps_per_profile: Number of gaps per profile
        severity_weights: Gap type distribution

    Returns:
        profile_id -> list of gaps (each with source_pages)
    """
    all_gaps: dict[str, list[dict]] = {}

    for profile in profiles:
        profile_id = profile.get("profile_id", "unknown")
        pc_data = page_content_by_profile.get(profile_id)
        if not pc_data:
            logger.warning(f"No page content for profile {profile_id}, skipping")
            all_gaps[profile_id] = []
            continue

        page_content, _selected = pc_data
        try:
            gaps = await generate_gaps_from_pages(
                page_content=page_content,
                student_profile=profile,
                num_gaps=gaps_per_profile,
                severity_weights=severity_weights,
            )
            all_gaps[profile_id] = gaps
        except Exception as e:
            logger.error(f"Failed to generate gaps for profile {profile_id}: {e}")
            all_gaps[profile_id] = []

    return all_gaps
