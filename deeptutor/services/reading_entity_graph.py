"""LLM-backed entity graph generation for stored reading materials."""

from __future__ import annotations

from collections import OrderedDict
import hashlib
import time

from deeptutor.reading.entity_graph import (
    EntityGraphExtractionError,
    normalise_entity_graph,
    render_entity_graph_mermaid,
)
from deeptutor.reading.models import (
    EntityGraph,
    EntityGraphResult,
    EntityGraphScope,
    ReadingError,
)
from deeptutor.reading.store import ReadingStore
from deeptutor.services.llm import (
    complete as llm_complete,
)
from deeptutor.services.llm import (
    get_llm_config,
    get_token_limit_kwargs,
)
from deeptutor.utils.json_parser import parse_json_response

MAX_GRAPH_CHARS = 45_000
_MAX_CURRENT_CHARS = 15_000
_MAX_PRIOR_CHARS = 30_000
_SCHEMA_VERSION = 1
_CACHE_LIMIT = 32

_SYSTEM_PROMPT = """\
You extract relationship graphs from reading passages.

Return only a JSON object with this exact shape:
{
  "nodes": [
    {"id": "stable_id", "name": "display name", "aliases": ["alias"],
     "description": "one concise sentence", "confidence": 0.9}
  ],
  "edges": [
    {"source": "stable_id", "target": "stable_id", "relation": "short relation",
     "evidence": "one verbatim sentence from the supplied text", "confidence": 0.9}
  ]
}

Rules:
- Include people, organizations, creatures, named places, and other entities important to the passage.
- Normalize duplicate names and aliases to one node.
- Write names, descriptions, and relations in the language of the source text.
- Include only entities actually present in the supplied text.
- Include only relationships explicitly supported by the supplied text.
- Evidence must be copied verbatim from one supplied sentence; do not paraphrase.
- Use confidence from 0 to 1 and omit uncertain entities or relationships.
- If nothing qualifies, return {"nodes": [], "edges": []}.
"""

_CACHE: OrderedDict[str, EntityGraphResult] = OrderedDict()


def _cache_key(context: str, scope: EntityGraphScope) -> str:
    digest = hashlib.sha256(f"{_SCHEMA_VERSION}\n{scope}\n{context}".encode()).hexdigest()
    return digest[:24]


def _cache_get(key: str) -> EntityGraphResult | None:
    result = _CACHE.get(key)
    if result is not None:
        _CACHE.move_to_end(key)
    return result


def _cache_put(key: str, result: EntityGraphResult) -> None:
    _CACHE[key] = result
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_LIMIT:
        _CACHE.popitem(last=False)


def _render_context(unit: str, rows: list[tuple[int, str]]) -> str:
    label = unit.capitalize()
    return "\n\n".join(f"--- {label} {locator} ---\n{text.strip()}" for locator, text in rows)


async def _extract(context: str, rows: list[tuple[int, str]]) -> EntityGraph:
    config = get_llm_config()
    kwargs = get_token_limit_kwargs(config.model, max_tokens=3000)
    kwargs.update({"temperature": 0.1, "response_format": {"type": "json_object"}})
    try:
        raw = await llm_complete(
            prompt=context,
            system_prompt=_SYSTEM_PROMPT,
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            api_version=getattr(config, "api_version", None),
            binding=getattr(config, "binding", None) or "openai",
            **kwargs,
        )
    except Exception as exc:
        raise EntityGraphExtractionError("relationship graph generation failed; try again") from exc
    payload = parse_json_response(raw, fallback={})
    try:
        # Evidence is checked against the exact rows sent to the model, so a
        # graph cannot carry plausible-but-invented relationships.
        return normalise_entity_graph(payload, rows)
    except EntityGraphExtractionError as exc:
        raise EntityGraphExtractionError(
            "the model returned an invalid relationship graph; try again"
        ) from exc


async def build_entity_graph(
    store: ReadingStore,
    material_id: str,
    *,
    locator: int,
    scope: EntityGraphScope = "current",
    force_refresh: bool = False,
) -> EntityGraphResult:
    """Build a locator-scoped graph, reusing bounded in-process results."""
    manifest = store.manifest(material_id)
    if not 1 <= locator <= manifest.unit_count:
        raise ReadingError(
            f"{manifest.unit} {locator} is out of range — this material has {manifest.unit_count}."
        )

    current, current_truncated = store.read_units(
        material_id, [locator], max_chars=_MAX_CURRENT_CHARS
    )
    if scope == "current":
        rows = current
        truncated = current_truncated
    else:
        prior, prior_truncated = store.read_units(
            material_id,
            range(1, locator),
            max_chars=_MAX_PRIOR_CHARS,
        )
        rows = prior + current
        # Keep the current unit on its own budget. A long history must not
        # crowd out the chapter the learner is actually reading.
        truncated = prior_truncated or current_truncated

    has_text = any(text.strip() for _, text in rows)
    context = _render_context(manifest.unit, rows)
    if not has_text:
        graph = EntityGraph()
        return EntityGraphResult(
            graph=graph,
            mermaid=render_entity_graph_mermaid(graph),
            generated_at=time.time(),
            scope=scope,
            locator=locator,
            included_locators=tuple(row[0] for row in rows),
            truncated=truncated,
        )

    key = _cache_key(context, scope)
    if not force_refresh:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    graph = await _extract(context, rows)
    result = EntityGraphResult(
        graph=graph,
        mermaid=render_entity_graph_mermaid(graph),
        generated_at=time.time(),
        scope=scope,
        locator=locator,
        included_locators=tuple(row[0] for row in rows),
        truncated=truncated,
    )
    _cache_put(key, result)
    return result


__all__ = [
    "EntityGraphExtractionError",
    "EntityGraphScope",
    "MAX_GRAPH_CHARS",
    "build_entity_graph",
]
