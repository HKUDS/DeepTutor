#!/usr/bin/env python
"""
NoteAgent - Recording Agent
Responsible for information compression and summary generation, converting raw data returned by tools into usable knowledge summaries
"""

import json
from string import Template
from typing import Any, Optional

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.research.data_structures import ToolTrace
from deeptutor.core.trace import build_trace_metadata, new_call_id

from ..utils.json_utils import extract_json_from_text


class NoteAgent(BaseAgent):
    """Recording Agent"""

    _MODE_TO_STYLE = {
        "notes": "study_notes",
        "report": "report",
        "comparison": "comparison",
        "learning_path": "learning_path",
    }

    @staticmethod
    def _build_trace_meta(tool_type: str, query: str) -> dict[str, Any]:
        return build_trace_metadata(
            call_id=new_call_id("research-note"),
            phase="researching",
            label="Summarize evidence",
            call_kind="llm_observation",
            trace_role="observe",
            trace_kind="llm_generation",
            tool_name=tool_type,
            query=query,
        )

    def __init__(
        self,
        config: dict[str, Any],
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        api_version: Optional[str] = None,
    ):
        language = config.get("system", {}).get("language", "zh")
        super().__init__(
            module_name="research",
            agent_name="note_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            config=config,
        )
        researching_cfg = config.get("researching", {})
        self.summary_mode = researching_cfg.get("note_agent_mode", "auto")
        intent_mode = str(config.get("intent", {}).get("mode", "") or "")
        reporting_style = str(config.get("reporting", {}).get("style", "") or "")
        self._research_style = reporting_style or self._MODE_TO_STYLE.get(intent_mode, "report")

    async def process(
        self,
        tool_type: str,
        query: str,
        raw_answer: str,
        citation_id: str,
        topic: str = "",
        context: str = "",
    ) -> ToolTrace:
        """
        Process raw data returned by tool, generate summary and create ToolTrace

        Args:
            tool_type: Tool type
            query: Query statement
            raw_answer: Raw answer returned by tool
            citation_id: Citation ID (REQUIRED, must be obtained from CitationManager)
            topic: Topic (for context)
            context: Additional context

        Returns:
            ToolTrace object

        Note:
            citation_id must be obtained from CitationManager before calling this method.
            Use CitationManager.get_next_citation_id() or its async variant.
        """
        print(f"\n{'=' * 70}")
        print("📝 NoteAgent - Information Recording and Summary")
        print(f"{'=' * 70}")
        print(f"Tool: {tool_type}")
        print(f"Query: {query}")
        print(f"Citation ID: {citation_id}")
        print(f"Raw Answer Length: {len(raw_answer)} characters\n")

        summary = ""
        use_rule = self.summary_mode in ("rule", "auto")
        use_llm_fallback = self.summary_mode in ("llm", "auto")

        if use_rule:
            summary = self._extract_summary_by_rule(tool_type=tool_type, raw_answer=raw_answer)

        if (not summary or len(summary) < 50) and use_llm_fallback:
            summary = await self._generate_summary(
                tool_type=tool_type, query=query, raw_answer=raw_answer, topic=topic, context=context
            )
        elif not summary:
            summary = raw_answer[:1000]

        print(f"✓ Summary generation completed ({len(summary)} characters)")

        # Create ToolTrace with the provided citation ID
        tool_id = self._generate_tool_id()
        trace = ToolTrace(
            tool_id=tool_id,
            citation_id=citation_id,
            tool_type=tool_type,
            query=query,
            raw_answer=raw_answer,
            summary=summary,
        )

        return trace

    @staticmethod
    def _convert_to_template_format(template_str: str) -> str:
        """
        Convert {var} style placeholders to $var style for string.Template.
        This avoids conflicts with LaTeX braces like {\rho}.
        """
        import re

        # Only convert simple {var_name} patterns, not nested or complex ones
        return re.sub(r"\{(\w+)\}", r"$\1", template_str)

    @staticmethod
    def _truncate_text(text: str, limit: int = 800) -> str:
        """Keep summaries compact for iterative accumulation."""
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _get_mode_contract(self, stage: str) -> str:
        return (
            self.get_prompt("mode_contracts", f"{self._research_style}_{stage}", "")
            or ""
        ).strip()

    def _get_mode_instruction_text(self, stage: str) -> str:
        instruction = self._get_mode_contract(stage)
        if not instruction:
            return ""
        return f"Mode-specific note focus:\n{instruction}\n"

    def _extract_summary_by_rule(self, tool_type: str, raw_answer: str) -> str:
        """Extract a concise summary from structured tool output without LLM."""
        try:
            data = json.loads(raw_answer)
        except Exception:
            return ""

        tool_type = (tool_type or "").lower()

        if tool_type in {"rag_hybrid", "rag_naive", "rag"}:  # aliases kept for backward compat
            answer = data.get("answer") or data.get("content") or ""
            return self._truncate_text(answer)

        if tool_type == "web_search":
            answer = data.get("answer") or ""
            snippets: list[str] = []
            for item in (data.get("search_results") or data.get("results") or [])[:3]:
                if not isinstance(item, dict):
                    continue
                title = (item.get("title") or "").strip()
                snippet = (item.get("snippet") or item.get("content") or "").strip()
                piece = " - ".join(part for part in [title, snippet] if part)
                if piece:
                    snippets.append(piece)
            combined = "\n".join(part for part in [answer.strip(), *snippets] if part)
            return self._truncate_text(combined)

        if tool_type == "paper_search":
            papers = data.get("papers") or []
            formatted: list[str] = []
            for paper in papers[:3]:
                if not isinstance(paper, dict):
                    continue
                title = (paper.get("title") or "").strip()
                authors = paper.get("authors") or []
                if isinstance(authors, list):
                    authors_text = ", ".join(authors[:3])
                else:
                    authors_text = str(authors)
                year = paper.get("year")
                abstract = (paper.get("abstract") or "").strip()
                parts = [title]
                if authors_text:
                    parts.append(authors_text)
                if year:
                    parts.append(str(year))
                header = " | ".join(part for part in parts if part)
                body = "\n".join(part for part in [header, abstract] if part)
                if body:
                    formatted.append(body)
            return self._truncate_text("\n\n".join(formatted))

        if tool_type in {"run_code", "code_execution", "code_execute"}:
            stdout = (data.get("stdout") or "").strip()
            stderr = (data.get("stderr") or "").strip()
            artifacts = data.get("artifacts") or []
            parts = []
            if stdout:
                parts.append(f"stdout:\n{stdout}")
            if stderr:
                parts.append(f"stderr:\n{stderr}")
            if artifacts:
                parts.append(f"artifacts: {', '.join(str(item) for item in artifacts)}")
            return self._truncate_text("\n\n".join(parts))

        if isinstance(data, dict):
            for key in ("answer", "content", "summary", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return self._truncate_text(value)

        return ""

    async def _generate_summary(
        self, tool_type: str, query: str, raw_answer: str, topic: str = "", context: str = ""
    ) -> str:
        """
        Generate summary

        Args:
            tool_type: Tool type
            query: Query statement
            raw_answer: Raw answer
            topic: Topic
            context: Additional context

        Returns:
            Generated summary
        """
        system_prompt = self.get_prompt("system", "role")
        if not system_prompt:
            raise ValueError(
                "NoteAgent missing system prompt, please configure system.role in prompts/{lang}/note_agent.yaml"
            )

        user_prompt_template = self.get_prompt("process", "generate_summary")
        if not user_prompt_template:
            raise ValueError(
                "NoteAgent missing generate_summary prompt, please configure process.generate_summary in prompts/{lang}/note_agent.yaml"
            )

        # Use string.Template to avoid conflicts with LaTeX braces like {\rho}
        # Convert {var} to $var format, then use safe_substitute
        template_str = self._convert_to_template_format(user_prompt_template)
        template = Template(template_str)
        user_prompt = template.safe_substitute(
            tool_type=tool_type,
            query=query,
            raw_answer=raw_answer,
            topic=topic,
            context=context,
            mode_instruction=self._get_mode_instruction_text("note"),
        )

        _chunks: list[str] = []
        async for _c in self.stream_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            stage="generate_summary",
            trace_meta=self._build_trace_meta(tool_type, query),
        ):
            _chunks.append(_c)
        response = "".join(_chunks)

        # Parse JSON output (strict validation)
        from ..utils.json_utils import ensure_json_dict, ensure_keys

        data = extract_json_from_text(response)
        try:
            obj = ensure_json_dict(data)
            ensure_keys(obj, ["summary"])
            summary = obj.get("summary", "")
            # Ensure summary is string type
            if not isinstance(summary, str):
                summary = str(summary) if summary else ""
            return summary
        except Exception:
            # Fallback: directly use text prefix
            return (response or "")[:1000]

    def _generate_tool_id(self) -> str:
        """Generate tool ID"""
        import time

        timestamp = int(time.time() * 1000)
        return f"tool_{timestamp}"


__all__ = ["NoteAgent"]
