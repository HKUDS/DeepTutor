"""
Solve API Router
================

WebSocket endpoint for real-time problem solving with streaming logs.
"""

import asyncio
from pathlib import Path
import re
import sys
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from src.agents.solve import MainSolver, SolverSessionManager
from src.api.utils.history import ActivityType, history_manager
from src.api.utils.log_interceptor import LogInterceptor
from src.api.utils.task_id_manager import TaskIDManager

_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))
from src.logging import get_logger
from src.services.config import load_config_with_main
from src.services.llm import get_llm_config

# Initialize logger with config
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("SolveAPI", level="INFO", log_dir=log_dir)

router = APIRouter()

# Initialize session manager
solver_session_manager = SolverSessionManager()


# =============================================================================
# REST Endpoints for Session Management
# =============================================================================


@router.get("/solve/sessions")
async def list_solver_sessions(limit: int = 20):
    """
    List recent solver sessions.

    Args:
        limit: Maximum number of sessions to return

    Returns:
        List of session summaries
    """
    return solver_session_manager.list_sessions(limit=limit, include_messages=False)


@router.get("/solve/sessions/{session_id}")
async def get_solver_session(session_id: str):
    """
    Get a specific solver session with full message history.

    Args:
        session_id: Session identifier

    Returns:
        Complete session data including messages
    """
    session = solver_session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/solve/sessions/{session_id}")
async def delete_solver_session(session_id: str):
    """
    Delete a solver session.

    Args:
        session_id: Session identifier

    Returns:
        Success message
    """
    if solver_session_manager.delete_session(session_id):
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")


# =============================================================================
# WebSocket Endpoint for Solving
# =============================================================================


