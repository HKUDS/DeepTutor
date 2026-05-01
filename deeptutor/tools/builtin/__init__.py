"""Built-in tool implementations and metadata."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.tools.prompting import load_prompt_hints

logger = logging.getLogger(__name__)


class _PromptHintsMixin:
    """Shared prompt-hint loader for built-in tools."""

    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)


class BrainstormTool(_PromptHintsMixin, BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="brainstorm",
            description="Broadly explore multiple possibilities for a topic and give a short rationale for each.",
            parameters=[
                ToolParameter(
                    name="topic",
                    type="string",
                    description="The topic, goal, or problem to brainstorm about.",
                ),
                ToolParameter(
                    name="context",
                    type="string",
                    description="Optional supporting context, constraints, or background.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.brainstorm import brainstorm

        result = await brainstorm(
            topic=kwargs.get("topic", ""),
            context=kwargs.get("context", ""),
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
            model=kwargs.get("model"),
            max_tokens=kwargs.get("max_tokens"),
            temperature=kwargs.get("temperature"),
        )
        return ToolResult(content=result.get("answer", ""), metadata=result)


class RAGTool(_PromptHintsMixin, BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="rag",
            description=(
                "Search a knowledge base using Retrieval-Augmented Generation. "
                "Returns relevant passages and an LLM-synthesised answer."
            ),
            parameters=[
                ToolParameter(name="query", type="string", description="Search query."),
                ToolParameter(
                    name="kb_name",
                    type="string",
                    description="Knowledge base to search.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.rag_tool import rag_search

        query = str(kwargs.get("query") or "").strip()
        if not query:
            raise ValueError("RAG query must be a non-empty string.")
        kb_name = kwargs.get("kb_name")
        event_sink = kwargs.get("event_sink")
        extra_kwargs = {
            key: value
            for key, value in kwargs.items()
            if key not in {"query", "kb_name", "event_sink"}
        }

        result = await rag_search(
            query=query,
            kb_name=kb_name,
            event_sink=event_sink,
            **extra_kwargs,
        )
        content = result.get("answer") or result.get("content", "")
        return ToolResult(
            content=content,
            sources=[{"type": "rag", "query": query, "kb_name": kb_name}],
            metadata=result,
        )


class WebSearchTool(_PromptHintsMixin, BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_search",
            description="Search the web and return summarised results with citations.",
            parameters=[
                ToolParameter(name="query", type="string", description="Search query."),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.web_search import web_search

        query = kwargs.get("query", "")
        output_dir = kwargs.get("output_dir")
        verbose = kwargs.get("verbose", False)
        result = await asyncio.to_thread(
            web_search,
            query=query,
            output_dir=output_dir,
            verbose=verbose,
        )

        if isinstance(result, dict):
            answer = result.get("answer", "")
            citations = result.get("citations", [])
        else:
            answer = str(result)
            citations = []

        return ToolResult(
            content=answer,
            sources=[
                {"type": "web", "url": citation.get("url", ""), "title": citation.get("title", "")}
                for citation in citations
            ],
            metadata=result if isinstance(result, dict) else {"raw": answer},
        )


class CodeExecutionTool(_PromptHintsMixin, BaseTool):
    _CODEGEN_SYSTEM_PROMPT = """You are a Python code generator.

Convert the user's natural-language request into executable Python code only.

