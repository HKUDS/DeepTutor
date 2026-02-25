"""
Notebook Chat WebSocket Router
===============================

Dedicated WebSocket endpoint for notebook grounded QA.
This is separate from the standalone chat (/api/v1/chat) to avoid coupling.

Key differences from chat.py:
- Does NOT write to SessionManager / chat_sessions.json
- Supports sources_kb_name for selected sources retrieval
- Supports require_sources for strict grounded QA mode
- Notebook sessions are managed by notebook_manager, not here
"""

from pathlib import Path
import sys

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

from src.agents.chat import ChatAgent
from src.logging import get_logger
from src.services.config import load_config_with_main

# Initialize logger
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("NotebookChatAPI", level="INFO", log_dir=log_dir)

router = APIRouter()


@router.websocket("/chat")
async def websocket_notebook_chat(websocket: WebSocket):
    """
    WebSocket endpoint for notebook grounded QA.

    This endpoint is mounted at /api/v1/notebook/chat and is used exclusively
    by the notebook page for context-aware Q&A over selected sources and KBs.

    Message format:
    {
        "message": str,              # User message
        "history": [...] | null,     # Conversation history
        "kb_name": str,              # Knowledge base name (for RAG)
        "sources_kb_name": str,      # KB for notebook selected sources
        "enable_rag": bool,          # Enable RAG retrieval
        "enable_web_search": bool,   # Enable Web Search
        "require_sources": bool,     # Require sources before answering (grounded QA)
        "selected_sources": list     # Optional source catalog with ref_number mapping
    }

    Response format:
    - {"type": "status", "stage": str, "message": str} # Status updates
    - {"type": "stream", "content": str}               # Streaming response chunks
    - {"type": "sources", "rag": list, "web": list, "source_catalog": list}
      # Source citations + reference catalog
    - {"type": "result", "content": str}               # Final complete response
    - {"type": "error", "message": str}                # Error message
    """
    await websocket.accept()

    # Get system language for agent
    language = config.get("system", {}).get("language", "en")

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            message = data.get("message", "").strip()
            history = data.get("history") or []
            kb_name = data.get("kb_name", "")
            sources_kb_name = data.get("sources_kb_name") or ""
            enable_rag = data.get("enable_rag", False)
            enable_web_search = data.get("enable_web_search", False)
            require_sources = data.get("require_sources", False)
            source_catalog = data.get("selected_sources") or []
            if not isinstance(source_catalog, list):
                source_catalog = []

            if not message:
                await websocket.send_json({"type": "error", "message": "Message is required"})
                continue

            logger.info(
                f"Notebook chat: message={message[:50]}..., "
                f"rag={enable_rag}, web={enable_web_search}, "
                f"sources_kb={sources_kb_name or 'none'}, "
                f"catalog={len(source_catalog)}"
            )

            try:
                # Initialize ChatAgent
                agent = ChatAgent(language=language, config=config)

                # Send status updates
                if enable_rag and kb_name:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "stage": "rag",
                            "message": f"Searching knowledge base: {kb_name}...",
                        }
                    )

                if sources_kb_name:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "stage": "sources",
                            "message": "Searching selected sources...",
                        }
                    )

                if enable_web_search:
                    await websocket.send_json(
                        {
                            "type": "status",
                            "stage": "web",
                            "message": "Searching the web...",
                        }
                    )

                await websocket.send_json(
                    {
                        "type": "status",
                        "stage": "generating",
                        "message": "Generating response...",
                    }
                )

                # Process with streaming
                full_response = ""
                sources = {"rag": [], "web": []}
                resolved_catalog = source_catalog

                stream_generator = await agent.process(
                    message=message,
                    history=history,
                    kb_name=kb_name,
                    sources_kb_name=sources_kb_name,
                    enable_rag=enable_rag,
                    enable_web_search=enable_web_search,
                    require_sources=require_sources,
                    source_catalog=source_catalog,
                    stream=True,
                )

                async for chunk_data in stream_generator:
                    if chunk_data["type"] == "chunk":
                        await websocket.send_json(
                            {
                                "type": "stream",
                                "content": chunk_data["content"],
                            }
                        )
                        full_response += chunk_data["content"]
                    elif chunk_data["type"] == "complete":
                        full_response = chunk_data["response"]
                        sources = chunk_data.get("sources", {"rag": [], "web": []})
                        resolved_catalog = chunk_data.get("source_catalog", source_catalog)

                # Send sources/catalog if any
                if sources.get("rag") or sources.get("web") or resolved_catalog:
                    await websocket.send_json(
                        {
                            "type": "sources",
                            **sources,
                            "source_catalog": resolved_catalog,
                        }
                    )

                # Send final result
                await websocket.send_json(
                    {
                        "type": "result",
                        "content": full_response,
                    }
                )

                # NOTE: No SessionManager write here!
                # Notebook sessions are managed by notebook_manager on the frontend side.

                logger.info(f"Notebook chat completed: {len(full_response)} chars")

            except Exception as e:
                logger.error(f"Notebook chat processing error: {e}")
                await websocket.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        logger.debug("Client disconnected from notebook chat")
    except Exception as e:
        logger.error(f"Notebook chat WebSocket error: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
