#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ReportingAgent - Report generation Agent (DR-in-KG 2.0)
- Deduplication and cleaning
- Generate linear outline (introduction → sections → conclusion)
- Write final report (prefer LLM JSON return markdown, fallback to local assembly on failure)
- Inline citations and References anchors (based on citation_id)
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import re
from string import Template
import sys
from typing import Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agents.base_agent import BaseAgent
from src.agents.research.data_structures import DynamicTopicQueue, TopicBlock

from ..utils.json_utils import ensure_json_dict, ensure_keys, extract_json_from_text


class ReportingAgent(BaseAgent):
    """Report generation Agent"""

    @staticmethod
    def _escape_braces(text: str) -> str:
        """
        Escape curly braces in text to prevent str.format() from interpreting them.
        This is needed because JSON data may contain LaTeX formulas with braces like {L}, {x}.

        Args:
            text: Input text that may contain curly braces

        Returns:
            Text with braces escaped ({{ and }})
        """
        return text.replace("{", "{{").replace("}", "}}")

    @staticmethod
    def _convert_to_template_format(template_str: str) -> str:
        """
        Convert {var} style placeholders to $var style for string.Template.
        This avoids conflicts with LaTeX braces like {\rho}, {L}.
        """
        return re.sub(r"\{(\w+)\}", r"$\1", template_str)

    def _safe_format(self, template_str: str, **kwargs) -> str:
        """
        Safe string formatting using string.Template to avoid LaTeX brace conflicts.
        Converts {var} to $var format, then uses safe_substitute.
        """
        converted = self._convert_to_template_format(template_str)
        return Template(converted).safe_substitute(**kwargs)

    def __init__(
        self, config: dict[str, Any], api_key: str | None = None, base_url: str | None = None
    ):
        language = config.get("system", {}).get("language", "zh")
        super().__init__(
            module_name="research",
            agent_name="reporting_agent",
            api_key=api_key,
            base_url=base_url,
            language=language,
            config=config,
        )
        self.reporting_config = config.get("reporting", {})
        self.citation_manager = None  # Will be set during process

        # Citation configuration: read from config, default off
        self.enable_citation_list = self.reporting_config.get("enable_citation_list", True)
        self.enable_inline_citations = True  # Force enable inline citations for Deep Research

    def set_citation_manager(self, citation_manager):
        """Set citation manager"""
        self.citation_manager = citation_manager

    @staticmethod
    def _normalize_source_url(raw: str) -> str:
        value = (raw or "").strip()
        if not value:
            return ""
        return re.sub(r"/+$", "", value)

    def _build_source_key(
        self,
        source_type: str,
        title: str,
        url: str = "",
        source: str = "",
        page: str = "",
        chunk_id: str = "",
        fallback: str = "",
    ) -> str:
        normalized_url = self._normalize_source_url(url)
        if normalized_url:
            return f"{source_type}-{normalized_url}"

        locator_parts = [
            (source or "").strip(),
            (page or "").strip(),
            (chunk_id or "").strip(),
        ]
        locator = "|".join(part for part in locator_parts if part)
        if locator:
            return f"{source_type}-{locator}"

        basis = (title or fallback or "").strip()
        return f"{source_type}-{basis}" if basis else ""

    def _build_structured_sources_and_catalog(
        self,
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """
        Build source lists and a stable source_catalog with ref numbers.

        The catalog is source-level (not citation-level), so every unique source
        has its own [N], which keeps the report References and left-source list aligned.
        """
        structured_sources: dict[str, list[dict[str, Any]]] = {"web": [], "rag": []}
        source_catalog: list[dict[str, Any]] = []

        if not self.citation_manager:
            return structured_sources, source_catalog

        all_citations = self.citation_manager.get_all_citations()
        ref_map = self.citation_manager.get_ref_number_map()
        if not all_citations:
            return structured_sources, source_catalog

        sorted_citation_ids = sorted(
            all_citations.keys(), key=self.citation_manager._extract_citation_sort_key
        )

        by_key: dict[str, dict[str, Any]] = {}
        ref_owner: dict[int, str] = {}
        max_ref = 0

        def allocate_ref(source_key: str, preferred_ref: int = 0) -> int:
            nonlocal max_ref
            existing = by_key.get(source_key)
            if existing and existing.get("ref_number"):
                ref_num = int(existing["ref_number"])
                ref_owner[ref_num] = source_key
                max_ref = max(max_ref, ref_num)
                return ref_num

            preferred = int(preferred_ref) if isinstance(preferred_ref, int | float) else 0
            if preferred > 0 and ref_owner.get(preferred, source_key) == source_key:
                ref_owner[preferred] = source_key
                max_ref = max(max_ref, preferred)
                return preferred

            candidate = max_ref + 1
            while candidate in ref_owner:
                candidate += 1
            ref_owner[candidate] = source_key
            max_ref = max(max_ref, candidate)
            return candidate

        def upsert_source(
            source_type: str,
            title: str,
            url: str = "",
            content: str = "",
            source: str = "",
            page: str = "",
            chunk_id: str = "",
            kb_name: str = "",
            citation_id: str = "",
            preferred_ref: int = 0,
        ) -> None:
            source_title = (title or url or "Untitled").strip()
            source_url = (url or "").strip()
            source_key = self._build_source_key(
                source_type=source_type,
                title=source_title,
                url=source_url,
                source=source,
                page=page,
                chunk_id=chunk_id,
                fallback=citation_id,
            )
            if not source_key:
                return

            ref_number = allocate_ref(source_key, preferred_ref)
            source_entry = {
                "title": source_title,
                "url": source_url,
                "content": (content or "").strip(),
                "source": source,
                "page": str(page or "").strip(),
                "chunk_id": str(chunk_id or "").strip(),
                "kb_name": (kb_name or "").strip(),
                "source_key": source_key,
                "ref_number": ref_number,
            }

            existing = by_key.get(source_key)
            if existing:
                for key, value in source_entry.items():
                    if value and not existing.get(key):
                        existing[key] = value
                return
            by_key[source_key] = source_entry

        for citation_id in sorted_citation_ids:
            citation = all_citations.get(citation_id) or {}
            tool_type = (citation.get("tool_type") or "").lower()
            citation_ref = ref_map.get(citation_id, 0)
            used_preferred = False

            if tool_type == "web_search":
                web_items = citation.get("web_sources", []) or citation.get("citations", [])
                if not web_items and citation.get("url"):
                    web_items = [citation]

                for item in web_items:
                    if not isinstance(item, dict):
                        continue
                    preferred = citation_ref if citation_ref > 0 and not used_preferred else 0
                    upsert_source(
                        source_type="web",
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        content=item.get("snippet", "")
                        or item.get("content", "")
                        or citation.get("summary", ""),
                        citation_id=citation_id,
                        preferred_ref=preferred,
                    )
                    if preferred > 0:
                        used_preferred = True

            elif tool_type in ("rag_naive", "rag_hybrid", "query_item"):
                rag_items = citation.get("sources", [])
                for item in rag_items:
                    if not isinstance(item, dict):
                        continue
                    preferred = citation_ref if citation_ref > 0 and not used_preferred else 0
                    upsert_source(
                        source_type="kb",
                        title=item.get("title", "")
                        or item.get("source_file", "")
                        or item.get("source", ""),
                        url=item.get("url", ""),
                        content=item.get("content_preview", ""),
                        source=item.get("source_file", "") or item.get("source", ""),
                        page=str(item.get("page", "")).strip(),
                        chunk_id=str(item.get("chunk_id", "")).strip(),
                        kb_name=citation.get("kb_name", ""),
                        citation_id=citation_id,
                        preferred_ref=preferred,
                    )
                    if preferred > 0:
                        used_preferred = True

            elif tool_type == "paper_search":
                papers = citation.get("papers", [])
                for idx, paper in enumerate(papers):
                    if not isinstance(paper, dict):
                        continue
                    paper_ref_key = f"{citation_id}-{idx + 1}"
                    preferred = ref_map.get(paper_ref_key, 0) or (
                        citation_ref if citation_ref > 0 and not used_preferred else 0
                    )
                    doi = (paper.get("doi") or "").strip()
                    url = (paper.get("url") or "").strip()
                    if doi and not url:
                        url = f"https://doi.org/{doi}"
                    upsert_source(
                        source_type="web",
                        title=paper.get("title", ""),
                        url=url,
                        content=paper.get("abstract", ""),
                        citation_id=paper_ref_key,
                        preferred_ref=preferred,
                    )
                    if preferred > 0:
                        used_preferred = True

        for item in by_key.values():
            catalog_item = {
                "ref_number": item["ref_number"],
                "source_key": item["source_key"],
                "title": item["title"],
                "url": item.get("url", ""),
                "type": "kb" if item.get("source") else "web",
            }
            source_catalog.append(catalog_item)
            if catalog_item["type"] == "kb":
                structured_sources["rag"].append(item)
            else:
                structured_sources["web"].append(item)

        source_catalog.sort(key=lambda x: int(x.get("ref_number", 0)))
        structured_sources["web"].sort(key=lambda x: int(x.get("ref_number", 0)))
        structured_sources["rag"].sort(key=lambda x: int(x.get("ref_number", 0)))
        return structured_sources, source_catalog

    async def process(
        self,
        queue: DynamicTopicQueue,
        topic: str,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """
        Generate final report
        Returns:
            {
              "report": str,
              "word_count": int,
              "sections": int,
              "citations": int
            }
        """
        print(f"\n{'=' * 70}")
        print("📄 ReportingAgent - Report Generation")
        print(f"{'=' * 70}")
        print(f"Topic: {topic}")
        print(f"Topic Blocks: {len(queue.blocks)}\n")

        # Store progress_callback for use in _write_report
        self._progress_callback = progress_callback

        self._notify_progress(
            progress_callback, "reporting_started", topic=topic, total_blocks=len(queue.blocks)
        )

        # 1) Deduplication
        print("🔄 Step 1: Deduplication and cleaning...")
        cleaned_blocks = await self._deduplicate_blocks(queue.blocks)
        print(f"✓ Cleaning completed: {len(cleaned_blocks)} topic blocks")
        self._notify_progress(
            progress_callback, "deduplicate_completed", kept_blocks=len(cleaned_blocks)
        )

        structured_sources, source_catalog = self._build_structured_sources_and_catalog()
        self._current_source_catalog = source_catalog

        if self.reporting_config.get("report_type") == "summary":
            # Summary mode: Fast generation without outline
            print("\n✍️  Step 2: Writing summary report...")
            report_markdown = await self._write_summary_report(topic, cleaned_blocks)
            print("✓ Summary report writing completed")
            self._notify_progress(progress_callback, "writing_completed")
        else:
            # 2) Outline
            print("\n📋 Step 2: Generating outline...")
            outline = await self._generate_outline(topic, cleaned_blocks)
            print("✓ Outline generation completed")
            self._notify_progress(
                progress_callback, "outline_completed", sections=len(outline.get("sections", []))
            )

            # Save outline for later use
            self._current_outline = outline

            # 3) Writing
            print("\n✍️  Step 3: Writing report...")
            report_markdown = await self._write_report(topic, cleaned_blocks, outline)
            print("✓ Report writing completed")
            self._notify_progress(progress_callback, "writing_completed")

        word_count = len(report_markdown)
        sections = len(cleaned_blocks)
        citations = sum(len(b.tool_traces) for b in cleaned_blocks)

        print("\n📊 Report Statistics:")
        print(f"   Word Count: {word_count}")
        print(f"   Sections: {sections}")
        print(f"   Citations: {citations}")
        self._notify_progress(
            progress_callback,
            "reporting_completed",
            word_count=word_count,
            sections=sections,
            citations=citations,
        )

        # Prepare structured sources/source-catalog for frontend
        if not structured_sources.get("web"):
            fallback_urls = self._extract_urls(report_markdown)
            for url in fallback_urls:
                source_key = self._build_source_key("web", title=url, url=url)
                if not source_key:
                    continue
                if any(item.get("source_key") == source_key for item in structured_sources["web"]):
                    continue
                next_ref = (
                    max((int(item.get("ref_number", 0)) for item in source_catalog), default=0) + 1
                )
                source_item = {
                    "title": url,
                    "url": url,
                    "content": "",
                    "source_key": source_key,
                    "ref_number": next_ref,
                }
                structured_sources["web"].append(source_item)
                source_catalog.append(
                    {
                        "ref_number": next_ref,
                        "source_key": source_key,
                        "title": url,
                        "url": url,
                        "type": "web",
                    }
                )

        source_catalog.sort(key=lambda x: int(x.get("ref_number", 0)))
        structured_sources["web"].sort(key=lambda x: int(x.get("ref_number", 0)))
        structured_sources["rag"].sort(key=lambda x: int(x.get("ref_number", 0)))

        result = {
            "report": report_markdown,
            "word_count": word_count,
            "sections": sections,
            "citations": citations,
            "sources": structured_sources,  # Add structured sources
            "source_catalog": source_catalog,
        }

        # If outline has been generated, add it to result
        if hasattr(self, "_current_outline"):
            result["outline"] = self._current_outline
            delattr(self, "_current_outline")
        if hasattr(self, "_current_source_catalog"):
            delattr(self, "_current_source_catalog")

        return result

    def _get_structured_sources(self) -> dict[str, list[dict]]:
        """Extract structured sources for frontend display"""
        sources = {"web": [], "rag": []}

        if not self.citation_manager:
            return sources

        all_citations = self.citation_manager.get_all_citations()

        for citation in all_citations.values():
            tool_type = citation.get("tool_type", "").lower()

            if tool_type == "web_search":
                # Extract web links
                web_items = citation.get("web_sources", []) or citation.get("citations", [])
                # If individual items not found, try to use the citation itself if it looks like a web source
                if not web_items and citation.get("url"):
                    web_items = [citation]

                for item in web_items:
                    sources["web"].append(
                        {
                            "title": item.get("title", "Untitled"),
                            "url": item.get("url", ""),
                            "content": item.get("snippet", "")
                            or item.get("content", "")
                            or citation.get("summary", ""),
                            "id": str(item.get("id", "")) or citation.get("citation_id", ""),
                        }
                    )
            elif tool_type in ("rag_naive", "rag_hybrid", "query_item"):
                # Extract RAG documents
                rag_items = citation.get("sources", [])
                for item in rag_items:
                    source_title = (
                        item.get("title", "")
                        or item.get("source_file", "")
                        or item.get("source", "")
                    )
                    sources["rag"].append(
                        {
                            "title": source_title,
                            "source": item.get("source_file", "") or item.get("source", ""),
                            "content": item.get("content_preview", ""),
                            "page": item.get("page", ""),
                            "chunk_id": item.get("chunk_id", ""),
                            "kb_name": citation.get("kb_name", ""),
                        }
                    )

        return sources

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        if not text:
            return []
        urls = re.findall(r"https?://[^\s)\]]+", text)
        seen = set()
        ordered = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                ordered.append(url)
        return ordered

    async def _deduplicate_blocks(self, blocks: list[TopicBlock]) -> list[TopicBlock]:
        if len(blocks) <= 1:
            return blocks
        system_prompt = self.get_prompt("system", "role")
        if not system_prompt:
            raise ValueError(
                "ReportingAgent missing system prompt, please configure system.role in prompts/{lang}/reporting_agent.yaml"
            )
        user_prompt = self.get_prompt("process", "deduplicate")
        if not user_prompt:
            raise ValueError(
                "ReportingAgent missing deduplicate prompt, please configure process.deduplicate in prompts/{lang}/reporting_agent.yaml"
            )
        topics_text = "\n".join(
            [f"{i + 1}. {b.sub_topic}: {b.overview[:200]}" for i, b in enumerate(blocks)]
        )
        filled = self._safe_format(user_prompt, topics=topics_text, total_topics=len(blocks))
        resp = await self.call_llm(filled, system_prompt, stage="deduplicate", verbose=False)
        data = extract_json_from_text(resp)
        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["keep_indices"])
            keep_indices = obj.get("keep_indices", [])
            return [blocks[i] for i in keep_indices if isinstance(i, int) and i < len(blocks)]
        except Exception:
            return blocks

    async def _generate_outline(self, topic: str, blocks: list[TopicBlock]) -> dict[str, Any]:
        """Generate report outline based on complete subtopic, overview and all tool_trace summaries

        Supports three-level heading system:
        - Level 1 (#): Report main title
        - Level 2 (##): Main sections (Introduction, Core Sections, Conclusion)
        - Level 3 (###): Subsections within each section
        """
        system_prompt = self.get_prompt("system", "role")
        if not system_prompt:
            raise ValueError(
                "ReportingAgent missing system prompt, please configure system.role in prompts/{lang}/reporting_agent.yaml"
            )
        user_prompt = self.get_prompt("process", "generate_outline")
        if not user_prompt:
            raise ValueError(
                "ReportingAgent missing generate_outline prompt, please configure process.generate_outline in prompts/{lang}/reporting_agent.yaml"
            )

        # Build complete topic information, including subtopic, overview and all tool_trace summaries
        topics_data = []
        for i, block in enumerate(blocks, 1):
            topic_info = {
                "index": i,
                "block_id": block.block_id,
                "sub_topic": block.sub_topic,
                "overview": block.overview,
                "tool_summaries": (
                    [trace.summary for trace in block.tool_traces] if block.tool_traces else []
                ),
            }
            topics_data.append(topic_info)

        import json as _json

        topics_json = _json.dumps(topics_data, ensure_ascii=False, indent=2)
        # Use safe_format to avoid conflicts with LaTeX braces like {\rho}, {L}
        filled = self._safe_format(
            user_prompt, topic=topic, topics_json=topics_json, total_topics=len(blocks)
        )

        resp = await self.call_llm(filled, system_prompt, stage="generate_outline", verbose=False)
        data = extract_json_from_text(resp)
        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["title", "introduction", "sections", "conclusion"])
            # Ensure title uses markdown format (# prefix)
            if not obj.get("title", "").startswith("#"):
                obj["title"] = f"# {obj.get('title', topic)}"
            # Ensure introduction and conclusion use markdown format (## prefix)
            if obj.get("introduction") and not obj["introduction"].startswith("##"):
                obj["introduction"] = f"## {obj['introduction']}"
            if obj.get("conclusion") and not obj["conclusion"].startswith("##"):
                obj["conclusion"] = f"## {obj['conclusion']}"

            # Process sections to ensure proper formatting
            for section in obj.get("sections", []):
                # Ensure section title has ## prefix
                if section.get("title") and not section["title"].startswith("##"):
                    section["title"] = f"## {section['title']}"
                # Process subsections if present
                for subsection in section.get("subsections", []):
                    if subsection.get("title") and not subsection["title"].startswith("###"):
                        subsection["title"] = f"### {subsection['title']}"

            return obj
        except Exception:
            # Fallback to default outline with subsections
            return self._create_default_outline(topic, blocks)

    def _create_default_outline(self, topic: str, blocks: list[TopicBlock]) -> dict[str, Any]:
        """Create a default outline with three-level heading structure"""
        sections = []
        for i, b in enumerate(blocks, 1):
            section = {
                "title": f"## {i}. {b.sub_topic}",
                "instruction": f"Provide detailed introduction to {b.sub_topic}, including core concepts, key mechanisms, and practical applications",
                "block_id": b.block_id,
                "subsections": [
                    {
                        "title": f"### {i}.1 Core Concepts and Definitions",
                        "instruction": f"Explain the fundamental concepts and definitions related to {b.sub_topic}",
                    },
                    {
                        "title": f"### {i}.2 Key Mechanisms and Principles",
                        "instruction": f"Analyze the underlying mechanisms and theoretical principles of {b.sub_topic}",
                    },
                ],
            }
            sections.append(section)

        return {
            "title": f"# {topic}",
            "introduction": "## Introduction",
            "introduction_instruction": "Present the research background, motivation, objectives, and report structure",
            "sections": sections,
            "conclusion": "## Conclusion and Future Directions",
            "conclusion_instruction": "Summarize core findings, research contributions, limitations, and future directions",
        }

    def _ser_block(self, b: TopicBlock) -> dict[str, Any]:
        """Serialize TopicBlock to dictionary, including complete tool traces

        If self._citation_map is available (built by _build_citation_number_map),
        each trace will include a ref_number field for inline citation use.
        """
        traces = []
        for t in b.tool_traces:
            cid = getattr(t, "citation_id", None) or f"CIT-{b.block_id.split('_')[-1]}-01"
            trace_data = {
                "citation_id": cid,
                "tool_type": t.tool_type,
                "query": t.query,
                "raw_answer": t.raw_answer,  # Include complete original response
                "summary": t.summary,
            }
            # Add ref_number if citation map is available
            if hasattr(self, "_citation_map") and self._citation_map:
                ref_num = self._citation_map.get(cid, 0)
                if ref_num > 0:
                    trace_data["ref_number"] = ref_num
            traces.append(trace_data)
        return {
            "block_id": b.block_id,
            "sub_topic": b.sub_topic,
            "overview": b.overview,
            "traces": traces,
        }

    def _build_citation_table(self, block: TopicBlock) -> str:
        """Build a clear citation reference table for LLM to understand the mapping

        This creates an easy-to-read table showing:
        - Reference number to use in text (use [N] format)
        - Tool type
        - Query summary (truncated)

        Args:
            block: TopicBlock containing tool traces

        Returns:
            Formatted citation table string
        """
        if not block.tool_traces:
            return "  (No citations available for this section)"

        lines = []
        for trace in block.tool_traces:
            cid = getattr(trace, "citation_id", None)
            if not cid:
                continue

            ref_num = self._citation_map.get(cid, 0) if hasattr(self, "_citation_map") else 0
            if ref_num <= 0:
                continue

            # Truncate query for readability
            query_preview = trace.query[:60] + "..." if len(trace.query) > 60 else trace.query
            tool_display = {
                "rag_naive": "RAG",
                "rag_hybrid": "Hybrid RAG",
                "query_item": "KB Query",
                "paper_search": "Paper",
                "web_search": "Web",
                "run_code": "Code",
            }.get(trace.tool_type.lower(), trace.tool_type)

            # Use clear format: cite as [N] -> source description
            lines.append(f"  - Cite as [{ref_num}] → ({tool_display}) {query_preview}")

        if not lines:
            return "  (No citations available for this section)"

        return "\n".join(lines)

    async def _write_introduction(
        self, topic: str, blocks: list[TopicBlock], outline: dict[str, Any]
    ) -> str:
        """Write report introduction section"""
        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are an academic writing expert specializing in writing the introduction section of research reports.",
        )
        tmpl = self.get_prompt("process", "write_introduction", "")
        if not tmpl:
            raise ValueError(
                "Cannot get introduction writing prompt template, report generation failed"
            )

        import json as _json

        # Prepare context for introduction: overview information of all topics
        topics_summary = []
        for b in blocks:
            topics_summary.append(
                {"sub_topic": b.sub_topic, "overview": b.overview, "tool_count": len(b.tool_traces)}
            )

        # Use introduction_instruction if available, otherwise fall back to introduction title
        intro_instruction = outline.get("introduction_instruction", "") or outline.get(
            "introduction", ""
        )

        # Use safe_format to avoid conflicts with LaTeX braces like {\rho}, {L}
        topics_summary_json = _json.dumps(topics_summary, ensure_ascii=False, indent=2)
        filled = self._safe_format(
            tmpl,
            topic=topic,
            introduction_instruction=intro_instruction,
            topics_summary=topics_summary_json,
            total_topics=len(blocks),
        )

        resp = await self.call_llm(filled, system_prompt, stage="write_introduction", verbose=False)
        try:
            data = extract_json_from_text(resp)
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["introduction"])
            intro = obj.get("introduction", "")
            if isinstance(intro, str) and intro.strip():
                return intro
        except Exception:
            # Fallback: if JSON parsing fails, check if the response itself looks like content
            # Only accept if it's substantial enough
            if len(resp) > 50:
                self.logger.warning(
                    "Introduction JSON parsing failed, using raw response as fallback"
                )
                return resp.strip()

        raise ValueError("LLM returned empty or invalid introduction field")

    async def _write_section_body(
        self, topic: str, block: TopicBlock, section_outline: dict[str, Any]
    ) -> str:
        """Write main content of a single section"""
        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are an academic writing expert specializing in writing chapter content for research reports.",
        )
        tmpl = self.get_prompt("process", "write_section_body", "")
        if not tmpl:
            raise ValueError("Cannot get section writing prompt template, report generation failed")

        import json as _json

        block_data = self._ser_block(block)

        # Dynamically build citation instructions based on configuration
        if self.enable_inline_citations:
            # Build clear citation reference table for this block
            citation_table = self._build_citation_table(block)

            citation_instruction_template = self.get_prompt("citation", "enabled_instruction")
            if citation_instruction_template:
                citation_instruction = citation_instruction_template.format(
                    citation_table=citation_table
                )
            else:
                # Fallback if YAML not configured
                citation_instruction = f"**Citation Reference Table**:\n{citation_table}"
            citation_output_hint = ", citations"
        else:
            citation_instruction = self.get_prompt("citation", "disabled_instruction") or ""
            citation_output_hint = ""

        # Use safe_format to avoid conflicts with LaTeX braces like {\rho}, {L}
        block_data_json = _json.dumps(block_data, ensure_ascii=False, indent=2)
        filled = self._safe_format(
            tmpl,
            topic=topic,
            section_title=section_outline.get("title", block.sub_topic),
            section_instruction=section_outline.get("instruction", ""),
            block_data=block_data_json,
            min_section_length=self.reporting_config.get("min_section_length", 500),
            citation_instruction=citation_instruction,
            citation_output_hint=citation_output_hint,
        )

        resp = await self.call_llm(filled, system_prompt, stage="write_section_body", verbose=False)
        try:
            data = extract_json_from_text(resp)
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["section_content"])
            content = obj.get("section_content", "")
            if isinstance(content, str) and content.strip():
                return content
        except Exception:
            # Fallback: if JSON parsing fails, assume the LLM returned raw markdown
            if len(resp) > 100:
                self.logger.warning(
                    f"Section {section_outline.get('title')} JSON parsing failed, using raw response as fallback"
                )
                return resp.strip()

        raise ValueError("LLM returned empty or invalid section_content field")

    async def _write_conclusion(
        self, topic: str, blocks: list[TopicBlock], outline: dict[str, Any]
    ) -> str:
        """Write report conclusion section"""
        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are an academic writing expert specializing in writing the conclusion section of research reports.",
        )
        tmpl = self.get_prompt("process", "write_conclusion", "")
        if not tmpl:
            raise ValueError(
                "Cannot get conclusion writing prompt template, report generation failed"
            )

        import json as _json

        # Prepare context for conclusion: key findings of all topics
        topics_findings = []
        for b in blocks:
            findings = {
                "sub_topic": b.sub_topic,
                "overview": b.overview,
                "key_findings": [
                    t.summary for t in b.tool_traces[:3]
                ],  # Top 3 key findings for each topic
            }
            topics_findings.append(findings)

        # Use conclusion_instruction if available, otherwise fall back to conclusion title
        conclusion_instruction = outline.get("conclusion_instruction", "") or outline.get(
            "conclusion", ""
        )

        # Use safe_format to avoid conflicts with LaTeX braces like {\rho}, {L}
        topics_findings_json = _json.dumps(topics_findings, ensure_ascii=False, indent=2)
        filled = self._safe_format(
            tmpl,
            topic=topic,
            conclusion_instruction=conclusion_instruction,
            topics_findings=topics_findings_json,
            total_topics=len(blocks),
        )

        resp = await self.call_llm(filled, system_prompt, stage="write_conclusion", verbose=False)
        try:
            data = extract_json_from_text(resp)
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["conclusion"])
            conclusion = obj.get("conclusion", "")
            if isinstance(conclusion, str) and conclusion.strip():
                return conclusion
        except Exception:
            # Fallback
            if len(resp) > 50:
                self.logger.warning(
                    "Conclusion JSON parsing failed, using raw response as fallback"
                )
                return resp.strip()

        raise ValueError("LLM returned empty or invalid conclusion field")

    def _build_citation_number_map(self, blocks: list[TopicBlock]) -> dict[str, int]:
        """Build citation_id to reference number mapping with deduplication

        This method delegates to CitationManager for unified mapping logic.
        The mapping is built once and cached in CitationManager.

        Returns:
            Dictionary mapping citation_id (e.g., "CIT-1-01") to reference number (e.g., 1)
        """
        if self.citation_manager:
            # Use CitationManager's unified mapping (single source of truth)
            return self.citation_manager.build_ref_number_map()

        # Fallback: build from blocks when no CitationManager available
        citation_map = {}

        def extract_citation_number(cit_id):
            try:
                if cit_id.startswith("PLAN-"):
                    num = int(cit_id.replace("PLAN-", ""))
                    return (0, 0, num)
                parts_list = cit_id.replace("CIT-", "").split("-")
                if len(parts_list) == 2:
                    return (1, int(parts_list[0]), int(parts_list[1]))
            except:
                pass
            return (999, 999, 999)

        all_citations = []
        for block in blocks:
            if block.tool_traces:
                for trace in block.tool_traces:
                    citation_id = getattr(trace, "citation_id", None)
                    if citation_id and citation_id not in [c["citation_id"] for c in all_citations]:
                        all_citations.append({"citation_id": citation_id})

        all_citations.sort(key=lambda x: extract_citation_number(x["citation_id"]))

        for idx, cit in enumerate(all_citations, 1):
            citation_map[cit["citation_id"]] = idx

        return citation_map

    def _generate_references(self, blocks: list[TopicBlock]) -> str:
        """Generate References section"""
        catalog = getattr(self, "_current_source_catalog", None)
        if isinstance(catalog, list) and catalog:
            parts = ["## References\n\n"]
            for item in sorted(catalog, key=lambda x: int(x.get("ref_number", 0))):
                ref_number = int(item.get("ref_number", 0))
                if ref_number <= 0:
                    continue
                title = (item.get("title") or f"Reference {ref_number}").strip()
                url = (item.get("url") or "").strip()
                if url and url.startswith(("http://", "https://")):
                    parts.append(f"[{ref_number}] [{title}]({url})\n\n")
                else:
                    parts.append(f"[{ref_number}] {title}\n\n")
            return (
                "".join(parts) if len(parts) > 1 else "## References\n\n*No citations available.*\n"
            )

        # If using CitationManager, generate from JSON file
        if self.citation_manager:
            return self._generate_references_from_manager(blocks)

        # Otherwise use original method of extracting from blocks (backward compatible)
        return self._generate_references_from_blocks(blocks)

    def _get_citation_dedup_key(self, citation: dict, paper: dict = None) -> str:
        """Generate unique key for citation deduplication

        Args:
            citation: The citation dict
            paper: Optional paper dict for paper_search citations

        Returns:
            Unique string key for deduplication
        """
        tool_type = citation.get("tool_type", "").lower()

        if tool_type == "paper_search" and paper:
            # For papers: use title + first author (normalized)
            title = paper.get("title", "").lower().strip()
            authors = paper.get("authors", "").lower().strip()
            # Extract first author if multiple
            first_author = authors.split(",")[0].strip() if authors else ""
            return f"paper:{title}|{first_author}"
        elif tool_type == "paper_search":
            # Fallback for paper_search without paper dict
            title = citation.get("title", "").lower().strip()
            authors = citation.get("authors", "").lower().strip()
            first_author = authors.split(",")[0].strip() if authors else ""
            return f"paper:{title}|{first_author}"
        else:
            # For RAG/web_search/etc: use tool_type + query (normalized)
            query = citation.get("query", "").lower().strip()
            # Use first 100 chars of query for dedup
            return f"{tool_type}:{query[:100]}"

    def _generate_references_from_manager(self, blocks: list[TopicBlock]) -> str:
        """Generate References section from CitationManager in academic paper style

        Uses CitationManager's ref_number_map to ensure consistency between
        in-text citations and the References section.

        Format:
        - Ordered by reference number (consistent with in-text citations)
        - Paper citations: APA format
        - RAG/Query citations: Tool name, query, summary
        - Web search: Tool name, query, summary + collapsible links
        """
        parts = ["## References\n\n"]

        # Get all citations and the ref_number_map
        all_citations = self.citation_manager.get_all_citations()

        if not all_citations:
            return "## References\n\n*No citations available.*\n"

        # Get the ref_number_map from CitationManager (single source of truth)
        ref_map = self.citation_manager.get_ref_number_map()

        # Build reverse map: ref_number -> (citation_id, paper_idx or None)
        # This groups citations by their ref_number for consistent output
        ref_to_citations: dict[int, list[tuple[str, dict, dict | None]]] = {}

        for citation_id, citation in all_citations.items():
            tool_type = citation.get("tool_type", "").lower()

            if tool_type == "paper_search":
                papers = citation.get("papers", [])
                if papers:
                    for paper_idx, paper in enumerate(papers):
                        # Check if this paper has a ref_number
                        paper_ref_key = f"{citation_id}-{paper_idx + 1}"
                        ref_num = ref_map.get(paper_ref_key) or ref_map.get(citation_id, 0)
                        if ref_num > 0:
                            if ref_num not in ref_to_citations:
                                ref_to_citations[ref_num] = []
                            ref_to_citations[ref_num].append((citation_id, citation, paper))
                else:
                    ref_num = ref_map.get(citation_id, 0)
                    if ref_num > 0:
                        if ref_num not in ref_to_citations:
                            ref_to_citations[ref_num] = []
                        ref_to_citations[ref_num].append((citation_id, citation, None))
            else:
                ref_num = ref_map.get(citation_id, 0)
                if ref_num > 0:
                    if ref_num not in ref_to_citations:
                        ref_to_citations[ref_num] = []
                    ref_to_citations[ref_num].append((citation_id, citation, None))

        # Generate references in order of ref_number.
        # Keep one entry per line to avoid mixed/nested reference blocks.
        for ref_num in sorted(ref_to_citations.keys()):
            entries = ref_to_citations[ref_num]
            if not entries:
                continue

            # Use the first entry for this ref_number (others are duplicates)
            _, citation, paper = entries[0]
            tool_type = citation.get("tool_type", "").lower()
            line = ""

            if tool_type == "paper_search":
                if paper:
                    line = self._format_single_paper_apa(paper)
                else:
                    line = self._format_paper_citation_apa(citation)
            elif tool_type == "web_search":
                line = self._format_web_search_citation(citation)
            elif tool_type in ("rag_naive", "rag_hybrid", "query_item"):
                line = self._format_rag_citation(citation)
            elif tool_type == "run_code":
                query = citation.get("query", "")
                summary = citation.get("summary", "")
                if summary:
                    line = f"Code Execution: {summary[:260]}"
                elif query:
                    line = f"Code Execution: {query[:260]}"
                else:
                    line = "Code Execution"
            else:
                # Generic format
                query = citation.get("query", "")
                summary = citation.get("summary", "")
                clean_summary = self._strip_markdown(summary)
                if clean_summary:
                    line = f"{tool_type}: {clean_summary[:260]}"
                elif query:
                    line = f"{tool_type}: {query[:260]}"
                else:
                    line = tool_type

            line = " ".join((line or "").split())
            if line:
                parts.append(f"[{ref_num}] {line}\n")

        return "".join(parts)

    def _format_single_paper_apa(self, paper: dict) -> str:
        """Format a single paper reference as a compact line."""
        title = (paper.get("title") or "Untitled").strip()
        url = paper.get("url", "")
        doi = paper.get("doi", "")
        if doi:
            return f"[{title}](https://doi.org/{doi})"
        if url:
            return f"[{title}]({url})"
        return title

    def _format_paper_citation_apa(self, citation: dict) -> str:
        """Format paper reference (fallback for citations without papers array)."""
        title = (citation.get("title") or "Untitled").strip()
        url = citation.get("url", "")
        doi = citation.get("doi", "")
        if doi:
            return f"[{title}](https://doi.org/{doi})"
        if url:
            return f"[{title}]({url})"
        return title

    def _format_web_search_citation(self, citation: dict) -> str:
        """Format web search citation as a single-line markdown reference."""
        web_sources = citation.get("web_sources", []) or citation.get("citations", [])

        if not web_sources:
            query = (citation.get("query", "") or "").strip()
            return query or "Web Source"

        best = None
        for source in web_sources:
            if not isinstance(source, dict):
                continue
            if source.get("url") or source.get("title"):
                best = source
                break
        best = best or {}
        title = (best.get("title") or best.get("url") or "Web Source").strip()
        url = (best.get("url") or "").strip()
        if url:
            return f"[{title}]({url})"
        return title

    def _format_rag_citation(self, citation: dict) -> str:
        """Format RAG/Query citation as a single-line markdown reference."""
        sources = citation.get("sources", [])
        if not sources:
            query = (citation.get("query", "") or "").strip()
            return query or "RAG Source"

        best = sources[0] if isinstance(sources[0], dict) else {}
        title = (
            best.get("title") or best.get("source_file") or best.get("source") or "Document"
        ).strip()
        page = (best.get("page") or "").strip()
        url = (best.get("url") or "").strip()
        if page:
            title = f"{title} (Page {page})"
        if url and url.startswith(("http://", "https://")):
            return f"[{title}]({url})"
        return title

    def _strip_markdown(self, text: str) -> str:
        """Strip markdown formatting from text to get plain text"""
        import re

        if not text:
            return ""

        # Remove bold/italic markers
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # **bold**
        text = re.sub(r"\*([^*]+)\*", r"\1", text)  # *italic*
        text = re.sub(r"__([^_]+)__", r"\1", text)  # __bold__
        text = re.sub(r"_([^_]+)_", r"\1", text)  # _italic_

        # Remove headers
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

        # Remove links but keep text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

        # Remove inline code
        text = re.sub(r"`([^`]+)`", r"\1", text)

        # Remove bullet points
        text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)

        # Remove numbered lists
        text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)

        # Remove blockquotes
        text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

        # Normalize whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"  +", " ", text)

        return text.strip()

    def _format_code_citation(self, citation: dict) -> str:
        """Format code execution citation"""
        query = citation.get("query", "")  # This is usually the code
        summary = citation.get("summary", "")

        result = "**Code Execution**\n\n"
        if query:
            # Truncate long code
            code_preview = query[:300] + ("..." if len(query) > 300 else "")
            result += f"- **Code**: `{code_preview}`\n"
        if summary:
            summary_text = summary[:300] + ("..." if len(summary) > 300 else "")
            result += f"- **Result**: {summary_text}\n"

        return result

    def _generate_references_from_blocks(self, blocks: list[TopicBlock]) -> str:
        """Generate References section from blocks (fallback mode, one line per item)."""
        parts = ["## References\n\n"]

        # Collect all citations
        all_citations = []
        for block in blocks:
            if block.tool_traces:
                for trace in block.tool_traces:
                    citation_id = (
                        getattr(trace, "citation_id", None)
                        or f"CIT-{block.block_id.split('_')[-1]}-01"
                    )
                    all_citations.append(
                        {"citation_id": citation_id, "block": block, "trace": trace}
                    )

        if not all_citations:
            return "## References\n\n*No citations available.*\n"

        # Sort by citation_id (extract numeric parts for sorting)
        def extract_citation_number(cit_id):
            try:
                if cit_id.startswith("PLAN-"):
                    num = int(cit_id.replace("PLAN-", ""))
                    return (0, 0, num)
                # CIT-X-XX format
                parts_list = cit_id.replace("CIT-", "").split("-")
                if len(parts_list) == 2:
                    return (1, int(parts_list[0]), int(parts_list[1]))
            except:
                pass
            return (999, 999, 999)

        all_citations.sort(key=lambda x: extract_citation_number(x["citation_id"]))

        # Generate compact numbered references (one line per reference).
        for idx, cit in enumerate(all_citations, 1):
            trace = cit["trace"]
            tool_type = trace.tool_type.lower() if trace.tool_type else ""

            tool_display = {
                "rag_naive": "RAG Retrieval",
                "rag_hybrid": "Hybrid RAG Retrieval",
                "query_item": "Knowledge Base Query",
                "paper_search": "Paper Search",
                "web_search": "Web Search",
                "run_code": "Code Execution",
            }.get(tool_type, tool_type)

            line = trace.query or trace.summary or ""
            if trace.summary:
                line = trace.summary
            line = " ".join((line or "").split())
            if len(line) > 280:
                line = line[:280] + "..."
            if line:
                parts.append(f"[{idx}] {tool_display}: {line}\n")
            else:
                parts.append(f"[{idx}] {tool_display}\n")

        return "".join(parts)

    def _convert_citation_format(self, text: str) -> str:
        """
        Normalize citation markers to plain [N] format.

        Handles:
        - [ref=N] -> [N]
        - [[N]](#ref-N) -> [N]
        - [N](#ref-N) -> [N]

        Args:
            text: Text with citations in various formats

        Returns:
            Text with plain [N] citations
        """
        import re

        text = re.sub(r"\[ref=(\d+)\]", r"[\1]", text)
        text = re.sub(r"\[\[(\d+)\]\]\(#ref-\d+\)", r"[\1]", text)
        text = re.sub(r"\[(\d+)\]\(#ref-\d+\)", r"[\1]", text)

        return text

    def _validate_and_fix_citations(self, text: str) -> tuple[str, dict]:
        """
        Validate citations in text and fix invalid ones.

        Args:
            text: Text with citations

        Returns:
            Tuple of (fixed_text, validation_result)
        """
        import re

        # Get valid ref_numbers
        valid_refs = set()
        if hasattr(self, "_citation_map") and self._citation_map:
            valid_refs = set(self._citation_map.values())

        # Find all citations in plain [N] format
        pattern = r"\[(\d+)\]"
        found_citations = re.findall(pattern, text)

        valid = []
        invalid = []

        for ref in found_citations:
            try:
                num = int(ref)
                if num in valid_refs:
                    valid.append(num)
                else:
                    invalid.append(num)
            except ValueError:
                invalid.append(ref)

        validation_result = {
            "valid_citations": valid,
            "invalid_citations": invalid,
            "is_valid": len(invalid) == 0,
            "total_found": len(found_citations),
        }

        return text, validation_result

    async def _write_report(
        self, topic: str, blocks: list[TopicBlock], outline: dict[str, Any]
    ) -> str:
        """Write complete report using step-by-step method with three-level heading support"""
        parts = []

        # Build citation number map before writing (for consistent ref_number in traces)
        if self.enable_inline_citations:
            self._citation_map = self._build_citation_number_map(blocks)
            print(f"  📋 Built citation map with {len(self._citation_map)} entries")
        else:
            self._citation_map = {}

        # 1. Add main title (from outline, or use topic if not available)
        title = outline.get("title", f"# {topic}")
        if not title.startswith("#"):
            title = f"# {title}"
        parts.append(f"{title}\n\n")

        # 2. Write introduction
        print("  📝 Writing introduction...")
        self._notify_progress(
            getattr(self, "_progress_callback", None),
            "writing_section",
            current_section="Introduction",
            section_index=0,
            total_sections=len(outline.get("sections", [])) + 2,  # +2 for intro and conclusion
        )
        introduction = await self._write_introduction(topic, blocks, outline)
        # Get introduction title from outline, or use default if not available
        intro_title = outline.get("introduction", "## Introduction")
        if not intro_title.startswith("##"):
            intro_title = f"## {intro_title}"
        parts.append(f"{intro_title}\n\n")
        parts.append(introduction)
        parts.append("\n\n")

        # 3. Write each section with subsection support
        sections = outline.get("sections", [])
        for i, section in enumerate(sections, 1):
            block_id = section.get("block_id")
            block = next((b for b in blocks if b.block_id == block_id), None)
            if not block:
                print(
                    f"  ⚠️  Warning: Cannot find topic block with block_id={block_id}, skipping this section"
                )
                continue

            section_title = section.get("title", block.sub_topic)
            # Clean section title for display (remove markdown markers)
            display_title = section_title.replace("##", "").strip()
            print(f"  📝 Writing section {i}/{len(sections)}: {section_title}...")
            self._notify_progress(
                getattr(self, "_progress_callback", None),
                "writing_section",
                current_section=display_title,
                section_index=i,  # 1-based, after introduction
                total_sections=len(sections) + 2,  # +2 for intro and conclusion
            )

            # Check if section has subsections defined in outline
            subsections = section.get("subsections", [])

            if subsections:
                # Write section with explicit subsection structure
                section_content = await self._write_section_with_subsections(
                    topic, block, section, subsections
                )
            else:
                # Write section normally (LLM will generate its own subsection structure)
                section_content = await self._write_section_body(topic, block, section)

            # Section content already includes ## level title, append directly
            parts.append(section_content)
            parts.append("\n\n")

        # 4. Write conclusion
        print("  📝 Writing conclusion...")
        total_sections = len(sections) + 2
        self._notify_progress(
            getattr(self, "_progress_callback", None),
            "writing_section",
            current_section="Conclusion",
            section_index=total_sections - 1,  # Last section
            total_sections=total_sections,
        )
        conclusion = await self._write_conclusion(topic, blocks, outline)
        # Get conclusion title from outline, or use default if not available
        conclusion_title = outline.get("conclusion", "## Conclusion")
        if not conclusion_title.startswith("##"):
            conclusion_title = f"## {conclusion_title}"
        parts.append(f"{conclusion_title}\n\n")
        parts.append(conclusion)
        parts.append("\n\n")

        # 5. Generate References based on configuration
        if self.enable_citation_list:
            print("  📝 Generating citation list...")
            references = self._generate_references(blocks)
            parts.append(references)
        else:
            print("  ℹ️  Citation list disabled, skipping generation")

        # Combine all parts
        report = "".join(parts)

        # 6. Post-process citations (convert [N] to [[N]](#ref-N) format)
        if self.enable_inline_citations:
            print("  🔗 Converting citation format...")
            report = self._convert_citation_format(report)

            # Validate and fix invalid citations
            print("  ✓ Validating citations...")
            report, validation = self._validate_and_fix_citations(report)

            if not validation["is_valid"]:
                print(
                    f"  ⚠️  Removed {len(validation['invalid_citations'])} invalid citations: {validation['invalid_citations']}"
                )
            else:
                print(f"  ✓ All {validation['total_found']} citations are valid")

        return report

    async def _write_section_with_subsections(
        self,
        topic: str,
        block: TopicBlock,
        section: dict[str, Any],
        subsections: list[dict[str, Any]],
    ) -> str:
        """Write a section that has explicitly defined subsections in the outline

        This method writes the section as a whole, passing subsection structure to the LLM
        to guide the content organization while maintaining coherence.
        """
        import json as _json

        # Enhance section instruction with subsection information
        subsection_info = []
        for j, sub in enumerate(subsections, 1):
            subsection_info.append(
                {
                    "title": sub.get("title", f"### Subsection {j}"),
                    "instruction": sub.get("instruction", ""),
                }
            )

        # Create enhanced section data with subsection guidance
        enhanced_section = {
            "title": section.get("title", block.sub_topic),
            "instruction": section.get("instruction", ""),
            "subsection_structure": subsection_info,
        }

        # Prepare block data with subsection hints
        block_data = self._ser_block(block)
        block_data["expected_subsections"] = subsection_info

        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are an academic writing expert specializing in writing comprehensive research report sections with structured subsections.",
        )
        tmpl = self.get_prompt("process", "write_section_body", "")
        if not tmpl:
            raise ValueError("Cannot get section writing prompt template, report generation failed")

        # Build enhanced instruction including subsection structure
        section_instruction = section.get("instruction", "")
        if subsection_info:
            subsection_guide = "\n\n**Expected subsection structure:**\n"
            for sub in subsection_info:
                subsection_guide += f"- {sub['title']}: {sub['instruction']}\n"
            section_instruction += subsection_guide

        # Dynamically build citation instructions based on configuration
        if self.enable_inline_citations:
            # Build clear citation reference table for this block
            citation_table = self._build_citation_table(block)

            citation_instruction_template = self.get_prompt("citation", "enabled_instruction")
            if citation_instruction_template:
                citation_instruction = citation_instruction_template.format(
                    citation_table=citation_table
                )
            else:
                # Fallback if YAML not configured
                citation_instruction = f"**Citation Reference Table**:\n{citation_table}"
            citation_output_hint = ", citations"
        else:
            citation_instruction = self.get_prompt("citation", "disabled_instruction") or ""
            citation_output_hint = ""

        # Use safe_format to avoid conflicts with LaTeX braces like {\rho}, {L}
        block_data_json = _json.dumps(block_data, ensure_ascii=False, indent=2)
        filled = self._safe_format(
            tmpl,
            topic=topic,
            section_title=section.get("title", block.sub_topic),
            section_instruction=section_instruction,
            block_data=block_data_json,
            min_section_length=self.reporting_config.get("min_section_length", 800),
            citation_instruction=citation_instruction,
            citation_output_hint=citation_output_hint,
        )

        resp = await self.call_llm(
            filled,
            system_prompt,
            stage="write_section_with_subsections",
            verbose=False,
        )
        data = extract_json_from_text(resp)

        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["section_content"])
            content = obj.get("section_content", "")
            if isinstance(content, str) and content.strip():
                return content
            raise ValueError("LLM returned empty or invalid section_content field")
        except Exception as e:
            # Fallback: if JSON parsing fails, assume the LLM returned raw markdown
            if len(resp) > 100:
                self.logger.warning(
                    f"Section {section.get('title')} JSON parsing failed, using raw response as fallback: {e}"
                )
                return resp.strip()

            raise ValueError(
                f"Unable to parse LLM returned section content: {e!s}. Report generation failed."
            )

    def _notify_progress(
        self, callback: Callable[[dict[str, Any]], None] | None, status: str, **payload: Any
    ) -> None:
        if not callback:
            return
        event = {"status": status}
        event.update({k: v for k, v in payload.items() if v is not None})
        try:
            callback(event)
        except Exception:
            pass

    async def _write_summary_report(self, topic: str, blocks: list[TopicBlock]) -> str:
        """Write a comprehensive summary report from blocks (for Fast Research)"""
        # Collect all context
        context_parts = []
        for b in blocks:
            for t in b.tool_traces:
                if t.tool_type == "web_search":
                    # For web search, include query and snippet/summary
                    context_parts.append(
                        f"Source: Web Search\nQuery: {t.query}\nContent: {t.summary}"
                    )
                elif t.tool_type in ("rag_naive", "rag_hybrid", "query_item"):
                    context_parts.append(
                        f"Source: Knowledge Base\nQuery: {t.query}\nContent: {t.summary}"
                    )

        full_context = "\n\n".join(context_parts)

        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are a helpful AI assistant capable of synthesizing information from multiple sources.",
        )

        # Simple prompt for summary
        user_prompt = (
            f"Please provide a comprehensive answer to the topic: {topic}\n\n"
            f"Based STRICTLY on the following research results:\n\n{full_context}\n\n"
            f"Instructions:\n"
            f"- Synthesize the information into a cohesive summary.\n"
            f"- Do not just list links or sources.\n"
            f"- Provide a clear and readable response.\n"
            f"- If the research results are insufficient/irrelevant, state that clearly."
        )

        # Reuse call_llm
        resp = await self.call_llm(
            user_prompt, system_prompt, stage="write_summary_report", verbose=False
        )

        # Clean up response (if it's JSON wrapped, though typically call_llm returns string processing result if configured, but base_agent usually returns string)
        # BaseAgent.call_llm returns string.

        return resp


__all__ = ["ReportingAgent"]
