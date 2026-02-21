"""
Notebook API Router
Provides notebook creation, querying, updating, deletion, and record management functions
"""

import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

# Ensure module can be imported
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.routers.knowledge import _kb_base_dir, run_upload_processing_task
from src.api.utils.notebook_manager import notebook_manager
from src.knowledge.manager import KnowledgeBaseManager
from src.logging import get_logger
from src.services.config import load_config_with_main
from src.services.llm import get_llm_config
from src.tools.web_crawler import fetch_urls

router = APIRouter()

# Initialize logger
config = load_config_with_main("solve_config.yaml", project_root)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("Notebook", level="INFO", log_dir=log_dir)


# === Helper Functions ===
def _strip_research_banner(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return content

    first_line = re.sub(r"^[#>*\\s]+", "", lines[0]).strip()
    first_line = first_line.replace("*", "").strip()
    if "深度研究完成" in first_line:
        return "\n".join(lines[1:]).lstrip()
    return content


def _extract_markdown_title(content: str) -> str:
    lines = content.splitlines()
    # Prefer first H1 after banner
    for line in lines:
        if re.match(r"^#\\s+\\S", line):
            return re.sub(r"^#\\s+", "", line).strip()
    # Fallback to any heading
    for line in lines:
        if re.match(r"^#{2,6}\\s+\\S", line):
            return re.sub(r"^#{2,6}\\s+", "", line).strip()
    # Final fallback to first non-empty text line
    for line in lines:
        cleaned = re.sub(r"^[#>*\\s]+", "", line).strip()
        cleaned = cleaned.replace("*", "").strip()
        if cleaned:
            return cleaned
    return ""


MAX_SOURCE_CONTENT_CHARS = 8000
REPORT_SOURCE_CONTENT_CHARS = 50000  # 增加到 50000 字符（约 25000 中文字）
SOURCES_KB_DESCRIPTION = "Notebook selected sources"


def _get_notebook_sources_kb_name(notebook_id: str) -> str:
    return f"notebook_{notebook_id}_sources"


def _normalize_source_payload(source: dict) -> dict:
    content = (source.get("content") or "").strip()
    max_chars = (
        REPORT_SOURCE_CONTENT_CHARS
        if source.get("type") == "report"
        else MAX_SOURCE_CONTENT_CHARS
    )
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[truncated]"
    return {
        "id": source.get("id") or "",
        "type": source.get("type") or "web",
        "title": source.get("title") or source.get("url") or "Source",
        "url": source.get("url") or "",
        "content": content,
    }


def _source_key(source: dict) -> str:
    key = source.get("url") or source.get("id") or source.get("title") or ""
    return f"{source.get('type','')}-{key}"


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for source in sources:
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _collect_selected_sources(sessions: list[dict]) -> list[dict]:
    selected = []
    for session in sessions:
        for source in session.get("sources", []) or []:
            if not source:
                continue
            if source.get("selected", True):
                selected.append(_normalize_source_payload(source))
    return _dedupe_sources(selected)


def _source_digest(source: dict) -> dict:
    content = source.get("content") or ""
    content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()
    return {
        "id": source.get("id") or "",
        "type": source.get("type") or "",
        "title": source.get("title") or "",
        "url": source.get("url") or "",
        "content_hash": content_hash,
    }


def _sources_signature(sources: list[dict]) -> str:
    payload = [_source_digest(source) for source in sources]
    payload.sort(key=lambda item: (item["type"], item["url"], item["id"], item["title"]))
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_sources_manifest(kb_dir: Path) -> dict:
    manifest_path = kb_dir / "sources_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_sources_manifest(kb_dir: Path, signature: str, sources: list[dict]) -> None:
    manifest = {
        "signature": signature,
        "count": len(sources),
        "updated_at": time.time(),
        "sources": [
            {
                "id": source.get("id") or "",
                "type": source.get("type") or "",
                "title": source.get("title") or "",
                "url": source.get("url") or "",
            }
            for source in sources
        ],
    }
    manifest_path = kb_dir / "sources_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=True, indent=2)


def _format_source_markdown(source: dict) -> str:
    title = source.get("title") or source.get("url") or "Source"
    lines = [f"# {title}"]
    if source.get("type"):
        lines.append(f"\nType: {source['type']}")
    if source.get("url"):
        lines.append(f"\nSource: {source['url']}")
    if source.get("content"):
        lines.append(f"\n\n{source['content']}")
    return "\n".join(lines).strip() + "\n"


async def _enrich_sources_with_content(sources: list[dict]) -> list[dict]:
    """
    Enrich sources by fetching web content for URLs that don't have content yet.
    Returns a new list with enriched sources.
    """
    # Find sources that need fetching (type=web, has url, no content)
    urls_to_fetch = []
    url_to_source_idx = {}

    for idx, source in enumerate(sources):
        if (
            source.get("type") == "web"
            and source.get("url")
            and not source.get("content")
        ):
            url = source["url"]
            urls_to_fetch.append(url)
            url_to_source_idx[url] = idx

    if not urls_to_fetch:
        return sources  # Nothing to fetch

    logger.info(f"Fetching content for {len(urls_to_fetch)} source URLs")

    # Fetch all URLs concurrently
    fetch_results = await fetch_urls(urls_to_fetch, concurrency=5)

    # Create enriched sources list
    enriched = [s.copy() for s in sources]

    for result in fetch_results:
        url = result["url"]
        idx = url_to_source_idx.get(url)
        if idx is None:
            continue

        if result.get("error"):
            logger.warning(f"Failed to fetch {url}: {result['error']}")
            # Add error info to source
            enriched[idx]["fetch_error"] = result["error"]
        else:
            # Successfully fetched
            enriched[idx]["content"] = result["content"]
            if result.get("title") and not enriched[idx].get("title"):
                enriched[idx]["title"] = result["title"]
            logger.info(f"Fetched {len(result['content'])} chars from {url}")

    return enriched


def _write_source_files(raw_dir: Path, sources: list[dict]) -> list[str]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    file_paths = []
    for source in sources:
        key = _source_key(source) or f"source-{len(file_paths)}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        filename = f"source_{digest}.md"
        file_path = raw_dir / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_format_source_markdown(source))
        file_paths.append(str(file_path))
    return file_paths


