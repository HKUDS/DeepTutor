#!/usr/bin/env python
"""
Knowledge Scope Generator

Queries an existing knowledge base via RAGService and uses LLM to
generate a structured knowledge scope description. This scope is the
foundation for all downstream generation (profiles, gaps, tasks).
"""

import json
import logging

from benchmark.data_generation.llm_utils import call_llm_json, load_prompt, render_prompt

logger = logging.getLogger("benchmark.scope_generator")


async def query_kb_for_content(
    kb_name: str,
    seed_queries: list[str] | None = None,
    mode: str = "naive",
    kb_base_dir: str | None = None,
) -> str:
    """
    Query a knowledge base with seed queries to extract representative content.

    Uses RAGService (the project's unified RAG interface) to retrieve
    content from the KB without LLM answer generation.

    Args:
        kb_name: Name of the knowledge base
        seed_queries: List of queries to probe the KB
        mode: RAG query mode ("naive", "hybrid", "local", "global")
        kb_base_dir: Override KB base directory

    Returns:
        Concatenated content string from all queries
    """
    from src.services.rag.service import RAGService

    if seed_queries is None:
        seed_queries = [
            "What are the main knowledge points and core concepts in this content?",
            "What key theorems, formulas, or methods does this content cover?",
            "What are typical application scenarios and example problems in this content?",
        ]

    service = RAGService(kb_base_dir=kb_base_dir)
    all_contents = []

    for query in seed_queries:
        try:
            result = await service.search(
                query=query,
                kb_name=kb_name,
                mode=mode,
            )
            content = result.get("content", result.get("answer", ""))
            if content and content.strip():
                all_contents.append(f"--- Query: {query} ---\n{content}")
        except Exception as e:
            logger.warning(f"Failed to query KB '{kb_name}' with '{query[:30]}...': {e}")

    if not all_contents:
        logger.error(f"No content retrieved from KB '{kb_name}'")
        return ""

    return "\n\n".join(all_contents)


async def generate_knowledge_scope(
    kb_name: str,
    kb_contents: str | None = None,
    seed_queries: list[str] | None = None,
    mode: str = "naive",
    kb_base_dir: str | None = None,
) -> dict:
    """
    Generate a structured knowledge scope description for a KB.

    If kb_contents is not provided, queries the KB first using seed_queries.

    Args:
        kb_name: Knowledge base name
        kb_contents: Pre-fetched KB content (optional)
        seed_queries: Seed queries for KB probing (if kb_contents not provided)
        mode: RAG query mode
        kb_base_dir: Override KB base directory

    Returns:
        Knowledge scope dictionary with domain, concepts, hierarchy, etc.
    """
    logger.info(f"Generating knowledge scope for KB: {kb_name}")

    # Fetch KB content if not provided
    if not kb_contents:
        kb_contents = await query_kb_for_content(
            kb_name=kb_name,
            seed_queries=seed_queries,
            mode=mode,
            kb_base_dir=kb_base_dir,
        )

    if not kb_contents:
        raise ValueError(f"Cannot generate scope: no content from KB '{kb_name}'")

    # Load prompt and call LLM
    prompt = load_prompt("generate_knowledge_scope")
    user_prompt = render_prompt(
        prompt["user_template"],
        kb_name=kb_name,
        kb_contents=kb_contents,
    )

    result = await call_llm_json(
        user_prompt=user_prompt,
        system_prompt=prompt["system"],
        temperature=0.5,
        max_tokens=4096,
    )

    # Tag with source KB
    result["source_kb"] = kb_name

    logger.info(
        f"Knowledge scope generated for '{kb_name}': "
        f"{result.get('domain', '?')} / {result.get('subtopic_title', '?')} "
        f"({len(result.get('core_concepts', []))} concepts)"
    )
    return result
