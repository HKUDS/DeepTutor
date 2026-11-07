#!/usr/bin/env python
"""
Task Generator - Generate learning tasks for a profile's knowledge gaps

Creates natural learning tasks that, when pursued in conversation with a tutor,
will organically expose one or more of the student's knowledge gaps.
Each task may target one or multiple gaps — the LLM decides.

When using generate_tasks_with_partition(), each gap is assigned to exactly one task:
gaps are removed from the pool after each task is generated (hardcoded partition).
"""

import json
import logging

from benchmark.data_generation.llm_utils import call_llm_json, load_prompt, render_prompt

logger = logging.getLogger("benchmark.task_generator")
MIN_GAPS_PER_TASK = 3


def _normalize_task_id(task: dict, task_index: int) -> str:
    """
    Build a deterministic task_id from generation index.

    We preserve a simple prefix signal from model output (e.g. task_reflect),
    but always rewrite the numeric suffix so IDs are unique within a profile.
    """
    raw_id = str(task.get("task_id", "") or "")
    prefix = "task_reflect" if raw_id.startswith("task_reflect") else "task"
    return f"{prefix}_{task_index + 1:03d}"


def _build_default_gap_pacing_plan(target_gaps: list[str]) -> list[dict]:
    """
    Build a deterministic staged gap exposure plan.

    Rule of thumb:
    - first gap: turns 1-2
    - second gap: turns 3-4
    - third gap: turns 5-6
    """
    plan = []
    for idx, gid in enumerate(target_gaps):
        start_turn = idx * 2 + 1
        plan.append(
            {
                "gap_id": gid,
                "turn_window": f"{start_turn}-{start_turn + 1}",
                "trigger": "Reveal only when current confusion is partly addressed.",
            }
        )
    return plan


def _normalize_gap_pacing_plan(task: dict, target_gaps: list[str]) -> list[dict]:
    """
    Normalize LLM-provided gap_pacing_plan; fall back to default if malformed.
    """
    raw = task.get("gap_pacing_plan", [])
    if not isinstance(raw, list):
        return _build_default_gap_pacing_plan(target_gaps)

    valid_set = set(target_gaps)
    normalized = []
    used = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        gid = item.get("gap_id")
        if gid in valid_set and gid not in used:
            normalized.append(
                {
                    "gap_id": gid,
                    "turn_window": str(item.get("turn_window", "")) or "later",
                    "trigger": str(item.get("trigger", "")) or "Reveal progressively.",
                }
            )
            used.add(gid)

    # Ensure all target gaps appear exactly once in plan
    if len(normalized) != len(target_gaps):
        return _build_default_gap_pacing_plan(target_gaps)
    return normalized


async def generate_tasks(
    knowledge_scope: dict,
    student_profile: dict,
    knowledge_gaps: list[dict],
    num_tasks: int = 2,
) -> list[dict]:
    """
    Generate learning tasks for a (profile, gaps) combination.

    The LLM receives all gaps and decides which gaps each task targets.
    Each task specifies its target_gaps (list of gap_ids).

    Args:
        knowledge_scope: Knowledge scope dictionary
        student_profile: Student profile dictionary
        knowledge_gaps: All knowledge gap dictionaries for this profile
        num_tasks: Number of tasks to generate

    Returns:
        List of task dictionaries, each with a 'target_gaps' field
    """
    profile_id = student_profile.get("profile_id", "unknown")
    logger.info(f"Generating {num_tasks} tasks for profile '{profile_id}' ({len(knowledge_gaps)} gaps)")

    prompt = load_prompt("generate_tasks")

    scope_text = json.dumps(knowledge_scope, ensure_ascii=False, indent=2)
    profile_text = json.dumps(student_profile, ensure_ascii=False, indent=2)
    gaps_text = json.dumps(knowledge_gaps, ensure_ascii=False, indent=2)

    user_prompt = render_prompt(
        prompt["user_template"],
        knowledge_scope=scope_text,
        student_profile=profile_text,
        knowledge_gaps=gaps_text,
        num_tasks=num_tasks,
    )

    result = await call_llm_json(
        user_prompt=user_prompt,
        system_prompt=prompt["system"],
        temperature=0.7,
        max_tokens=4096,
    )

    tasks = result.get("tasks", [])

    # If the LLM returned a single task object instead of a list, wrap it
    if not isinstance(tasks, list):
        tasks = [result] if "task_id" in result or "title" in result else []

    # Ensure task IDs and validate target_gaps
    gap_ids = {g.get("gap_id") for g in knowledge_gaps}
    for i, task in enumerate(tasks):
        task["task_id"] = _normalize_task_id(task, i)

        # Ensure target_gaps is a list of valid gap_ids
        target = task.get("target_gaps", [])
        if isinstance(target, str):
            target = [target]
        task["target_gaps"] = [gid for gid in target if gid in gap_ids]

        if not task["target_gaps"]:
            logger.warning(f"  Task {task['task_id']} has no valid target_gaps")

    logger.info(f"  Generated {len(tasks)} tasks: {[t.get('type', '?') for t in tasks]}")
    return tasks


