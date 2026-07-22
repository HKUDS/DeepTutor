import asyncio
from datetime import datetime
import json
import logging
import re
import traceback
from typing import AsyncGenerator, Literal
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from deeptutor.co_writer.edit_agent import (
    EditAgent,
    append_history,
    load_history,
    print_stats,
    tool_calls_dir,
)
from deeptutor.co_writer.storage import (
    CoWriterDocument,
    CoWriterDocumentSummary,
    get_co_writer_storage,
)
from deeptutor.core.stream_bus import StreamBus
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.settings.interface_settings import get_ui_language

router = APIRouter()

# Initialize logger with config
config = load_config_with_main("main.yaml", PROJECT_ROOT)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = logging.getLogger(__name__)

_edit_agent: EditAgent | None = None


def _current_language() -> str:
    # Prefer UI settings, fall back to main.yaml system.language
    return get_ui_language(default=config.get("system", {}).get("language", "en"))


def get_edit_agent() -> EditAgent:
    """
    Get the singleton EditAgent instance with refreshed configuration.

    Uses a singleton pattern with refresh_config() to ensure:
    1. Efficient reuse of the agent instance
    2. Latest LLM configuration from Settings is always used
    """
    global _edit_agent
    lang = _current_language()
    if _edit_agent is None or getattr(_edit_agent, "language", None) != lang:
        _edit_agent = EditAgent(language=lang)
    # Refresh config to pick up any changes from Settings
    _edit_agent.refresh_config()
    return _edit_agent


# Generous ceilings — they exist to stop runaway payloads (OOM / surprise
# LLM bills), not to constrain normal documents.
_MAX_DOC_CHARS = 600_000
_MAX_SELECTION_CHARS = 120_000
_MAX_INSTRUCTION_CHARS = 10_000


class EditRequest(BaseModel):
    text: str = Field(max_length=_MAX_DOC_CHARS)
    instruction: str = Field(max_length=_MAX_INSTRUCTION_CHARS)
    action: Literal["rewrite", "shorten", "expand"] = "rewrite"
    source: Literal["rag", "web"] | None = None
    kb_name: str | None = None


class EditResponse(BaseModel):
    edited_text: str
    operation_id: str


class ReactEditRequest(BaseModel):
    selected_text: str = Field(max_length=_MAX_SELECTION_CHARS)
    instruction: str = Field(default="", max_length=_MAX_INSTRUCTION_CHARS)
    mode: Literal["rewrite", "shorten", "expand", "none"] = "rewrite"
    tools: list[Literal["rag", "web"]] = []
    kb_name: str | None = None


class ReactEditResponse(BaseModel):
    edited_text: str
    operation_id: str
    tools_used: list[str] = []


class AutoMarkRequest(BaseModel):
    text: str = Field(max_length=_MAX_DOC_CHARS)


class AutoMarkResponse(BaseModel):
    marked_text: str
    operation_id: str


def _default_mode_instruction(mode: str, language: str) -> str:
    zh = language.startswith("zh")
    defaults = {
        "rewrite": "润色这段 markdown，保持原意、结构和语气自然。",
        "shorten": "压缩这段 markdown，让表达更精炼，同时保留关键信息。",
        "expand": "扩展这段 markdown，补充必要细节，同时保持原有风格。",
        "none": "根据用户要求编辑这段 markdown。",
    }
    if zh:
        return defaults.get(mode, defaults["none"])
    defaults_en = {
        "rewrite": "Rewrite this markdown snippet while preserving its meaning, structure, and tone.",
        "shorten": "Shorten this markdown snippet while preserving the key information.",
        "expand": "Expand this markdown snippet with helpful detail while keeping the original style.",
        "none": "Edit this markdown snippet according to the user's request.",
    }
    return defaults_en.get(mode, defaults_en["none"])


