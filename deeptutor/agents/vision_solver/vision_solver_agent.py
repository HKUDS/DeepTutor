"""Vision Solver Agent — single-call image → GeoGebra command generation.

Collapses the old four-stage pipeline (BBox → Analysis → GGBScript →
Reflection) into ONE vision call that reads the figure and emits GeoGebra
commands directly, plus a single gated repair pass that only fires when the
first call produced no usable commands. Public surface is unchanged
(:meth:`process` + :meth:`format_ggb_block`) so the ``geogebra_analysis`` tool
— the sole live consumer, used by both chat and solve — keeps working.
"""

import json
from pathlib import Path
import re
from typing import Any

from deeptutor.agents.base_agent import BaseAgent


class VisionSolverAgent(BaseAgent):
    """Analyze a math-problem image and produce GeoGebra commands in one shot."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        vision_model: str | None = None,
        language: str = "zh",
        **kwargs: Any,
    ):
        super().__init__(
            module_name="vision_solver",
            agent_name="vision_solver_agent",
            api_key=api_key,
            base_url=base_url,
            model=model,
            language=language,
            **kwargs,
        )
        self.vision_model = vision_model or model
        prompt_file = Path(__file__).parent / "prompts" / "geogebra.md"
        self._prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else ""
        if not self._prompt:
            self.logger.warning("geogebra prompt missing: %s", prompt_file)

    # ==================== Public API ====================

    async def process(
        self,
        question_text: str,
        image_base64: str | None = None,
        session_id: str = "default",
    ) -> dict[str, Any]:
        """Analyze the image and return GeoGebra commands + a geometric summary.

        Returns a dict with ``has_image``, ``final_ggb_commands`` (list of
        ``{command, description}``), ``analysis_output`` (the raw model JSON:
        constraints / geometric_relations / ...), and ``image_is_reference``.
        """
        if not image_base64:
            return {"has_image": False, "final_ggb_commands": []}

        self.logger.info("geogebra analysis - session: %s", session_id)
        analysis = await self._analyze(question_text, image_base64)
        commands = _coerce_commands(analysis.get("commands"))
        if not commands:
            # Gated repair: a single retry only when the first pass yielded no
            # usable commands (malformed JSON or an empty list). A good first
            # pass never pays for this.
            self.logger.info("geogebra analysis - empty commands, running repair pass")
            analysis = await self._analyze(question_text, image_base64, repair=True)
            commands = _coerce_commands(analysis.get("commands"))

        self.logger.info("geogebra analysis completed - commands: %d", len(commands))
        return {
            "has_image": True,
            "final_ggb_commands": commands,
            "analysis_output": analysis,
            "image_is_reference": bool(analysis.get("image_is_reference")),
        }

    def format_ggb_block(
        self,
        commands: list[dict[str, Any]],
        page_id: str = "main",
        title: str = "题目图形",
    ) -> str:
        """Wrap commands in a ``ggbscript`` fenced block the frontend renders."""
        content = self._format_commands(commands)
        if not content:
            return ""
        return f"```ggbscript[{page_id};{title}]\n{content}\n```"

    # ==================== Internals ====================

    async def _analyze(
        self,
        question_text: str,
        image_base64: str,
        *,
        repair: bool = False,
    ) -> dict[str, Any]:
        prompt = self._prompt.replace("{{ question_text }}", question_text or "")
        if repair:
            prompt += (
                "\n\n## 修复\n上一次输出未能生成有效的 `commands`。请重新审视图片，"
                "确保输出合法 JSON，且 `commands` 至少包含一条可执行的 GeoGebra 命令。"
            )
        response = await self._call_vision_llm(prompt, image_base64)
        try:
            data = self._extract_json(response)
        except (json.JSONDecodeError, ValueError):
            self.logger.warning("geogebra analysis - JSON parse failed: %s", response[:300])
            return {}
        return data if isinstance(data, dict) else {}

    async def _call_vision_llm(
        self,
        prompt: str,
        image_base64: str,
        temperature: float = 0.3,
    ) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_base64}},
                ],
            }
        ]
        chunks: list[str] = []
        async for chunk in self.stream_llm(
            user_prompt="",
            system_prompt="",
            messages=messages,
            temperature=temperature,
            model=self.vision_model or self.get_model(),
            verbose=False,
        ):
            chunks.append(chunk)
        return "".join(chunks)

    @staticmethod
    def _extract_json(response: str) -> dict[str, Any]:
        """Pull the JSON object out of an LLM response (markdown-fenced or raw)."""
        matches = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", response)
        json_str = matches[0] if matches else response
        json_str = re.sub(r"//.*?$", "", json_str, flags=re.MULTILINE)
        json_str = re.sub(r"/\*.*?\*/", "", json_str, flags=re.DOTALL)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Last resort: strip trailing commas, a common model slip.
            return json.loads(re.sub(r",\s*([}\]])", r"\1", json_str))

    @staticmethod
    def _format_commands(commands: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for cmd in commands or []:
            if isinstance(cmd, dict):
                command = str(cmd.get("command") or "").strip()
                if command:
                    lines.append(command)
            elif cmd:
                lines.append(str(cmd))
        return "\n".join(lines)


def _coerce_commands(raw: Any) -> list[dict[str, Any]]:
    """Normalize the model's ``commands`` into a list of command dicts.

    Accepts the canonical ``[{command, description}]`` shape and degrades
    gracefully to bare command strings, dropping anything empty.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("command") or "").strip():
            out.append(
                {
                    "command": str(item["command"]).strip(),
                    "description": str(item.get("description") or ""),
                }
            )
        elif isinstance(item, str) and item.strip():
            out.append({"command": item.strip(), "description": ""})
    return out