async def generate_single_task(
    knowledge_scope: dict,
    student_profile: dict,
    available_gaps: list[dict],
    task_index: int = 0,
) -> dict | None:
    """
    Generate a single task from the available (remaining) gaps.

    Used for iterative partition: each call consumes some gaps; the caller
    removes them from the pool before the next call.

    Args:
        knowledge_scope: Knowledge scope dictionary
        student_profile: Student profile dictionary
        available_gaps: Gaps not yet assigned to any task
        task_index: 0-based index for task_id

    Returns:
        Task dict with target_gaps, or None if no gaps available
    """
    if not available_gaps:
        return None
    if len(available_gaps) < MIN_GAPS_PER_TASK:
        logger.warning(
            "Insufficient available gaps for one task: need >= %d, got %d",
            MIN_GAPS_PER_TASK,
            len(available_gaps),
        )
        return None

    profile_id = student_profile.get("profile_id", "unknown")
    ordered_gap_ids = [g.get("gap_id") for g in available_gaps if g.get("gap_id")]
    gap_ids = set(ordered_gap_ids)
    logger.info(
        f"Generating task {task_index + 1} for profile '{profile_id}' "
        f"({len(available_gaps)} gaps available)"
    )

    prompt = load_prompt("generate_task_single")
    scope_text = json.dumps(knowledge_scope, ensure_ascii=False, indent=2)
    profile_text = json.dumps(student_profile, ensure_ascii=False, indent=2)
    gaps_text = json.dumps(available_gaps, ensure_ascii=False, indent=2)

    user_prompt = render_prompt(
        prompt["user_template"],
        knowledge_scope=scope_text,
        student_profile=profile_text,
        available_gaps=gaps_text,
    )

    result = await call_llm_json(
        user_prompt=user_prompt,
        system_prompt=prompt["system"],
        temperature=0.7,
        max_tokens=2048,
    )

    task = result if isinstance(result, dict) else {}
    task["task_id"] = _normalize_task_id(task, task_index)

    target = task.get("target_gaps", [])
    if isinstance(target, str):
        target = [target]

    # Keep only valid IDs, deduplicated, preserving order.
    seen = set()
    normalized = []
    for gid in target:
        if gid in gap_ids and gid not in seen:
            normalized.append(gid)
            seen.add(gid)

    # Hard constraint: each task must include at least MIN_GAPS_PER_TASK non-overlapping gaps.
    if len(normalized) < MIN_GAPS_PER_TASK:
        for gid in ordered_gap_ids:
            if gid not in seen:
                normalized.append(gid)
                seen.add(gid)
            if len(normalized) >= MIN_GAPS_PER_TASK:
                break

    if len(normalized) < MIN_GAPS_PER_TASK:
        logger.warning(
            "  Task %s has only %d target gaps (<%d), dropping",
            task["task_id"],
            len(normalized),
            MIN_GAPS_PER_TASK,
        )
        return None

    task["target_gaps"] = normalized
    task.pop("gap_pacing_plan", None)
    task["primary_gap"] = normalized[0]

    logger.info(f"  Task targets gaps: {task['target_gaps']}")
    return task


async def generate_tasks_with_partition(
    knowledge_scope: dict,
    student_profile: dict,
    knowledge_gaps: list[dict],
    task_index_offset: int = 0,
) -> list[dict]:
    """
    Generate tasks by iteratively partitioning gaps. Each gap is assigned to
    exactly one task: after each task is generated, its target_gaps are removed
    from the pool for the next task.

    Args:
        knowledge_scope: Knowledge scope dictionary
        student_profile: Student profile dictionary
        knowledge_gaps: All knowledge gaps for this profile
        task_index_offset: Offset for task_id (e.g. when generating multiple batches)

    Returns:
        List of task dicts; union of target_gaps equals all gap_ids, no overlap
    """
    tasks: list[dict] = []
    remaining = list(knowledge_gaps)
    task_index = task_index_offset

    while len(remaining) >= MIN_GAPS_PER_TASK:
        task = await generate_single_task(
            knowledge_scope=knowledge_scope,
            student_profile=student_profile,
            available_gaps=remaining,
            task_index=task_index,
        )
        if not task or len(task.get("target_gaps", [])) < MIN_GAPS_PER_TASK:
            break

        tasks.append(task)
        assigned_ids = set(task["target_gaps"])
        remaining = [g for g in remaining if g.get("gap_id") not in assigned_ids]
        task_index += 1

    if remaining:
        logger.info(
            "  Partition complete: %d tasks, %d leftover gaps dropped (<%d required per task)",
            len(tasks),
            len(remaining),
            MIN_GAPS_PER_TASK,
        )
    else:
        logger.info(f"  Partition complete: {len(tasks)} tasks, all gaps assigned")
    return tasks


