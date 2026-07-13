"""Built-in tool implementations and metadata."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from deeptutor.capabilities.mastery import MASTERY_TOOL_TYPES
from deeptutor.capabilities.obsidian import OBSIDIAN_TOOL_TYPES
from deeptutor.capabilities.solve import SOLVE_TOOL_TYPES
from deeptutor.capabilities.subagent import SUBAGENT_TOOL_TYPES
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.tools.exec_tool import ExecTool
from deeptutor.tools.media_gen_tool import ImagegenTool, VideogenTool
from deeptutor.tools.partner_memory import (
    PARTNER_BUILTIN_TOOL_NAMES,
    PartnerMemorizeTool,
    PartnerReadTool,
    PartnerSearchTool,
)
from deeptutor.tools.prompting import load_prompt_hints

logger = logging.getLogger(__name__)


def _unique_run_token() -> str:
    """Short collision-resistant token for naming per-call code run dirs."""
    import uuid

    return uuid.uuid4().hex[:12]


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
                "Retrieve relevant passages from one of the knowledge bases the "
                "user attached to this turn. Call once per knowledge base you "
                "want to consult; the system runs them in parallel."
            ),
            parameters=[
                ToolParameter(name="query", type="string", description="Search query."),
                ToolParameter(
                    name="kb_name",
                    type="string",
                    description="Knowledge base to search. Must be one of the attached knowledge bases.",
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.rag_tool import rag_search

        query = str(kwargs.get("query") or "").strip()
        if not query:
            raise ValueError("RAG query must be a non-empty string.")
        kb_name = str(kwargs.get("kb_name") or "").strip()
        if not kb_name:
            raise ValueError("RAG requires an explicit kb_name.")
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
    """Compile and run a code snippet inside the execution sandbox.

    A typed front-end over the same sandbox ``exec`` uses: the model passes
    ready-to-run source as ``code`` + a ``language``; we write it into the
    turn's workspace, build the per-language compile/run command, and execute
    it through :mod:`deeptutor.services.sandbox`. No second LLM call, and the
    same OS-level isolation + quota as ``exec`` — so it inherits exec's gating
    (unavailable when no sandbox backend is configured).
    """

    # language -> (source filename, shell command template). ``{src}`` is the
    # source file, ``{bin}`` the compiled binary, ``{stdin}`` an optional
    # ``< file`` redirect (empty when no stdin is supplied). Commands run with
    # the workspace subdir as cwd, so plain relative names are enough.
    _LANGUAGES: dict[str, tuple[str, str]] = {
        "python": ("main.py", "python3 {src} {stdin}"),
        "c": ("main.c", "cc {src} -O2 -o prog && ./prog {stdin}"),
        "cpp": ("main.cpp", "c++ -std=c++17 -O2 {src} -o prog && ./prog {stdin}"),
    }
    _LANGUAGE_ALIASES: dict[str, str] = {
        "py": "python",
        "python3": "python",
        "c++": "cpp",
        "cxx": "cpp",
        "cc": "c",
    }

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="code_execution",
            description=(
                "Run a code snippet in an isolated sandbox and return its "
                "stdout/stderr. Pass complete, ready-to-run source in `code` "
                "and pick `language` (python, c, or cpp). Use for calculation, "
                "algorithm checking, and numerical verification — print results "
                "to stdout. Not a substitute for explaining your reasoning."
            ),
            parameters=[
                ToolParameter(
                    name="language",
                    type="string",
                    description="Source language: 'python', 'c', or 'cpp'.",
                ),
                ToolParameter(
                    name="code",
                    type="string",
                    description="The complete source code to compile/run.",
                ),
                ToolParameter(
                    name="stdin",
                    type="string",
                    description="Optional text piped to the program's stdin.",
                    required=False,
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Max execution time in seconds (default 30, max 300).",
                    required=False,
                    default=30,
                ),
            ],
        )

    def _resolve_language(self, raw: Any) -> str:
        name = str(raw or "").strip().lower()
        name = self._LANGUAGE_ALIASES.get(name, name)
        if name not in self._LANGUAGES:
            supported = ", ".join(sorted(self._LANGUAGES))
            raise ValueError(f"Unsupported language {raw!r}; supported: {supported}.")
        return name

    async def execute(self, **kwargs: Any) -> ToolResult:
        from pathlib import Path

        from deeptutor.services.sandbox import (
            ExecRequest,
            Mount,
            ResourceLimits,
            get_sandbox_service,
        )
        from deeptutor.services.sandbox.artifacts import (
            collect_public_artifacts,
            render_artifacts_for_tool,
        )

        code = str(kwargs.get("code") or "").strip()
        if not code:
            raise ValueError("code_execution requires non-empty 'code'.")
        language = self._resolve_language(kwargs.get("language"))
        source_name, command_template = self._LANGUAGES[language]

        try:
            timeout = int(kwargs.get("timeout") or 30)
        except (TypeError, ValueError):
            timeout = 30
        timeout = max(1, min(timeout, 300))

        # ``_sandbox_*`` kwargs are injected server-side by the pipeline; the
        # LLM never supplies them. Mirror ExecTool's contract.
        user_id = str(kwargs.get("_sandbox_user_id") or "anonymous")
        workdir = str(kwargs.get("_sandbox_workdir") or "").strip()
        mounts = tuple(kwargs.get("_sandbox_mounts") or ())
        if not workdir:
            # No pipeline workspace (e.g. direct/tool tests): fall back to the
            # detached code workspace the path service already manages.
            from deeptutor.services.path_service import get_path_service

            workdir = str(get_path_service().get_run_code_workspace_dir())
            mounts = (Mount(host_path=workdir, sandbox_path=workdir, read_only=False),)

        # Each call gets its own subdir so concurrent runs don't clobber one
        # another's source / binary. The subdir lives inside the mounted
        # workspace, so the sandbox sees it at the same path.
        run_dir = Path(workdir) / f"{language}_{_unique_run_token()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / source_name).write_text(code, encoding="utf-8")

        stdin_redirect = ""
        if str(kwargs.get("stdin") or "") != "":
            (run_dir / "stdin.txt").write_text(str(kwargs["stdin"]), encoding="utf-8")
            stdin_redirect = "< stdin.txt"
        command = command_template.format(src=source_name, stdin=stdin_redirect).strip()

        limits = ResourceLimits(timeout_s=timeout)
        request = ExecRequest(
            command=command,
            workdir=str(run_dir),
            mounts=mounts,
            limits=limits,
        )
        result = await get_sandbox_service().run(request, user_id=user_id)

        # The source file, compiled binary, and stdin scratch are inputs we
        # wrote ourselves — exclude them so only program-generated files
        # surface as artifacts.
        meta_files = {source_name, "prog", "stdin.txt"}
        artifacts = [
            artifact
            for artifact in collect_public_artifacts(str(run_dir))
            if artifact.filename not in meta_files
        ]
        artifact_rows = [artifact.to_dict() for artifact in artifacts]
        content_parts = [result.render(limits.max_output_chars)]
        artifact_text = render_artifacts_for_tool(artifacts)
        if artifact_text:
            content_parts.append(artifact_text)

        return ToolResult(
            content="\n\n".join(content_parts),
            success=result.ok and result.exit_code == 0,
            sources=[
                {
                    "type": "artifact",
                    "filename": row["filename"],
                    "url": row["url"],
                    "path": row["path"],
                    "mime_type": row["mime_type"],
                    "size_bytes": row["size_bytes"],
                }
                for row in artifact_rows
            ],
            metadata={
                "language": language,
                "code": code,
                "command": command,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
                "sandbox_error": result.error,
                "run_dir": str(run_dir),
                "artifacts": artifact_rows,
            },
        )


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
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.agents.vision_solver.vision_solver_agent import VisionSolverAgent
        from deeptutor.services.llm.config import get_llm_config

        question = kwargs.get("question", "")
        image_base64 = kwargs.get("image_base64", "")
        # language is server-injected from the user's session setting by the
        # chat pipeline; never accept an LLM-provided override.
        language = kwargs.get("language") or "zh"

        if not image_base64:
            return ToolResult(
                content="No image provided. This tool requires an image attachment.",
                success=False,
            )

        # VisionSolverAgent expects a fully-qualified ``data:image/<fmt>;base64,…``
        # URI for the OpenAI image_url shape. The chat pipeline injects this
        # form already, but defensively normalize for any other caller (or a
        # hallucinated kwarg) so we don't silently fall through 4 empty stages.
        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/png;base64,{image_base64}"

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
                "constraints_count": len(constraints),
                "relations_count": len(relations),
            },
        )


class ReadSourceTool(_PromptHintsMixin, BaseTool):
    """Load the full text of an attached Space source by its manifest id.

    The chat pipeline auto-enables this tool whenever a turn has any non-image
    attached source (notebook record, book reference, history session,
    question-bank entry, or document attachment). The per-turn full-text
    payload is carried in ``context.metadata["source_index"]`` as
    ``{source_id: str}`` and injected into the tool call by
    ``_augment_tool_kwargs``. The tool itself stays stateless.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_source",
            description=(
                "Load the full text of one attached source by id. Use ONLY when "
                "the preview shown in the Attached Sources manifest is "
                "insufficient to answer the user's question. The id must be "
                "copied verbatim from the manifest — do not invent ids. Do not "
                "call this on every source 'just in case'."
            ),
            parameters=[
                ToolParameter(
                    name="source_id",
                    type="string",
                    description=(
                        "The source identifier from the Attached Sources "
                        "manifest. Begins with one of: nb- (notebook record), "
                        "bk- (book reference), hs- (history session), qb- "
                        "(question-bank entry), at- (document attachment)."
                    ),
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        source_id = str(kwargs.get("source_id") or "").strip()
        if not source_id:
            return ToolResult(
                content="Error: source_id is required.",
                success=False,
            )
        source_index = kwargs.get("source_index")
        if not isinstance(source_index, dict) or not source_index:
            return ToolResult(
                content=("Error: no attached sources are available for this turn."),
                success=False,
            )
        full_text = source_index.get(source_id)
        if not full_text:
            available = ", ".join(sorted(source_index.keys()))
            return ToolResult(
                content=(
                    f"Error: unknown source_id {source_id!r}. "
                    f"Valid ids for this turn: {available or '(none)'}."
                ),
                success=False,
            )
        return ToolResult(
            content=str(full_text),
            metadata={"source_id": source_id, "char_count": len(str(full_text))},
        )


class ReadMemoryTool(_PromptHintsMixin, BaseTool):
    """Read the current user's L3 cross-surface Memory.

    Returns the concatenation of the four L3 markdown documents
    (recent / profile / scope / preferences). Multi-user-safe: paths
    resolve to the active user via the runtime's ContextVars.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_memory",
            description=(
                "Read the user's persistent memory: recent learning summary, "
                "user profile, knowledge scope, and explicit preferences. "
                "Use to personalise tone, depth, and examples — not on "
                "every turn, not for purely factual questions."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.memory import get_memory_store

        text = get_memory_store().read_l3_concat()
        return ToolResult(
            content=text,
            metadata={"char_count": len(text)},
        )


class WriteMemoryTool(_PromptHintsMixin, BaseTool):
    """Persist an explicit user preference into the L3 ``preferences.md``.

    The only chat-mode write into memory. Other memory docs are updated
    through the Memory workbench by the user manually. This tool is for
    moments when the user *explicitly* states a preference — speak it
    back to them only if natural, then call this with the substance.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_memory",
            description=(
                "Save an explicit user preference (writing style, language "
                "choice, depth, format) to long-term memory. Call ONLY when "
                "the user clearly states a preference — never speculate."
            ),
            parameters=[
                ToolParameter(
                    name="op",
                    type="string",
                    description="`add` for a new preference, `edit` to revise an existing one.",
                    enum=["add", "edit"],
                    required=True,
                ),
                ToolParameter(
                    name="text",
                    type="string",
                    description="The preference, in the user's own words where possible. ≤ 240 chars.",
                    required=True,
                ),
                ToolParameter(
                    name="target_id",
                    type="string",
                    description="Existing entry id (form `m_xxx`). Required for `edit`.",
                    required=False,
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description="Optional one-line note shown in the Memory workbench.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.memory import get_memory_store
        from deeptutor.services.memory.trace import TraceEvent

        op = str(kwargs.get("op") or "").strip().lower()
        text = str(kwargs.get("text") or "").strip()
        target_id = kwargs.get("target_id")
        reason = kwargs.get("reason")

        if op not in {"add", "edit"}:
            return ToolResult(
                content=f"Error: op must be 'add' or 'edit', got {op!r}.", success=False
            )
        if not text:
            return ToolResult(
                content="Error: text is required and must be non-empty.", success=False
            )

        store = get_memory_store()
        # Emit an L1 trace so the preference's footnote points at a real event.
        event = TraceEvent.new(
            "chat",
            "preference_stated",
            {"op": op, "text": text, "target_id": target_id, "reason": reason},
        )
        await store.emit(event)

        report = await store.write_preference(
            op=op,  # type: ignore[arg-type]
            text=text,
            target_id=str(target_id).strip() if target_id else None,
            reason=str(reason).strip() if reason else None,
            trace_id=event.id,
        )
        if not report.accepted:
            return ToolResult(
                content=f"write_memory rejected: {report.reason}",
                success=False,
                metadata={"op": op},
            )
        entry_id = report.results[0].entry_id if report.results else None
        return ToolResult(
            content=f"preference {op}ed (entry={entry_id or target_id}).",
            metadata={"op": op, "entry_id": entry_id or target_id},
        )


class WebFetchTool(_PromptHintsMixin, BaseTool):
    """Fetch a specific URL and return readable markdown.

    The actual fetch / extract / safety logic lives in
    ``deeptutor.tools.web_fetch`` so this wrapper stays free of network
    code — easier to unit-test the BaseTool boilerplate without spinning
    up an httpx mock.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="web_fetch",
            description=(
                "Fetch a specific URL and extract readable content as "
                "markdown. Use this when the user shares a specific link; "
                "use `web_search` for general topic searches."
            ),
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="Full http:// or https:// URL.",
                ),
                ToolParameter(
                    name="max_chars",
                    type="integer",
                    description="Cap on the extracted text length; defaults to 50000.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.web_fetch import (
            DEFAULT_MAX_CHARS,
            fetch_url_as_markdown,
        )

        url = str(kwargs.get("url") or "").strip()
        if not url:
            return ToolResult(content="Error: url is required.", success=False)
        try:
            max_chars = int(kwargs.get("max_chars") or DEFAULT_MAX_CHARS)
        except (TypeError, ValueError):
            max_chars = DEFAULT_MAX_CHARS
        outcome = await fetch_url_as_markdown(url, max_chars=max_chars)
        if not outcome.ok:
            return ToolResult(
                content=outcome.error or "Fetch failed.",
                success=False,
                metadata={"url": url},
            )
        return ToolResult(
            content=outcome.markdown,
            sources=[{"type": "web", "url": outcome.url, "title": outcome.title}],
            metadata={
                "url": outcome.url,
                "title": outcome.title,
                "char_count": len(outcome.markdown),
                "truncated": outcome.truncated,
            },
        )


class ListNotebookTool(_PromptHintsMixin, BaseTool):
    """List the user's notebooks, or list the records inside one notebook.

    Two-mode discovery tool. Auto-mounted by the chat pipeline iff the
    user has at least one notebook. The tool itself is stateless; the
    chat pipeline supplies no extra context — list calls go straight
    against the per-user notebook manager.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="list_notebook",
            description=(
                "Discover the user's notebooks and the records inside "
                "them. Call with no arguments to list every notebook "
                "the user owns (id + name + record count). Call with a "
                "specific `notebook_id` to drill in and list its "
                "records (record_id + title + summary + timestamp). "
                "Use this BEFORE `write_note` in edit mode so you have "
                "valid record ids."
            ),
            parameters=[
                ToolParameter(
                    name="notebook_id",
                    type="string",
                    description=(
                        "Optional. When omitted, returns the notebook "
                        "index. When supplied, returns the records in "
                        "that notebook. Must be a valid id from the "
                        "notebook index — do not invent ids."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.list_notebook import list_notebooks_or_records

        outcome = list_notebooks_or_records(
            notebook_id=str(kwargs.get("notebook_id") or ""),
        )
        if not outcome.ok:
            return ToolResult(content=outcome.error, success=False)
        return ToolResult(
            content=outcome.text,
            metadata=outcome.summary or {},
        )


class WriteNoteTool(_PromptHintsMixin, BaseTool):
    """Create OR edit a notebook record from the chat agent.

    Two modes mirror what a human sees in the notebook UI:

    * ``append`` — create a new record in a notebook (the model picks
      a title; the body defaults to the actual chat transcript built
      from injected conversation history, or to an agent-authored
      markdown body if ``content`` is explicitly provided).
    * ``edit`` — patch an existing record's title / body / summary.
      Requires a known ``record_id`` (obtained via ``list_notebook``).

    Auto-mounted only when the user has at least one notebook. The
    pipeline injects ``conversation_history`` + ``current_user_message``
    so the model never has to fabricate the saved chat.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="write_note",
            description=(
                "Save or edit a notebook record. mode='append' creates "
                "a NEW record (default body = the actual recent chat "
                "transcript built by the tool; pass `content` instead "
                "to save an agent-authored markdown body). "
                "mode='edit' patches an existing record's title / body "
                "/ summary — `record_id` is required (call `list_notebook` "
                "first to discover valid ids)."
            ),
            parameters=[
                ToolParameter(
                    name="mode",
                    type="string",
                    description="'append' (new record) or 'edit' (patch existing).",
                    enum=["append", "edit"],
                ),
                ToolParameter(
                    name="notebook_id",
                    type="string",
                    description=(
                        "Id of the target notebook from the schema enum (do not invent ids)."
                    ),
                ),
                ToolParameter(
                    name="record_id",
                    type="string",
                    description=("Required for mode='edit'. Discover with `list_notebook` first."),
                    required=False,
                ),
                ToolParameter(
                    name="title",
                    type="string",
                    description=(
                        "For append: required, short descriptive title. "
                        "For edit: optional new title (leave empty to "
                        "keep the existing one)."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description=(
                        "For append: optional agent-authored markdown body "
                        "(when omitted the tool inserts the real Q&A "
                        "transcript itself, the recommended default). "
                        "For edit: replacement body (leave empty to keep "
                        "the existing body)."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="turns_to_include",
                    type="string",
                    description=(
                        "Append mode only. Number of recent user+assistant "
                        "turns to render into the transcript body. Pass an "
                        "integer as a string (e.g. '3') or 'all' to include "
                        "every turn currently in scope. Ignored when "
                        "`content` is provided. Default '3'."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="note",
                    type="string",
                    description=(
                        "Optional one-paragraph commentary. In append "
                        "mode it's prepended above the transcript; in "
                        "edit mode it replaces the record's summary."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.write_note import write_note

        outcome = write_note(
            mode=str(kwargs.get("mode") or ""),
            notebook_id=str(kwargs.get("notebook_id") or ""),
            record_id=str(kwargs.get("record_id") or ""),
            title=str(kwargs.get("title") or ""),
            content=str(kwargs.get("content") or ""),
            turns_to_include=kwargs.get("turns_to_include") or 3,
            note=str(kwargs.get("note") or ""),
            conversation_history=kwargs.get("conversation_history") or [],
            current_user_message=str(kwargs.get("current_user_message") or ""),
        )
        if not outcome.ok:
            return ToolResult(content=outcome.error, success=False)
        action = "Saved new record" if outcome.mode == "append" else "Updated record"
        return ToolResult(
            content=(
                f"{action} in notebook {outcome.notebook_name!r} (record id: {outcome.record_id})."
            ),
            metadata={
                "mode": outcome.mode,
                "record_id": outcome.record_id,
                "notebook_id": outcome.notebook_id,
                "notebook_name": outcome.notebook_name,
            },
        )


class GithubTool(_PromptHintsMixin, BaseTool):
    """Read-only GitHub queries via `gh`. Always auto-mounted; the
    underlying call gracefully reports "gh unavailable" when the CLI
    isn't installed on the server."""

    _ALLOWED_QUERY_TYPES = ("pr", "issue", "run", "repo", "api")

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="github",
            description=(
                "Read-only queries against GitHub PRs / issues / repos / "
                "CI runs via the gh CLI. This tool cannot write — no "
                "comments, no closes, no merges."
            ),
            parameters=[
                ToolParameter(
                    name="query_type",
                    type="string",
                    description=("One of 'pr', 'issue', 'run', 'repo', 'api'."),
                    enum=list(_ALLOWED_QUERY_TYPES := ("pr", "issue", "run", "repo", "api")),
                ),
                ToolParameter(
                    name="target",
                    type="string",
                    description=(
                        "owner/repo[#number] or full URL for pr/issue; "
                        "owner/repo for run/repo; gh-api relative path "
                        "for api."
                    ),
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.github_query import run_github_query

        outcome = await run_github_query(
            query_type=str(kwargs.get("query_type") or ""),
            target=str(kwargs.get("target") or ""),
        )
        if not outcome.ok:
            return ToolResult(
                content=outcome.error,
                success=False,
                metadata={"query_type": outcome.query_type, "target": outcome.target},
            )
        return ToolResult(
            content=outcome.output,
            sources=[
                {
                    "type": "github",
                    "query_type": outcome.query_type,
                    "target": outcome.target,
                }
            ],
            metadata={
                "query_type": outcome.query_type,
                "target": outcome.target,
            },
        )


class AskUserTool(_PromptHintsMixin, BaseTool):
    """Pause the turn mid-loop to ask the user a clarifying question.

    Returns ``pause_for_user`` carrying the structured question payload.
    The chat pipeline halts the agentic loop after this call, surfaces
    the question + options as a card in the chat UI, and **waits for
    the user's reply on the same turn**. When the reply arrives the
    loop resumes with the user's answer substituted into this tool's
    result body — so subsequent iterations see "User answered: <text>"
    as the matching ``role=tool`` content and can act on it. The user
    can also abort the wait at any time via the composer's stop button
    (which cancels the whole turn).
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ask_user",
            description=(
                "Pause the conversation to ask the user 1-4 clarifying "
                "questions in one batch, rendered as a card with "
                "clickable options. Use ONLY when you are blocked on a "
                "decision that is genuinely the user's to make — one "
                "you cannot resolve from the request, the conversation, "
                "the attached material, or sensible defaults. Never use "
                "it to ask 'should I proceed?', to confirm what the "
                "user already said, or for choices with an obvious "
                "conventional answer — pick that answer, mention it, "
                "and proceed. The turn does NOT end: when the answers "
                "arrive the agentic loop resumes with them as this "
                "tool's result, and you must then complete the user's "
                "original request."
            ),
            parameters=[
                ToolParameter(
                    name="questions",
                    type="array",
                    description=(
                        "1-4 questions to ask in one card. Bundle ALL "
                        "clarifications into this single call — never "
                        "emit a second ask_user in the same message. "
                        "Give each question 2-4 distinct, mutually "
                        "exclusive options (set multi_select: true when "
                        "choices can combine, and phrase the question "
                        "accordingly). Option labels are short (1-5 "
                        "words); put what picking it implies in the "
                        "description. If you recommend an option, place "
                        "it FIRST and append ' (Recommended)' to its "
                        "label. Never add your own 'Other' option — the "
                        "card offers free-form input automatically."
                    ),
                    required=True,
                    items={
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": "The complete question text.",
                            },
                            "header": {
                                "type": "string",
                                "description": (
                                    "Very short tab label (max 12 chars), "
                                    "e.g. 'Scope', 'Depth', '受众'."
                                ),
                            },
                            "options": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": ("Concise display text (1-5 words)."),
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": (
                                                "What this choice means or "
                                                "implies, trade-offs "
                                                "included."
                                            ),
                                        },
                                    },
                                    "required": ["label"],
                                },
                            },
                            "multi_select": {
                                "type": "boolean",
                                "description": ("true = the user may pick several options."),
                            },
                            "id": {"type": "string"},
                            "allow_free_text": {"type": "boolean"},
                            "placeholder": {
                                "type": "string",
                                "description": ("Hint shown in the free-form input."),
                            },
                        },
                        "required": ["prompt"],
                    },
                ),
                ToolParameter(
                    name="intro",
                    type="string",
                    description=(
                        "Optional one-line lead-in shown above the "
                        "questions (e.g. 'To tailor the research, please "
                        "answer:')."
                    ),
                    required=False,
                ),
                # NOTE: the legacy top-level ``{question, options}`` shape
                # is still ACCEPTED by ``execute()`` (normalised into a
                # one-element ``questions`` list) but is no longer
                # advertised in the schema — two redundant entry points
                # measurably degraded call accuracy on weaker models.
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.ask_user import build_ask_user_payload

        payload, err = build_ask_user_payload(
            questions=kwargs.get("questions"),
            intro=kwargs.get("intro"),
            question=kwargs.get("question"),
            options=kwargs.get("options"),
        )
        if payload is None:
            return ToolResult(content=err or "Invalid ask_user arguments.", success=False)

        payload_dict = payload.to_dict()
        prompts = ", ".join(q.prompt for q in payload.questions)
        return ToolResult(
            # The placeholder content is overwritten by the pipeline
            # once the user's reply arrives; the model never sees this
            # literal string on a normal flow. It only surfaces if the
            # runtime crashes mid-pause (in which case the LLM at least
            # gets a coherent log entry).
            content=f"[awaiting user reply to: {prompts}]",
            metadata={"ask_user": payload_dict},
            pause_for_user=payload_dict,
        )


class ReadSkillTool(_PromptHintsMixin, BaseTool):
    """Read a skill package's SKILL.md or one of its reference files.

    The system prompt carries only a one-line manifest per skill; this tool
    is how the model pulls the full playbook on demand (progressive
    disclosure). Multi-user-safe: skills resolve via the active user's
    workspace (user layer shadows builtin), plus admin-assigned skills for
    non-admin users.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_skill",
            description=(
                "Read a skill's full playbook (SKILL.md) or one of its "
                "reference files. Call this BEFORE attempting a task that "
                "matches a skill listed in the Skills section, then follow "
                "the returned instructions."
            ),
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description="Skill name exactly as listed in the Skills section.",
                ),
                ToolParameter(
                    name="file",
                    type="string",
                    description=(
                        "Optional file inside the skill package (e.g. "
                        "'references/api.md'). Defaults to SKILL.md."
                    ),
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.skill import get_skill_service
        from deeptutor.services.skill.service import (
            InvalidSkillNameError,
            InvalidSkillPathError,
            SkillNotFoundError,
            SkillService,
        )

        name = str(kwargs.get("name") or "").strip()
        rel_path = str(kwargs.get("file") or "SKILL.md").strip() or "SKILL.md"
        if not name:
            raise ValueError("read_skill requires a skill name.")

        services: list[SkillService] = [get_skill_service()]
        try:
            from deeptutor.multi_user.context import get_current_user
            from deeptutor.multi_user.paths import get_admin_path_service
            from deeptutor.multi_user.skill_access import assigned_skill_ids

            user = get_current_user()
            if not user.is_admin and name in assigned_skill_ids(user.id):
                services.append(
                    SkillService(root=get_admin_path_service().get_workspace_dir() / "skills")
                )
        except Exception:
            logger.debug("read_skill: assigned-skill scope unavailable", exc_info=True)

        for service in services:
            try:
                content = service.read_skill_file(name, rel_path)
            except SkillNotFoundError:
                continue
            except (InvalidSkillNameError, InvalidSkillPathError) as exc:
                return ToolResult(content=f"(read_skill error: {exc})", success=False)
            return ToolResult(
                content=content,
                metadata={"skill": name, "file": rel_path, "char_count": len(content)},
            )
        return ToolResult(
            content=(
                f"(skill not found: {name!r} — use a name exactly as listed in the Skills section)"
            ),
            success=False,
        )


class LoadToolsTool(_PromptHintsMixin, BaseTool):
    """Load deferred (Extended) tools' schemas into the current session.

    The ``_tool_loader`` kwarg is injected server-side by the chat pipeline
    (a per-turn :class:`DeferredToolLoader`); the LLM only supplies
    ``names``.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="load_tools",
            description=(
                "Load one or more Extended Tools (listed in the Extended "
                "Tools section) so they become callable. Call this BEFORE "
                "using any extended tool; loaded tools stay available for "
                "the rest of the session."
            ),
            parameters=[
                ToolParameter(
                    name="names",
                    type="array",
                    description=(
                        "Exact tool names to load, as listed in the Extended Tools section."
                    ),
                    items={"type": "string"},
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        loader = kwargs.get("_tool_loader")
        names = kwargs.get("names")
        if loader is None:
            return ToolResult(
                content="(load_tools is unavailable in this context)",
                success=False,
            )
        if not isinstance(names, list) or not names:
            raise ValueError("load_tools requires a non-empty `names` array.")
        outcome = loader.load(names)
        parts: list[str] = []
        if outcome["loaded"]:
            parts.append("Loaded (now callable): " + ", ".join(outcome["loaded"]))
        if outcome["already_loaded"]:
            parts.append("Already loaded: " + ", ".join(outcome["already_loaded"]))
        if outcome["unknown"]:
            parts.append(
                "Unknown: "
                + ", ".join(outcome["unknown"])
                + " (use exact names from the Extended Tools section)"
            )
        return ToolResult(
            content="\n".join(parts) or "(nothing to load)",
            success=not outcome["unknown"] or bool(outcome["loaded"]),
            metadata=outcome,
        )


class CronTool(_PromptHintsMixin, BaseTool):
    """Schedule, list, and cancel timed tasks for the current conversation.

    Mirrors nanobot's cron tool. Jobs belong to the conversation that
    created them: a chat job re-runs as a turn appended to that session; a
    partner job is injected into the partner's message bus so the reply
    rides the original IM channel. The owner routing context arrives via
    the pipeline-injected ``_cron_owner`` kwarg — never from the model.
    """

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="cron",
            description=(
                "Schedule a task to run later, list scheduled tasks, or "
                "cancel one. When a task is due, its message is executed "
                "as a new instruction in this same conversation and the "
                "result is delivered here. Use action='schedule' with "
                "`message` plus EXACTLY ONE of: `at` (ISO 8601 time, one-"
                "shot), `every_seconds` (repeating interval, min 30), or "
                "`cron_expr` (cron expression like '0 9 * * *', optional "
                "`tz` IANA timezone). Use action='list' to see this "
                "conversation's tasks and action='cancel' with `job_id` "
                "to remove one. Times without a timezone are server-local."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="What to do.",
                    required=True,
                    enum=["schedule", "list", "cancel"],
                ),
                ToolParameter(
                    name="message",
                    type="string",
                    description=(
                        "schedule: the instruction to execute when due — "
                        "write it as a complete, self-contained request."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="name",
                    type="string",
                    description="schedule: short human-readable task name.",
                    required=False,
                ),
                ToolParameter(
                    name="at",
                    type="string",
                    description=(
                        "schedule (one-shot): ISO 8601 time, e.g. "
                        "'2026-06-12T09:00' or with offset '…+08:00'."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="every_seconds",
                    type="integer",
                    description="schedule (repeating): interval in seconds, minimum 30.",
                    required=False,
                ),
                ToolParameter(
                    name="cron_expr",
                    type="string",
                    description="schedule (cron): 5-field cron expression, e.g. '0 9 * * 1-5'.",
                    required=False,
                ),
                ToolParameter(
                    name="tz",
                    type="string",
                    description="schedule (cron): IANA timezone for cron_expr, e.g. 'Asia/Hong_Kong'.",
                    required=False,
                ),
                ToolParameter(
                    name="delete_after_run",
                    type="boolean",
                    description="schedule: remove the task after one run (default true for 'at').",
                    required=False,
                ),
                ToolParameter(
                    name="job_id",
                    type="string",
                    description="cancel: id of the task to remove (from action='list').",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.tools.cron_tool import run_cron_action

        outcome = run_cron_action(kwargs)
        return ToolResult(content=outcome.text, success=outcome.ok, metadata=outcome.meta)


BUILTIN_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    BrainstormTool,
    RAGTool,
    WebSearchTool,
    CodeExecutionTool,
    ReasonTool,
    PaperSearchToolWrapper,
    ReadSourceTool,
    ReadMemoryTool,
    WriteMemoryTool,
    ReadSkillTool,
    LoadToolsTool,
    ExecTool,
    WebFetchTool,
    ListNotebookTool,
    WriteNoteTool,
    GithubTool,
    AskUserTool,
    CronTool,
    # Image → GeoGebra figure reconstruction. User-toggleable in chat; the
    # solve loop capability force-mounts it for diagram problems.
    GeoGebraAnalysisTool,
    # Text-to-image / text-to-video generation. User-toggleable + per-user
    # grant-gated; the chat pipeline only mounts them when a model is configured.
    ImagegenTool,
    VideogenTool,
    # Mastery Path + Solve + Obsidian tools — globally registered so schemas/API
    # stay stable; the chat loop capabilities decide when to auto-mount them for
    # a turn. Obsidian is a knowledge capability: when its vault is selected it
    # runs the turn exclusively on these tools.
    *MASTERY_TOOL_TYPES,
    *SOLVE_TOOL_TYPES,
    *OBSIDIAN_TOOL_TYPES,
    # Subagent consult tool — globally registered; the subagent knowledge
    # capability runs the turn exclusively on it when a connected agent is the
    # selected KB.
    *SUBAGENT_TOOL_TYPES,
    # Partner-only memory + history tools. Globally registered so schemas/API
    # stay stable, but never mounted in product chat: the partner runtime
    # force-mounts them (and suppresses chat's read_memory/write_memory) on
    # every partner turn. Deliberately absent from CONFIGURABLE_BUILTIN_TOOL_NAMES
    # — they are mandatory, not owner-configurable.
    PartnerReadTool,
    PartnerMemorizeTool,
    PartnerSearchTool,
)

# No tools are parked right now. When a tool's implementation is being
# redesigned, list its type here: it stays OUT of the runtime registry (the
# chat agent cannot invoke it) while the settings page still surfaces it with
# a "Coming soon" badge. Re-add to ``BUILTIN_TOOL_TYPES`` when ready to ship.
COMING_SOON_TOOL_TYPES: tuple[type[BaseTool], ...] = ()

BUILTIN_TOOL_NAMES: tuple[str, ...] = tuple(tool_type().name for tool_type in BUILTIN_TOOL_TYPES)

COMING_SOON_TOOL_NAMES: tuple[str, ...] = tuple(
    tool_type().name for tool_type in COMING_SOON_TOOL_TYPES
)

# Tools the user can switch on/off from /settings/tools ("体验增强" /
# Experience Enhancement). Everything else in BUILTIN_TOOL_NAMES is mounted
# automatically by the chat pipeline under per-tool context gates and is
# locked-on from the user's perspective. Ordering here is the canonical
# display order for the settings page.
USER_TOGGLEABLE_TOOL_NAMES: tuple[str, ...] = (
    "brainstorm",
    "web_search",
    "paper_search",
    "reason",
    "geogebra_analysis",
    "imagegen",
    "videogen",
)

# Built-in tools the chat agent loop auto-mounts under context gates (a KB
# attached, the sandbox enabled, the user having memory/notebooks, …) rather
# than user toggles — "locked-on" in the product chat composer. Partners,
# however, can selectively allow/deny these per companion (default: all
# allowed) so an IM-facing partner can be denied e.g. memory access.
# ``tool_composition.AUTO_MOUNTED_TOOLS`` is derived from this tuple, so the
# two stay in lockstep; this ordering is the canonical display order for the
# partner config UI. Capability-owned tools (mastery/solve/obsidian/subagent)
# are intentionally absent — they are gated by capability activation, never by
# this surface.
CONFIGURABLE_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "rag",
    "code_execution",
    "read_source",
    "read_memory",
    "write_memory",
    "read_skill",
    "list_notebook",
    "write_note",
    "web_fetch",
    "github",
    "exec",
    "load_tools",
    "cron",
    "ask_user",
)

TOOL_ALIASES: dict[str, tuple[str, dict[str, Any]]] = {
    "rag_hybrid": ("rag", {"mode": "hybrid"}),
    "rag_naive": ("rag", {"mode": "naive"}),
    "rag_search": ("rag", {}),
    "code_execute": ("code_execution", {}),
    "run_code": ("code_execution", {}),
}

__all__ = [
    "BUILTIN_TOOL_NAMES",
    "BUILTIN_TOOL_TYPES",
    "COMING_SOON_TOOL_NAMES",
    "COMING_SOON_TOOL_TYPES",
    "CONFIGURABLE_BUILTIN_TOOL_NAMES",
    "PARTNER_BUILTIN_TOOL_NAMES",
    "TOOL_ALIASES",
    "USER_TOGGLEABLE_TOOL_NAMES",
    "AskUserTool",
    "BrainstormTool",
    "CodeExecutionTool",
    "ExecTool",
    "GeoGebraAnalysisTool",
    "GithubTool",
    "ImagegenTool",
    "VideogenTool",
    "ListNotebookTool",
    "PaperSearchToolWrapper",
    "PartnerMemorizeTool",
    "PartnerReadTool",
    "PartnerSearchTool",
    "RAGTool",
    "LoadToolsTool",
    "ReadMemoryTool",
    "ReadSkillTool",
    "ReadSourceTool",
    "ReasonTool",
    "WebFetchTool",
    "WebSearchTool",
    "WriteMemoryTool",
    "WriteNoteTool",
]
