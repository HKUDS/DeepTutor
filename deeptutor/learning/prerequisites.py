"""Lightweight, cycle-safe prerequisite links between knowledge points.

Prerequisite ids are explicit metadata on ``KnowledgePoint``. Module order is
never treated as a graph: that would mark every later objective as dependent
and incorrectly boost (or appear to block) learning. Back-edges are ignored
so a cycle cannot recurse forever.
"""

from __future__ import annotations

from collections.abc import Iterator

from deeptutor.learning.misconceptions import has_active_misconception
from deeptutor.learning.models import KnowledgePoint, LearningModule, LearningProgress

REASON_WEAK_PREREQUISITE = "weak_prerequisite"
WEAK_MASTERY_THRESHOLD = 0.5


def knowledge_points_by_id(progress: LearningProgress) -> dict[str, KnowledgePoint]:
    return {kp.id: kp for module in progress.modules for kp in module.knowledge_points}


def iter_prerequisites(
    progress: LearningProgress,
    kp_id: str,
    *,
    _visiting: set[str] | None = None,
    _emitted: set[str] | None = None,
) -> Iterator[str]:
    """Yield reachable prerequisite ids, skipping back-edges and duplicates."""
    visiting = _visiting if _visiting is not None else set()
    emitted = _emitted if _emitted is not None else set()
    if kp_id in visiting:
        return
    visiting.add(kp_id)
    index = knowledge_points_by_id(progress)
    kp = index.get(kp_id)
    if kp is None:
        visiting.remove(kp_id)
        return
    for prereq_id in kp.prerequisite_ids:
        if not prereq_id or prereq_id == kp_id or prereq_id in visiting:
            continue
        if prereq_id not in emitted:
            emitted.add(prereq_id)
            yield prereq_id
        yield from iter_prerequisites(progress, prereq_id, _visiting=visiting, _emitted=emitted)
    visiting.remove(kp_id)


def has_prerequisite_cycle(progress: LearningProgress) -> bool:
    """Whether any declared prerequisite walk contains a back-edge."""
    index = knowledge_points_by_id(progress)
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> bool:
        if node in done:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        kp = index.get(node)
        if kp is not None:
            for prereq_id in kp.prerequisite_ids:
                if prereq_id and visit(prereq_id):
                    return True
        visiting.remove(node)
        done.add(node)
        return False

    return any(visit(kp_id) for kp_id in index)


def is_prerequisite_weak(progress: LearningProgress, prereq_id: str) -> bool:
    """Demonstrated instability — not merely "not yet started" or "not gated"."""
    from deeptutor.learning.policy import find_knowledge_point, is_mastered, objective_status

    kp, _, _ = find_knowledge_point(progress, prereq_id)
    if kp is None:
        return False
    if is_mastered(progress, kp):
        return False
    if objective_status(progress, kp) == "new":
        return False
    if has_active_misconception(progress, prereq_id):
        return True
    if any(
        record.knowledge_point_id == prereq_id and record.status in ("active", "retrying")
        for record in progress.error_records
    ):
        return True
    if progress.qualitative_mastery.get(prereq_id) is False:
        return True
    return float(progress.mastery_levels.get(prereq_id, 0.0)) < WEAK_MASTERY_THRESHOLD


def weak_prerequisite_ids(progress: LearningProgress, kp_id: str) -> list[str]:
    """Reachable prerequisites that are currently weak. Cycles do not hang."""
    weak: list[str] = []
    seen: set[str] = set()
    for prereq_id in iter_prerequisites(progress, kp_id):
        if prereq_id in seen:
            continue
        seen.add(prereq_id)
        if is_prerequisite_weak(progress, prereq_id):
            weak.append(prereq_id)
    return weak


def weak_prerequisite_names(progress: LearningProgress, kp_id: str) -> list[str]:
    index = knowledge_points_by_id(progress)
    names: list[str] = []
    for prereq_id in weak_prerequisite_ids(progress, kp_id):
        kp = index.get(prereq_id)
        names.append(kp.name if kp is not None else prereq_id)
    return names


def unique_id_aliases(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """``source → target`` only when *source* maps to exactly one target."""
    grouped: dict[str, set[str]] = {}
    for source, target in pairs:
        src = str(source or "").strip()
        dst = str(target or "").strip()
        if not src or not dst or src == dst:
            continue
        grouped.setdefault(src, set()).add(dst)
    return {src: next(iter(targets)) for src, targets in grouped.items() if len(targets) == 1}


def resolve_prerequisite_ids(
    modules: list[LearningModule],
    extra_points: list[KnowledgePoint] | None = None,
    aliases: dict[str, str] | None = None,
) -> None:
    """Keep known ids, map unique names/aliases, drop self-refs and unknowns.

    ``extra_points`` participate in lookup only (other modules on the path).
    ``aliases`` map caller-facing ids (JSON ``id``, pre-rewrite ids) onto the
    generated ids that actually live on the modules.
    """
    targets = [kp for module in modules for kp in module.knowledge_points]
    lookup = list(targets)
    if extra_points:
        lookup.extend(extra_points)
    by_id = {kp.id: kp for kp in lookup}
    by_alias = {
        source: target
        for source, target in (aliases or {}).items()
        if source and target and target in by_id
    }
    by_name: dict[str, list[str]] = {}
    for kp in lookup:
        by_name.setdefault(kp.name, []).append(kp.id)
    for kp in targets:
        resolved: list[str] = []
        seen: set[str] = set()
        for ref in kp.prerequisite_ids:
            target = ""
            value = str(ref or "").strip()
            if not value:
                continue
            if value in by_id:
                target = value
            elif value in by_alias:
                target = by_alias[value]
            elif len(by_name.get(value, [])) == 1:
                target = by_name[value][0]
            if not target or target == kp.id or target in seen:
                continue
            seen.add(target)
            resolved.append(target)
        kp.prerequisite_ids = resolved


def remap_prerequisite_ids(
    points: list[KnowledgePoint],
    id_map: dict[str, str],
    *,
    known_ids: set[str] | None = None,
) -> None:
    """Rewrite prerequisite ids after a batch of knowledge-point ids changed.

    Unmapped refs are kept only when they still name a live knowledge point
    (``known_ids``). Unknown or retired ids are dropped.
    """
    allowed = known_ids
    for kp in points:
        remapped: list[str] = []
        seen: set[str] = set()
        for ref in kp.prerequisite_ids:
            source = str(ref or "").strip()
            if not source:
                continue
            target = id_map.get(source, source)
            if not target or target == kp.id or target in seen:
                continue
            if allowed is not None and target not in allowed:
                continue
            seen.add(target)
            remapped.append(target)
        kp.prerequisite_ids = remapped


__all__ = [
    "REASON_WEAK_PREREQUISITE",
    "WEAK_MASTERY_THRESHOLD",
    "has_prerequisite_cycle",
    "is_prerequisite_weak",
    "iter_prerequisites",
    "knowledge_points_by_id",
    "remap_prerequisite_ids",
    "resolve_prerequisite_ids",
    "unique_id_aliases",
    "weak_prerequisite_ids",
    "weak_prerequisite_names",
]
