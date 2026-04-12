"""
Guided Learning API Router
==========================

Provides session creation, learning progress management, and chat interaction.
"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from deeptutor.agents.notebook import NotebookAnalysisAgent
from deeptutor.agents.base_agent import BaseAgent
from deeptutor.agents.guide.guide_manager import GuideManager
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.logging import get_logger
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.config import parse_language
from deeptutor.services.llm import get_llm_config
from deeptutor.services.notebook import notebook_manager
from deeptutor.services.settings.interface_settings import get_ui_language

router = APIRouter()
_guide_manager: GuideManager | None = None
_guide_manager_language: str | None = None

# Initialize logger with config
config = load_config_with_main("main.yaml", PROJECT_ROOT)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("Guide", level="INFO", log_dir=log_dir)


# === Request/Response Models ===


class CreateSessionRequest(BaseModel):
    """Create session request"""

    user_input: str = ""
    notebook_id: str | None = None  # Optional, single notebook mode
    records: list[dict] | None = None  # Optional, cross-notebook mode with direct records
    notebook_references: list[dict] | None = None
    language: str | None = None


class ChatRequest(BaseModel):
    """Chat request"""

    session_id: str
    message: str
    knowledge_index: int | None = None


class FixHtmlRequest(BaseModel):
    """Fix HTML request"""

    session_id: str
    bug_description: str


class SessionActionRequest(BaseModel):
    """Session action request"""

    session_id: str


class NavigateRequest(BaseModel):
    """Navigate to a knowledge point."""

    session_id: str
    knowledge_index: int


class RetryPageRequest(BaseModel):
    """Retry a failed page generation."""

    session_id: str
    page_index: int


# === Helper Functions ===


def get_guide_manager(language: str | None = None):
    """Get GuideManager instance"""
    global _guide_manager, _guide_manager_language
    requested_language = parse_language(language) if language else None

    if (
        _guide_manager is not None
        and (requested_language is None or requested_language == _guide_manager_language)
    ):
        return _guide_manager

    try:
        llm_config = get_llm_config()
        api_key = llm_config.api_key
        base_url = llm_config.base_url
        api_version = getattr(llm_config, "api_version", None)
        binding = llm_config.binding
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM config error: {e!s}")

    ui_language = requested_language or get_ui_language(
        default=config.get("system", {}).get("language", "zh")
    )
    ui_language = parse_language(ui_language)
    _guide_manager = GuideManager(
        api_key=api_key,
        base_url=base_url,
        api_version=api_version,
        language=ui_language,
        binding=binding,
    )  # Read from config file
    _guide_manager_language = ui_language
    return _guide_manager


def _build_user_input_from_records(records: list[dict]) -> str:
    """Build a compact user input string from legacy record payloads."""
    parts: list[str] = []
    for record in records:
        user_query = str(record.get("user_query", "")).strip()
        if user_query:
            parts.append(user_query)

    if not parts:
        return ""

    joined = "\n".join(f"- {part}" for part in parts)
    return f"Please design a guided learning plan based on these learner requests:\n{joined}"


# === REST API Endpoints ===


@router.post("/create_session")
async def create_session(request: CreateSessionRequest):
    """
    Create a new guided learning session.

    Returns:
        Session creation result with knowledge point list.
    """
    task_manager = TaskIDManager.get_instance()

    try:
        user_input = request.user_input.strip()

        if not user_input and request.records and isinstance(request.records, list):
            user_input = _build_user_input_from_records(request.records)
        elif not user_input and request.notebook_id:
            notebook = notebook_manager.get_notebook(request.notebook_id)
            if not notebook:
                raise HTTPException(status_code=404, detail="Notebook not found")
            user_input = _build_user_input_from_records(notebook.get("records", []))

        if not user_input:
            raise HTTPException(
                status_code=400, detail="Must provide user_input, notebook_id, or records"
            )

        raw_user_input = user_input
        notebook_context = ""
        requested_language = parse_language(request.language) if request.language else None
        if request.notebook_references:
            selected_records = notebook_manager.get_records_by_references(request.notebook_references)
            if selected_records:
                analysis_agent = NotebookAnalysisAgent(
                    language=requested_language or get_ui_language(default="zh")
                )
                notebook_context = await analysis_agent.analyze(
                    user_question=raw_user_input,
                    records=selected_records,
                )
                user_input = (
                    f"[Notebook Context]\n{notebook_context}\n\n"
                    f"[User Question]\n{raw_user_input}"
                )

        # Reset LLM stats for new session
        BaseAgent.reset_stats("guide")

        manager = get_guide_manager(requested_language)
        result = await manager.create_session(
            user_input=user_input,
            display_title=raw_user_input,
            notebook_context=notebook_context,
        )

        if result and "session_id" in result:
            session_id = result["session_id"]
            task_id = task_manager.generate_task_id("guide", session_id)
            logger.info(f"[{task_id}] Session created: {session_id}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create session failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/start")
async def start_learning(request: SessionActionRequest):
    """
    Start learning (get the first knowledge point).
    """
    try:
        manager = get_guide_manager()
        result = await manager.start_learning(request.session_id)
        return result
    except Exception as e:
        logger.error(f"Start learning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/navigate")
async def navigate_to_knowledge(request: NavigateRequest):
    """
    Navigate to any knowledge point.
    """
    try:
        manager = get_guide_manager()
        result = await manager.navigate_to_knowledge(request.session_id, request.knowledge_index)
        return result
    except Exception as e:
        logger.error(f"Navigate knowledge failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/complete")
async def complete_learning(request: SessionActionRequest):
    """
    Complete guided learning and generate a summary.
    """
    try:
        manager = get_guide_manager()
        result = await manager.complete_learning(request.session_id)
        BaseAgent.print_stats("guide")
        return result
    except Exception as e:
        logger.error(f"Complete learning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Send a chat message.
    """
    try:
        manager = get_guide_manager()
        result = await manager.chat(request.session_id, request.message, request.knowledge_index)
        return result
    except Exception as e:
        logger.error(f"Chat failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fix_html")