async def _sync_sources_kb(notebook_id: str, background_tasks: BackgroundTasks) -> str | None:
    sessions = notebook_manager.list_sessions(notebook_id)
    selected_sources = _collect_selected_sources(sessions)
    if not selected_sources:
        return None

    # Enrich sources by fetching web content
    selected_sources = await _enrich_sources_with_content(selected_sources)

    signature = _sources_signature(selected_sources)
    kb_name = _get_notebook_sources_kb_name(notebook_id)
    kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))

    if kb_name in kb_manager.list_knowledge_bases():
        kb_dir = kb_manager.get_knowledge_base_path(kb_name)
        manifest = _load_sources_manifest(kb_dir)
        if manifest.get("signature") == signature:
            return kb_name
        kb_manager.delete_knowledge_base(kb_name, confirm=True)

    kb_dir = Path(kb_manager.create_knowledge_base(kb_name, description=SOURCES_KB_DESCRIPTION))
    raw_dir = kb_dir / "raw"
    file_paths = _write_source_files(raw_dir, selected_sources)
    _write_sources_manifest(kb_dir, signature, selected_sources)

    if file_paths:
        llm_cfg = get_llm_config()
        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(_kb_base_dir),
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url,
            uploaded_file_paths=file_paths,
        )

    return kb_name