def _build_react_edit_prompt(
    *,
    selected_text: str,
    instruction: str,
    mode: str,
    language: str,
    context: str = "",
) -> str:
    user_instruction = instruction.strip() or _default_mode_instruction(mode, language)
    if language.startswith("zh"):
        context_block = f"参考资料（按需取用，不必全部使用）:\n{context}\n\n" if context else ""
        return (
            "你正在编辑一段从 Markdown 编辑器里选中的文本。\n\n"
            f"编辑模式: {mode}\n"
            f"用户要求: {user_instruction}\n\n"
            f"{context_block}"
            "待编辑的选中文本:\n"
            "```markdown\n"
            f"{selected_text}\n"
            "```\n\n"
            "要求:\n"
            "1. 只输出编辑后的那段 Markdown 文本，供编辑器直接替换。\n"
            "2. 不要输出解释、标题、前后缀、代码围栏。\n"
            "3. 保持 Markdown 语法合法。\n"
            "4. 如果给了参考资料，把相关事实自然融入结果，不要提工具或资料来源。\n"
        )
    context_block = (
        f"Reference material (use what is relevant, ignore the rest):\n{context}\n\n"
        if context
        else ""
    )
    return (
        "You are editing a text selection from a Markdown editor.\n\n"
        f"Edit mode: {mode}\n"
        f"User request: {user_instruction}\n\n"
        f"{context_block}"
        "Selected text to edit:\n"
        "```markdown\n"
        f"{selected_text}\n"
        "```\n\n"
        "Requirements:\n"
        "1. Output only the edited Markdown snippet for direct replacement.\n"
        "2. Do not include explanations, headings, prefixes, suffixes, or code fences.\n"
        "3. Keep the Markdown valid.\n"
        "4. If reference material is given, weave the relevant facts in naturally "
        "without mentioning tools or sources.\n"
    )


def _strip_markdown_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return cleaned


def _clean_react_edit_output(text: str, *, binding: str | None, model: str | None) -> str:
    return _strip_markdown_fence(clean_thinking_tags(text, binding, model))


def _normalize_react_edit_tools(tools: list[str] | None) -> list[str]:
    allowed = {"rag", "web"}
    result: list[str] = []
    for tool in tools or []:
        name = str(tool or "").strip()
        if name in allowed and name not in result:
            result.append(name)
    return result


def _prepare_react_edit_request(
    request: ReactEditRequest, language: str
) -> tuple[str, str, list[str]]:
    tools = _normalize_react_edit_tools(request.tools)
    instruction = request.instruction.strip()
    if request.mode == "none" and not instruction:
        detail = (
            "请输入编辑要求，或选择 shorten / expand / rewrite 模式。"
            if language.startswith("zh")
            else "Provide an edit instruction, or choose shorten / expand / rewrite mode."
        )
        raise HTTPException(status_code=400, detail=detail)

    selected_text = request.selected_text.strip("\n")
    if not selected_text.strip():
        detail = (
            "请先选中一段文本。"
            if language.startswith("zh")
            else "Please select a text passage first."
        )
        raise HTTPException(status_code=400, detail=detail)

    return selected_text, instruction, tools


_TRACE_PREVIEW_CHARS = 1200


def _trace_preview(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) <= _TRACE_PREVIEW_CHARS:
        return cleaned
    return cleaned[:_TRACE_PREVIEW_CHARS].rstrip() + "…"