def _format_source_for_rejection(page_content: dict[int, str], page_indices: list[int]) -> str:
    """Format source content for rejection sampling (only relevant pages)."""
    lines = []
    for p in sorted(set(page_indices) & set(page_content.keys())):
        text = page_content.get(p, "")
        if text:
            lines.append(f"### Page {p}\n{text[:2500]}{'...' if len(text) > 2500 else ''}")
    return "\n\n".join(lines) if lines else "(no content)"


async def batch_rejection_sample_tasks(
    tasks: list[dict],
    gap_by_id: dict[str, dict],
    page_content: dict[int, str],
) -> tuple[list[dict], list[dict]]:
    """
    Batch rejection sampling: verify each task + gaps align with source content.

    Args:
        tasks: List of task dicts with target_gaps
        gap_by_id: Mapping gap_id -> gap dict
        page_content: page_idx -> text

    Returns:
        (accepted_tasks, rejected_tasks)
    """
    if not tasks or not page_content:
        return tasks

    # Collect all source pages used by any task
    all_page_indices = []
    for task in tasks:
        for gid in task.get("target_gaps", []):
            gap = gap_by_id.get(gid, {})
            all_page_indices.extend(gap.get("source_pages", []))

    source_text = _format_source_for_rejection(page_content, all_page_indices)

    # Build tasks_with_gaps: each task + its full gap objects
    tasks_with_gaps_list = []
    for task in tasks:
        target_gaps = [
            gap_by_id.get(gid, {"gap_id": gid})
            for gid in task.get("target_gaps", [])
            if gid in gap_by_id
        ]
        tasks_with_gaps_list.append({
            "task": task,
            "gaps": target_gaps,
        })

    tasks_text = json.dumps(tasks_with_gaps_list, ensure_ascii=False, indent=2)

    prompt = load_prompt("reject_task_batch")
    user_prompt = prompt["user_template"].format(
        source_content=source_text,
        tasks_with_gaps=tasks_text,
    )

    try:
        result = await call_llm_json(
            user_prompt=user_prompt,
            system_prompt=prompt["system"],
            temperature=0.1,
            max_tokens=2048,
        )
    except Exception as e:
        logger.warning(f"Rejection sampling failed: {e}, accepting all tasks")
        return tasks, []

    results = result.get("results", [])
    if not isinstance(results, list):
        logger.warning("Rejection result malformed, accepting all tasks")
        return tasks, []

    accepted_ids = {r["task_id"] for r in results if r.get("accepted") is True}
    accepted = [t for t in tasks if t.get("task_id") in accepted_ids]
    rejected = [t for t in tasks if t.get("task_id") not in accepted_ids]
    if rejected:
        for r in results:
            if not r.get("accepted"):
                logger.info(f"  Rejected task {r.get('task_id')}: {r.get('reason', '?')}")

    return accepted, rejected


async def generate_tasks_with_partition_and_rejection(
    knowledge_scope: dict,
    student_profile: dict,
    knowledge_gaps: list[dict],
    page_content: dict[int, str],
    max_retries: int = 2,
    task_index_offset: int = 0,
) -> list[dict]:
    """
    Generate tasks with partition, then batch rejection sampling with retry.

    Flow: 10 pages → gaps → tasks (partition). For each task, verify alignment with source.
    Rejected tasks are regenerated (same gaps, new task) and re-checked.

    Args:
        knowledge_scope: Knowledge scope
        student_profile: Student profile
        knowledge_gaps: All gaps (with source_pages)
        page_content: page_idx -> text for rejection check
        max_retries: Max regeneration attempts for rejected tasks

    Returns:
        List of accepted tasks only
    """
    tasks = await generate_tasks_with_partition(
        knowledge_scope=knowledge_scope,
        student_profile=student_profile,
        knowledge_gaps=knowledge_gaps,
        task_index_offset=task_index_offset,
    )
    gap_by_id = {g["gap_id"]: g for g in knowledge_gaps if "gap_id" in g}

    if not page_content:
        return tasks

    all_accepted = []
    to_process = list(tasks)
    retry_count = 0

    while to_process and retry_count <= max_retries:
        accepted, rejected = await batch_rejection_sample_tasks(
            tasks=to_process,
            gap_by_id=gap_by_id,
            page_content=page_content,
        )
        all_accepted.extend(accepted)

        if not rejected:
            break

        logger.info(f"  Regenerating {len(rejected)} rejected tasks (retry {retry_count + 1})")
        to_process = []
        for old_task in rejected:
            gap_ids = old_task.get("target_gaps", [])
            remaining = [gap_by_id[gid] for gid in gap_ids if gid in gap_by_id]
            if not remaining:
                continue
            new_task = await generate_single_task(
                knowledge_scope=knowledge_scope,
                student_profile=student_profile,
                available_gaps=remaining,
                task_index=task_index_offset + len(all_accepted) + len(to_process),
            )
            if new_task:
                to_process.append(new_task)

        retry_count += 1

    if to_process and retry_count > max_retries:
        logger.warning(f"  {len(to_process)} tasks still rejected after {max_retries} retries, accepting them")
        all_accepted.extend(to_process)

    return all_accepted