async def _trigger_kb_indexing(kb_sync_info: dict, background_tasks: BackgroundTasks):
    """Trigger KB indexing for a synced note"""
    try:
        if not kb_sync_info:
            return
            
        kb_name = kb_sync_info.get("kb_name")
        file_path = kb_sync_info.get("file_path")
        
        if not kb_name or not file_path:
            return
            
        llm_cfg = get_llm_config()
        
        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(_kb_base_dir),
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url,
            uploaded_file_paths=[file_path],
        )
    except Exception as e:
        # Just log error, don't fail the request
        print(f"Failed to trigger KB indexing: {e}")


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
    record_type: Literal["solve", "question", "research", "co_writer", "chat", "note"]
    title: str
    user_query: str
    output: str
    metadata: dict = {}
    kb_name: str | None = None


class RemoveRecordRequest(BaseModel):
    """Remove record request"""

    record_id: str


class GenerateTitleRequest(BaseModel):
    """Generate title request"""

    content: str


class SessionMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    isStreaming: bool | None = None


class SessionSource(BaseModel):
    id: str
    type: Literal["web", "file", "kb", "report"]
    title: str
    url: str | None = None
    selected: bool = True
    content: str | None = None


class SessionSnapshot(BaseModel):
    session_id: str | None = None
    title: str | None = None
    messages: list[SessionMessage] = []
    sources: list[SessionSource] = []
    research_report: str | None = None
    research_state: dict | None = None
    studio_state: dict | None = None
    created_at: float | None = None
    updated_at: float | None = None


