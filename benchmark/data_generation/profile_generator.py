#!/usr/bin/env python
"""
Profile Generator - Generate realistic student profiles

Creates diverse student profiles with varying backgrounds, knowledge states,
and personalities based on a knowledge scope description.
"""

import json
import logging

from benchmark.data_generation.llm_utils import call_llm_json, load_prompt, render_prompt

logger = logging.getLogger("benchmark.profile_generator")


async def generate_profile(
    knowledge_scope: dict,
    background_type: str = "intermediate",
    profile_id: str | None = None,
) -> dict:
    """
    Generate a single student profile for a given knowledge scope.

    Args:
        knowledge_scope: Knowledge scope dictionary (from scope_generator)
        background_type: One of "beginner", "intermediate", "advanced"
        profile_id: Optional specific profile ID

    Returns:
        Student profile dictionary with fields:
        - profile_id
        - education_background (single string)
        - learning_purpose
        - knowledge_state: {known_well, partially_known, unknown}
        - personality (single paragraph)
        - source_kb
    """
    kb_name = knowledge_scope.get("source_kb", "unknown")
    logger.info(f"Generating {background_type} profile for KB: {kb_name}")

    prompt = load_prompt("generate_profile")

    # Format knowledge scope as readable text
    scope_text = json.dumps(knowledge_scope, ensure_ascii=False, indent=2)

    user_prompt = render_prompt(
        prompt["user_template"],
        knowledge_scope=scope_text,
        background_type=background_type,
    )

    result = await call_llm_json(
        user_prompt=user_prompt,
        system_prompt=prompt["system"],
        temperature=0.7,
        max_tokens=4096,
    )

    # Ensure fields are set
    if profile_id:
        result["profile_id"] = profile_id
    elif "profile_id" not in result:
        result["profile_id"] = f"profile_{background_type}"

    result["source_kb"] = kb_name

    return result


async def generate_profiles_for_kb(
    knowledge_scope: dict,
    background_types: list[str] | None = None,
    profiles_per_kb: int = 3,
) -> list[dict]:
    """
    Generate multiple student profiles for a knowledge scope.

    Distributes profiles across background types. For example, with
    profiles_per_kb=3 and types=["beginner","intermediate","advanced"],
    generates one of each type.

    Args:
        knowledge_scope: Knowledge scope dictionary
        background_types: List of background types
        profiles_per_kb: Total number of profiles to generate

    Returns:
        List of student profile dictionaries
    """
    if background_types is None:
        background_types = ["beginner", "intermediate", "advanced"]

    kb_name = knowledge_scope.get("source_kb", "unknown")
    profiles = []

    for i in range(profiles_per_kb):
        bg_type = background_types[i % len(background_types)]
        pid = f"{kb_name}_{bg_type}_{i:02d}"

        try:
            profile = await generate_profile(
                knowledge_scope=knowledge_scope,
                background_type=bg_type,
                profile_id=pid,
            )
            profiles.append(profile)
            logger.info(f"  ✓ Profile: {profile.get('profile_id', pid)}")
        except Exception as e:
            logger.error(f"  ✗ Failed to generate profile {pid}: {e}")

    return profiles