async def fix_html(request: FixHtmlRequest):
    """
    Fix HTML page bugs.
    """
    try:
        manager = get_guide_manager()
        result = await manager.fix_html(request.session_id, request.bug_description)
        return result
    except Exception as e:
        logger.error(f"Fix HTML failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry_page")
async def retry_page(request: RetryPageRequest):
    """
    Retry a failed page generation.
    """
    try:
        manager = get_guide_manager()
        result = await manager.retry_page(request.session_id, request.page_index)
        return result
    except Exception as e:
        logger.error(f"Retry page failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_session(request: SessionActionRequest):
    """
    Reset the current guided learning session.
    """
    try:
        manager = get_guide_manager()
        result = await manager.reset_session(request.session_id)
        return result
    except Exception as e:
        logger.error(f"Reset session failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """
    Permanently delete a guided learning session.
    """
    try:
        manager = get_guide_manager()
        result = await manager.delete_session(session_id)
        return result
    except Exception as e:
        logger.error(f"Delete session failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def list_sessions():
    """
    List all guided learning sessions (summary only, no HTML).
    """
    try:
        manager = get_guide_manager()
        sessions = manager.list_sessions()
        return {"sessions": sessions}
    except Exception as e:
        logger.error(f"List sessions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}")
async def get_session(session_id: str):
    """
    Get session information.
    """
    try:
        manager = get_guide_manager()
        session = manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get session failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/html")
async def get_current_html(session_id: str):
    """
    Get the current HTML page.
    """
    try:
        manager = get_guide_manager()
        html = manager.get_current_html(session_id)
        if html is None:
            raise HTTPException(status_code=404, detail="Session not found or no HTML content")
        return {"html": html}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get HTML failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/session/{session_id}/pages")
async def get_session_pages(session_id: str):
    """
    Get page generation status and ready HTML pages.
    """
    try:
        manager = get_guide_manager()
        pages = manager.get_session_pages(session_id)
        if not pages:
            raise HTTPException(status_code=404, detail="Session not found")
        return pages
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get session pages failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === WebSocket Endpoint ===


@router.websocket("/ws/{session_id}")
async def websocket_guide(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time interaction.

    Message types:
    - start: Start learning
    - next: Next knowledge point
    - chat: Send chat message
    - fix_html: Fix HTML
    - get_session: Get session state
    """
    await websocket.accept()

    task_manager = TaskIDManager.get_instance()
    task_id = task_manager.generate_task_id("guide", session_id)

    try:
        await websocket.send_json({"type": "task_id", "task_id": task_id})
    except (RuntimeError, WebSocketDisconnect, ConnectionError) as e:
        logger.debug(f"Failed to send task_id: {e}")

    try:
        manager = get_guide_manager()

        session = manager.get_session(session_id)
        if not session:
            await websocket.send_json({"type": "error", "content": "Session not found"})
            await websocket.close()
            return

        logger.info(f"[{task_id}] Guide session started: {session_id}")

        await websocket.send_json({"type": "session_info", "data": session})

        while True:
            try:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")

                if msg_type == "start":
                    logger.debug(f"[{task_id}] Start learning")
                    result = await manager.start_learning(session_id)
                    await websocket.send_json({"type": "start_result", "data": result})

                elif msg_type == "navigate":
                    knowledge_index = int(data.get("knowledge_index", 0))
                    logger.debug(f"[{task_id}] Navigate to knowledge point {knowledge_index}")
                    result = await manager.navigate_to_knowledge(session_id, knowledge_index)
                    await websocket.send_json({"type": "navigate_result", "data": result})

                elif msg_type == "complete":
                    logger.debug(f"[{task_id}] Complete learning")
                    result = await manager.complete_learning(session_id)
                    await websocket.send_json({"type": "complete_result", "data": result})

                elif msg_type == "chat":
                    message = data.get("message", "")
                    knowledge_index = data.get("knowledge_index")
                    if message:
                        logger.debug(f"[{task_id}] User message: {message[:50]}...")
                        result = await manager.chat(session_id, message, knowledge_index)
                        await websocket.send_json({"type": "chat_result", "data": result})

                elif msg_type == "fix_html":
                    bug_desc = data.get("bug_description", "")
                    logger.debug(f"[{task_id}] Fix HTML: {bug_desc[:50]}...")
                    result = await manager.fix_html(session_id, bug_desc)
                    await websocket.send_json({"type": "fix_result", "data": result})

                elif msg_type == "get_session":
                    session = manager.get_session(session_id)
                    await websocket.send_json({"type": "session_info", "data": session})

                elif msg_type == "get_pages":
                    pages = manager.get_session_pages(session_id)
                    await websocket.send_json({"type": "pages_info", "data": pages})

                elif msg_type == "retry_page":
                    page_index = int(data.get("page_index", 0))
                    result = await manager.retry_page(session_id, page_index)
                    await websocket.send_json({"type": "retry_result", "data": result})

                elif msg_type == "reset":
                    result = await manager.reset_session(session_id)
                    await websocket.send_json({"type": "reset_result", "data": result})
                    await websocket.close()
                    return

                else:
                    await websocket.send_json(
                        {"type": "error", "content": f"Unknown message type: {msg_type}"}
                    )

            except WebSocketDisconnect:
                logger.debug(f"WebSocket disconnected: {session_id}")
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await websocket.send_json({"type": "error", "content": str(e)})

    except Exception as e:
        logger.error(f"WebSocket connection error: {e}")
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect, ConnectionError):
            pass  # Connection already closed


@router.get("/health")
async def health_check():
    """Health check"""
    return {"status": "healthy", "service": "guide"}
