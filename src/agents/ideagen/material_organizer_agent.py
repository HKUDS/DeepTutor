"""
Material Organizer Agent - Extracts knowledge points from notebook records.
Uses unified PromptManager for prompt loading.
"""

import json
from pathlib import Path
import sys
from typing import Any

# Add project root to path
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.agents.base_agent import BaseAgent
from src.services.prompt import get_prompt_manager


class MaterialOrganizerAgent(BaseAgent):
    """Material Organizer Agent - Extracts knowledge points"""

    def __init__(
        self,
        language: str = "en",
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str | None = None,
        model: str | None = None,
    ):
        super().__init__(
            module_name="ideagen",
            agent_name="material_organizer",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            model=model,
            language=language,
        )
        self._prompts = get_prompt_manager().load_prompts(
            module_name="ideagen",
            agent_name="material_organizer",
            language=language,
        )

    async def process(
        self, records: list[dict[str, Any]], user_thoughts: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Organize materials and extract knowledge points

        Args:
            records: Notebook record list
            user_thoughts: Optional user thoughts

        Returns:
            Knowledge point list, each containing:
            - knowledge_point: Knowledge point name
            - description: Description of this knowledge point from system response
        """
        materials = []
        for record in records:
            materials.append(
                {
                    "type": record.get("type", ""),
                    "title": record.get("title", ""),
                    "user_query": record.get("user_query", ""),
                    "output": record.get("output", ""),
                }
            )

        materials_text = ""
        for i, mat in enumerate(materials, 1):
            materials_text += f"\n\n=== Record {i} ===\n"
            materials_text += f"Type: {mat['type']}\n"
            materials_text += f"Title: {mat['title']}\n"
            materials_text += f"User Query: {mat['user_query']}\n"
            materials_text += f"System Response: {mat['output']}\n"

        user_thoughts_text = ""
        if user_thoughts and user_thoughts.strip():
            user_thoughts_text = f"\n\nUser Additional Thoughts:\n{user_thoughts}"

        system_prompt = self._prompts.get("system", "")
        user_template = self._prompts.get("user_template", "")
        user_prompt = user_template.format(
            materials_text=materials_text,
            user_thoughts_text=user_thoughts_text,
        )

        self.logger.info(f"Processing {len(records)} records...")

        response = await self.call_llm(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            response_format={"type": "json_object"},
        )

        self.logger.debug(f"LLM response length: {len(response)} chars")

        try:
            result = json.loads(response)
            knowledge_points = result.get("knowledge_points", [])
            self.logger.info(f"Extracted {len(knowledge_points)} knowledge points")

            validated_points = []
            for point in knowledge_points:
                if "knowledge_point" in point and "description" in point:
                    kp = str(point["knowledge_point"]).strip()
                    desc = str(point["description"]).strip()
                    if kp and desc and len(desc) >= 10:
                        validated_points.append({"knowledge_point": kp, "description": desc})

            if not validated_points and records:
                return await self._fallback_extract(records, user_thoughts)

            self.logger.info(f"Validated {len(validated_points)} knowledge points")
            return validated_points
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}")
            self.logger.debug(f"Raw response: {response[:500]}...")
            return await self._fallback_extract(records, user_thoughts)

    async def _fallback_extract(
        self, records: list[dict[str, Any]], user_thoughts: str | None = None
    ) -> list[dict[str, Any]]:
        """Fallback extraction method using more lenient strategy"""
        materials_text = ""
        for i, record in enumerate(records, 1):
            materials_text += (
                f"\nRecord {i}: {record.get('title', '')} - {record.get('user_query', '')[:100]}"
            )

        system_prompt = self._prompts.get("fallback_system", "")
        user_template = self._prompts.get("fallback_user_template", "")
        user_thoughts_str = f"User thoughts: {user_thoughts}" if user_thoughts else ""
        user_prompt = user_template.format(
            materials_text=materials_text,
            user_thoughts=user_thoughts_str,
        )

        try:
            response = await self.call_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
                response_format={"type": "json_object"},
            )
            result = json.loads(response)
            knowledge_points = result.get("knowledge_points", [])

            validated_points = []
            for point in knowledge_points:
                if "knowledge_point" in point and "description" in point:
                    kp = str(point["knowledge_point"]).strip()
                    desc = str(point["description"]).strip()
                    if kp and desc:
                        validated_points.append({"knowledge_point": kp, "description": desc})

            return (
                validated_points
                if validated_points
                else [
                    {
                        "knowledge_point": "Comprehensive Knowledge Point",
                        "description": f"Comprehensive knowledge content based on {len(records)} records, containing multiple research directions and concepts.",
                    }
                ]
            )
        except Exception:
            return [
                {
                    "knowledge_point": "Comprehensive Research Topic",
                    "description": f"Based on the selected {len(records)} notebook records, multiple research directions and knowledge points can be explored.",
                }
            ]
