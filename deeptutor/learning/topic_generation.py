"""Bounded mixed-source route generation for Mastery Topics."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
import uuid

from deeptutor.learning import prompts as learning_prompts
from deeptutor.learning.models import (
    KnowledgePoint,
    KnowledgeType,
    LearningModule,
    TopicSource,
    TopicSourceKind,
)
from deeptutor.services.llm import complete
from deeptutor.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)

_ALLOWED_TYPES = {item.value for item in KnowledgeType}
_MAX_SOURCES = 16
_MAX_SOURCE_EXCERPT = 4_000
_MAX_SOURCE_TOTAL = 24_000


class TopicGenerationError(RuntimeError):
    pass


def _source_payload(sources: list[TopicSource]) -> list[dict[str, Any]]:
    remaining = _MAX_SOURCE_TOTAL
    payload: list[dict[str, Any]] = []
    for source in sorted(sources, key=lambda item: item.position)[:_MAX_SOURCES]:
        excerpt = str(source.excerpt or "")[: min(_MAX_SOURCE_EXCERPT, remaining)]
        remaining -= len(excerpt)
        payload.append(
            {
                "kind": source.kind.value,
                "label": str(source.label or "")[:200],
                "excerpt": excerpt,
            }
        )
        if remaining <= 0:
            break
    return payload


def _retrieved_context(result: dict[str, Any]) -> str:
    blocks: list[str] = []
    raw_sources = result.get("sources")
    if isinstance(raw_sources, list):
        for raw_source in raw_sources[:6]:
            if not isinstance(raw_source, dict):
                continue
            title = str(raw_source.get("title") or raw_source.get("source") or "").strip()
            content = str(
                raw_source.get("content")
                or raw_source.get("text")
                or raw_source.get("snippet")
                or ""
            ).strip()
            if content:
                blocks.append(f"{title}\n{content}".strip())
    # Some providers return one context block and only file-level source
    # metadata. Include it when snippets alone do not provide useful grounding.
    if sum(len(block) for block in blocks) < 500:
        content = str(result.get("content") or result.get("answer") or "").strip()
        if content:
            blocks.append(content)
    return "\n\n".join(blocks)[:_MAX_SOURCE_EXCERPT]


async def _ground_knowledge_base_source(
    source: TopicSource,
    *,
    query: str,
) -> TopicSource:
    grounded = source.model_copy(deep=True)
    if (
        grounded.kind != TopicSourceKind.KNOWLEDGE_BASE
        or not grounded.available
        or not grounded.source_id.strip()
    ):
        return grounded
    try:
        from deeptutor.tools.rag_tool import rag_search

        result = await rag_search(query, grounded.source_id, top_k=4)
        context = _retrieved_context(result if isinstance(result, dict) else {})
        if not context:
            raise ValueError("knowledge base returned no retrievable context")
        grounded.excerpt = context
        grounded.metadata = {
            **grounded.metadata,
            "grounded_for_route": True,
            "retrieval_provider": str(result.get("provider") or ""),
        }
    except Exception:
        logger.exception(
            "Knowledge-base grounding failed source_id=%s label=%s",
            grounded.source_id,
            grounded.label,
        )
        # One unavailable source must not discard the user's other selected
        # material or prevent a goal-only draft. Its degraded state is returned
        # to the client and persisted when the user confirms the route.
        grounded.available = False
        grounded.metadata = {
            **grounded.metadata,
            "unavailable_during_generation": True,
        }
    return grounded


async def ground_topic_sources(
    *,
    name: str,
    goal: str,
    sources: list[TopicSource],
) -> list[TopicSource]:
    query = f"{str(name or '').strip()}\n{str(goal or '').strip()}".strip()[:2_000]
    return list(
        await asyncio.gather(
            *(
                _ground_knowledge_base_source(source, query=query)
                for source in sorted(sources, key=lambda item: item.position)[:_MAX_SOURCES]
            )
        )
    )


def _new_entity_id(prefix: str, reserved: set[str]) -> str:
    """Allocate a durable id that cannot inherit evidence from a deleted row."""

    while True:
        candidate = f"{prefix}_{uuid.uuid4().hex[:12]}"
        if candidate not in reserved:
            reserved.add(candidate)
            return candidate


def materialize_modules(
    path_id: str,
    raw_modules: list[dict[str, Any]],
    *,
    strict: bool = False,
    existing_module_ids: set[str] | None = None,
    existing_objective_ids: set[str] | None = None,
    discarded_modules: list[dict[str, Any]] | None = None,
) -> list[LearningModule]:
    """Validate and normalize a route while keeping existing entity identity.

    Draft generation is intentionally forgiving because model JSON can contain
    one malformed item among otherwise useful content. User-confirmed routes
    use ``strict=True`` so saving can never report success after silently
    dropping a region or waypoint.

    Position is presentation state, not identity. Existing ids are accepted
    only when the caller proves they belong to this topic; every new entity gets
    a collision-proof id so a deleted objective's evidence can never be reused.
    """

    allowed_modules = set(existing_module_ids or ())
    allowed_objectives = set(existing_objective_ids or ())
    reserved_modules = set(allowed_modules)
    reserved_objectives = set(allowed_objectives)
    used_modules: set[str] = set()
    used_objectives: set[str] = set()
    modules: list[LearningModule] = []

    def record_discard(module_index: int, reason: str) -> None:
        if discarded_modules is not None:
            discarded_modules.append({"index": module_index + 1, "reason": reason})

    for module_index, raw_module in enumerate(raw_modules[:8]):
        if not isinstance(raw_module, dict):
            if strict:
                raise TopicGenerationError(f"Route region {module_index + 1} is invalid")
            record_discard(module_index, "module is not an object")
            continue
        module_name = str(raw_module.get("name") or "").strip()[:200]
        if not module_name:
            if strict:
                raise TopicGenerationError(f"Route region {module_index + 1} needs a name")
            record_discard(module_index, "module name is missing")
            continue
        requested_module_id = str(raw_module.get("id") or "").strip()
        if requested_module_id in allowed_modules and requested_module_id not in used_modules:
            module_id = requested_module_id
            used_modules.add(module_id)
        elif existing_module_ids is None:
            module_id = f"{path_id}_m{module_index}"
            reserved_modules.add(module_id)
        else:
            module_id = _new_entity_id(f"{path_id}_m", reserved_modules)
        knowledge_points: list[KnowledgePoint] = []
        raw_kps = raw_module.get("knowledge_points")
        if not isinstance(raw_kps, list):
            if strict:
                raise TopicGenerationError(
                    f"Route region {module_index + 1} needs at least one waypoint"
                )
            record_discard(module_index, "knowledge_points is not a list")
            continue
        if strict and not raw_kps:
            raise TopicGenerationError(
                f"Route region {module_index + 1} needs at least one waypoint"
            )
        for kp_index, raw_kp in enumerate(raw_kps[:7]):
            if not isinstance(raw_kp, dict):
                if strict:
                    raise TopicGenerationError(
                        f"Route region {module_index + 1} waypoint {kp_index + 1} is invalid"
                    )
                continue
            name = str(raw_kp.get("name") or "").strip()[:200]
            if len(name) < 2:
                if strict:
                    raise TopicGenerationError(
                        f"Route region {module_index + 1} waypoint {kp_index + 1} needs a name"
                    )
                continue
            kp_type = str(raw_kp.get("type") or "concept").strip().lower()
            if kp_type not in _ALLOWED_TYPES:
                if strict:
                    raise TopicGenerationError(
                        f"Route region {module_index + 1} waypoint {kp_index + 1} has an invalid type"
                    )
                kp_type = "concept"
            requested_objective_id = str(raw_kp.get("id") or "").strip()
            if (
                requested_objective_id in allowed_objectives
                and requested_objective_id not in used_objectives
            ):
                objective_id = requested_objective_id
                used_objectives.add(objective_id)
            elif existing_objective_ids is None:
                objective_id = f"{module_id}_kp{kp_index}"
                reserved_objectives.add(objective_id)
            else:
                objective_id = _new_entity_id(f"{module_id}_kp", reserved_objectives)
            knowledge_points.append(
                KnowledgePoint(
                    id=objective_id,
                    name=name,
                    type=KnowledgeType(kp_type),
                    module_id=module_id,
                )
            )
        if knowledge_points:
            modules.append(
                LearningModule(
                    id=module_id,
                    name=module_name,
                    order=len(modules),
                    pass_threshold=0.7,
                    knowledge_points=knowledge_points,
                )
            )
        elif strict:
            raise TopicGenerationError(
                f"Route region {module_index + 1} needs at least one waypoint"
            )
        else:
            record_discard(module_index, "module has no usable waypoints")
    if not strict and len(raw_modules) > 8:
        for module_index in range(8, len(raw_modules)):
            record_discard(module_index, "module limit exceeded")
    if not modules:
        raise TopicGenerationError("The generated route contains no usable objectives")
    return modules


async def generate_topic_draft(
    *,
    name: str,
    goal: str,
    sources: list[TopicSource],
    language: str,
) -> dict[str, Any]:
    grounded_sources = await ground_topic_sources(
        name=name,
        goal=goal,
        sources=sources,
    )
    source_json = json.dumps(_source_payload(grounded_sources), ensure_ascii=False)
    system_prompt, prompt = learning_prompts.topic_generation_prompts(
        language,
        name=str(name or "").strip()[:120],
        goal=str(goal or "").strip()[:2_000],
        sources_json=source_json,
    )
    response = await complete(prompt=prompt, system_prompt=system_prompt)
    data = parse_json_response(response, fallback=None)
    if not isinstance(data, dict):
        raise TopicGenerationError("The model returned invalid route JSON")
    raw_modules = data.get("modules")
    if not isinstance(raw_modules, list):
        raise TopicGenerationError("The generated route has no module list")
    discarded_modules: list[dict[str, Any]] = []
    try:
        modules = materialize_modules(
            "draft",
            raw_modules,
            discarded_modules=discarded_modules,
        )
    finally:
        if discarded_modules:
            logger.warning(
                "Discarded %d generated route module(s): %s",
                len(discarded_modules),
                "; ".join(
                    f"region {item['index']}: {item['reason']}" for item in discarded_modules
                ),
            )
    return {
        "description": str(data.get("description") or "").strip()[:500],
        "modules": [module.model_dump(mode="json") for module in modules],
        "sources": [source.model_dump(mode="json") for source in grounded_sources],
        "discarded_module_count": len(discarded_modules),
        "discarded_modules": discarded_modules,
    }


__all__ = [
    "TopicGenerationError",
    "generate_topic_draft",
    "ground_topic_sources",
    "materialize_modules",
]
