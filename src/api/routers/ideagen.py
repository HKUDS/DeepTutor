"""
IdeaGen API Router
Used to generate research ideas from notebook content
"""

from datetime import datetime
from pathlib import Path
import sys

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

# Ensure project modules can be imported
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.agents.base_agent import BaseAgent
from src.agents.ideagen.idea_generation_workflow import IdeaGenerationWorkflow
from src.agents.ideagen.material_organizer_agent import MaterialOrganizerAgent
from src.api.utils.notebook_manager import NotebookManager
from src.api.utils.task_id_manager import TaskIDManager
from src.logging import get_logger
from src.services.config import load_config_with_main
from src.services.llm import get_llm_config

router = APIRouter()

# Initialize logger with config
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)  # Use any config to get main.yaml
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("IdeaGen", level="INFO", log_dir=log_dir)


class IdeaGenRequest(BaseModel):
    notebook_id: str
    record_ids: list[str] | None = None  # If None, use all records


# Define status constants to make state flow clearer
class IdeaGenStage:
    """IdeaGen status stages"""

    INIT = "init"  # Initialization
    EXTRACTING = "extracting"  # Extracting knowledge points
    KNOWLEDGE_EXTRACTED = "knowledge_extracted"  # Knowledge points extraction completed
    FILTERING = "filtering"  # Loose filtering
    FILTERED = "filtered"  # Filtering completed
    EXPLORING = "exploring"  # Exploring research ideas
    EXPLORED = "explored"  # Exploration completed
    STRICT_FILTERING = "strict_filtering"  # Strict filtering
    GENERATING = "generating"  # Generating statement
    IDEA_READY = "idea_ready"  # Single idea ready
    COMPLETE = "complete"  # All completed
    ERROR = "error"  # Error


async def send_status(
    websocket: WebSocket, stage: str, message: str, data: dict = None, task_id: str = None
):
    """Unified status sending function"""
    payload = {
        "type": "status",
        "stage": stage,
        "message": message,
        "timestamp": datetime.now().isoformat(),
    }
    if data:
        payload["data"] = data

    await websocket.send_json(payload)

    # Log to file
    log_msg = f"[{stage}] {message}"
    if task_id:
        log_msg = f"[{task_id}] {log_msg}"
    logger.info(log_msg)


