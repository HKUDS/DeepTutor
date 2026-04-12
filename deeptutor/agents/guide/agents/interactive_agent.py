#!/usr/bin/env python
"""
InteractiveAgent - Agent for generating interactive HTML pages
Converts knowledge points into visual, interactive learning pages
"""

import re
from typing import Any

from deeptutor.agents.base_agent import BaseAgent


class InteractiveAgent(BaseAgent):
    """Interactive page generation agent"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        language: str = "zh",
        api_version: str | None = None,
        binding: str = "openai",
    ):
        super().__init__(
            module_name="guide",
            agent_name="interactive_agent",
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            language=language,
        )

    def _extract_html(self, response: str) -> str:
        """Extract HTML code from LLM response"""
        html_pattern = r"```html\s*([\s\S]*?)\s*```"
        match = re.search(html_pattern, response)
        if match:
            return match.group(1).strip()

        code_pattern = r"```\s*([\s\S]*?)\s*```"
        match = re.search(code_pattern, response)
        if match:
            content = match.group(1).strip()
            if content.startswith("<!DOCTYPE") or content.startswith("<html"):
                return content

        if response.strip().startswith("<!DOCTYPE") or response.strip().startswith("<html"):
            return response.strip()

        return response.strip()

    def _validate_html(self, html: str) -> bool:
        """Validate if HTML is basically valid"""
        return (
            "<html" in html.lower()
            or "<!doctype" in html.lower()
            or "<body" in html.lower()
            or "<div" in html.lower()
        )

    def _is_retryable_error(self, error: str) -> bool:
        lowered = error.lower()
        return any(
            marker in lowered
            for marker in (
                "429",
                "rate limit",
                "rate_limit",
                "too many requests",
                "resource exhausted",
                "resource has been exhausted",
                "quota",
            )
        )

    def _generate_fallback_html(self, knowledge: dict[str, Any]) -> str:
        """Generate fallback HTML page"""
        title = knowledge.get("knowledge_title", "Knowledge Point")
        summary = knowledge.get("knowledge_summary", "").replace("\n", "<br>")
        difficulty = knowledge.get("user_difficulty", "").replace("\n", "<br>")

        return f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" integrity="sha384-n8MVd4RsNIU0tAv4ct0nTaAbDJwPJzDEaqSD1odI+WdtXRGWt2kTvGFasHpSy3SV" crossorigin="anonymous">
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js" integrity="sha384-XjKyOOlGwcjNTAIQHIpgOno0Hl1YQqzUOEleOLALmuqehneUG+vnGctmUb0ZY0l8" crossorigin="anonymous"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js" integrity="sha384-+VBxd3r6XgURycqtZ117n7w6ODWgRrA7TlVzRsFtwW3ZxUo8h4w20Z5J3d3xjfcw" crossorigin="anonymous" onload="renderMathInElement(document.body);"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #F8FAFC 0%, #EFF6FF 100%);
            min-height: 100vh;
            padding: 2rem;
            color: #1E293B;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        .card {{
            background: white;
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 25px -5px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #1E40AF;
            font-size: 1.75rem;
            margin-bottom: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        h2 {{
            color: #3B82F6;
            font-size: 1.25rem;
            margin-bottom: 1rem;
        }}
        .content {{
            line-height: 1.8;
            color: #475569;
        }}
        .difficulty {{
            background: #FEF3C7;
            border-left: 4px solid #F59E0B;
            padding: 1rem;
            border-radius: 0 8px 8px 0;
            margin-top: 1rem;
        }}
        .difficulty h3 {{
            color: #B45309;
            margin-bottom: 0.5rem;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>📚 {title}</h1>
        </div>
        <div class="card">
            <h2>Knowledge Content</h2>
            <div class="content">{summary}</div>
        </div>
        <div class="card">
            <h2>💡 Notes</h2>
            <div class="difficulty">
                <h3>Possible Difficulties</h3>
                <p>{difficulty}</p>
            </div>
        </div>
    </div>
</body>
</html>"""

    async def process(
        self, knowledge: dict[str, Any], retry_with_bug: str | None = None
    ) -> dict[str, Any]:
        """
        Generate interactive HTML learning page

        Args:
            knowledge: Knowledge point information (knowledge_title, knowledge_summary, user_difficulty)
            retry_with_bug: If provided, it's a bug fix request

        Returns:
            Dictionary containing HTML code
        """
        system_prompt = self.get_prompt("system")
        if not system_prompt:
            raise ValueError(
                "InteractiveAgent missing system prompt, please configure system in prompts/{lang}/interactive_agent.yaml"
            )

        user_template = self.get_prompt("user_template")
        if not user_template:
            raise ValueError(
                "InteractiveAgent missing user_template, please configure user_template in prompts/{lang}/interactive_agent.yaml"
            )

        if retry_with_bug:
            formatted_knowledge = user_template.format(
                knowledge_title=knowledge.get("knowledge_title", ""),
                knowledge_summary=knowledge.get("knowledge_summary", ""),
                user_difficulty=knowledge.get("user_difficulty", ""),
                generation_requirements=knowledge.get("generation_requirements", ""),
                content_blueprint=knowledge.get("content_blueprint", ""),
            )
            user_prompt = f"""The previously generated HTML page has the following issues:
{retry_with_bug}

Please fix these issues and regenerate the HTML page.

Original knowledge point information:
{formatted_knowledge}"""
        else:
            user_prompt = user_template.format(
                knowledge_title=knowledge.get("knowledge_title", ""),
                knowledge_summary=knowledge.get("knowledge_summary", ""),
                user_difficulty=knowledge.get("user_difficulty", ""),
                generation_requirements=knowledge.get("generation_requirements", ""),
                content_blueprint=knowledge.get("content_blueprint", ""),
            )

        try:
            _chunks: list[str] = []
            async for _c in self.stream_llm(
                user_prompt=user_prompt,
                system_prompt=system_prompt,
            ):
                _chunks.append(_c)
            response = "".join(_chunks)

            html_code = self._extract_html(response)

            if not self._validate_html(html_code):
                html_code = self._generate_fallback_html(knowledge)
                return {
                    "success": True,
                    "html": html_code,
                    "is_fallback": True,
                    "message": "Used fallback template",
                }

            return {"success": True, "html": html_code, "is_fallback": False}

        except Exception as e:
            error_message = str(e)
            if self._is_retryable_error(error_message):
                return {
                    "success": False,
                    "retryable": True,
                    "error": error_message,
                    "html": "",
                }

            html_code = self._generate_fallback_html(knowledge)
            return {
                "success": True,
                "html": html_code,
                "is_fallback": True,
                "error": error_message,
                "message": "Error occurred, used fallback template",
            }