Rules:
- Output only Python code, with no markdown fences or explanation.
- Prefer standard library plus these common packages when useful: math, numpy, pandas, matplotlib, scipy, sympy.
- Print the final answer to stdout.
- Save plots or generated files to the current working directory.
- Keep the code focused on the requested computation or verification task.
"""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="code_execution",
            description="Turn a natural-language computation request into Python, run it in a restricted Python worker, and return the result.",
            parameters=[
                ToolParameter(
                    name="intent",
                    type="string",
                    description="Natural-language description of the computation or verification task.",
                ),
                ToolParameter(
                    name="code",
                    type="string",
                    description="Optional raw Python code to execute directly.",
                    required=False,
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Max execution time in seconds.",
                    required=False,
                    default=30,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.code_executor import run_code

        code = str(kwargs.get("code") or "").strip()
        intent = str(kwargs.get("intent") or kwargs.get("query") or "").strip()
        timeout = int(kwargs.get("timeout", 30) or 30)
        workspace_dir = kwargs.get("workspace_dir")
        feature = kwargs.get("feature")
        task_id = kwargs.get("task_id")
        session_id = kwargs.get("session_id")
        turn_id = kwargs.get("turn_id")

        if not code:
            if not intent:
                raise ValueError("code_execution requires either 'intent' or 'code'")
            code = await self._generate_code(intent)

        result = await run_code(
            language="python",
            code=code,
            timeout=timeout,
            workspace_dir=workspace_dir,
            feature=feature,
            task_id=task_id,
            session_id=session_id,
            turn_id=turn_id,
        )
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        exit_code = result.get("exit_code", 1)
        artifacts = result.get("artifacts", [])

        parts: list[str] = []
        if stdout:
            parts.append(stdout.strip())
        if stderr:
            label = "Error" if exit_code else "Stderr"
            parts.append(f"{label}:\n{stderr.strip()}")
        if artifacts:
            parts.append(f"Artifacts: {', '.join(str(item) for item in artifacts)}")
        if not parts:
            parts.append("Execution completed with no output.")

        metadata = {**result, "code": code, "intent": intent}
        return ToolResult(
            content="\n\n".join(parts),
            success=exit_code == 0,
            sources=[{"type": "code", "file": artifact} for artifact in artifacts],
            metadata=metadata,
        )

    async def _generate_code(self, intent: str) -> str:
        from deeptutor.services.llm import complete, get_token_limit_kwargs
        from deeptutor.services.llm.config import get_llm_config

        llm_config = get_llm_config()
        completion_kwargs: dict[str, Any] = {"temperature": 0.0}
        if getattr(llm_config, "model", None):
            completion_kwargs.update(get_token_limit_kwargs(llm_config.model, 1200))

        response = await complete(
            prompt=intent,
            system_prompt=self._CODEGEN_SYSTEM_PROMPT,
            model=llm_config.model,
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=getattr(llm_config, "api_version", None),
            binding=getattr(llm_config, "binding", None),
            **completion_kwargs,
        )
        code = self._strip_markdown_fences(response)
        if not code.strip():
            raise ValueError("LLM returned empty code for code_execution")
        return code

    @staticmethod
    def _strip_markdown_fences(content: str) -> str:
        cleaned = content.strip()
        if not cleaned.startswith("```"):
            return cleaned

        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()


class ReasonTool(_PromptHintsMixin, BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="reason",
            description=(
                "Perform deep reasoning on a complex sub-problem using a dedicated LLM call. "
                "Use when the current context is insufficient for a confident answer."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="The sub-problem to reason about.",
                ),
                ToolParameter(
                    name="context",
                    type="string",
                    description="Supporting context for reasoning.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.reason import reason

        result = await reason(
            query=kwargs.get("query", ""),
            context=kwargs.get("context", ""),
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url"),
            model=kwargs.get("model"),
            max_tokens=kwargs.get("max_tokens"),
            temperature=kwargs.get("temperature"),
        )
        return ToolResult(content=result.get("answer", ""), metadata=result)


class PaperSearchToolWrapper(_PromptHintsMixin, BaseTool):
    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="paper_search",
            description="Search arXiv preprints by keyword and return concise metadata.",
            parameters=[
                ToolParameter(name="query", type="string", description="Search query."),
                ToolParameter(
                    name="max_results",
                    type="integer",
                    description="Maximum papers to return.",
                    required=False,
                    default=3,
                ),
                ToolParameter(
                    name="years_limit",
                    type="integer",
                    description="Only include preprints from the last N years.",
                    required=False,
                    default=3,
                ),
                ToolParameter(
                    name="sort_by",
                    type="string",
                    description="Sort by relevance or submission date.",
                    required=False,
                    default="relevance",
                    enum=["relevance", "date"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.paper_search_tool import ArxivSearchTool

        try:
            papers = await ArxivSearchTool().search_papers(
                query=kwargs.get("query", ""),
                max_results=kwargs.get("max_results", 3),
                years_limit=kwargs.get("years_limit", 3),
                sort_by=kwargs.get("sort_by", "relevance"),
            )
        except Exception:
            return ToolResult(
                content="arXiv search is temporarily unavailable (rate-limited or network error). Please try again later.",
                sources=[],
                metadata={"provider": "arxiv", "papers": [], "error": True},
            )
        if not papers:
            return ToolResult(
                content="No arXiv preprints found for this query.",
                sources=[],
                metadata={"provider": "arxiv", "papers": []},
            )

        lines: list[str] = []
        for paper in papers:
            lines.append(f"**{paper['title']}** ({paper.get('year', '?')})")
            lines.append(f"Authors: {', '.join(paper.get('authors', []))}")
            lines.append(f"arXiv: {paper.get('arxiv_id', '')}")
            lines.append(f"URL: {paper.get('url', '')}")
            lines.append(f"Abstract: {paper.get('abstract', '')[:400]}")
            lines.append("")

        return ToolResult(
            content="\n".join(lines),
            sources=[
                {
                    "type": "paper",
                    "provider": "arxiv",
                    "url": paper.get("url", ""),
                    "title": paper.get("title", ""),
                    "arxiv_id": paper.get("arxiv_id", ""),
                }
                for paper in papers
            ],
            metadata={"provider": "arxiv", "papers": papers},
        )


class VisitUrlTool(_PromptHintsMixin, BaseTool):
    """Fetch one or more URLs in parallel and verify whether each is alive and contains the expected content."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="visit_url",
            description=(
                "Fetch one or more URLs in parallel, verify each is reachable (HTTP 2xx), and extract readable text. "
                "Pass multiple URLs as newline-separated strings. "
                "Use this to validate that cited source URLs actually exist and contain the claimed content. "
                "Returns per-URL results with title, alive flag, and claim verification."
            ),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description=(
                        "A single URL or multiple newline-separated URLs to visit and verify. "
                        "Example: 'https://example.com' or 'https://a.com\\nhttps://b.com'"
                    ),
                ),
                ToolParameter(
                    name="claim",
                    type="string",
                    description="Optional claim or citation text to check against the page content. If provided, the tool will indicate whether the claim appears to be supported by the page.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        raw_url = kwargs.get("url", "")
        claim = str(kwargs.get("claim", "")).strip()

        # Normalize to list: handle string (single or newline-separated), list, or list-like
        if isinstance(raw_url, str):
            url_str = raw_url.strip()
            if not url_str:
                return ToolResult(
                    content="No URL provided.",
                    success=False,
                    metadata={"alive": False, "status_code": None},
                )
            # Split newline-separated URLs
            url_list = [u.strip() for u in url_str.split("\n") if u.strip()]
        elif isinstance(raw_url, (list, tuple)):
            url_list = [str(u).strip() for u in raw_url if str(u).strip()]
            if not url_list:
                return ToolResult(
                    content="No URL provided.",
                    success=False,
                    metadata={"alive": False, "status_code": None},
                )
        else:
            url_list = [str(raw_url).strip()]
            if not url_list[0]:
                return ToolResult(
                    content="No URL provided.",
                    success=False,
                    metadata={"alive": False, "status_code": None},
                )

        import asyncio
        import textwrap

        try:
            import httpx
        except ImportError:
            return ToolResult(
                content="httpx is not installed. Install it with: pip install httpx",
                success=False,
                metadata={"alive": False, "error": "httpx not available"},
            )

        def _verify_claim_via_embedding(claim_text: str, page_text: str) -> bool | None:
            """Check claim against page using embedding similarity; falls back to token check."""
            try:
                from llama_index.core import Settings

                embed_model = getattr(Settings, "embed_model", None)
                if embed_model is None:
                    raise RuntimeError("embed_model not configured")

                import numpy as np

                claim_emb = embed_model.get_text_embedding(claim_text)
                page_emb = embed_model.get_text_embedding(page_text[:3000])

                norm_claim = np.linalg.norm(claim_emb)
                norm_page = np.linalg.norm(page_emb)
                if norm_claim == 0 or norm_page == 0:
                    return None

                similarity = float(np.dot(claim_emb, page_emb) / (norm_claim * norm_page))
                return similarity >= 0.75
            except Exception:
                # Fallback to token-based check
                claim_tokens = [t.strip() for t in claim_text.lower().split() if len(t.strip()) >= 4]
                if not claim_tokens:
                    return None
                page_lower = page_text.lower()
                missing = [t for t in claim_tokens if t not in page_lower]
                return (len(missing) / len(claim_tokens)) <= 0.2

        async def _fetch_one(target_url: str) -> dict[str, Any]:
            """Fetch a single URL and return structured result."""
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; DeepTutorBot/1.0; +https://example.com/bot)"
            }
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    response = await client.get(target_url, headers=headers)
                    status = response.status_code
                    raw_text = response.text
                    title = ""
                    if "text/html" in response.headers.get("content-type", ""):
                        import re
                        m = re.search(r"<title[^>]*>([^<]+)</title>", raw_text, re.IGNORECASE)
                        if m:
                            title = m.group(1).strip()
                        try:
                            from lxml import html
                            tree = html.fromstring(raw_text)
                            clean_text = tree.text_content() or ""
                        except Exception:
                            clean_text = raw_text
                    else:
                        clean_text = raw_text

                    alive = 200 <= status < 400
                    page_text = clean_text[:8000]

                    if not alive:
                        result_content = f"URL is not reachable (status {status}). The source may be broken or the page no longer exists."
                        claim_verified = None
                    else:
                        lines = [f"Title: {title}"] if title else []
                        lines.append(f"Status: {status} OK")
                        if claim:
                            # Primary: embedding-based semantic similarity check
                            claim_verified = _verify_claim_via_embedding(claim, page_text)
                            if claim_verified is True:
                                lines.append("Claim SUPPORTED: semantically aligned with page content.")
                            elif claim_verified is False:
                                lines.append("Claim NOT VERIFIED: the cited content was not found in the page. The claim may be inaccurate or the URL may point to a different version of the content.")
                            else:
                                # None means both methods failed — be conservative
                                lines.append("Claim VERIFICATION INCONCLUSIVE: could not verify claim.")
                            lines.append("")
                        lines.append("Page content snippet:")
                        lines.append(textwrap.fill(page_text[:2000], width=120))
                        result_content = "\n".join(lines)

                    return {
                        "url": target_url,
                        "content": result_content,
                        "alive": alive,
                        "status_code": status,
                        "title": title,
                        "claim_verified": claim_verified,
                    }
            except httpx.UnsupportedProtocol:
                return {
                    "url": target_url,
                    "content": f"Invalid URL format: missing http:// or https:// protocol.",
                    "alive": False,
                    "status_code": None,
                    "title": "",
                    "claim_verified": None,
                }
            except Exception as exc:
                return {
                    "url": target_url,
                    "content": f"Failed to fetch URL: {exc}",
                    "alive": False,
                    "status_code": None,
                    "title": "",
                    "claim_verified": None,
                }

        try:
            results: list[dict[str, Any]] = await asyncio.wait_for(
                asyncio.gather(*[_fetch_one(u) for u in url_list]),
                timeout=20.0,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                content=f"URL fetch timed out after 20 seconds: {url_list[0]}" + (" and others" if len(url_list) > 1 else ""),
                success=False,
                metadata={"alive": False, "error": "timeout"},
            )

        # Aggregate results
        all_alive = all(r["alive"] for r in results)
        all_sources = [{"type": "web", "url": r["url"], "title": r["title"]} for r in results]

        if len(results) == 1:
            r = results[0]
            return ToolResult(
                content=r["content"],
                success=r["alive"],
                sources=all_sources,
                metadata={
                    "alive": r["alive"],
                    "status_code": r["status_code"],
                    "url": r["url"],
                    "title": r["title"],
                    "claim_verified": r["claim_verified"],
                },
            )

        # Multiple URLs — format as batch report
        lines = [f"## Batch URL Verification ({len(results)} URLs)\n"]
        for r in results:
            lines.append(f"### {r['url']}")
            status_str = f"DEAD ({r['status_code']})" if not r["alive"] else "ALIVE"
            lines.append(f"Status: {status_str}")
            if r["title"]:
                lines.append(f"Title: {r['title']}")
            if claim:
                lines.append(f"Claim: {claim}")
                lines.append(f"Claim verified: {'YES' if r['claim_verified'] else 'NO'}")
            lines.append(f"Content:\n{r['content']}")
            lines.append("")
        content = "\n".join(lines).strip()

        return ToolResult(
            content=content,
            success=all_alive,
            sources=all_sources,
            metadata={
                "alive": all_alive,
                "url_count": len(results),
                "alive_count": sum(1 for r in results if r["alive"]),
                "dead_count": sum(1 for r in results if not r["alive"]),
                "results": [
                    {
                        "url": r["url"],
                        "alive": r["alive"],
                        "status_code": r["status_code"],
                        "title": r["title"],
                        "claim_verified": r["claim_verified"],
                    }
                    for r in results
                ],
            },
        )

    execute._uses_batch = True  # type: ignore[attr-defined]