@router.websocket("/generate")
async def websocket_ideagen(websocket: WebSocket):
    """
    WebSocket endpoint: Execute idea generation workflow

    Status flow:
    1. init -> Initialization
    2. extracting -> Extract knowledge points
    3. knowledge_extracted -> Knowledge points extraction completed
    4. filtering -> Loose filtering
    5. filtered -> Filtering completed
    6. exploring -> Explore research ideas (loop)
    7. explored -> Exploration completed
    8. strict_filtering -> Strict filtering
    9. generating -> Generate statement
    10. idea_ready -> Single idea ready
    11. complete -> All completed

    Request format:
    {
        "notebook_id": "string",        // Optional, single notebook mode
        "record_ids": ["id1", "id2"],   // Optional, specify specific records
        "records": [...],               // Optional, cross-notebook mode directly provide records
        "user_thoughts": "string"       // Optional, user additional thoughts
    }
    """
    await websocket.accept()
    logger.info("=" * 60)
    logger.info("WebSocket connection accepted")
    logger.info("=" * 60)

    # Get task ID manager
    task_manager = TaskIDManager.get_instance()
    task_id = None

    try:
        # Receive request data
        data = await websocket.receive_json()
        notebook_id = data.get("notebook_id")
        record_ids = data.get("record_ids")
        direct_records = data.get("records")
        user_thoughts = data.get("user_thoughts", "")

        logger.info(
            f"Received request: notebook_id={notebook_id}, record_ids={record_ids}, direct_records_count={len(direct_records) if direct_records else 0}"
        )

        # Generate task ID
        task_key = (
            f"ideagen_{notebook_id or 'cross_notebook'}_{hash(str(direct_records or record_ids))}"
        )
        task_id = task_manager.generate_task_id("ideagen", task_key)

        # Send task ID to frontend
        await websocket.send_json({"type": "task_id", "task_id": task_id})
        logger.info(f"Task ID: {task_id}")

        # ========== Stage 1: INIT ==========
        await send_status(
            websocket,
            IdeaGenStage.INIT,
            "Initializing idea generation workflow...",
            task_id=task_id,
        )

        # Reset LLM stats for this session
        BaseAgent.reset_stats("ideagen")

        # Get LLM configuration
        llm_config = get_llm_config()

        # Get records
        records = []

        if direct_records and isinstance(direct_records, list):
            records = direct_records
            logger.info(f"Using {len(records)} direct records")
        elif notebook_id:
            nb_manager = NotebookManager()
            notebook = nb_manager.get_notebook(notebook_id)
            if not notebook:
                await send_status(
                    websocket, IdeaGenStage.ERROR, "Notebook not found", task_id=task_id
                )
                await websocket.close()
                return

            records = notebook.get("records", [])
            if record_ids:
                records = [r for r in records if r.get("id") in record_ids]
            logger.info(f"Loaded {len(records)} records from notebook")

        # Check if we have either records or user_thoughts
        if not records and not user_thoughts:
            await send_status(
                websocket,
                IdeaGenStage.ERROR,
                "Please provide notebook records or describe your research topic",
                task_id=task_id,
            )
            await websocket.close()
            return

        # ========== Stage 2: EXTRACTING ==========
        # If we have records, extract knowledge points from them
        # If only user_thoughts, create a virtual knowledge point from the text
        if records:
            await send_status(
                websocket,
                IdeaGenStage.EXTRACTING,
                f"Extracting knowledge points from {len(records)} records...",
                {"record_count": len(records)},
                task_id=task_id,
            )

            organizer = MaterialOrganizerAgent(
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                api_version=getattr(llm_config, "api_version", None),
                model=llm_config.model,
            )

            knowledge_points = await organizer.process(
                records, user_thoughts if user_thoughts else None
            )
            logger.info(f"Extracted {len(knowledge_points)} knowledge points")
        else:
            # Text-only mode: create virtual knowledge point from user_thoughts
            await send_status(
                websocket,
                IdeaGenStage.EXTRACTING,
                "Processing your research topic description...",
                {"record_count": 0, "text_only_mode": True},
                task_id=task_id,
            )

            # Create a virtual knowledge point from user_thoughts
            knowledge_points = [
                {
                    "knowledge_point": "User Research Topic",
                    "description": user_thoughts.strip(),
                }
            ]
            logger.info("Created virtual knowledge point from user thoughts (text-only mode)")

        # ========== Stage 3: KNOWLEDGE_EXTRACTED ==========
        await send_status(
            websocket,
            IdeaGenStage.KNOWLEDGE_EXTRACTED,
            f"Extracted {len(knowledge_points)} knowledge points",
            {"knowledge_points": knowledge_points, "count": len(knowledge_points)},
            task_id=task_id,
        )

        if not knowledge_points:
            await send_status(
                websocket,
                IdeaGenStage.COMPLETE,
                "No valid knowledge points extracted from notes",
                {"ideas": [], "count": 0},
                task_id=task_id,
            )
            await websocket.close()
            return

        # ========== Stage 4: FILTERING (Loose Filter) ==========
        await send_status(
            websocket,
            IdeaGenStage.FILTERING,
            f"Filtering {len(knowledge_points)} knowledge points (loose criteria)...",
            {"total": len(knowledge_points)},
            task_id=task_id,
        )

        workflow = IdeaGenerationWorkflow(
            api_key=llm_config.api_key,
            base_url=llm_config.base_url,
            api_version=getattr(llm_config, "api_version", None),
            model=llm_config.model,
            progress_callback=None,  # We manually manage status here
        )

        filtered_points = await workflow.loose_filter(knowledge_points)
        logger.info(
            f"Loose filter: {len(knowledge_points)} -> {len(filtered_points)} knowledge points"
        )

        # ========== Stage 5: FILTERED ==========
        await send_status(
            websocket,
            IdeaGenStage.FILTERED,
            f"Filtered to {len(filtered_points)} knowledge points",
            {
                "filtered_points": filtered_points,
                "original": len(knowledge_points),
                "filtered": len(filtered_points),
            },
            task_id=task_id,
        )

        if not filtered_points:
            await send_status(
                websocket,
                IdeaGenStage.COMPLETE,
                "All knowledge points were filtered out",
                {"ideas": [], "count": 0},
                task_id=task_id,
            )
            await websocket.close()
            return

        # ========== Stage 6-10: Process each knowledge point ==========
        all_ideas = []
        total_points = len(filtered_points)

        for idx, point in enumerate(filtered_points):
            point_name = point.get("knowledge_point", f"Point {idx + 1}")
            logger.info(f"Processing knowledge point {idx + 1}/{total_points}: {point_name}")

            # ========== Stage 6: EXPLORING ==========
            await send_status(
                websocket,
                IdeaGenStage.EXPLORING,
                f"Exploring research ideas for: {point_name} ({idx + 1}/{total_points})",
                {"index": idx + 1, "total": total_points, "knowledge_point": point_name},
                task_id=task_id,
            )

            research_ideas = await workflow.explore_ideas(point)
            logger.info(f"Generated {len(research_ideas)} research ideas")

            # ========== Stage 7: EXPLORED ==========
            await send_status(
                websocket,
                IdeaGenStage.EXPLORED,
                f"Generated {len(research_ideas)} research ideas for: {point_name}",
                {
                    "index": idx + 1,
                    "ideas_count": len(research_ideas),
                    "knowledge_point": point_name,
                },
                task_id=task_id,
            )

            if not research_ideas:
                logger.warning("No ideas generated, skipping")
                continue

            # ========== Stage 8: STRICT_FILTERING ==========
            await send_status(
                websocket,
                IdeaGenStage.STRICT_FILTERING,
                f"Strictly filtering {len(research_ideas)} ideas for: {point_name}",
                {
                    "index": idx + 1,
                    "ideas_count": len(research_ideas),
                    "knowledge_point": point_name,
                },
                task_id=task_id,
            )

            kept_ideas = await workflow.strict_filter(point, research_ideas)
            logger.info(f"Kept {len(kept_ideas)} ideas after strict filter")

            if not kept_ideas:
                logger.warning("No ideas kept, skipping")
                continue

            # ========== Stage 9: GENERATING ==========
            await send_status(
                websocket,
                IdeaGenStage.GENERATING,
                f"Generating statement for: {point_name}",
                {"index": idx + 1, "kept_ideas": len(kept_ideas), "knowledge_point": point_name},
                task_id=task_id,
            )

            statement = await workflow.generate_statement(point, kept_ideas)
            logger.info(f"Statement generated ({len(statement)} chars)")

            idea_result = {
                "id": f"idea-{idx}",
                "knowledge_point": point_name,
                "description": point.get("description", ""),
                "research_ideas": kept_ideas,
                "statement": statement,
                "expanded": False,
            }
            all_ideas.append(idea_result)

            # ========== Stage 10: IDEA_READY ==========
            # Send status message
            await send_status(
                websocket,
                IdeaGenStage.IDEA_READY,
                f"Research idea ready: {point_name}",
                {"index": idx + 1, "total": total_points},
                task_id=task_id,
            )

            # Important: Also send type="idea" message, frontend needs this to render ideas
            await websocket.send_json({"type": "idea", "data": idea_result})
            logger.info(f"Sent idea to frontend: {point_name}")

        # ========== Stage 11: COMPLETE ==========
        logger.success(
            f"Workflow complete: generated {len(all_ideas)} ideas from {total_points} knowledge points"
        )
        await send_status(
            websocket,
            IdeaGenStage.COMPLETE,
            f"Successfully generated {len(all_ideas)} research ideas",
            {"ideas": all_ideas, "count": len(all_ideas)},
            task_id=task_id,
        )

        # Print LLM usage stats
        BaseAgent.print_stats("ideagen")

        # Update task status
        task_manager.update_task_status(task_id, "completed")
        logger.success(f"Task {task_id} completed")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected (task_id={task_id})")
    except Exception as e:
        logger.error(f"ERROR: {e}")

        logger.exception("Exception details:")

        if task_id:
            task_manager.update_task_status(task_id, "error", error=str(e))

        try:
            # Send unified error message via send_status
            # Note: send_status sends {"type": "status", "stage": "error", ...}
            # which is the standard format for this WebSocket protocol
            await send_status(
                websocket,
                IdeaGenStage.ERROR,
                f"Error: {e!s}",
                {"error": str(e)},
                task_id=task_id,
            )
        except (RuntimeError, WebSocketDisconnect, ConnectionError):
            pass  # Connection already closed
    finally:
        try:
            await websocket.close()
            logger.info("WebSocket closed")
        except (RuntimeError, WebSocketDisconnect, ConnectionError):
            pass  # Connection already closed
        logger.info("=" * 60)


@router.get("/test")
async def test_ideagen():
    """Test endpoint"""
    return {"status": "ok", "message": "IdeaGen API is working"}
