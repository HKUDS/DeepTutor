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

#: Regions in a generated route when the material does not argue for more.
DEFAULT_MODULE_LIMIT = 8
#: The ceiling, however much material there is. Past this a route stops being
#: a route and becomes a table of contents.
MAX_MODULE_LIMIT = 20
#: Waypoints one region may hold. A strict caller that exceeds it is told.
_MAX_OBJECTIVES_PER_MODULE = 7
#: Documents named per knowledge base when handing the model its inventory.
#: A route has to be able to *account for* every file, which means seeing the
#: list — but a 400-document library would otherwise crowd out the excerpts.
_MAX_KB_DOCUMENTS = 60


class TopicGenerationError(RuntimeError):
    pass


def source_documents(source: TopicSource) -> list[str]:
    """The document names a grounded source says it holds.

    Written by :func:`_ground_knowledge_base_source` and read by both the
    prompt payload and the coverage report, so "what the model was shown" and
    "what the route is measured against" are the same list.
    """
    raw = (source.metadata or {}).get("documents")
    if not isinstance(raw, list):
        return []
    return [str(name).strip() for name in raw if str(name or "").strip()]


def _source_payload(sources: list[TopicSource]) -> list[dict[str, Any]]:
    remaining = _MAX_SOURCE_TOTAL
    payload: list[dict[str, Any]] = []
    for source in sorted(sources, key=lambda item: item.position)[:_MAX_SOURCES]:
        excerpt = str(source.excerpt or "")[: min(_MAX_SOURCE_EXCERPT, remaining)]
        remaining -= len(excerpt)
        entry: dict[str, Any] = {
            "kind": source.kind.value,
            "label": str(source.label or "")[:200],
            "excerpt": excerpt,
        }
        # Retrieval answers "what does this library say about my goal?" and
        # cannot answer "what is in it?" — four passages from a twenty-PDF
        # library used to be the model's entire view of it, which is why
        # generated routes silently covered two files and ignored the rest.
        documents = source_documents(source)
        if documents:
            entry["documents"] = documents
            omitted = int((source.metadata or {}).get("documents_omitted") or 0)
            if omitted > 0:
                entry["documents_omitted"] = omitted
        payload.append(entry)
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


async def _knowledge_base_inventory(kb_ref: str) -> tuple[list[str], int]:
    """The document names in ``kb_ref``, plus how many were left out.

    Empty for a connected external resource with no enumerable document set —
    a route over one of those is grounded by retrieval alone, and saying so is
    better than pretending the library is empty.
    """
    try:
        from deeptutor.multi_user.knowledge_access import resolve_kb_manifest

        manifest = await asyncio.to_thread(
            resolve_kb_manifest,
            kb_ref,
            limit=_MAX_KB_DOCUMENTS,
        )
    except Exception:
        logger.exception("Knowledge-base inventory failed source_id=%s", kb_ref)
        return [], 0
    if manifest is None or not manifest.enumerable:
        return [], 0
    return [document.name for document in manifest.documents], manifest.omitted


def _inventory_metadata(inventory: tuple[list[str], int]) -> dict[str, Any]:
    documents, omitted = inventory
    if not documents:
        return {}
    return {
        "documents": documents,
        **({"documents_omitted": omitted} if omitted > 0 else {}),
    }


