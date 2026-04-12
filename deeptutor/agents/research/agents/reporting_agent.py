#!/usr/bin/env python
"""
ReportingAgent - Report generation Agent (DR-in-KG 2.0)
- Deduplication and cleaning
- Generate linear outline (introduction → sections → conclusion)
- Write final report (prefer LLM JSON return markdown, fallback to local assembly on failure)
- Inline citations and References anchors (based on citation_id)
"""

from __future__ import annotations

from collections.abc import Callable
import re
from string import Template
from typing import Any

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.research.data_structures import DynamicTopicQueue, TopicBlock
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..utils.json_utils import ensure_json_dict, ensure_keys, extract_json_from_text


class ReportingAgent(BaseAgent):
    """Report generation Agent"""

    @staticmethod
    def _build_trace_meta(label: str, trace_kind: str = "llm_generation") -> dict[str, Any]:
        return build_trace_metadata(
            call_id=new_call_id("research-report"),
            phase="reporting",
            label=label,
            call_kind=trace_kind,
            trace_role="response",
            trace_kind=trace_kind,
        )

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
        self,
        config: dict[str, Any],
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
    ):
        language = config.get("system", {}).get("language", "zh")
        super().__init__(
            module_name="research",
            agent_name="reporting_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            config=config,
        )
        self.reporting_config = config.get("reporting", {})
        self.citation_manager = None  # Will be set during process

        # Citation configuration: read from config, default off
        self.enable_citation_list = self.reporting_config.get("enable_citation_list", False)
        self.enable_inline_citations = self.reporting_config.get("enable_inline_citations", False)
        self.deduplicate_enabled = self.reporting_config.get("deduplicate_enabled", False)
        self.single_pass_threshold = int(self.reporting_config.get("report_single_pass_threshold", 0))
        self.report_style = str(self.reporting_config.get("style", "report") or "report")

    def set_citation_manager(self, citation_manager):
        """Set citation manager"""
        self.citation_manager = citation_manager

    @staticmethod
    def _append_contract(prompt: str, heading: str, contract: str) -> str:
        contract = str(contract or "").strip()
        if not contract:
            return prompt
        return f"{prompt}\n\n{heading}:\n{contract}\n"

    def _get_mode_contract(self, stage: str) -> str:
        return (
            self.get_prompt("mode_contracts", f"{self.report_style}_{stage}", "")
            or ""
        ).strip()

    def _get_mode_process_prompt(self, base_key: str, default: str = "") -> str:
        """Select mode-specific process template, falling back to the generic one.

        Tries ``process.{base_key}_{report_style}`` first (e.g.
        ``generate_outline_study_notes``).  If the YAML has no such key the
        generic ``process.{base_key}`` is returned instead.
        """
        if self.report_style and self.report_style != "report":
            mode_key = f"{base_key}_{self.report_style}"
            mode_prompt = self.get_prompt("process", mode_key, "")
            if mode_prompt:
                return mode_prompt
        return self.get_prompt("process", base_key, default)

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

        candidate_blocks = queue.get_all_completed_blocks() or queue.blocks

        # 1) Optional deduplication
        print("🔄 Step 1: Preparing topic blocks...")
        if self.deduplicate_enabled:
            cleaned_blocks = await self._deduplicate_blocks(candidate_blocks)
        else:
            cleaned_blocks = candidate_blocks
        print(f"✓ Preparation completed: {len(cleaned_blocks)} topic blocks")
        self._notify_progress(
            progress_callback, "deduplicate_completed", kept_blocks=len(cleaned_blocks)
        )

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

        result = {
            "report": report_markdown,
            "word_count": word_count,
            "sections": sections,
            "citations": citations,
        }

        # If outline has been generated, add it to result
        if hasattr(self, "_current_outline"):
            result["outline"] = self._current_outline
            delattr(self, "_current_outline")

        return result

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
        _chunks: list[str] = []
        async for _c in self.stream_llm(
            filled,
            system_prompt,
            stage="deduplicate",
            trace_meta=self._build_trace_meta("Deduplicate topics"),
        ):
            _chunks.append(_c)
        resp = "".join(_chunks)
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
        user_prompt = self._get_mode_process_prompt("generate_outline")
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
        filled = self._append_contract(
            filled,
            "Mode-specific outline contract",
            self._get_mode_contract("outline"),
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            filled,
            system_prompt,
            stage="generate_outline",
            trace_meta=self._build_trace_meta("Generate outline"),
        ):
            _chunks.append(_c)
        resp = "".join(_chunks)
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
        intro_title = "## Introduction"
        intro_instruction = "Present the research background, motivation, objectives, and report structure"
        conclusion_title = "## Conclusion and Future Directions"
        conclusion_instruction = (
            "Summarize core findings, research contributions, limitations, and future directions"
        )

        if self.report_style == "study_notes":
            intro_title = "## Study Overview"
            intro_instruction = "Orient the learner, define the scope, and state the main learning goals"
            conclusion_title = "## Key Takeaways"
            conclusion_instruction = "Summarize the most important concepts, mechanisms, and memory anchors"
        elif self.report_style == "comparison":
            intro_title = "## Comparison Setup"
            intro_instruction = "Define the comparison target, criteria, and evaluation lens"
            conclusion_title = "## Recommendation by Scenario"
            conclusion_instruction = "Summarize the trade-offs and recommend which option fits which scenario"
        elif self.report_style == "learning_path":
            intro_title = "## Learning Goal and Scope"
            intro_instruction = "Clarify the learner profile, expected progression, and prerequisite assumptions"
            conclusion_title = "## Milestones and Next Steps"
            conclusion_instruction = "Summarize stage milestones, practice checkpoints, and how to keep progressing"

        sections = []
        for i, b in enumerate(blocks, 1):
            section_instruction = (
                f"Provide detailed introduction to {b.sub_topic}, including core concepts, key mechanisms, and practical applications"
            )
            section_title = f"## {i}. {b.sub_topic}"
            subsections = [
                {
                    "title": f"### {i}.1 Core Concepts and Definitions",
                    "instruction": f"Explain the fundamental concepts and definitions related to {b.sub_topic}",
                },
                {
                    "title": f"### {i}.2 Key Mechanisms and Principles",
                    "instruction": f"Analyze the underlying mechanisms and theoretical principles of {b.sub_topic}",
                },
            ]
            if self.report_style == "study_notes":
                section_title = f"## Note {i}. {b.sub_topic}"
                section_instruction = (
                    f"Write compact study notes for {b.sub_topic}, focusing on definitions, mechanisms, examples, and takeaways"
                )
                subsections = [
                    {
                        "title": f"### {i}.1 What It Means",
                        "instruction": f"State the definition, intuition, and key idea of {b.sub_topic}",
                    },
                    {
                        "title": f"### {i}.2 Why It Matters",
                        "instruction": f"Explain the mechanism, a quick example, and the main takeaway for {b.sub_topic}",
                    },
                    {
                        "title": f"### {i}.3 Common Pitfalls",
                        "instruction": f"List typical misunderstandings or mistakes related to {b.sub_topic}",
                    },
                ]
            elif self.report_style == "comparison":
                section_title = f"## Dimension {i}. {b.sub_topic}"
                section_instruction = (
                    f"Compare {b.sub_topic} across key dimensions, trade-offs, strengths, weaknesses, and best-fit scenarios"
                )
                subsections = [
                    {
                        "title": f"### {i}.1 Side-by-Side Contrast",
                        "instruction": f"Compare the relevant options under the dimension of {b.sub_topic}",
                    },
                    {
                        "title": f"### {i}.2 Trade-offs",
                        "instruction": f"Explain strengths, weaknesses, and trade-offs under {b.sub_topic}",
                    },
                    {
                        "title": f"### {i}.3 Best-Fit Scenarios",
                        "instruction": f"Recommend which option fits which scenario for the dimension {b.sub_topic}",
                    },
                ]
            elif self.report_style == "learning_path":
                section_title = f"## Stage {i}. {b.sub_topic}"
                section_instruction = (
                    f"Explain how {b.sub_topic} fits into a learning roadmap, including prerequisites, what to practice, and what comes next"
                )
                subsections = [
                    {
                        "title": f"### {i}.1 Learn First",
                        "instruction": f"Explain the prerequisite ideas and what the learner should understand before tackling {b.sub_topic}",
                    },
                    {
                        "title": f"### {i}.2 Practice Plan",
                        "instruction": f"Describe how to practice {b.sub_topic}, including exercise focus and progression",
                    },
                    {
                        "title": f"### {i}.3 Checkpoint",
                        "instruction": f"Define what counts as finishing this stage and what should come next after {b.sub_topic}",
                    },
                ]
            section = {
                "title": section_title,
                "instruction": section_instruction,
                "block_id": b.block_id,
                "subsections": subsections,
            }
            sections.append(section)

        return {
            "title": f"# {topic}",
            "introduction": intro_title,
            "introduction_instruction": intro_instruction,
            "sections": sections,
            "conclusion": conclusion_title,
            "conclusion_instruction": conclusion_instruction,
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
                "rag": "RAG",
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
        tmpl = self._get_mode_process_prompt("write_introduction")
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
        filled = self._append_contract(
            filled,
            "Mode-specific introduction contract",
            self._get_mode_contract("introduction"),
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            filled,
            system_prompt,
            stage="write_introduction",
            trace_meta=self._build_trace_meta("Write introduction"),
        ):
            _chunks.append(_c)
        resp = "".join(_chunks)
        data = extract_json_from_text(resp)

        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["introduction"])
            intro = obj.get("introduction", "")
            if isinstance(intro, str) and intro.strip():
                return intro
            raise ValueError("LLM returned empty or invalid introduction field")
        except Exception as e:
            raise ValueError(
                f"Unable to parse LLM returned introduction content: {e!s}. Report generation failed."
            )

    async def _write_section_body(
        self, topic: str, block: TopicBlock, section_outline: dict[str, Any]
    ) -> str:
        """Write main content of a single section"""
        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are an academic writing expert specializing in writing chapter content for research reports.",
        )
        tmpl = self._get_mode_process_prompt("write_section_body")
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
        filled = self._append_contract(
            filled,
            "Mode-specific section contract",
            self._get_mode_contract("section"),
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            filled,
            system_prompt,
            stage="write_section_body",
            trace_meta=self._build_trace_meta("Write section"),
        ):
            _chunks.append(_c)
        resp = "".join(_chunks)
        data = extract_json_from_text(resp)

        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["section_content"])
            content = obj.get("section_content", "")
            if isinstance(content, str) and content.strip():
                return content
            raise ValueError("LLM returned empty or invalid section_content field")
        except Exception as e:
            raise ValueError(
                f"Unable to parse LLM returned section content: {e!s}. Report generation failed."
            )

    async def _write_conclusion(
        self, topic: str, blocks: list[TopicBlock], outline: dict[str, Any]
    ) -> str:
        """Write report conclusion section"""
        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are an academic writing expert specializing in writing the conclusion section of research reports.",
        )
        tmpl = self._get_mode_process_prompt("write_conclusion")
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
        filled = self._append_contract(
            filled,
            "Mode-specific conclusion contract",
            self._get_mode_contract("conclusion"),
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            filled,
            system_prompt,
            stage="write_conclusion",
            trace_meta=self._build_trace_meta("Write conclusion"),
        ):
            _chunks.append(_c)
        resp = "".join(_chunks)
        data = extract_json_from_text(resp)

        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["conclusion"])
            conclusion = obj.get("conclusion", "")
            if isinstance(conclusion, str) and conclusion.strip():
                return conclusion
            raise ValueError("LLM returned empty or invalid conclusion field")
        except Exception as e:
            raise ValueError(
                f"Unable to parse LLM returned conclusion content: {e!s}. Report generation failed."
            )

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
        parts = ["## References\n"]

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

        # Generate references in order of ref_number
        for ref_num in sorted(ref_to_citations.keys()):
            entries = ref_to_citations[ref_num]
            if not entries:
                continue

            # Use the first entry for this ref_number (others are duplicates)
            citation_id, citation, paper = entries[0]
            tool_type = citation.get("tool_type", "").lower()

            anchor = f"ref-{ref_num}"
            parts.append(f'<a id="{anchor}"></a>**[{ref_num}]** ')

            if tool_type == "paper_search":
                if paper:
                    formatted = self._format_single_paper_apa(paper)
                else:
                    formatted = self._format_paper_citation_apa(citation)
                parts.append(formatted)
            elif tool_type == "web_search":
                formatted = self._format_web_search_citation(citation)
                parts.append(formatted)
            elif tool_type in ("rag", "rag_naive", "rag_hybrid"):
                formatted = self._format_rag_citation(citation)
                parts.append(formatted)
            elif tool_type == "run_code":
                formatted = self._format_code_citation(citation)
                parts.append(formatted)
            else:
                # Generic format
                query = citation.get("query", "")
                summary = citation.get("summary", "")
                parts.append(f"**{tool_type}**\n\n")
                parts.append(f"- **Query**: {query}\n")
                if summary:
                    clean_summary = self._strip_markdown(summary)
                    parts.append(
                        f"- **Summary**: {clean_summary[:300]}{'...' if len(clean_summary) > 300 else ''}\n"
                    )

            parts.append("\n\n")

        return "".join(parts)

    def _format_single_paper_apa(self, paper: dict) -> str:
        """Format a single paper in APA style

        Format: Authors (Year). *Title*. Venue. arXiv:ID. URL
        """
        authors = paper.get("authors", "Unknown Author")
        year = paper.get("year", "n.d.")
        title = paper.get("title", "Untitled")
        url = paper.get("url", "")
        arxiv_id = paper.get("arxiv_id", "")
        venue = paper.get("venue", "")
        doi = paper.get("doi", "")

        # APA format
        result = f"{authors} ({year}). *{title}*."
        if venue:
            result += f" {venue}."
        if arxiv_id:
            result += f" arXiv:{arxiv_id}."
        if doi:
            result += f" https://doi.org/{doi}"
        elif url:
            result += f" {url}"

        return result

    def _format_paper_citation_apa(self, citation: dict) -> str:
        """Format paper citation in APA style (fallback for citations without papers array)

        Format: Authors (Year). *Title*. Venue. arXiv:ID. URL
        """
        authors = citation.get("authors", "Unknown Author")
        year = citation.get("year", "n.d.")
        title = citation.get("title", "Untitled")
        url = citation.get("url", "")
        arxiv_id = citation.get("arxiv_id", "")
        venue = citation.get("venue", "")
        doi = citation.get("doi", "")

        result = f"{authors} ({year}). *{title}*."
        if venue:
            result += f" {venue}."
        if arxiv_id:
            result += f" arXiv:{arxiv_id}."
        if doi:
            result += f" https://doi.org/{doi}"
        elif url:
            result += f" {url}"
        return result

    def _format_web_search_citation(self, citation: dict) -> str:
        """Format web search citation with collapsible links"""
        query = citation.get("query", "")
        summary = citation.get("summary", "")
        web_sources = citation.get("web_sources", [])

        result = "**Web Search**\n\n"
        result += f"- **Query**: {query}\n"
        if summary:
            # Clean summary to avoid markdown rendering issues
            clean_summary = self._strip_markdown(summary)
            summary_text = clean_summary[:300] + ("..." if len(clean_summary) > 300 else "")
            result += f"- **Summary**: {summary_text}\n"

        # Add collapsible links section
        if web_sources:
            result += "\n<details>\n<summary>📎 Retrieved Sources ({} links)</summary>\n\n".format(
                len(web_sources)
            )
            for i, source in enumerate(web_sources, 1):
                title = source.get("title", "Untitled")
                url = source.get("url", "")
                snippet = source.get("snippet", "")
                if url:
                    result += f"{i}. [{title}]({url})"
                    if snippet:
                        clean_snippet = self._strip_markdown(snippet)
                        result += f"\n   > {clean_snippet[:150]}{'...' if len(clean_snippet) > 150 else ''}"
                    result += "\n\n"
            result += "</details>"

        return result

    def _format_rag_citation(self, citation: dict) -> str:
        """Format RAG/Query citation"""
        tool_type = citation.get("tool_type", "")
        query = citation.get("query", "")
        summary = citation.get("summary", "")
        kb_name = citation.get("kb_name", "")
        sources = citation.get("sources", [])

        # Tool name display
        result = f"**RAG**"
        if kb_name:
            result += f" (KB: {kb_name})"
        result += "\n\n"
        result += f"- **Query**: {query}\n"
        if summary:
            # Clean summary: remove markdown formatting to avoid rendering issues
            clean_summary = self._strip_markdown(summary)
            summary_text = clean_summary[:300] + ("..." if len(clean_summary) > 300 else "")
            result += f"- **Summary**: {summary_text}\n"

        # Add source documents if available
        if sources:
            result += "\n<details>\n<summary>📄 Source Documents ({} docs)</summary>\n\n".format(
                len(sources)
            )
            for i, source in enumerate(sources, 1):
                title = source.get("title", "") or source.get("source_file", f"Document {i}")
                content = source.get("content_preview", "")
                page = source.get("page", "")
                result += f"{i}. **{title}**"
                if page:
                    result += f" (Page {page})"
                if content:
                    clean_content = self._strip_markdown(content)
                    result += (
                        f"\n   > {clean_content[:150]}{'...' if len(clean_content) > 150 else ''}"
                    )
                result += "\n\n"
            result += "</details>"

        return result

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
        """Generate References section from blocks (backward compatible, academic paper style)"""
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

        # Generate numbered references in academic paper style
        # Using simple ref-N anchor format for clickable inline citations
        for idx, cit in enumerate(all_citations, 1):
            trace = cit["trace"]
            citation_id = cit["citation_id"]

            # Use simple ref-N anchor format (consistent with _generate_references_from_manager)
            anchor = f"ref-{idx}"
            tool_type = trace.tool_type.lower() if trace.tool_type else ""

            # Tool name display
            tool_display = {
                "rag": "RAG",
                "paper_search": "Paper Search",
                "web_search": "Web Search",
                "run_code": "Code Execution",
            }.get(tool_type, tool_type)

            parts.append(f'<a id="{anchor}"></a>**[{idx}]** **{tool_display}**\n\n')
            parts.append(f"- **Query**: {trace.query}\n")
            if trace.summary:
                summary_text = trace.summary[:500] + ("..." if len(trace.summary) > 500 else "")
                parts.append(f"- **Summary**: {summary_text}\n")
            parts.append("\n")

        return "".join(parts)

    def _convert_citation_format(self, text: str) -> str:
        """
        Convert various citation formats to clickable [[N]](#ref-N) format.

        Handles:
        - [N] format (simple number in brackets)
        - [ref=N] format (from citation table)

        Args:
            text: Text with citations in various formats

        Returns:
            Text with [[N]](#ref-N) clickable citations
        """
        import re

        # Get valid ref_numbers from the citation map
        valid_refs = set()
        if hasattr(self, "_citation_map") and self._citation_map:
            valid_refs = set(self._citation_map.values())

        def replace_citation(match):
            # Get the number from the match
            ref_num = match.group(1)

            # Only convert if it's a valid ref_number
            try:
                num = int(ref_num)
                if num in valid_refs:
                    return f"[[{ref_num}]](#ref-{ref_num})"
            except ValueError:
                pass

            # Return unchanged if not a valid reference
            return match.group(0)

        # First, convert [ref=N] format to clickable format
        # Pattern: [ref=N] where N is a number
        ref_pattern = r"\[ref=(\d+)\]"
        text = re.sub(ref_pattern, replace_citation, text)

        # Then, convert simple [N] format (but NOT already converted [[N]])
        # Pattern to match [N] where N is a number, but NOT already in [[N]] format
        # Use negative lookbehind and lookahead to avoid matching [[N]] or [N](#ref-N)
        simple_pattern = r"(?<!\[)\[(\d+)\](?!\(#ref-)"
        text = re.sub(simple_pattern, replace_citation, text)

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

        # Find all citations in [[N]](#ref-N) format
        pattern = r"\[\[(\d+)\]\]\(#ref-\d+\)"
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

        # Remove invalid citations
        if invalid:

            def remove_invalid(match):
                ref_num = match.group(1)
                try:
                    num = int(ref_num)
                    if num not in valid_refs:
                        return ""  # Remove invalid citation
                except ValueError:
                    return ""
                return match.group(0)

            text = re.sub(pattern, remove_invalid, text)

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
        # Build citation number map before writing (for consistent ref_number in traces)
        if self.enable_inline_citations:
            self._citation_map = self._build_citation_number_map(blocks)
            print(f"  📋 Built citation map with {len(self._citation_map)} entries")
        else:
            self._citation_map = {}

        if self.single_pass_threshold > 0 and len(blocks) <= self.single_pass_threshold:
            print("  ⚡ Using single-pass report writing mode...")
            report = await self._write_report_single_pass(topic, blocks, outline)
        else:
            report = await self._write_report_step_by_step(topic, blocks, outline)

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

    async def _write_report_step_by_step(
        self, topic: str, blocks: list[TopicBlock], outline: dict[str, Any]
    ) -> str:
        """Write complete report using the original multi-call chapter flow."""
        parts = []

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
        return "".join(parts)

    async def _write_report_single_pass(
        self, topic: str, blocks: list[TopicBlock], outline: dict[str, Any]
    ) -> str:
        """Write the full report in one LLM call for lightweight runs."""
        import json as _json

        system_prompt = self.get_prompt(
            "system",
            "role",
            "You are an academic writing expert specializing in concise, high-quality research reports.",
        )
        tmpl = self._get_mode_process_prompt("write_full_report")
        if not tmpl:
            raise ValueError("Cannot get single-pass report prompt template, report generation failed")

        blocks_data = [self._ser_block(block) for block in blocks]
        outline_json = _json.dumps(outline, ensure_ascii=False, indent=2)
        blocks_json = _json.dumps(blocks_data, ensure_ascii=False, indent=2)

        if self.enable_inline_citations:
            citation_instruction = (
                "Use inline citations in [N] format whenever a trace provides a ref_number. "
                "Do not invent citation numbers and do not add a References section."
            )
        else:
            citation_instruction = (
                "Do not add inline citations and do not add a References section."
            )

        filled = self._safe_format(
            tmpl,
            topic=topic,
            outline_json=outline_json,
            blocks_json=blocks_json,
            total_topics=len(blocks),
            citation_instruction=citation_instruction,
        )
        filled = self._append_contract(
            filled,
            "Mode-specific full-report contract",
            self._get_mode_contract("single_pass"),
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            filled,
            system_prompt,
            stage="write_full_report",
            trace_meta=self._build_trace_meta("Write full report"),
        ):
            _chunks.append(_c)
        resp = "".join(_chunks)
        data = extract_json_from_text(resp)

        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["report"])
            report = obj.get("report", "")
            if not isinstance(report, str) or not report.strip():
                raise ValueError("LLM returned empty report field")
        except Exception:
            if isinstance(data, dict) and ("sections" in data or "title" in data):
                report = self._assemble_markdown_from_structured(data)
            else:
                stripped = resp.strip()
                if stripped and stripped.startswith("#"):
                    report = stripped
                else:
                    report = self._strip_json_wrapper(resp)

        if self.enable_citation_list:
            report = report.rstrip() + "\n\n" + self._generate_references(blocks)

        return report

    @staticmethod
    def _assemble_markdown_from_structured(obj: dict[str, Any]) -> str:
        """Reconstruct markdown from a structured JSON report the LLM returned
        instead of the expected {report: "..."} wrapper."""
        parts: list[str] = []
        if obj.get("title"):
            parts.append(str(obj["title"]))
        if obj.get("introduction"):
            parts.append(str(obj["introduction"]))
        for section in obj.get("sections", []):
            if isinstance(section, str):
                parts.append(section)
                continue
            if not isinstance(section, dict):
                continue
            if section.get("title"):
                parts.append(str(section["title"]))
            if section.get("content"):
                parts.append(str(section["content"]))
            for sub in section.get("subsections", []):
                if isinstance(sub, str):
                    parts.append(sub)
                elif isinstance(sub, dict):
                    if sub.get("title"):
                        parts.append(str(sub["title"]))
                    if sub.get("content"):
                        parts.append(str(sub["content"]))
        if obj.get("conclusion"):
            parts.append(str(obj["conclusion"]))
        return "\n\n".join(parts)

    @staticmethod
    def _strip_json_wrapper(resp: str) -> str:
        """Best-effort extraction of readable text from a JSON response."""
        import json as _json
        try:
            obj = _json.loads(resp.strip())
            if isinstance(obj, dict):
                for key in ("report", "content", "text", "markdown", "output"):
                    if key in obj and isinstance(obj[key], str):
                        return obj[key]
        except (ValueError, TypeError):
            pass
        stripped = resp.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            for line in stripped.split("\\n"):
                if line.strip().startswith("#"):
                    return stripped.replace("\\n", "\n")
        return stripped

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
        tmpl = self._get_mode_process_prompt("write_section_body")
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
        filled = self._append_contract(
            filled,
            "Mode-specific section contract",
            self._get_mode_contract("section"),
        )

        # TODO Implement retry logic for LLM calls when JSON parsing or post-processing fails (e.g., malformed output, schema violations).
        _chunks: list[str] = []
        async for _c in self.stream_llm(
            filled,
            system_prompt,
            stage="write_section_with_subsections",
            trace_meta=self._build_trace_meta("Write section"),
        ):
            _chunks.append(_c)
        resp = "".join(_chunks)
        data = extract_json_from_text(resp)

        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["section_content"])
            content = obj.get("section_content", "")
            if isinstance(content, str) and content.strip():
                return content
            raise ValueError("LLM returned empty or invalid section_content field")
        except Exception as e:
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


__all__ = ["ReportingAgent"]
