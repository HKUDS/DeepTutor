"""
Notebook API Router
Provides notebook creation, querying, updating, deletion, and record management functions
"""

import json
from typing import AsyncGenerator, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from deeptutor.agents.notebook import NotebookSummarizeAgent
from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.notebook import notebook_manager
from deeptutor.services.notebook.service import NotebookCorruptedError

router = APIRouter()


def _unreadable(exc: NotebookCorruptedError) -> HTTPException:
    """Translate a damaged notebook file into a response the UI can explain.

    409 rather than 500: the request was fine, the stored file is not, and
    the client can act on it (restore a backup, delete the notebook).

    Every endpoint re-raises through this before its generic `except
    Exception`, because that generic clause would otherwise flatten a
    diagnosable "your file is damaged" into an anonymous 500. The contract is
    covered by a test that walks the routes, so a new endpoint that forgets
    it fails CI rather than degrading quietly.
    """
    return HTTPException(
        status_code=409,
        detail={
            "code": "notebook_unreadable",
            "notebook_id": exc.notebook_id,
            "message": str(exc),
        },
    )


# === Request/Response Models ===


class CreateNotebookRequest(BaseModel):
    """Create notebook request"""

    name: str
    description: str = ""
    color: str = "#3B82F6"
    icon: str = "book"


class UpdateNotebookRequest(BaseModel):
    """Update notebook request"""

    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None


class AddRecordRequest(BaseModel):
    """Add record request"""

    notebook_ids: list[str]
    record_type: Literal["solve", "question", "research", "chat", "co_writer", "tutorbot"]
    title: str
    summary: str = ""
    user_query: str
    output: str
    metadata: dict = {}
    kb_name: str | None = None


class RemoveRecordRequest(BaseModel):
    """Remove record request"""

    record_id: str


class UpdateRecordRequest(BaseModel):
    """Update an existing notebook record.

    Only the fields the client actually sends are forwarded (see
    ``exclude_unset`` at the call site), which is what keeps ``kb_name``
    from being wiped by a request that merely renames the record.
    """

    title: str | None = None
    summary: str | None = None
    user_query: str | None = None
    output: str | None = None
    metadata: dict | None = None
    kb_name: str | None = None


class MoveRecordRequest(BaseModel):
    """Move or copy a record into another notebook."""

    target_notebook_id: str


# === API Endpoints ===


async def _build_record_summary(request: AddRecordRequest) -> str:
    if request.summary.strip():
        return clean_thinking_tags(request.summary).strip()
    agent = NotebookSummarizeAgent(language=str(request.metadata.get("ui_language", "en")))
    return clean_thinking_tags(
        await agent.summarize(
            title=request.title,
            record_type=request.record_type,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
        )
    ).strip()