async def _ground_file_source(source: TopicSource) -> TopicSource:
    """Read one document the learner picked out of a knowledge base.

    Selecting a single lesson is the difference between "design a route over
    my whole course" and "design one over chapter 3", and retrieval cannot
    express the second: it answers by similarity across the library. So this
    reads the file itself, in a short-lived isolated process — a malformed PDF
    must not be able to take the server down mid-wizard.
    """
    grounded = source.model_copy(deep=True)
    if grounded.kind != TopicSourceKind.FILE or not grounded.available:
        return grounded
    metadata = grounded.metadata or {}
    kb_ref = str(metadata.get("kb_name") or metadata.get("knowledge_base") or "").strip()
    rel_path = str(metadata.get("path") or grounded.source_id or "").strip()
    try:
        from deeptutor.multi_user.knowledge_access import resolve_kb_document_path
        from deeptutor.utils.document_extractor import extract_text_from_path_isolated

        path = await asyncio.to_thread(resolve_kb_document_path, kb_ref, rel_path)
        if path is None:
            raise ValueError(f"{rel_path!r} is not a readable document in {kb_ref!r}")
        text = await extract_text_from_path_isolated(
            path,
            max_chars=_MAX_SOURCE_EXCERPT,
            timeout=60.0,
        )
        if not str(text or "").strip():
            raise ValueError(f"{rel_path!r} yielded no extractable text")
        grounded.excerpt = str(text)[:_MAX_SOURCE_EXCERPT]
        grounded.metadata = {
            **metadata,
            "grounded_for_route": True,
            # Named as a one-document inventory so coverage treats a picked
            # file exactly like a library's file: something the route owes an
            # answer for.
            "documents": [rel_path],
        }
    except Exception:
        logger.exception(
            "File grounding failed kb=%s path=%s label=%s",
            kb_ref,
            rel_path,
            grounded.label,
        )
        grounded.available = False
        grounded.metadata = {
            **metadata,
            "unavailable_during_generation": True,
        }
    return grounded


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
    inventory = await _knowledge_base_inventory(grounded.source_id)
    try:
        from deeptutor.tools.rag_tool import rag_search

        result = await rag_search(query, grounded.source_id, top_k=4)
        context = _retrieved_context(result if isinstance(result, dict) else {})
        if not context and not inventory[0]:
            raise ValueError("knowledge base returned no retrievable context")
        grounded.excerpt = context
        grounded.metadata = {
            **grounded.metadata,
            "grounded_for_route": True,
            "retrieval_provider": str(result.get("provider") or ""),
            **_inventory_metadata(inventory),
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

    async def ground(source: TopicSource) -> TopicSource:
        if source.kind == TopicSourceKind.FILE:
            return await _ground_file_source(source)
        return await _ground_knowledge_base_source(source, query=query)

    return list(
        await asyncio.gather(
            *(
                ground(source)
                for source in sorted(sources, key=lambda item: item.position)[:_MAX_SOURCES]
            )
        )
    )


#: Keys a model reaches for when asked for a module's purpose. The prompt asks
#: for ``objective``; the rest are what models substitute for it in practice,
#: and a purpose written under the wrong key is still a purpose.
_MODULE_OBJECTIVE_KEYS = ("objective", "goal", "purpose", "summary", "description")
#: One sentence. Long enough to state a purpose, short enough that a whole
#: outline's worth of them still fits beside the map.
_MAX_MODULE_OBJECTIVE = 300


def _module_objective(raw_module: dict[str, Any]) -> str:
    """The one-sentence purpose a module was designed around, if it has one.

    Never raises and never blocks a module: an outline without objectives is
    the pre-existing shape, so a missing one degrades to empty rather than
    failing generation that would otherwise have succeeded.
    """
    for key in _MODULE_OBJECTIVE_KEYS:
        value = raw_module.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:_MAX_MODULE_OBJECTIVE]
    return ""


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
    module_limit: int = DEFAULT_MODULE_LIMIT,
) -> list[LearningModule]:
    """Validate and normalize a route while keeping existing entity identity.

    Draft generation is intentionally forgiving because model JSON can contain
    one malformed item among otherwise useful content. User-confirmed routes
    use ``strict=True`` so saving can never report success after silently
    dropping a region or waypoint — which includes the region *limit*: past it
    a strict caller is told, rather than having its tail quietly removed.

    ``module_limit`` scales with the material: a course whose knowledge base
    holds fourteen documents cannot be covered by eight regions, and the old
    fixed cap is why generated routes stopped part-way through a library.

    Position is presentation state, not identity. Existing ids are accepted
    only when the caller proves they belong to this topic; every new entity gets
    a collision-proof id so a deleted objective's evidence can never be reused.
    """
    cap = max(1, min(int(module_limit or DEFAULT_MODULE_LIMIT), MAX_MODULE_LIMIT))
    if strict and len(raw_modules) > cap:
        raise TopicGenerationError(
            f"A route may have at most {cap} regions; this one has {len(raw_modules)}"
        )

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

    for module_index, raw_module in enumerate(raw_modules[:cap]):
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
        module_objective = _module_objective(raw_module)
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
        if strict and len(raw_kps) > _MAX_OBJECTIVES_PER_MODULE:
            raise TopicGenerationError(
                f"Route region {module_index + 1} may have at most "
                f"{_MAX_OBJECTIVES_PER_MODULE} waypoints; it has {len(raw_kps)}"
            )
        for kp_index, raw_kp in enumerate(raw_kps[:_MAX_OBJECTIVES_PER_MODULE]):
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
                    objective=module_objective,
                    knowledge_points=knowledge_points,
                )
            )
        elif strict:
            raise TopicGenerationError(
                f"Route region {module_index + 1} needs at least one waypoint"
            )
        else:
            record_discard(module_index, "module has no usable waypoints")
    if not strict and len(raw_modules) > cap:
        for module_index in range(cap, len(raw_modules)):
            record_discard(module_index, "module limit exceeded")
    if not modules:
        raise TopicGenerationError("The generated route contains no usable objectives")
    return modules