async def _run_react_edit(
    request: ReactEditRequest,
    *,
    language: str,
    stream: StreamBus | None = None,
) -> dict[str, object]:
    selected_text, instruction, tools = _prepare_react_edit_request(request, language)
    operation_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]

    agent = get_edit_agent()

    # Optional reference retrieval before the edit. Each tool degrades to a
    # plain edit on failure — retrieval must never block the user's edit.
    query = instruction or selected_text[:400]
    context_blocks: list[str] = []
    tools_used: list[str] = []
    for tool in tools:
        kb_name = request.kb_name if tool == "rag" else None
        if tool == "rag" and not kb_name:
            continue
        if stream is not None:
            await stream.tool_call(
                tool,
                {"query": query, **({"kb_name": kb_name} if kb_name else {})},
                source="co_writer_react_edit",
                stage="exploring",
            )
        context, _file = await agent.gather_context(
            source=tool,
            query=query,
            kb_name=kb_name,
            operation_id=operation_id,
        )
        if stream is not None:
            await stream.tool_result(
                tool,
                _trace_preview(context) if context else "(no result)",
                source="co_writer_react_edit",
                stage="exploring",
            )
        if context:
            context_blocks.append(context)
            tools_used.append(tool)

    system_prompt = (
        "You are an expert markdown editor."
        if not language.startswith("zh")
        else "你是一个严格的 Markdown 编辑助手。"
    )
    prompt = _build_react_edit_prompt(
        selected_text=selected_text,
        instruction=instruction,
        mode=request.mode,
        language=language,
        context="\n\n".join(context_blocks),
    )

    response_chunks: list[str] = []

    async def _consume() -> None:
        async for chunk in agent.stream_llm(
            user_prompt=prompt,
            system_prompt=system_prompt,
            stage=f"react_edit_{request.mode}",
        ):
            if not chunk:
                continue
            response_chunks.append(chunk)
            if stream is not None:
                await stream.content(
                    chunk,
                    source="co_writer_react_edit",
                    stage="responding",
                )

    if stream is not None:
        async with stream.stage("responding", source="co_writer_react_edit"):
            await _consume()
    else:
        await _consume()

    edited_text = _clean_react_edit_output(
        "".join(response_chunks),
        binding=agent.binding,
        model=agent.get_model(),
    )

    append_history(
        {
            "id": operation_id,
            "timestamp": datetime.now().isoformat(),
            "action": "react_edit",
            "mode": request.mode,
            "tools": tools_used,
            "kb_name": request.kb_name,
            "input": {
                "selected_text": request.selected_text,
                "instruction": instruction,
            },
            "output": {"edited_text": edited_text},
            "model": agent.get_model(),
        }
    )
    print_stats()

    result = {
        "edited_text": edited_text,
        "operation_id": operation_id,
        "tools_used": tools_used,
    }
    if stream is not None:
        await stream.result(result, source="co_writer_react_edit")
    return result


async def _stream_react_edit(request: ReactEditRequest) -> AsyncGenerator[str, None]:
    language = _current_language()
    bus = StreamBus()
    error_holder: dict[str, str] = {}
    result_holder: dict[str, object] | None = None

    async def _run() -> None:
        nonlocal result_holder
        try:
            result_holder = await _run_react_edit(request, language=language, stream=bus)
        except HTTPException as exc:
            error_holder["detail"] = str(exc.detail)
        except Exception as exc:
            error_holder["detail"] = str(exc)
        finally:
            await bus.close()

    task = asyncio.create_task(_run())
    try:
        async for event in bus.subscribe():
            yield f"event: stream\ndata: {json.dumps(event.to_dict(), default=str)}\n\n"

        await task
        if error_holder:
            yield f"event: error\ndata: {json.dumps(error_holder, default=str)}\n\n"
        else:
            yield f"event: result\ndata: {json.dumps(result_holder or {}, default=str)}\n\n"
    finally:
        if not task.done():
            task.cancel()


