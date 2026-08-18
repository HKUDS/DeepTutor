"""Character relationship graph extraction and rendering.

Converts requested reading text into a character relationship graph by:

1. Asking the LLM to extract a structured JSON payload of characters and
   their relationships.
2. Converting the structured data into a Mermaid ``graph LR`` source that
   the existing React ``<Mermaid>`` component renders.
"""

from __future__ import annotations

import logging

from .blocks._llm_writer import llm_json
from .models import (
    CharacterEdge,
    CharacterGraph,
    CharacterNode,
)

logger = logging.getLogger(__name__)

MAX_NODES_CURRENT = 30


# ─────────────────────────────────────────────────────────────────────────────
# LLM extraction
# ─────────────────────────────────────────────────────────────────────────────


_SYSTEM_PROMPT_EN = """\
You are a literary analysis assistant. Given text from a book chapter, \
extract all named characters and their relationships.

Return ONLY a JSON object with this exact structure:
{
  "nodes": [
    {"id": "slug", "name": "Display Name", "aliases": ["alt"], \
"description": "role", "confidence": 0.9}
  ],
  "edges": [
    {"source": "slug_a", "target": "slug_b", "relation": "friend", \
"description": "brief", "confidence": 0.8}
  ]
}

Rules:
- Use lowercase ASCII slugs for ids (underscores, no spaces).
- relation should be short (1-3 words): friend, enemy, parent_of, sibling, \
lover, mentor, rival, ally, servant, etc.
- Only include characters that actually appear or are mentioned.
- If no characters are found, return empty arrays.
- Do not include future plot events or spoilers beyond the given text.
"""

_SYSTEM_PROMPT_ZH = """\
你是一位文学分析助手。根据小说章节文本，提取所有具名人物及其关系。

只返回如下结构的 JSON 对象：
{
  "nodes": [
    {"id": "pinyin_slug", "name": "角色名", "aliases": ["别名"], \
"description": "角色简介", "confidence": 0.9}
  ],
  "edges": [
    {"source": "slug_a", "target": "slug_b", "relation": "关系类型", \
"description": "简要说明", "confidence": 0.8}
  ]
}

规则：
- id 使用小写拼音或英文 slug（下划线连接，不含空格）。
- relation 简短（1-3个字）：朋友、敌人、父子、师徒、恋人、对手等。
- 只提取在给定文本中出现或被提及的角色。
- 如果没有角色，返回空数组。
- 不要包含超出给定文本的未来剧情。
"""


async def extract_character_graph(
    *,
    text: str,
    language: str = "en",
    included_chapter_ids: list[str] | None = None,
    max_nodes: int = MAX_NODES_CURRENT,
) -> CharacterGraph:
    """Call the LLM to extract characters from *text*.

    Returns a validated :class:`CharacterGraph` with empty ``book_id`` /
    ``chapter_id`` (filled by the caller).
    """
    if not text.strip():
        return CharacterGraph()

    sys_prompt = _SYSTEM_PROMPT_ZH if language == "zh" else _SYSTEM_PROMPT_EN

    data = await llm_json(
        user_prompt=f"Extract characters and relationships from this text:\n\n{text}",
        system_prompt=sys_prompt,
        max_tokens=3000,
        temperature=0.3,
        language=language,
        expected_key="nodes",
    )

    nodes_data = data.get("nodes") or []
    edges_data = data.get("edges") or []

    # Build nodes with validation
    seen_ids: set[str] = set()
    nodes: list[CharacterNode] = []
    for raw in nodes_data[:max_nodes]:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        if not node_id:
            node_id = name.lower().replace(" ", "_")[:32]
        # Ensure unique
        if node_id in seen_ids:
            node_id = f"{node_id}_{len(seen_ids)}"
        seen_ids.add(node_id)

        aliases_raw = raw.get("aliases") or []
        aliases = [str(a).strip() for a in aliases_raw if str(a).strip()][:8]

        nodes.append(
            CharacterNode(
                id=node_id,
                name=name,
                aliases=aliases,
                description=str(raw.get("description") or "").strip()[:300],
                evidence_chapter_ids=list(included_chapter_ids or []),
                confidence=float(raw.get("confidence") or 1.0),
            )
        )

    # Build edges
    edges: list[CharacterEdge] = []
    for raw in edges_data:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or "").strip()
        target = str(raw.get("target") or "").strip()
        if source not in seen_ids or target not in seen_ids:
            continue
        relation = str(raw.get("relation") or "").strip()[:50]
        if not relation:
            relation = "related"
        edges.append(
            CharacterEdge(
                source=source,
                target=target,
                relation=relation,
                description=str(raw.get("description") or "").strip()[:200],
                evidence_chapter_ids=list(included_chapter_ids or []),
                confidence=float(raw.get("confidence") or 1.0),
            )
        )

    return CharacterGraph(nodes=nodes, edges=edges)


# ─────────────────────────────────────────────────────────────────────────────
# Mermaid rendering
# ─────────────────────────────────────────────────────────────────────────────


def _safe_mermaid_id(node_id: str, used: set[str]) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in (node_id or "n"))
    cleaned = cleaned.strip("_") or "n"
    candidate = cleaned[:32]
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{cleaned[:30]}_{suffix}"
    used.add(candidate)
    return candidate


def _escape_label(text: str, max_len: int = 24) -> str:
    cleaned = " ".join((text or "").split())
    cleaned = cleaned.replace('"', "'")
    if len(cleaned) > max_len:
        cleaned = cleaned[: max_len - 1] + "..."
    return cleaned or "?"


def render_character_graph_mermaid(graph: CharacterGraph) -> str:
    """Render a :class:`CharacterGraph` as Mermaid ``graph LR`` source."""
    if not graph.nodes:
        return 'graph LR\n  empty["No characters found"]'

    used: set[str] = set()
    id_map: dict[str, str] = {}
    lines = ["graph LR"]

    for node in graph.nodes:
        sid = _safe_mermaid_id(node.id or node.name, used)
        id_map[node.id] = sid
        label = _escape_label(node.name)
        lines.append(f'  {sid}["{label}"]')

    for edge in graph.edges:
        if edge.source not in id_map or edge.target not in id_map:
            continue
        relation = _escape_label(edge.relation, max_len=20)
        lines.append(f'  {id_map[edge.source]} -- "{relation}" --> {id_map[edge.target]}')

    return "\n".join(lines)


__all__ = [
    "extract_character_graph",
    "render_character_graph_mermaid",
]