@router.websocket("/solve")
async def websocket_solve(websocket: WebSocket):
    await websocket.accept()

    task_manager = TaskIDManager.get_instance()
    connection_closed = asyncio.Event()
    log_queue = asyncio.Queue()
    pusher_task = None

    async def safe_send_json(data: dict[str, Any]):
        """Safely send JSON to WebSocket, checking if connection is closed"""
        if connection_closed.is_set():
            return False
        try:
            await websocket.send_json(data)
            return True
        except (WebSocketDisconnect, RuntimeError, ConnectionError) as e:
            logger.debug(f"WebSocket connection closed: {e}")
            connection_closed.set()
            return False
        except Exception as e:
            logger.debug(f"Error sending WebSocket message: {e}")
            return False

    async def log_pusher():
        while not connection_closed.is_set():
            try:
                # Use timeout to periodically check if connection is closed
                entry = await asyncio.wait_for(log_queue.get(), timeout=0.5)
                try:
                    await websocket.send_json(entry)
                except (WebSocketDisconnect, RuntimeError, ConnectionError) as e:
                    # Connection closed, stop pushing
                    logger.debug(f"WebSocket connection closed in log_pusher: {e}")
                    connection_closed.set()
                    log_queue.task_done()
                    break
                except Exception as e:
                    logger.debug(f"Error sending log entry: {e}")
                    # Continue to next entry
                log_queue.task_done()
            except asyncio.TimeoutError:
                # Timeout, check if connection is still open
                continue
            except Exception as e:
                logger.debug(f"Error in log_pusher: {e}")
                break

    session_id = None  # Track session for this connection

    try:
        # 1. Wait for the initial message with the question and config
        data = await websocket.receive_json()
        question = data.get("question")
        kb_name = data.get("kb_name", "ai_textbook")
        session_id = data.get("session_id")  # Optional session ID

        if not question:
            await websocket.send_json({"type": "error", "content": "Question is required"})
            return

        # Get or create session
        if session_id:
            session = solver_session_manager.get_session(session_id)
            if not session:
                # Session not found, create new one
                session = solver_session_manager.create_session(
                    title=question[:50] + ("..." if len(question) > 50 else ""),
                    kb_name=kb_name,
                )
                session_id = session["session_id"]
        else:
            # Create new session
            session = solver_session_manager.create_session(
                title=question[:50] + ("..." if len(question) > 50 else ""),
                kb_name=kb_name,
            )
            session_id = session["session_id"]

        # Send session ID to frontend
        await websocket.send_json({"type": "session", "session_id": session_id})

        # Add user message to session
        solver_session_manager.add_message(
            session_id=session_id,
            role="user",
            content=question,
        )

        task_key = f"solve_{kb_name}_{hash(str(question))}"
        task_id = task_manager.generate_task_id("solve", task_key)

        await websocket.send_json({"type": "task_id", "task_id": task_id})

        # 2. Initialize Solver
        root_dir = Path(__file__).parent.parent.parent.parent
        output_base = root_dir / "data" / "user" / "solve"

        try:
            llm_config = get_llm_config()
            api_key = llm_config.api_key
            base_url = llm_config.base_url
            api_version = getattr(llm_config, "api_version", None)
        except Exception as e:
            logger.error(f"Failed to get LLM config: {e}", exc_info=True)
            await websocket.send_json({"type": "error", "content": f"LLM configuration error: {e}"})
            return

        solver = MainSolver(
            kb_name=kb_name,
            output_base_dir=str(output_base),
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
        )

        # Complete async initialization
        await solver.ainit()

        logger.info(f"[{task_id}] Solving: {question[:50]}...")

        target_logger = solver.logger.logger

        # Note: System log forwarder removed - all logs now go to unified log file
        # The main logger already writes to data/user/logs/ai_tutor_YYYYMMDD.log

        # 3. Setup Log Queue
        # log_queue already initialized

        # 4. Setup status update mechanism
        display_manager = None
        if hasattr(solver.logger, "display_manager") and solver.logger.display_manager:
            display_manager = solver.logger.display_manager

            original_set_status = display_manager.set_agent_status

            def wrapped_set_status(agent_name: str, status: str):
                original_set_status(agent_name, status)
                try:
                    log_queue.put_nowait(
                        {
                            "type": "agent_status",
                            "agent": agent_name,
                            "status": status,
                            "all_agents": display_manager.agents_status.copy(),
                        }
                    )
                except Exception:
                    pass

            display_manager.set_agent_status = wrapped_set_status

            original_update_stats = display_manager.update_token_stats

            def wrapped_update_stats(summary: dict[str, Any]):
                original_update_stats(summary)
                try:
                    stats_copy = display_manager.stats.copy()
                    logger.debug(
                        f"Sending token_stats: model={stats_copy.get('model')}, calls={stats_copy.get('calls')}, cost={stats_copy.get('cost')}"
                    )
                    log_queue.put_nowait({"type": "token_stats", "stats": stats_copy})
                except Exception as e:
                    logger.debug(f"Failed to send token_stats: {e}")

            display_manager.update_token_stats = wrapped_update_stats

            # Re-register the callback to use the wrapped method
            # (The callback was set before wrapping in main_solver.py)
            if hasattr(solver, "token_tracker") and solver.token_tracker:
                solver.token_tracker.set_on_usage_added_callback(wrapped_update_stats)

        def send_progress_update(stage: str, progress: dict[str, Any]):
            """Send progress update to frontend"""
            try:
                log_queue.put_nowait({"type": "progress", "stage": stage, "progress": progress})
            except Exception:
                pass

        solver._send_progress_update = send_progress_update

        # 5. Background task to push logs to WebSocket
        pusher_task = asyncio.create_task(log_pusher())

        # 6. Run Solver within the LogInterceptor context
        interceptor = LogInterceptor(target_logger, log_queue)
        with interceptor:
            await safe_send_json({"type": "status", "content": "started"})

            if display_manager:
                await safe_send_json(
                    {
                        "type": "agent_status",
                        "agent": "all",
                        "status": "initial",
                        "all_agents": display_manager.agents_status.copy(),
                    }
                )
                await safe_send_json({"type": "token_stats", "stats": display_manager.stats.copy()})

            logger.progress(f"[{task_id}] Solving started")

            result = await solver.solve(question, verbose=True)

            logger.success(f"[{task_id}] Solving completed")
            task_manager.update_task_status(task_id, "completed")

            # Process Markdown content to fix image paths
            final_answer = result.get("final_answer", "")
            output_dir_str = result.get("output_dir", "")

            if output_dir_str and final_answer:
                try:
                    output_dir = Path(output_dir_str)

                    if not output_dir.is_absolute():
                        output_dir = output_dir.resolve()

                    path_str = str(output_dir).replace("\\", "/")
                    parts = path_str.split("/")

                    if "user" in parts:
                        idx = parts.index("user")
                        rel_path = "/".join(parts[idx + 1 :])
                        base_url = f"/api/outputs/{rel_path}"

                        pattern = r"\]\(artifacts/([^)]+)\)"
                        replacement = rf"]({base_url}/artifacts/\1)"
                        final_answer = re.sub(pattern, replacement, final_answer)
                except Exception as e:
                    logger.debug(f"Error processing image paths: {e}")

            # Send final agent status update
            if display_manager:
                final_agent_status = dict.fromkeys(display_manager.agents_status.keys(), "done")
                await safe_send_json(
                    {
                        "type": "agent_status",
                        "agent": "all",
                        "status": "complete",
                        "all_agents": final_agent_status,
                    }
                )

            # Send final result
            # Extract relative path from output_dir for frontend use
            dir_name = ""
            if output_dir_str:
                parts = output_dir_str.replace("\\", "/").split("/")
                dir_name = parts[-1] if parts else ""

            final_res = {
                "type": "result",
                "session_id": session_id,
                "final_answer": final_answer,
                "output_dir": output_dir_str,
                "output_dir_name": dir_name,
                "metadata": result.get("metadata"),
            }
            await safe_send_json(final_res)

            # Save assistant message to session
            if session_id:
                solver_session_manager.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=final_answer,
                    output_dir=dir_name,
                )
                # Update token stats in session
                if display_manager:
                    solver_session_manager.update_token_stats(
                        session_id=session_id,
                        token_stats=display_manager.stats.copy(),
                    )

            # Save to history
            history_manager.add_entry(
                activity_type=ActivityType.SOLVE,
                title=question[:50] + "..." if len(question) > 50 else question,
                content={
                    "question": question,
                    "answer": result.get("final_answer"),
                    "kb_name": kb_name,
                    "session_id": session_id,
                },
                summary=(
                    result.get("final_answer")[:100] + "..." if result.get("final_answer") else ""
                ),
            )

    except Exception as e:
        # Mark connection as closed before sending error (to prevent log_pusher from interfering)
        connection_closed.set()
        await safe_send_json({"type": "error", "content": str(e)})
        logger.error(f"[{task_id if 'task_id' in locals() else 'unknown'}] Solving failed: {e}")
        if "task_id" in locals():
            task_manager.update_task_status(task_id, "error", error=str(e))
    finally:
        # Stop log pusher first
        connection_closed.set()
        if pusher_task:
            pusher_task.cancel()
            try:
                await pusher_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"Error waiting for pusher task: {e}")

        # Close WebSocket connection
        try:
            # Check if connection is still open before closing
            if hasattr(websocket, "client_state"):
                state = websocket.client_state
                if hasattr(state, "name") and state.name != "DISCONNECTED":
                    await websocket.close()
            else:
                # Fallback: try to close anyway
                await websocket.close()
        except (WebSocketDisconnect, RuntimeError, ConnectionError):
            # Connection already closed, ignore
            pass
        except Exception as e:
            logger.debug(f"Error closing WebSocket: {e}")