@router.post("/edit", response_model=EditResponse)
async def edit_text(request: EditRequest):
    try:
        # Get agent with refreshed LLM configuration from Settings
        agent = get_edit_agent()

        result = await agent.process(
            text=request.text,
            instruction=request.instruction,
            action=request.action,
            source=request.source,
            kb_name=request.kb_name,
        )

        # Print token stats
        print_stats()

        return result

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/edit_react", response_model=ReactEditResponse)
async def edit_text_react(request: ReactEditRequest):
    try:
        return await _run_react_edit(request, language=_current_language())
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/edit_react/stream")
async def edit_text_react_stream(request: ReactEditRequest):
    try:
        _prepare_react_edit_request(request, _current_language())
    except HTTPException:
        raise
    return StreamingResponse(
        _stream_react_edit(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/automark", response_model=AutoMarkResponse)
async def auto_mark_text(request: AutoMarkRequest):
    """AI auto-mark text"""
    try:
        # Get agent with refreshed LLM configuration from Settings
        agent = get_edit_agent()

        result = await agent.auto_mark(text=request.text)

        # Print token stats
        print_stats()

        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_history():
    """Get all operation history"""
    try:
        history = load_history()
        return {"history": history, "total": len(history)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{operation_id}")
async def get_operation(operation_id: str):
    """Get single operation details"""
    try:
        history = load_history()
        for op in history:
            if op.get("id") == operation_id:
                return op
        raise HTTPException(status_code=404, detail="Operation not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tool_calls/{operation_id}")
async def get_tool_call(operation_id: str):
    """Get tool call details"""
    try:
        # Find matching file
        for filepath in tool_calls_dir().glob(f"{operation_id}_*.json"):
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        raise HTTPException(status_code=404, detail="Tool call not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Document CRUD (multi-project Co-Writer)
# ─────────────────────────────────────────────────────────────────────────────

# Storage builds paths as `documents/doc_{doc_id}`; an unvalidated id like
# "a/../../x" would escape the documents root (and DELETE runs rmtree).
_DOC_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")


def _validate_doc_id(doc_id: str) -> str:
    if not _DOC_ID_RE.fullmatch(doc_id):
        raise HTTPException(status_code=404, detail="Document not found")
    return doc_id


class CreateDocumentRequest(BaseModel):
    title: str | None = None
    content: str = ""


class UpdateDocumentRequest(BaseModel):
    title: str | None = None
    content: str | None = None


class DocumentResponse(BaseModel):
    id: str
    title: str
    content: str
    created_at: float
    updated_at: float

    @classmethod
    def from_model(cls, doc: CoWriterDocument) -> "DocumentResponse":
        return cls(
            id=doc.id,
            title=doc.title,
            content=doc.content,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )


class DocumentSummaryResponse(BaseModel):
    id: str
    title: str
    created_at: float
    updated_at: float
    preview: str = ""

    @classmethod
    def from_summary(cls, summary: CoWriterDocumentSummary) -> "DocumentSummaryResponse":
        return cls(
            id=summary.id,
            title=summary.title,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            preview=summary.preview,
        )


@router.get("/documents")
async def list_documents() -> dict[str, list[DocumentSummaryResponse]]:
    """List all Co-Writer documents (summary view, sorted by recency)."""
    try:
        storage = get_co_writer_storage()
        summaries = storage.list_documents()
        return {"documents": [DocumentSummaryResponse.from_summary(s) for s in summaries]}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/documents", response_model=DocumentResponse)
async def create_document(request: CreateDocumentRequest) -> DocumentResponse:
    """Create a new Co-Writer document."""
    try:
        storage = get_co_writer_storage()
        document = storage.create_document(title=request.title, content=request.content)
        return DocumentResponse.from_model(document)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str) -> DocumentResponse:
    """Get a single Co-Writer document by id."""
    try:
        storage = get_co_writer_storage()
        document = storage.load_document(_validate_doc_id(doc_id))
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentResponse.from_model(document)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/documents/{doc_id}", response_model=DocumentResponse)
async def update_document(doc_id: str, request: UpdateDocumentRequest) -> DocumentResponse:
    """Update a Co-Writer document (title and/or content)."""
    try:
        storage = get_co_writer_storage()
        document = storage.update_document(
            _validate_doc_id(doc_id), title=request.title, content=request.content
        )
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentResponse.from_model(document)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str) -> dict[str, bool]:
    """Delete a Co-Writer document."""
    try:
        storage = get_co_writer_storage()
        _validate_doc_id(doc_id)
        if not storage.doc_exists(doc_id):
            raise HTTPException(status_code=404, detail="Document not found")
        success = storage.delete_document(doc_id)
        return {"deleted": success}
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
