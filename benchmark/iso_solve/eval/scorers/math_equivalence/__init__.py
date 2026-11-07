from __future__ import annotations


def is_equiv(a: str | None, b: str | None) -> bool:
    """Lightweight fallback equivalence check.

    The old benchmark used an external math_equivalence package. The unified
    runner is LLM-first, so this function is only used as a deterministic
    fallback when needed.
    """
    if a is None or b is None:
        return False
    return a.strip().lower() == b.strip().lower()
