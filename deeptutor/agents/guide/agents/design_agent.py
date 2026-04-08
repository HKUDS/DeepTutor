#!/usr/bin/env python
"""
DesignAgent - Agent for designing guided learning plans
Generates progressive knowledge point plans from plain user input
"""

import json
from typing import Optional

from deeptutor.agents.base_agent import BaseAgent
from deeptutor.utils.json_parser import parse_json_response


class DesignAgent(BaseAgent):
    """Learning plan design agent"""

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
            agent_name="design_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
            binding=binding,
        )

    async def process(self, user_input: str) -> dict[str, object]:
        """
        Design a progressive guided learning plan from user input.

        Args:
            user_input: User's learning request

        Returns:
            Dictionary containing knowledge point list
        """
        if not user_input.strip():
            return {
                "success": False,
                "error": "User input cannot be empty",
                "knowledge_points": [],
            }

        system_prompt = self.get_prompt("system")
        if not system_prompt:
            raise ValueError(
                "DesignAgent missing system prompt, please configure system in prompts/{lang}/design_agent.yaml"
            )

        user_template = self.get_prompt("user_template")
        if not user_template:
            raise ValueError(
                "DesignAgent missing user_template, please configure user_template in prompts/{lang}/design_agent.yaml"
            )

        user_prompt = user_template.format(user_input=user_input.strip())

        try:
            _chunks: list[str] = []
            async for _c in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
            ):
                _chunks.append(_c)
            response = "".join(_chunks)

            try:
                result = parse_json_response(response, logger_instance=self.logger)

                if isinstance(result, list):
                    knowledge_points = result
                elif isinstance(result, dict):
                    knowledge_points = (
                        result.get("knowledge_points")
                        or result.get("points")
                        or result.get("data")
                        or []
                    )
                else:
                    knowledge_points = []

                validated_points = []
                for point in knowledge_points:
                    if isinstance(point, dict):
                        validated_points.append(
                            {
                                "knowledge_title": point.get(
                                    "knowledge_title", "Unnamed knowledge point"
                                ),
                                "knowledge_summary": point.get("knowledge_summary", ""),
                                "user_difficulty": point.get("user_difficulty", ""),
                            }
                        )

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