def module_limit_for(sources: list[TopicSource]) -> int:
    """How many regions this material can justify.

    A goal-only route wants a handful of regions; a knowledge base holding
    fourteen documents cannot be covered by eight, and squeezing it into eight
    is what made a generated route look like it had ignored most of the
    library. One region per document is the ceiling this asks for, bounded by
    :data:`MAX_MODULE_LIMIT`.
    """
    documents = {name for source in sources for name in source_documents(source)}
    return max(DEFAULT_MODULE_LIMIT, min(MAX_MODULE_LIMIT, len(documents)))


def _covered_documents(raw_modules: list[Any]) -> set[str]:
    """Which documents the model says its regions are built from.

    Read off the optional per-region ``materials`` list. It is not persisted —
    :class:`LearningModule` ignores unknown keys — because it answers a
    question that only exists while the draft is on screen: did this route
    account for everything the learner selected?
    """
    covered: set[str] = set()
    for raw_module in raw_modules:
        if not isinstance(raw_module, dict):
            continue
        materials = raw_module.get("materials")
        if isinstance(materials, str):
            materials = [materials]
        if not isinstance(materials, list):
            continue
        for material in materials:
            name = str(material or "").strip()
            if name:
                covered.add(name)
    return covered


def _coverage_report(
    sources: list[TopicSource],
    raw_modules: list[Any],
) -> dict[str, Any]:
    """What the route left out, per selected source.

    Matching is on the document names the model was handed, in both
    directions: a model that answers with ``"lecture03.pdf"`` for a document
    listed as ``"slides/lecture03.pdf"`` has covered it, and saying otherwise
    would send the learner regenerating a route that is already complete.
    """
    covered = _covered_documents(raw_modules)
    folded = [name.casefold() for name in covered]
    missing: list[dict[str, str]] = []
    total = 0
    for source in sorted(sources, key=lambda item: item.position):
        for name in source_documents(source):
            total += 1
            needle = name.casefold()
            if any(needle in item or item in needle for item in folded):
                continue
            missing.append({"label": source.label, "document": name})
    return {
        "documents": total,
        "covered": max(0, total - len(missing)),
        # Empty when the model named nothing at all: claiming every document
        # was missed is worse than admitting the route did not say.
        "missing": missing if covered else [],
        "reported": bool(covered),
    }


async def generate_topic_draft(
    *,
    name: str,
    goal: str,
    sources: list[TopicSource],
    language: str,
    must_cover: list[str] | None = None,
) -> dict[str, Any]:
    grounded_sources = await ground_topic_sources(
        name=name,
        goal=goal,
        sources=sources,
    )
    source_json = json.dumps(_source_payload(grounded_sources), ensure_ascii=False)
    module_limit = module_limit_for(grounded_sources)
    system_prompt, prompt = learning_prompts.topic_generation_prompts(
        language,
        name=str(name or "").strip()[:120],
        goal=str(goal or "").strip()[:2_000],
        sources_json=source_json,
        module_limit=module_limit,
        must_cover=[str(item).strip() for item in (must_cover or []) if str(item or "").strip()],
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
            module_limit=module_limit,
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
        "module_limit": module_limit,
        "coverage": _coverage_report(grounded_sources, raw_modules),
    }


__all__ = [
    "DEFAULT_MODULE_LIMIT",
    "MAX_MODULE_LIMIT",
    "TopicGenerationError",
    "generate_topic_draft",
    "ground_topic_sources",
    "materialize_modules",
    "module_limit_for",
    "source_documents",
]