# === API Endpoints ===


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add_record")
async def add_record(request: AddRecordRequest, background_tasks: BackgroundTasks):
    """
    Add record to notebook

    Args:
        request: Add record request
        background_tasks: Background tasks handler

    Returns:
        Addition result
    """
    try:
        result = notebook_manager.add_record(
            notebook_ids=request.notebook_ids,
            record_type=request.record_type,
            title=request.title,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        
        # Trigger KB indexing if sync info is present
        if "kb_sync_info" in result and result["kb_sync_info"]:
            await _trigger_kb_indexing(result["kb_sync_info"], background_tasks)
            
        return {
            "success": True,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}/records/{record_id}")
async def remove_record(notebook_id: str, record_id: str):
    """
    Remove record from notebook
    """
    try:
        success = notebook_manager.remove_record(notebook_id, record_id)
        if not success:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"success": True, "message": "Record removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SingleRecordRequest(BaseModel):
    """Add single record to a specific notebook"""

    type: Literal["solve", "question", "research", "co_writer", "chat", "note"]
    title: str
    user_query: str = ""
    output: str
    metadata: dict = {}
    kb_name: str | None = None


@router.post("/{notebook_id}/records")
async def add_single_record(notebook_id: str, request: SingleRecordRequest, background_tasks: BackgroundTasks):
    """
    Add a record directly to a specific notebook

    Args:
        notebook_id: Notebook ID
        request: Record data
        background_tasks: Background tasks handler

    Returns:
        Addition result
    """
    try:
        result = notebook_manager.add_record(
            notebook_ids=[notebook_id],
            record_type=request.type,
            title=request.title,
            user_query=request.user_query or request.title,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )
        
        # Trigger KB indexing if sync info is present
        if "kb_sync_info" in result and result["kb_sync_info"]:
            await _trigger_kb_indexing(result["kb_sync_info"], background_tasks)
            
        return {
            "success": True,
            "record": result["record"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/sessions")
async def list_sessions(notebook_id: str):
    """List all chat sessions for a notebook"""
    if not notebook_manager.get_notebook(notebook_id):
        raise HTTPException(status_code=404, detail="Notebook not found")
    sessions = notebook_manager.list_sessions(notebook_id)
    return {"sessions": sessions}


@router.get("/{notebook_id}/sessions/latest")
async def latest_session(notebook_id: str):
    """Get latest chat session for a notebook"""
    if not notebook_manager.get_notebook(notebook_id):
        raise HTTPException(status_code=404, detail="Notebook not found")
    session = notebook_manager.get_latest_session(notebook_id)
    return {"session": session}


@router.post("/{notebook_id}/sessions")
async def upsert_session(
    notebook_id: str, request: SessionSnapshot, background_tasks: BackgroundTasks
):
    """Create or update a chat session snapshot"""
    if not notebook_manager.get_notebook(notebook_id):
        raise HTTPException(status_code=404, detail="Notebook not found")
    payload = request.dict(exclude_none=True)
    session = notebook_manager.upsert_session(notebook_id, payload)
    try:
        await _sync_sources_kb(notebook_id, background_tasks)
    except Exception as e:
        print(f"Failed to sync session sources to KB: {e}")
    return {"session": session}



@router.post("/generate_title")
async def generate_title(request: GenerateTitleRequest):
    """Generate a short title for a note content"""
    try:
        from lightrag.llm.openai import openai_complete_if_cache

        from src.services.llm import get_llm_config

        llm_cfg = get_llm_config()

        cleaned_content = _strip_research_banner(request.content).strip()
        if cleaned_content != request.content.strip():
            title = _extract_markdown_title(cleaned_content)
            if title:
                return {"title": title[:30] + "..." if len(title) > 30 else title}

        prompt = f"""
Please generate a concise and descriptive title for the following note content.
The title should be under 10 words.
Do not wrap in quotes.

Content:
{cleaned_content[:1000]}...
"""
        
        title = await openai_complete_if_cache(
            model=llm_cfg.model,
            prompt=prompt,
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url
        )
        
        title = title.strip().strip('"')
        if not title:
            title = _extract_markdown_title(cleaned_content)
        return {"title": title or "New Note"}
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        # Fallback
        return {"title": "New Note"}


@router.get("/health")
async def health_check():
    """Health check"""
    return {"status": "healthy", "service": "notebook"}


@router.get("/{notebook_id}/sources_kb_status")
async def get_sources_kb_status(notebook_id: str):
    """
    Check the indexing status of the temporary sources knowledge base.

    Args:
        notebook_id: Notebook ID

    Returns:
        Status information:
        - ready: bool - Whether KB is ready for querying
        - status: str - "not_created" | "indexing" | "ready" | "error"
        - progress: dict | None - Progress information if indexing
    """
    try:
        kb_name = _get_notebook_sources_kb_name(notebook_id)
        kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))

        # Check if KB exists
        if kb_name not in kb_manager.list_knowledge_bases():
            return {
                "ready": False,
                "status": "not_created",
                "progress": None
            }

        # Check progress file
        kb_dir = kb_manager.get_knowledge_base_path(kb_name)
        progress_file = kb_dir / ".progress.json"

        if not progress_file.exists():
            # No progress file - either completed long ago or indexing hasn't started
            # Check if rag_storage exists as a sign of completion
            rag_storage = kb_dir / "rag_storage"
            if rag_storage.exists():
                return {
                    "ready": True,
                    "status": "ready",
                    "progress": None
                }
            else:
                # KB exists but no storage yet - probably just started
                return {
                    "ready": False,
                    "status": "indexing",
                    "progress": {
                        "stage": "initializing",
                        "message": "准备中...",
                        "progress_percent": 0
                    }
                }

        # Read progress file
        try:
            with open(progress_file, encoding="utf-8") as f:
                import json
                progress = json.load(f)

            stage = progress.get("stage", "")

            if stage == "completed":
                return {
                    "ready": True,
                    "status": "ready",
                    "progress": None
                }
            elif stage == "error":
                return {
                    "ready": False,
                    "status": "error",
                    "progress": progress
                }
            else:
                return {
                    "ready": False,
                    "status": "indexing",
                    "progress": progress
                }
        except Exception as e:
            logger.error(f"Failed to read progress file: {e}")
            # Assume ready if we can't read progress
            return {
                "ready": True,
                "status": "ready",
                "progress": None
            }

    except Exception as e:
        logger.error(f"Failed to check sources KB status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
