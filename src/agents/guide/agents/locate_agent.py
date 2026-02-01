#!/usr/bin/env python
"""
LocateAgent - Agent for locating and organizing knowledge points
Analyzes notebook content and generates progressive knowledge point learning plans
"""

import json
from typing import Any, Optional

from src.agents.base_agent import BaseAgent


class LocateAgent(BaseAgent):
    """Knowledge point location agent"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        language: str = "zh",
        api_version: Optional[str] = None,
        binding: str = "openai",
    ):
        super().__init__(
            module_name="guide",
            agent_name="locate_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            binding=binding,
        )

    def _format_records(self, records: list[dict[str, Any]]) -> str:
        """Format notebook records as readable text"""
        formatted = []
        for i, record in enumerate(records, 1):
            record_type = record.get("type", "unknown")
            title = record.get("title", "Untitled")
            user_query = record.get("user_query", "")
            output = record.get("output", "")

            if len(output) > 2000:
                output = output[:2000] + "\n...[Content truncated]..."

            formatted.append(
                f"""
### Record {i} [{record_type.upper()}]
**Title**: {title}

**User Question/Input**:
{user_query}

**System Output**:
{output}
---"""
            )

        return "\n".join(formatted)

    async def process(
        self, notebook_id: str, notebook_name: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Analyze notebook content and generate knowledge point learning plan

        Args:
            notebook_id: Notebook ID
            notebook_name: Notebook name
            records: List of records in notebook

        Returns:
            Dictionary containing knowledge point list
        """
        if not records:
            return {"success": False, "error": "No records in notebook", "knowledge_points": []}

        system_prompt = self.get_prompt("system")
        if not system_prompt:
            raise ValueError(
                "LocateAgent missing system prompt, please configure system in prompts/{lang}/locate_agent.yaml"
            )

        user_template = self.get_prompt("user_template")
        if not user_template:
            raise ValueError(
                "LocateAgent missing user_template, please configure user_template in prompts/{lang}/locate_agent.yaml"
            )

        records_content = self._format_records(records)

        user_prompt = user_template.format(
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            record_count=len(records),
            records_content=records_content,
        )

        try:
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
            )

            try:
                result = json.loads(response)

                # Debug: Log the parsed result structure
                self.logger.debug(f"Parsed JSON result type: {type(result).__name__}")
                if isinstance(result, dict):
                    self.logger.debug(f"Result keys: {list(result.keys())}")

                if isinstance(result, list):
                    knowledge_points = result
                elif isinstance(result, dict):
                    # Check if dict IS a single knowledge point (has knowledge_title key)
                    if "knowledge_title" in result or "title" in result:
                        self.logger.debug("Result is a single knowledge point, wrapping in list")
                        knowledge_points = [result]
                    else:
                        # Try multiple possible keys for array of points
                        knowledge_points = (
                            result.get("knowledge_points")
                            or result.get("points")
                            or result.get("data")
                            or result.get("items")
                            or result.get("learning_points")
                            or []
                        )
                        # If still empty but dict has content, try to extract from first list-like value
                        if not knowledge_points:
                            for key, value in result.items():
                                if isinstance(value, list) and len(value) > 0:
                                    self.logger.debug(f"Found list in key '{key}' with {len(value)} items")
                                    knowledge_points = value
                                    break
                else:
                    knowledge_points = []

                self.logger.debug(f"Extracted {len(knowledge_points)} knowledge points")

                validated_points = []
                for i, point in enumerate(knowledge_points):
                    if isinstance(point, dict):
                        # Debug: Log point keys
                        if i == 0:
                            self.logger.debug(f"First point keys: {list(point.keys())}")

                        # Try multiple key variations
                        title = (
                            point.get("knowledge_title")
                            or point.get("title")
                            or point.get("name")
                            or "Unnamed knowledge point"
                        )
                        summary = (
                            point.get("knowledge_summary")
                            or point.get("summary")
                            or point.get("description")
                            or point.get("content")
                            or ""
                        )
                        difficulty = (
                            point.get("user_difficulty")
                            or point.get("difficulty")
                            or point.get("challenges")
                            or ""
                        )

                        validated_points.append(
                            {
                                "knowledge_title": title,
                                "knowledge_summary": summary,
                                "user_difficulty": difficulty,
                            }
                        )
                    else:
                        self.logger.debug(f"Point {i} is not a dict: {type(point).__name__}")

                return {
                    "success": True,
                    "knowledge_points": validated_points,
                    "total_points": len(validated_points),
                }

            except json.JSONDecodeError as e:
                return {
                    "success": False,
                    "error": f"JSON parsing failed: {e!s}",
                    "raw_response": response,
                    "knowledge_points": [],
                }

        except Exception as e:
            return {"success": False, "error": str(e), "knowledge_points": []}
