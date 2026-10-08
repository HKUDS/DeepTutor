"""Decide whether a placed step continues the worked solution.

A placement is correct only when it is the correct step at that index and
every earlier slot is already the correct step. The expected id is never
returned to the caller.
"""

from __future__ import annotations


def placement_accepted(correct_ids: list[str], placed_ids: list[str], step_id: str, index: int) -> bool:
    if index < 0 or index > len(placed_ids):
        return False
    if index >= len(correct_ids):
        return False
    if correct_ids[index] != step_id:
        return False
    return placed_ids[:index] == correct_ids[:index]


def sequence_complete(correct_ids: list[str], placed_ids: list[str]) -> bool:
    return bool(correct_ids) and placed_ids == correct_ids
