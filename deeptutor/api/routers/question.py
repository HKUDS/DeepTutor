import asyncio
import base64
from datetime import datetime
import logging
from pathlib import Path
import re
import sys
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from deeptutor.agents.question import AgentCoordinator
from deeptutor.api.utils.task_id_manager import TaskIDManager
from deeptutor.logging import (
    ProcessLogEvent,
    bind_log_context,
    capture_process_logs,
    current_log_context,
)
from deeptutor.services.config import PROJECT_ROOT, load_config_with_main
from deeptutor.services.llm.config import get_llm_config
from deeptutor.services.path_service import get_path_service
from deeptutor.services.settings.interface_settings import get_ui_language
from deeptutor.tools.question import mimic_exam_questions
from deeptutor.utils.document_validator import DocumentValidator
from deeptutor.utils.error_utils import format_exception_message

# Setup module logger with unified logging system (from config)
config = load_config_with_main("main.yaml", PROJECT_ROOT)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = logging.getLogger(__name__)

router = APIRouter()


def _mimic_output_dir():
    # Resolved per-call so a per-user PathService (set after auth) routes
    # generated mimic papers under the caller's own workspace instead of
    # admin's directory frozen at import time.
    return get_path_service().get_question_dir() / "mimic_papers"


@router.websocket("/mimic")
async def websocket_mimic_generate(websocket: WebSocket):
    """
    WebSocket endpoint for mimic exam paper question generation.

    Supports two modes:
    1. Upload PDF directly via WebSocket (base64 encoded)
    2. Use a pre-parsed paper directory path

    Message format for PDF upload:
    {
        "mode": "upload",
        "pdf_data": "base64_encoded_pdf_content",
        "pdf_name": "exam.pdf",
        "kb_name": "knowledge_base_name",
        "max_questions": 5  // optional
    }

    Message format for pre-parsed:
    {
        "mode": "parsed",
        "paper_path": "directory_name",
        "kb_name": "knowledge_base_name",
        "max_questions": 5  // optional
    }
    """
    await websocket.accept()

    pusher_task = None
    original_stdout = sys.stdout

    try:
        # 1. Wait for config
        data = await websocket.receive_json()
        mode = data.get("mode", "parsed")  # "upload" or "parsed"
        kb_name = data.get("kb_name", "ai_textbook")
        max_questions = data.get("max_questions")

        logger.info(f"Starting mimic generation (mode: {mode}, kb: {kb_name})")

        # 2. Setup Log Queue
        log_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        task_id = f"question_mimic_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        def emit_process_log(event: ProcessLogEvent) -> None:
            loop.call_soon_threadsafe(log_queue.put_nowait, event.to_dict())

        async def log_pusher():
            while True:
                entry = await log_queue.get()
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
                log_queue.task_done()

        pusher_task = asyncio.create_task(log_pusher())

        # 3. Stdout interceptor for capturing prints
        # ANSI escape sequence pattern for stripping color codes
        ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

        class StdoutInterceptor:
            def __init__(self, queue, original):
                self.queue = queue
                self.original_stdout = original
                self._closed = False

            def write(self, message):
                if self._closed:
                    return
                # Write to terminal first (with ANSI codes for color)
                try:
                    self.original_stdout.write(message)
                except Exception:
                    pass
                # Strip ANSI escape codes before sending to frontend
                clean_message = ANSI_ESCAPE_PATTERN.sub("", message).strip()
                # Then send to frontend (non-blocking)
                if clean_message:
                    try:
                        event = ProcessLogEvent(
                            level="INFO",
                            message=clean_message,
                            logger="deeptutor.question.stdout",
                            timestamp=datetime.now().timestamp(),
                            context=current_log_context(),
                        )
                        self.queue.put_nowait(event.to_dict())
                    except (asyncio.QueueFull, RuntimeError):
                        pass

            def flush(self):
                if not self._closed:
                    try:
                        self.original_stdout.flush()
                    except Exception:
                        pass

            def close(self):
                """Mark interceptor as closed to prevent further writes."""
                self._closed = True

        interceptor = StdoutInterceptor(log_queue, original_stdout)
        sys.stdout = interceptor

        try:
            await websocket.send_json(
                {"type": "status", "stage": "init", "content": "Initializing..."}
            )

            pdf_path = None
            paper_dir = None

            # Handle PDF upload mode
            if mode == "upload":
                pdf_data = data.get("pdf_data")
                pdf_name = data.get("pdf_name", "exam.pdf")

                if not pdf_data:
                    await websocket.send_json(
                        {"type": "error", "content": "PDF data is required for upload mode"}
                    )
                    return

                # Decode PDF data first to check size
                try:
                    pdf_bytes = base64.b64decode(pdf_data)
                except Exception as e:
                    await websocket.send_json(
                        {"type": "error", "content": f"Invalid base64 PDF data: {e}"}
                    )
                    return

                # Pre-validate filename and file size before writing
                try:
                    safe_name = DocumentValidator.validate_upload_safety(
                        pdf_name, len(pdf_bytes), {".pdf"}
                    )
                except ValueError as e:
                    await websocket.send_json({"type": "error", "content": str(e)})
                    return

                # Create batch directory for this mimic session
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                pdf_stem = Path(safe_name).stem
                batch_dir = _mimic_output_dir() / f"mimic_{timestamp}_{pdf_stem}"
                batch_dir.mkdir(parents=True, exist_ok=True)

                # Save uploaded PDF in batch directory
                pdf_path = batch_dir / safe_name

                await websocket.send_json(
                    {"type": "status", "stage": "upload", "content": f"Saving PDF: {safe_name}"}
                )

                # Write the validated PDF bytes
                with open(pdf_path, "wb") as f:
                    f.write(pdf_bytes)

                # Additional validation (file readability, etc.)
                try:
                    DocumentValidator.validate_file(pdf_path)
                except (ValueError, FileNotFoundError, PermissionError) as e:
                    # Clean up invalid or inaccessible file
                    pdf_path.unlink(missing_ok=True)
                    await websocket.send_json({"type": "error", "content": str(e)})
                    return

                await websocket.send_json(
                    {
                        "type": "status",
                        "stage": "parsing",
                        "content": "Parsing PDF exam paper (MinerU)...",
                    }
                )
                logger.info(f"Saved and validated uploaded PDF to: {pdf_path}")

                # Pass batch_dir as output directory
                pdf_path = str(pdf_path)
                output_dir = str(batch_dir)

            elif mode == "parsed":
                paper_path = data.get("paper_path")
                if not paper_path:
                    await websocket.send_json(
                        {"type": "error", "content": "paper_path is required for parsed mode"}
                    )
                    return
                paper_dir = paper_path

                # Create batch directory for parsed mode too
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                batch_dir = _mimic_output_dir() / f"mimic_{timestamp}_{Path(paper_path).name}"
                batch_dir.mkdir(parents=True, exist_ok=True)
                output_dir = str(batch_dir)

            else:
                await websocket.send_json({"type": "error", "content": f"Unknown mode: {mode}"})
                return

            # Create WebSocket callback for real-time progress updates
            async def ws_callback(event_type: str, data: dict):
                """Send progress updates to the frontend via WebSocket."""
                try:
                    message = {"type": event_type, **data}
                    await websocket.send_json(message)
                except Exception as e:
                    logger.debug(f"WebSocket send failed: {e}")

            # Run the complete mimic workflow with callback
            await websocket.send_json(
                {
                    "type": "status",
                    "stage": "processing",
                    "content": "Executing question generation workflow...",
                }
            )

            with bind_log_context(task_id=task_id, capability="deep_question", sink="ui"):
                with capture_process_logs(emit_process_log, task_id=task_id):
                    result = await mimic_exam_questions(
                        pdf_path=pdf_path,
                        paper_dir=paper_dir,
                        kb_name=kb_name,
                        output_dir=output_dir,
                        max_questions=max_questions,
                        ws_callback=ws_callback,
                    )

            if result.get("success"):
                # Results are already sent via ws_callback during generation
                # Just send the final complete signal
                total_ref = result.get("total_reference_questions", 0)
                generated = result.get("generated_questions", [])
                failed = result.get("failed_questions", [])

                logger.info(
                    f"Mimic generation complete: {len(generated)} succeeded, {len(failed)} failed"
                )

                try:
                    await websocket.send_json({"type": "complete"})
                except (RuntimeError, WebSocketDisconnect):
                    logger.debug("WebSocket closed before complete signal could be sent")
            else:
                error_msg = result.get("error", "Unknown error")
                try:
                    await websocket.send_json({"type": "error", "content": error_msg})
                except (RuntimeError, WebSocketDisconnect):
                    pass
                logger.error(f"Mimic generation failed: {error_msg}")

        finally:
            # Close interceptor and restore stdout
            if "interceptor" in locals():
                interceptor.close()
            sys.stdout = original_stdout

    except WebSocketDisconnect:
        logger.debug("Client disconnected during mimic generation")
    except Exception as e:
        logger.exception("Mimic generation error")
        error_msg = format_exception_message(e)
        try:
            await websocket.send_json({"type": "error", "content": error_msg})
        except Exception:
            pass
    finally:
        # Ensure stdout is always restored
        sys.stdout = original_stdout

        # Clean up pusher task
        if pusher_task:
            try:
                pusher_task.cancel()
                await pusher_task
            except asyncio.CancelledError:
                pass  # Expected when cancelling
            except Exception:
                pass

        # Drain any remaining items in the queue
        try:
            while not log_queue.empty():
                log_queue.get_nowait()
        except Exception:
            pass

        # Close WebSocket
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/generate")
async def websocket_question_generate(websocket: WebSocket):
    await websocket.accept()

    # Get task ID manager
    task_manager = TaskIDManager.get_instance()

    try:
        # 1. Wait for config
        data = await websocket.receive_json()
        requirement = data.get("requirement")
        kb_name = data.get("kb_name", "ai_textbook")
        count = data.get("count", 1)

        if not requirement:
            try:
                await websocket.send_json({"type": "error", "content": "Requirement is required"})
            except (RuntimeError, WebSocketDisconnect):
                pass
            return

        # Generate task ID
        task_key = f"question_{kb_name}_{hash(str(requirement))}"
        task_id = task_manager.generate_task_id("question_gen", task_key)

        # Send task ID to frontend
        try:
            await websocket.send_json({"type": "task_id", "task_id": task_id})
        except (RuntimeError, WebSocketDisconnect):
            logger.debug("WebSocket closed, cannot send task_id")
            return

        logger.info(
            f"[{task_id}] Starting question generation: {requirement.get('knowledge_point', 'Unknown')}"
        )

        # 2. Initialize Coordinator
        path_service = get_path_service()
        output_base = path_service.get_question_batch_dir(task_id)

        try:
            llm_config = get_llm_config()
            api_key = llm_config.api_key
            base_url = llm_config.base_url
            api_version = getattr(llm_config, "api_version", None)
        except Exception:
            api_key = None
            base_url = None
            api_version = None

        coordinator = AgentCoordinator(
            api_key=api_key,
            base_url=base_url,
            api_version=api_version,
            kb_name=kb_name,
            language=get_ui_language(default=config.get("system", {}).get("language", "en")),
            output_dir=str(output_base),
        )

        # 3. Setup Log Queue for WebSocket streaming
        log_queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def emit_process_log(event: ProcessLogEvent) -> None:
            loop.call_soon_threadsafe(log_queue.put_nowait, event.to_dict())

        # WebSocket callback for coordinator to send structured updates
        async def ws_callback(data: dict):
            try:
                await log_queue.put(data)
            except Exception:
                pass

        coordinator.set_ws_callback(ws_callback)

        # 4. Define background pusher for logs
        async def log_pusher():
            while True:
                entry = await log_queue.get()
                try:
                    await websocket.send_json(entry)
                except Exception:
                    break
                log_queue.task_done()

        pusher_task = asyncio.create_task(log_pusher())

        # 5. Run generation while streaming logs bound to this task.
        try:
            with bind_log_context(task_id=task_id, capability="deep_question", sink="ui"):
                with capture_process_logs(emit_process_log, task_id=task_id):
                    try:
                        await websocket.send_json({"type": "status", "content": "started"})
                    except (RuntimeError, WebSocketDisconnect):
                        logger.debug("WebSocket closed, stopping question generation")
                        return

                    # Extract fields from requirement dict
                    user_topic = (
                        requirement.get("knowledge_point", "")
                        if isinstance(requirement, dict)
                        else str(requirement)
                    )
                    preference = (
                        requirement.get("preference", "") if isinstance(requirement, dict) else ""
                    )
                    difficulty = (
                        requirement.get("difficulty", "") if isinstance(requirement, dict) else ""
                    )
                    question_type = (
                        requirement.get("question_type", "")
                        if isinstance(requirement, dict)
                        else ""
                    )

                    logger.info(
                        f"Starting question generation for {count} question(s), topic: {user_topic}"
                    )

                    batch_result = await coordinator.generate_from_topic(
                        user_topic=user_topic,
                        preference=preference,
                        num_questions=count,
                        difficulty=difficulty,
                        question_type=question_type,
                    )

                    # Send batch summary
                    try:
                        await websocket.send_json(
                            {
                                "type": "batch_summary",
                                "requested": count,
                                "completed": batch_result.get("completed", 0),
                                "failed": batch_result.get("failed", 0),
                            }
                        )
                    except (RuntimeError, WebSocketDisconnect):
                        pass

                    if not batch_result.get("success"):
                        logger.warning(
                            f"Question generation had failures: {batch_result.get('failed', 0)} failed"
                        )

                    # Wait for any pending messages in the queue to be sent
                    # Give the pusher a moment to process remaining messages
                    await asyncio.sleep(0.1)
                    while not log_queue.empty():
                        await asyncio.sleep(0.05)

                    # Send complete signal
                    try:
                        await websocket.send_json({"type": "complete"})
                        logger.info(f"[{task_id}] Question generation completed")
                        task_manager.update_task_status(task_id, "completed")
                    except (RuntimeError, WebSocketDisconnect):
                        logger.debug("WebSocket closed, cannot send complete signal")

        except Exception as e:
            error_msg = format_exception_message(e)
            error_traceback = traceback.format_exc()
            logger.error(f"Question generation error: {error_msg}")
            logger.error(f"Error traceback:\n{error_traceback}")

            # Log additional context if available
            try:
                context_result = locals().get("batch_result")
                if context_result is not None:
                    logger.error(
                        f"Result type: {type(context_result)}, result keys: {context_result.keys() if isinstance(context_result, dict) else 'N/A'}"
                    )
                    if isinstance(context_result, dict) and "validation" in context_result:
                        validation = context_result["validation"]
                        logger.error(f"Validation type: {type(validation)}")
                        if isinstance(validation, dict):
                            logger.error(f"Validation keys: {validation.keys()}")
                            logger.error(
                                f"Issues type: {type(validation.get('issues'))}, value: {validation.get('issues')}"
                            )
                            logger.error(
                                f"Suggestions type: {type(validation.get('suggestions'))}, value: {validation.get('suggestions')}"
                            )
            except Exception as context_error:
                logger.warning(f"Failed to log error context: {context_error}")

            try:
                await websocket.send_json({"type": "error", "content": error_msg})
            except (RuntimeError, WebSocketDisconnect):
                logger.debug("WebSocket closed, cannot send error message")
            task_manager.update_task_status(task_id, "error", error=error_msg)

        finally:
            pusher_task.cancel()
            try:
                await pusher_task
            except asyncio.CancelledError:
                pass
            await websocket.close()

    except WebSocketDisconnect:
        logger.debug("Client disconnected")
    except Exception as e:
        error_msg = format_exception_message(e)
        logger.error(f"WebSocket error: {error_msg}")
