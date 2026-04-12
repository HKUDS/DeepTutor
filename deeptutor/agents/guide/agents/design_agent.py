#!/usr/bin/env python
"""
DesignAgent - Agent for designing guided learning plans
Generates progressive knowledge point plans from plain user input
"""

import json
import re
from typing import Optional

from deeptutor.agents.base_agent import BaseAgent


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
                result = self._parse_json_payload(response)

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
                fallback_points = self._fallback_points(user_input)
                return {
                    "success": True,
                    "knowledge_points": fallback_points,
                    "total_points": len(fallback_points),
                    "warning": f"JSON parsing failed: {e!s}",
                }

        except Exception as e:
            fallback_points = self._fallback_points(user_input)
            return {
                "success": True,
                "knowledge_points": fallback_points,
                "total_points": len(fallback_points),
                "warning": str(e),
            }

    def _parse_json_payload(self, response: str) -> object:
        text = (response or "").strip()
        if not text:
            raise json.JSONDecodeError("Empty response", response, 0)

        # 1) Direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 2) Fenced JSON block
        fence_match = re.search(r"```json\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
        if fence_match:
            return json.loads(fence_match.group(1).strip())

        # 3) First JSON object
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start != -1 and obj_end != -1 and obj_end > obj_start:
            candidate = text[obj_start : obj_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

        # 4) First JSON array
        arr_start = text.find("[")
        arr_end = text.rfind("]")
        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            candidate = text[arr_start : arr_end + 1]
            return json.loads(candidate)

        raise json.JSONDecodeError("No JSON payload found", response, 0)

    def _fallback_points(self, user_input: str) -> list[dict[str, str]]:
        clean = user_input.strip()
        seeds = []
        for chunk in re.split(r"[，,。；;、\n]+", clean):
            value = chunk.strip()
            if 2 <= len(value) <= 24:
                seeds.append(value)
            if len(seeds) >= 4:
                break

        if not seeds:
            seeds = ["核心概念", "高频方法", "典型练习"]

        points: list[dict[str, str]] = []
        for index, seed in enumerate(seeds, start=1):
            points.append(
                {
                    "knowledge_title": f"{seed}",
                    "knowledge_summary": f"围绕“{seed}”建立从概念到应用的理解，并形成可执行步骤。",
                    "user_difficulty": "容易停留在理解层，缺少题型迁移与错因归纳。",
                }
            )
            if index >= 5:
                break
        return points