class GeoGebraAnalysisTool(_PromptHintsMixin, BaseTool):
    """Analyze a math-problem image and generate GeoGebra visualization commands."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="geogebra_analysis",
            description=(
                "Analyze a math problem image, detect geometric elements, "
                "and generate validated GeoGebra commands for visualization. "
                "Requires an attached image."
            ),
            parameters=[
                ToolParameter(
                    name="question",
                    type="string",
                    description="The math problem text to analyze.",
                ),
                ToolParameter(
                    name="image_base64",
                    type="string",
                    description="Base64-encoded image (data URI or raw). Injected from attachments when called via function-calling.",
                    required=False,
                    default="",
                ),
                ToolParameter(
                    name="language",
                    type="string",
                    description="Output language: 'zh' or 'en'.",
                    required=False,
                    default="zh",
                    enum=["zh", "en"],
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.agents.vision_solver.vision_solver_agent import VisionSolverAgent
        from deeptutor.services.llm.config import get_llm_config

        question = kwargs.get("question", "")
        image_base64 = kwargs.get("image_base64", "")
        language = kwargs.get("language", "zh")

        if not image_base64:
            return ToolResult(
                content="No image provided. This tool requires an image attachment.",
                success=False,
            )

        llm_config = get_llm_config()
        agent = VisionSolverAgent(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            language=language,
        )

        try:
            result = await agent.process(
                question_text=question,
                image_base64=image_base64,
            )
        except Exception as exc:
            logger.exception("GeoGebra analysis pipeline failed")
            return ToolResult(content=f"Analysis pipeline error: {exc}", success=False)

        if not result.get("has_image"):
            return ToolResult(content="No image was processed.", success=False)

        final_commands = result.get("final_ggb_commands", [])
        ggb_block = agent.format_ggb_block(final_commands)

        analysis = result.get("analysis_output") or {}
        constraints = analysis.get("constraints", [])
        relations = analysis.get("geometric_relations", [])
        summary_parts: list[str] = []
        if constraints:
            summary_parts.append(
                f"Constraints ({len(constraints)}): {json.dumps(constraints[:5], ensure_ascii=False)}"
            )
        if relations:
            relation_descriptions = [
                relation.get("description", str(relation))
                if isinstance(relation, dict)
                else str(relation)
                for relation in relations[:5]
            ]
            summary_parts.append(
                f"Relations ({len(relations)}): {json.dumps(relation_descriptions, ensure_ascii=False)}"
            )

        content_parts: list[str] = []
        if summary_parts:
            content_parts.append("\n".join(summary_parts))
        content_parts.append(ggb_block or "(No GeoGebra commands generated.)")

        return ToolResult(
            content="\n\n".join(content_parts),
            metadata={
                "has_image": True,
                "commands_count": len(final_commands),
                "final_ggb_commands": final_commands,
                "image_is_reference": result.get("image_is_reference", False),
                "bbox_elements": len((result.get("bbox_output") or {}).get("elements", [])),
                "constraints_count": len(constraints),
                "relations_count": len(relations),
                "reflection_issues": len(
                    (result.get("reflection_output") or {}).get("issues_found", [])
                ),
            },
        )


BUILTIN_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    BrainstormTool,
    RAGTool,
    WebSearchTool,
    VisitUrlTool,
    CodeExecutionTool,
    ReasonTool,
    PaperSearchToolWrapper,
    GeoGebraAnalysisTool,
)

BUILTIN_TOOL_NAMES: tuple[str, ...] = tuple(tool_type().name for tool_type in BUILTIN_TOOL_TYPES)

TOOL_ALIASES: dict[str, tuple[str, dict[str, Any]]] = {
    "rag_hybrid": ("rag", {"mode": "hybrid"}),
    "rag_naive": ("rag", {"mode": "naive"}),
    "rag_search": ("rag", {}),
    "code_execute": ("code_execution", {}),
    "run_code": ("code_execution", {}),
    "visit_url": ("visit_url", {}),
}

__all__ = [
    "BUILTIN_TOOL_NAMES",
    "BUILTIN_TOOL_TYPES",
    "TOOL_ALIASES",
    "BrainstormTool",
    "CodeExecutionTool",
    "GeoGebraAnalysisTool",
    "PaperSearchToolWrapper",
    "RAGTool",
    "ReasonTool",
    "VisitUrlTool",
    "WebSearchTool",
]