async def _stream_add_record_with_summary(
    request: AddRecordRequest,
) -> AsyncGenerator[str, None]:
    try:
        agent = NotebookSummarizeAgent(language=str(request.metadata.get("ui_language", "en")))
        summary_parts: list[str] = []
        if request.summary.strip():
            summary = clean_thinking_tags(request.summary).strip()
            summary_parts.append(summary)
            if summary:
                yield f"data: {json.dumps({'type': 'summary_chunk', 'content': summary}, ensure_ascii=False)}\n\n"
        else:
            async for chunk in agent.stream_summary(
                title=request.title,
                record_type=request.record_type,
                user_query=request.user_query,
                output=request.output,
                metadata=request.metadata,
            ):
                if not chunk:
                    continue
                summary_parts.append(chunk)

            summary = clean_thinking_tags("".join(summary_parts)).strip()
            if summary:
                yield f"data: {json.dumps({'type': 'summary_chunk', 'content': summary}, ensure_ascii=False)}\n\n"

        summary = clean_thinking_tags("".join(summary_parts)).strip()
        result = notebook_manager.add_record(
            notebook_ids=request.notebook_ids,
            record_type=request.record_type,
            title=request.title,
            summary=summary,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        payload = {
            "type": "result",
            "success": True,
            "summary": summary,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception as exc:
        payload = {"type": "error", "detail": str(exc)}
        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# NOTE: every literal path below must stay above the `/{notebook_id}` routes.
# FastAPI matches in declaration order, so a literal declared later is shadowed
# by the parameterised route and becomes unreachable.
@router.get("/health")
async def health_check():
    """Health check"""
    return {"status": "healthy", "service": "notebook"}


@router.get("/list")
async def list_notebooks():
    """
    Get all notebook list

    Returns:
        Notebook list (includes summary information)
    """
    try:
        notebooks = notebook_manager.list_notebooks()
        return {"notebooks": notebooks, "total": len(notebooks)}
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics():
    """
    Get notebook statistics

    Returns:
        Statistics information
    """
    try:
        stats = notebook_manager.get_statistics()
        return stats
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_notebook(request: CreateNotebookRequest):
    """
    Create new notebook

    Args:
        request: Create request

    Returns:
        Created notebook information
    """
    try:
        notebook = notebook_manager.create_notebook(
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        return {"success": True, "notebook": notebook}
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: str):
    """
    Get notebook details

    Args:
        notebook_id: Notebook ID

    Returns:
        Notebook details (includes all records)
    """
    try:
        notebook = notebook_manager.get_notebook(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return notebook
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{notebook_id}")
async def update_notebook(notebook_id: str, request: UpdateNotebookRequest):
    """
    Update notebook information

    Args:
        notebook_id: Notebook ID
        request: Update request

    Returns:
        Updated notebook information
    """
    try:
        notebook = notebook_manager.update_notebook(
            notebook_id=notebook_id,
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"success": True, "notebook": notebook}
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str):
    """
    Delete notebook

    Args:
        notebook_id: Notebook ID

    Returns:
        Deletion result
    """
    try:
        success = notebook_manager.delete_notebook(notebook_id)
        if not success:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"success": True, "message": "Notebook deleted successfully"}
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add_record")
async def add_record(request: AddRecordRequest):
    """
    Add record to notebook

    Args:
        request: Add record request

    Returns:
        Addition result
    """
    try:
        summary = await _build_record_summary(request)
        result = notebook_manager.add_record(
            notebook_ids=request.notebook_ids,
            record_type=request.record_type,
            title=request.title,
            summary=summary,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        return {
            "success": True,
            "summary": summary,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add_record_with_summary")
async def add_record_with_summary(request: AddRecordRequest):
    """Add record to notebook and stream generated summary."""
    return StreamingResponse(
        _stream_add_record_with_summary(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{notebook_id}/records/{record_id}")
async def remove_record(notebook_id: str, record_id: str):
    """
    Remove record from notebook

    Args:
        notebook_id: Notebook ID
        record_id: Record ID

    Returns:
        Deletion result
    """
    try:
        success = notebook_manager.remove_record(notebook_id, record_id)
        if not success:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"success": True, "message": "Record removed successfully"}
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{notebook_id}/records/{record_id}")
async def update_record(notebook_id: str, record_id: str, request: UpdateRecordRequest):
    """Update an existing notebook record in place."""
    try:
        # Forward only what the client actually sent. Passing every field
        # unconditionally would hand `kb_name=None` to the service on every
        # request and clear the record's knowledge-base link as a side effect
        # of renaming it; the service's sentinel default only works if an
        # omitted field never reaches it.
        changes = request.model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(status_code=400, detail="No fields to update")
        updated = notebook_manager.update_record(
            notebook_id=notebook_id,
            record_id=record_id,
            **changes,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"success": True, "record": updated}
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/records/{record_id}/copy")
async def copy_record(notebook_id: str, record_id: str, request: MoveRecordRequest):
    """Duplicate a record into another notebook under a fresh id."""
    try:
        copied = notebook_manager.copy_record(notebook_id, record_id, request.target_notebook_id)
        if not copied:
            raise HTTPException(status_code=404, detail="Record or target notebook not found")
        return {"success": True, "record": copied}
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{notebook_id}/records/{record_id}/move")
async def move_record(notebook_id: str, record_id: str, request: MoveRecordRequest):
    """Move a record from this notebook into another one."""
    try:
        moved = notebook_manager.move_record(notebook_id, record_id, request.target_notebook_id)
        if not moved:
            raise HTTPException(status_code=404, detail="Record or target notebook not found")
        return {"success": True, "record": moved}
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/export", response_class=PlainTextResponse)
async def export_notebook(notebook_id: str):
    """Render the whole notebook as a single Markdown document."""
    try:
        markdown = notebook_manager.export_markdown(notebook_id)
        if markdown is None:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return PlainTextResponse(
            markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{notebook_id}.md"'},
        )
    except HTTPException:
        raise
    except NotebookCorruptedError as exc:
        raise _unreadable(exc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
