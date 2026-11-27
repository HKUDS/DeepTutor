"""Exact outline preview differences, independent of model summaries."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deeptutor.learning.models import LearningModule, LearningProgress


def reorder_modules(modules: list[LearningModule], module_order: list[str]) -> list[LearningModule]:
    """Reorder an existing module set without changing objective identity or content."""
    known = {module.id: module for module in modules}
    if (
        not isinstance(module_order, list)
        or not all(isinstance(module_id, str) and module_id for module_id in module_order)
        or len(module_order) != len(known)
        or len(set(module_order)) != len(module_order)
        or set(module_order) != set(known)
        or len(known) != len(modules)
    ):
        raise ValueError(
            "module_order must contain every existing module ID exactly once, "
            "with no omitted, duplicate, or foreign IDs."
        )
    return [
        known[module_id].model_copy(deep=True, update={"order": index})
        for index, module_id in enumerate(module_order)
    ]


def state_digest(progress: LearningProgress) -> str:
    state = progress.model_dump(mode="json", exclude={"version", "updated_at"})
    return hashlib.sha256(
        json.dumps(state, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def exact_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """JSON-pointer changes with exact old/new values, including additions/removals."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            pointer = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
            if key in before and key in after:
                changes.extend(exact_diff(before[key], after[key], pointer))
            else:
                changes.append(
                    {
                        "path": pointer,
                        "before_exists": key in before,
                        "after_exists": key in after,
                        "before": before.get(key),
                        "after": after.get(key),
                    }
                )
        return changes
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [
            change
            for i, (a, b) in enumerate(zip(before, after))
            for change in exact_diff(a, b, f"{path}/{i}")
        ]
    if type(before) is type(after) and before == after:
        return []
    return [
        {
            "path": path,
            "before_exists": True,
            "after_exists": True,
            "before": before,
            "after": after,
        }
    ]
