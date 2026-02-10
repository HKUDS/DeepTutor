#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NoteAgent - Note taker
Based on new knowledge, generates or updates notes, annotates covered pain points and missing points
"""

from pathlib import Path
import sys
from typing import Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.agents.base_agent import BaseAgent

from ..memory import CitationMemory, InvestigateMemory, KnowledgeItem
from ..utils import ParseError, validate_note_output
from ..utils.json_utils import extract_json_from_text


class NoteAgent(BaseAgent):
    """Note taker Agent - Generates and updates notes"""

    def __init__(self, config: dict[str, Any], api_key: str, base_url: str, token_tracker=None):
        language = config.get("system", {}).get("language", "zh")
        super().__init__(
            module_name="solve",
            agent_name="note_agent",
            api_key=api_key,
            base_url=base_url,
            language=language,
            config=config,
            token_tracker=token_tracker,
        )

    async def process(
        self,
        question: str,
        memory: InvestigateMemory,
        new_knowledge_ids: list[str],
        citation_memory: CitationMemory | None = None,
        output_dir: str | None = None,
        verbose: bool = True,
    ) -> dict[str, Any]:
        """
        Process note generation workflow (supports multiple knowledge_items in single round)

        Args:
            question: User question
            memory: Investigation memory
            new_knowledge_ids: List of cite_ids for new knowledge items
            citation_memory: Citation memory
            output_dir: Output directory
            verbose: Whether to print detailed information

        Returns:
            dict: Aggregated note result
        """
        if isinstance(new_knowledge_ids, str):  # Backward compatibility
            target_ids = [new_knowledge_ids]
        else:
            target_ids = new_knowledge_ids or []

        if not target_ids:
            return {"success": False, "reason": "new_knowledge_ids is empty"}

        system_prompt = self._build_system_prompt()
        processed_details = []
        failed_ids = []

        for cite_id in target_ids:
            knowledge_item = next((k for k in memory.knowledge_chain if k.cite_id == cite_id), None)
            if not knowledge_item:
                failed_ids.append({"cite_id": cite_id, "reason": "knowledge_item not found"})
                continue

            context = self._build_context(question, knowledge_item, memory)
            user_prompt = self._build_user_prompt(context)

            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                verbose=verbose,
                response_format={"type": "json_object"},
            )

            if verbose:
                self.logger.debug(f"cite_id={cite_id} LLM output stats:")
                self.logger.debug(f"  - Total length: {len(response)} chars")
                self.logger.debug(
                    f"  - Last 100 chars: ...{response[-100:] if len(response) > 100 else response}"
                )

            try:
                parsed_result = extract_json_from_text(response)
                if not parsed_result or not isinstance(parsed_result, dict):
                    raise ParseError("LLM output is not a valid JSON object")
                # citations is optional, default to empty list
                if parsed_result.get("citations") is None:
                    parsed_result["citations"] = []
                elif not isinstance(parsed_result.get("citations"), list):
                    raise ParseError("citations field must be a list")
                validate_note_output(parsed_result)
                if verbose:
                    summary_len = len(parsed_result.get("summary", ""))
                    print(f"📝 [NoteAgent] cite_id={cite_id} summary length: {summary_len}")
            except ParseError as e:
                failed_ids.append({"cite_id": cite_id, "reason": str(e)})
                continue
            except Exception as e:
                failed_ids.append({"cite_id": cite_id, "reason": str(e)})
                continue

            citations = parsed_result.get("citations", [])
            memory.update_knowledge_summary(cite_id=cite_id, summary=parsed_result["summary"])

            if citation_memory:
                sources = ", ".join(
                    citation.get("source", "") for citation in citations if citation.get("source")
                )
                metadata_block = {"extracted_sources": citations} if citations else None
                try:
                    citation_memory.update_citation(
                        cite_id=cite_id,
                        content=parsed_result["summary"],
                        source=sources or None,
                        metadata=metadata_block,
                        stage="analysis",
                    )
                except ValueError:
                    if verbose:
                        print(f"⚠️ cite_id not found in CitationMemory: {cite_id}")

            processed_details.append(
                {
                    "cite_id": cite_id,
                    "summary": parsed_result["summary"],
                    "citations_count": len(citations),
                }
            )

        if processed_details:
            if citation_memory:
                citation_memory.save()
            if output_dir:
                memory.save()

        return {
            "success": len(failed_ids) == 0,
            "processed_items": len(processed_details),
            "details": processed_details,
            "failed": failed_ids,
        }

    def _build_context(
        self, question: str, knowledge_item: KnowledgeItem, memory: InvestigateMemory
    ) -> dict[str, Any]:
        """Build context (pass complete content)"""
        return {
            "question": question,
            "tool_type": knowledge_item.tool_type,
            "query": knowledge_item.query,
            "raw_result": knowledge_item.raw_result,  # Complete content
        }

    def _build_system_prompt(self) -> str:
        """Build system prompt"""
        prompt = self.get_prompt("system") if self.has_prompts() else None
        if not prompt:
            raise ValueError(
                "NoteAgent missing system prompt, please configure system in prompts/zh/analysis_loop/note_agent.yaml."
            )
        return prompt

    def _build_user_prompt(self, context: dict[str, Any]) -> str:
        """Build user prompt (pass complete content)"""
        template = self.get_prompt("user_template") if self.has_prompts() else None
        if not template:
            raise ValueError(
                "NoteAgent missing user prompt template, please configure user_template in prompts/zh/analysis_loop/note_agent.yaml."
            )
        return template.format(**context)
