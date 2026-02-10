import asyncio
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path
import sys
import time
import traceback
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, WebSocket
from pydantic import BaseModel

from src.agents.research.agents import RephraseAgent
from src.agents.research.research_pipeline import ResearchPipeline
from src.api.utils.history import ActivityType, history_manager
from src.api.utils.notebook_manager import notebook_manager
from src.api.utils.task_id_manager import TaskIDManager
from src.logging import get_logger
from src.services.config import get_banana_ppt_config, get_ppt_config, load_config_with_main
from src.services.export.banana_ppt_service import BananaPptService
from src.services.export.pdf_generator import PDFGenerator

# Import the new PPTGenerator service
from src.services.export.ppt_generator import PPTGenerator
from src.services.export.source_report import SourceReportGenerator
from src.services.llm import get_llm_config

# Force stdout to use utf-8 to prevent encoding errors with emojis on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

router = APIRouter()


# Helper to load config (with main.yaml merge)
def load_config():
    project_root = Path(__file__).parent.parent.parent.parent
    return load_config_with_main("research_config.yaml", project_root)


def _read_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _file_sha256(path: Path) -> str | None:
    try:
        data = path.read_bytes()
        return hashlib.sha256(data).hexdigest()
    except Exception:
        return None


def _get_latest_event(progress: dict | None) -> dict | None:
    if not progress:
        return None
    events = progress.get("events") or []
    if not events:
        return None
    return events[-1]


def _persist_research_session(
    notebook_id: str | None,
    session_id: str | None,
    report_content: str,
    topic: str,
    metadata: dict | None = None,
) -> None:
    if not notebook_id or not session_id:
        return
    try:
        sessions = notebook_manager.list_sessions(notebook_id)
        existing = next((s for s in sessions if s.get("session_id") == session_id), None)
        if not existing:
            return
        updated = dict(existing)
        updated["research_report"] = report_content
        updated["research_state"] = None
        updated["updated_at"] = time.time()
        sources = list(updated.get("sources", []) or [])

        def source_key(item: dict) -> str:
            return f"{item.get('type')}-{item.get('url') or item.get('title') or item.get('id') or ''}"

        existing_keys = {source_key(s) for s in sources}

        def add_source(item: dict) -> None:
            key = source_key(item)
            if key in existing_keys:
                return
            existing_keys.add(key)
            sources.append(item)

        if report_content:
            title = f"深度研究报告 - {topic}" if topic else "深度研究报告"
            sources = [s for s in sources if s.get("type") != "report"]
            existing_keys = {source_key(s) for s in sources}
            add_source(
                {
                    "id": f"report-{int(time.time() * 1000)}",
                    "type": "report",
                    "title": title,
                    "selected": True,
                    "content": report_content,
                }
            )

        if metadata:
            web_sources = metadata.get("web_sources") or []
            for idx, source in enumerate(web_sources):
                add_source(
                    {
                        "id": f"research-web-{int(time.time() * 1000)}-{idx}",
                        "type": "web",
                        "title": source.get("title") or source.get("url") or f"网络来源 {idx + 1}",
                        "url": source.get("url") or "",
                        "content": source.get("content") or source.get("snippet") or "",
                        "selected": True,
                    }
                )

            rag_sources = metadata.get("rag_sources") or []
            for idx, source in enumerate(rag_sources):
                add_source(
                    {
                        "id": f"research-rag-{int(time.time() * 1000)}-{idx}",
                        "type": "kb",
                        "title": source.get("title")
                        or source.get("source")
                        or source.get("source_file")
                        or source.get("kb_name")
                        or f"知识库来源 {idx + 1}",
                        "url": source.get("url") or "",
                        "content": source.get("content") or source.get("content_preview") or "",
                        "selected": True,
                    }
                )

            misc_sources = metadata.get("sources") or []
            for idx, source in enumerate(misc_sources):
                add_source(
                    {
                        "id": source.get("id") or f"research-src-{int(time.time() * 1000)}-{idx}",
                        "type": source.get("type") or "web",
                        "title": source.get("title") or source.get("url") or f"来源 {idx + 1}",
                        "url": source.get("url") or "",
                        "content": source.get("content") or source.get("snippet") or "",
                        "selected": True,
                    }
                )

        updated["sources"] = sources
        notebook_manager.upsert_session(notebook_id, updated)
    except Exception as exc:
        logger.warning(f"Failed to persist research session: {exc}")


# Initialize logger with config
config = load_config()
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("ResearchAPI", log_dir=log_dir)


class OptimizeRequest(BaseModel):
    topic: str
    iteration: int = 0
    previous_result: dict[str, Any] | None = None
    kb_name: str | None = "ai_textbook"


class ExportPptxRequest(BaseModel):
    markdown: str
    title: str | None = None
    max_slides: int = 15
    style_prompt: str | None = None
    style_model: str | None = None
    style_api_key: str | None = None
    style_base_url: str | None = None
    template_name: str | None = None


class ExportPdfRequest(BaseModel):
    markdown: str
    title: str | None = None


class SourceItem(BaseModel):
    type: Literal["web", "kb", "file", "report"]
    title: str
    url: str | None = None
    content: str | None = None


class ComposeFromSourcesRequest(BaseModel):
    sources: list[SourceItem]
    topic: str | None = None


class PptStyleFromSourcesRequest(BaseModel):
    sources: list[SourceItem]
    topic: str | None = None


class PptStylePreviewRequest(BaseModel):
    style_prompt: str | None = None


class BananaPptOutlineRequest(BaseModel):
    source_content: str
    style_prompt: str | None = None
    max_slides: int | None = None


class BananaPptImageRequest(BaseModel):
    prompt: str


@router.post("/export_pptx")
async def export_pptx(request: ExportPptxRequest):
    project_root = Path(__file__).parent.parent.parent.parent
    export_dir = project_root / "data" / "user" / "research" / "exports"
    template_dir = project_root / "data" / "user" / "notebook" / "ppt_templates"
    
    # Initialize Generator
    generator = PPTGenerator(export_dir=export_dir)
    
    try:
        template_path = None
        if request.template_name:
            candidate = template_dir / request.template_name
            if not candidate.exists():
                raise HTTPException(status_code=404, detail="Template not found")
            template_path = candidate

        style_prompt = request.style_prompt
        if not template_path:
            ppt_config = get_ppt_config(project_root)
            if not style_prompt:
                style_prompt = ppt_config.default_style_prompt or None

        result = await generator.generate(
            markdown=request.markdown,
            title=request.title,
            style_prompt=style_prompt,
            style_model=request.style_model,
            style_api_key=request.style_api_key,
            style_base_url=request.style_base_url,
            max_slides=request.max_slides,
            template_path=template_path,
        )
        return result
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"PPT export dependencies not installed: {e}",
        )
    except Exception as e:
        logger.error(f"PPT Export failed: {e}")
        # Return generic error
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export_pdf")
async def export_pdf(request: ExportPdfRequest):
    project_root = Path(__file__).parent.parent.parent.parent
    export_dir = project_root / "data" / "user" / "notebook" / "exports"

    generator = PDFGenerator(export_dir=export_dir)

    try:
        result = await generator.generate(
            markdown=request.markdown,
            title=request.title,
        )
        return result
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF export dependencies not installed: {e}",
        )
    except Exception as e:
        logger.error(f"PDF Export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ppt_style_templates")
async def list_ppt_style_templates():
    ppt_config = get_ppt_config(Path(__file__).parent.parent.parent.parent)
    return {"templates": ppt_config.style_templates or []}


@router.post("/compose_from_sources")
async def compose_from_sources(request: ComposeFromSourcesRequest):
    try:
        generator = SourceReportGenerator()
        result = await generator.generate(
            sources=[s.model_dump() for s in request.sources],
            topic=request.topic,
        )
        return result
    except Exception as e:
        logger.error(f"Source report generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ppt_style_from_sources")
async def ppt_style_from_sources(request: PptStyleFromSourcesRequest):
    try:
        generator = SourceReportGenerator()
        result = await generator.generate_style_prompt(
            sources=[s.model_dump() for s in request.sources],
            topic=request.topic,
        )
        return result
    except Exception as e:
        logger.error(f"PPT style generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _theme_rgb(theme: dict, key: str) -> str:
    value = theme.get(key, (0, 0, 0))
    return f"rgb({value[0]}, {value[1]}, {value[2]})"


def _build_ppt_style_preview_svg(theme: dict) -> str:
    background = _theme_rgb(theme, "background")
    accent = _theme_rgb(theme, "accent")
    title = _theme_rgb(theme, "title_color")
    body = _theme_rgb(theme, "body_color")

    return f"""<svg width="640" height="360" viewBox="0 0 640 360" xmlns="http://www.w3.org/2000/svg">
  <rect width="640" height="360" rx="18" fill="{background}" />
  <rect width="640" height="28" fill="{accent}" />
  <text x="40" y="90" font-size="28" font-family="Arial" fill="{title}">Slide Title</text>
  <text x="40" y="140" font-size="16" font-family="Arial" fill="{body}">• Key insight goes here</text>
  <text x="40" y="170" font-size="16" font-family="Arial" fill="{body}">• Supporting detail goes here</text>
  <text x="40" y="200" font-size="16" font-family="Arial" fill="{body}">• Short takeaway goes here</text>
  <rect x="40" y="240" width="220" height="80" rx="12" fill="{accent}" opacity="0.12" />
  <rect x="280" y="240" width="320" height="80" rx="12" fill="{accent}" opacity="0.08" />
</svg>"""


@router.post("/ppt_style_preview")
async def ppt_style_preview(request: PptStylePreviewRequest):
    try:
        project_root = Path(__file__).parent.parent.parent.parent
        generator = PPTGenerator(export_dir=project_root / "data" / "user" / "research" / "exports")

        if request.style_prompt:
            try:
                sample_markdown = "# Preview Title\n\n## Section\n- Point one\n- Point two"
                spec = await generator._generate_ppt_spec(
                    sample_markdown, request.style_prompt, max_slides=5
                )
                theme = generator._parse_theme(spec.get("theme", {})) if spec else generator._parse_theme({})
            except Exception:
                theme = generator._parse_theme({})
        else:
            theme = generator._parse_theme({})

        return {
            "theme": theme,
            "preview_svg": _build_ppt_style_preview_svg(theme),
        }
    except Exception as e:
        logger.error(f"PPT style preview failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ppt_config")
async def get_ppt_config_for_banana():
    project_root = Path(__file__).parent.parent.parent.parent
    config = get_banana_ppt_config(project_root)
    return {
        "enabled": config.enabled,
        "max_slides": config.max_slides,
        "style_templates": config.style_templates,
    }


@router.post("/ppt_outline")
async def generate_ppt_outline(request: BananaPptOutlineRequest):
    project_root = Path(__file__).parent.parent.parent.parent
    config = get_banana_ppt_config(project_root)
    if not config.enabled:
        raise HTTPException(status_code=403, detail="Banana PPT is disabled")

    service = BananaPptService(project_root)
    try:
        return await service.generate_outline(
            source_content=request.source_content,
            style_prompt=request.style_prompt,
            max_slides=request.max_slides,
        )
    except Exception as e:
        logger.error(f"Banana PPT outline failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ppt_image")
async def generate_ppt_image(request: BananaPptImageRequest):
    project_root = Path(__file__).parent.parent.parent.parent
    config = get_banana_ppt_config(project_root)
    if not config.enabled:
        raise HTTPException(status_code=403, detail="Banana PPT is disabled")

    service = BananaPptService(project_root)
    try:
        image_data_url = await service.generate_image(request.prompt)
        return {"image_data_url": image_data_url}
    except Exception as e:
        logger.error(f"Banana PPT image failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ppt_templates")
async def list_ppt_templates():
    project_root = Path(__file__).parent.parent.parent.parent
    template_dir = project_root / "data" / "user" / "notebook" / "ppt_templates"
    template_dir.mkdir(parents=True, exist_ok=True)

    templates = []
    for path in template_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".pptx":
            continue
        stat = path.stat()
        templates.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "download_url": f"/api/outputs/notebook/ppt_templates/{path.name}",
            }
        )

    templates.sort(key=lambda item: item["modified_at"], reverse=True)
    return {"templates": templates}


@router.post("/ppt_templates/upload")
async def upload_ppt_template(file: UploadFile = File(...)):
    project_root = Path(__file__).parent.parent.parent.parent
    template_dir = project_root / "data" / "user" / "notebook" / "ppt_templates"
    template_dir.mkdir(parents=True, exist_ok=True)

    if not file.filename or not file.filename.lower().endswith(".pptx"):
        raise HTTPException(status_code=400, detail="Only .pptx templates are supported")

    safe_name = Path(file.filename).name.replace("/", "_").replace("\\", "_")
    target_path = template_dir / safe_name
    content = await file.read()
    target_path.write_bytes(content)

    return {"success": True, "name": safe_name}


@router.post("/optimize_topic")
async def optimize_topic(request: OptimizeRequest):
    try:
        config = load_config()

        # Inject API keys
        try:
            llm_config = get_llm_config()
            api_key = llm_config.api_key
            base_url = llm_config.base_url
        except Exception as e:
            return {"error": f"LLM config error: {e!s}"}

        # Init Agent
        agent = RephraseAgent(config=config, api_key=api_key, base_url=base_url)

        # Process
        # If iteration > 0, topic is treated as feedback
        if request.iteration == 0:
            result = await agent.process(request.topic, iteration=0)
        else:
            result = await agent.process(
                request.topic, iteration=request.iteration, previous_result=request.previous_result
            )

        return result

    except Exception as e:
        traceback.print_exc()
        return {"error": str(e)}


@router.get("/status/{research_id}")
async def research_status(research_id: str):
    project_root = Path(__file__).parent.parent.parent.parent
    base_dir = project_root / "data" / "user" / "research"
    cache_dir = base_dir / "cache" / research_id
    reports_dir = base_dir / "reports"

    planning = _read_json_file(cache_dir / "planning_progress.json")
    researching = _read_json_file(cache_dir / "researching_progress.json")
    reporting = _read_json_file(cache_dir / "reporting_progress.json")
    queue = _read_json_file(cache_dir / "queue.json")

    report_file = reports_dir / f"{research_id}.md"
    metadata_file = reports_dir / f"{research_id}_metadata.json"
    has_report = report_file.exists()

    if not any([planning, researching, reporting, queue]) and not has_report and not metadata_file.exists():
        raise HTTPException(status_code=404, detail="Research not found")

    report_url = None
    report_size = None
    report_updated_at = None
    report_hash = None
    if has_report:
        report_url = f"/api/outputs/research/reports/{report_file.name}"
        stat = report_file.stat()
        report_size = stat.st_size
        report_updated_at = datetime.fromtimestamp(stat.st_mtime).isoformat()
        report_hash = _file_sha256(report_file)

    metadata = _read_json_file(metadata_file)
    metadata_url = (
        f"/api/outputs/research/reports/{metadata_file.name}" if metadata_file.exists() else None
    )

    stage = "idle"
    if has_report:
        stage = "completed"
    elif reporting and reporting.get("events"):
        stage = "reporting"
    elif researching and researching.get("events"):
        stage = "researching"
    elif planning and planning.get("events"):
        stage = "planning"

    return {
        "research_id": research_id,
        "stage": stage,
        "has_report": has_report,
        "report_url": report_url,
        "report_size": report_size,
        "report_updated_at": report_updated_at,
        "report_hash": report_hash,
        "metadata": metadata,
        "metadata_url": metadata_url,
        "progress": {
            "planning": planning,
            "researching": researching,
            "reporting": reporting,
        },
        "latest_event": {
            "planning": _get_latest_event(planning),
            "researching": _get_latest_event(researching),
            "reporting": _get_latest_event(reporting),
        },
        "queue": queue,
    }


@router.get("/latest")
async def latest_research(topic: str | None = Query(default=None)):
    project_root = Path(__file__).parent.parent.parent.parent
    reports_dir = project_root / "data" / "user" / "research" / "reports"
    if not reports_dir.exists():
        raise HTTPException(status_code=404, detail="No research reports found")

    candidates: list[tuple[float, dict, Path]] = []
    for metadata_file in reports_dir.glob("*_metadata.json"):
        metadata = _read_json_file(metadata_file)
        if not metadata:
            continue
        if topic:
            topic_lower = topic.lower()
            haystack = " ".join(
                [
                    str(metadata.get("topic", "")),
                    str(metadata.get("optimized_topic", "")),
                ]
            ).lower()
            if topic_lower not in haystack:
                continue
        completed_at = metadata.get("completed_at")
        if completed_at:
            try:
                ts = datetime.fromisoformat(completed_at).timestamp()
            except ValueError:
                ts = metadata_file.stat().st_mtime
        else:
            ts = metadata_file.stat().st_mtime
        candidates.append((ts, metadata, metadata_file))

    if not candidates:
        raise HTTPException(status_code=404, detail="No matching research found")

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, metadata, metadata_file = candidates[0]
    research_id = metadata.get("research_id") or metadata_file.name.replace("_metadata.json", "")
    report_file = reports_dir / f"{research_id}.md" if research_id else None
    report_url = (
        f"/api/outputs/research/reports/{report_file.name}"
        if report_file and report_file.exists()
        else None
    )
    metadata_url = f"/api/outputs/research/reports/{metadata_file.name}"

    return {
        "research_id": research_id,
        "metadata": metadata,
        "report_url": report_url,
        "metadata_url": metadata_url,
    }


@router.websocket("/run")
async def websocket_research_run(websocket: WebSocket):
    await websocket.accept()

    # Get task ID manager
    task_manager = TaskIDManager.get_instance()

    pusher_task = None
    progress_pusher_task = None
    heartbeat_task = None
    ws_connected = True  # Track WebSocket connection state
    original_stdout = sys.stdout  # Save original stdout at the start

    # Safe send helper - checks connection before sending
    async def safe_send(data: dict) -> bool:
        nonlocal ws_connected
        if not ws_connected:
            return False
        try:
            await websocket.send_json(data)
            return True
        except Exception as e:
            logger.warning(f"WebSocket send failed: {e}")
            ws_connected = False
            return False

    try:
        # 1. Wait for config
        data = await websocket.receive_json()
        topic = data.get("topic")
        kb_name = data.get("kb_name", "ai_textbook")
        notebook_id = data.get("notebook_id")
        session_id = data.get("session_id")
        # New unified parameters
        plan_mode = data.get("plan_mode", "medium")  # quick, medium, deep, auto
        enabled_tools = data.get("enabled_tools", ["RAG"])  # RAG, Paper, Web
        if "Web" not in enabled_tools:
            enabled_tools = ["Web", *enabled_tools]
        enabled_tools = list(dict.fromkeys(enabled_tools))
        skip_rephrase = data.get("skip_rephrase", False)
        # Legacy support
        preset = data.get("preset")  # For backward compatibility
        research_mode = data.get("research_mode")

        if not topic:
            await websocket.send_json({"type": "error", "content": "Topic is required"})
            return

        # Generate task ID
        task_key = f"research_{kb_name}_{hash(str(topic))}"
        task_id = task_manager.generate_task_id("research", task_key)

        # Send task ID to frontend
        await websocket.send_json({"type": "task_id", "task_id": task_id})

        # Use unified logger
        config = load_config()
        try:
            # Get log_dir from config
            log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get(
                "log_dir"
            )
            research_logger = get_logger("Research", log_dir=log_dir)
            research_logger.info(f"[{task_id}] Starting research flow: {topic[:50]}...")
        except Exception as e:
            logger.warning(f"Failed to initialize research logger: {e}")

        # 2. Initialize Pipeline
        # Initialize nested config structures from research.* (main.yaml structure)
        # This ensures all research module configs are properly inherited from main.yaml
        research_config = config.get("research", {})

        # ... (config initialization code omitted for brevity as it remains same) ...
        # NOTE: Skipping large block of config init code, assuming standard execution flow continues here
        # We need to focus on where pipeline.run is called.

        # ... (omitted config setup) ...

        # To keep this tool call focused, let's target the later part where pipeline is created and run.
        # But wait, replace_file_content requires me to match content exactly within a range.
        # Since I cannot see the middle lines about config setup in lines 380-450 easily without viewing, 
        # I should use multi_replace or ensure I view the file or just replace the END of the function.
        
        # Let's adjust the strategy. I will modify the END of websocket_research_run function 
        # where the pipeline is initialized and run.
        # Initialize planning config from research.planning
        if "planning" not in config:
            config["planning"] = research_config.get("planning", {}).copy()
        else:
            # Merge with research.planning defaults
            default_planning = research_config.get("planning", {})
            for key, value in default_planning.items():
                if key not in config["planning"]:
                    config["planning"][key] = value if not isinstance(value, dict) else value.copy()
                elif isinstance(value, dict) and isinstance(config["planning"][key], dict):
                    # Deep merge for nested dicts like decompose, rephrase
                    for k, v in value.items():
                        if k not in config["planning"][key]:
                            config["planning"][key][k] = v

        # Ensure decompose and rephrase exist
        if "decompose" not in config["planning"]:
            config["planning"]["decompose"] = {}
        if "rephrase" not in config["planning"]:
            config["planning"]["rephrase"] = {}

        # Initialize researching config from research.researching
        # This ensures execution_mode, max_parallel_topics etc. are properly inherited
        if "researching" not in config:
            config["researching"] = research_config.get("researching", {}).copy()
        else:
            # Merge with research.researching defaults (research.researching has lower priority)
            default_researching = research_config.get("researching", {})
            for key, value in default_researching.items():
                if key not in config["researching"]:
                    config["researching"][key] = value

        # Initialize reporting config from research.reporting
        # This ensures enable_citation_list, enable_inline_citations etc. are properly inherited
        if "reporting" not in config:
            config["reporting"] = research_config.get("reporting", {}).copy()
        else:
            # Merge with research.reporting defaults
            default_reporting = research_config.get("reporting", {})
            for key, value in default_reporting.items():
                if key not in config["reporting"]:
                    config["reporting"][key] = value

        # Apply plan_mode configuration (unified approach affecting both planning and researching)
        # Each mode defines:
        # - Planning: tree depth (subtopics count) and mode (manual/auto)
        # - Researching: max iterations per topic and iteration_mode (fixed/flexible)
        plan_mode_config = {
            "quick": {
                "planning": {"decompose": {"initial_subtopics": 2, "mode": "manual"}},
                "researching": {"max_iterations": 2, "iteration_mode": "fixed"},
                "reporting": {"report_type": "summary"},
            },
            "medium": {
                "planning": {"decompose": {"initial_subtopics": 5, "mode": "manual"}},
                "researching": {"max_iterations": 4, "iteration_mode": "fixed"},
            },
            "deep": {
                "planning": {"decompose": {"initial_subtopics": 8, "mode": "manual"}},
                "researching": {"max_iterations": 7, "iteration_mode": "fixed"},
            },
            "auto": {
                "planning": {"decompose": {"mode": "auto", "auto_max_subtopics": 8}},
                "researching": {"max_iterations": 6, "iteration_mode": "flexible"},
            },
        }
        if plan_mode in plan_mode_config:
            mode_cfg = plan_mode_config[plan_mode]
            # Apply planning configuration
            if "planning" in mode_cfg:
                for key, value in mode_cfg["planning"].items():
                    if key not in config["planning"]:
                        config["planning"][key] = {}
                    config["planning"][key].update(value)
            # Apply researching configuration
            if "researching" in mode_cfg:
                config["researching"].update(mode_cfg["researching"])

        # Legacy preset support (for backward compatibility)
        if preset and "presets" in config and preset in config["presets"]:
            preset_config = config["presets"][preset]
            for key, value in preset_config.items():
                if key in config and isinstance(value, dict):
                    config[key].update(value)

        # Apply enabled_tools configuration
        # RAG includes: rag_naive, rag_hybrid, query_item
        # Paper includes: paper_search
        # Web includes: web_search
        # run_code is always enabled
        config["researching"]["enable_rag_naive"] = "RAG" in enabled_tools
        config["researching"]["enable_rag_hybrid"] = "RAG" in enabled_tools
        config["researching"]["enable_query_item"] = "RAG" in enabled_tools
        config["researching"]["enable_paper_search"] = "Paper" in enabled_tools
        config["researching"]["enable_web_search"] = "Web" in enabled_tools
        config["researching"]["enable_run_code"] = True  # Always enabled

        # Store enabled_tools for prompt generation
        config["researching"]["enabled_tools"] = enabled_tools

        # Legacy research_mode support
        if research_mode:
            config["researching"]["research_mode"] = research_mode

        # If skip_rephrase is True, disable the internal rephrase step
        if skip_rephrase:
            config["planning"]["rephrase"]["enabled"] = False

        # Define unified output directory
        # Use project root directory user/research as unified output directory
        root_dir = Path(__file__).parent.parent.parent.parent
        output_base = root_dir / "data" / "user" / "research"

        # Update config with unified output paths
        if "system" not in config:
            config["system"] = {}

        config["system"]["output_base_dir"] = str(output_base / "cache")
        config["system"]["reports_dir"] = str(output_base / "reports")

        # Inject API keys from env if not in config
        try:
            llm_config = get_llm_config()
            api_key = llm_config.api_key
            base_url = llm_config.base_url
        except ValueError as e:
            await websocket.send_json({"error": f"LLM configuration error: {e!s}"})
            await websocket.close()
            return

        # 3. Setup Queues for log and progress
        log_queue = asyncio.Queue()
        progress_queue = asyncio.Queue()

        # Progress callback function
        def progress_callback(event: dict[str, Any]):
            """Progress callback function, puts progress events into queue"""
            try:
                asyncio.get_event_loop().call_soon_threadsafe(progress_queue.put_nowait, event)
            except Exception as e:
                logger.error(f"Progress callback error: {e}")

        pipeline = ResearchPipeline(
            config=config,
            api_key=api_key,
            base_url=base_url,
            kb_name=kb_name,
            progress_callback=progress_callback,
        )

        # 4. Background log pusher
        async def log_pusher():
            while True:
                try:
                    log = await log_queue.get()
                    if log is None:
                        break
                    await safe_send({"type": "log", "content": log})
                    log_queue.task_done()
                except Exception as e:
                    logger.error(f"Log pusher error: {e}")
                    break

        # 5. Background progress pusher
        async def progress_pusher():
            while True:
                try:
                    event = await progress_queue.get()
                    if event is None:
                        break
                    await safe_send(event)
                    progress_queue.task_done()
                except Exception as e:
                    logger.error(f"Progress pusher error: {e}")
                    break

        pusher_task = asyncio.create_task(log_pusher())
        progress_pusher_task = asyncio.create_task(progress_pusher())

        # 6. Background heartbeat to keep WebSocket alive
        async def heartbeat():
            """Send periodic ping to prevent connection timeout"""
            while True:
                try:
                    await asyncio.sleep(30)  # Send heartbeat every 30 seconds
                    await safe_send({"type": "ping", "timestamp": datetime.now().isoformat()})
                except Exception:
                    break  # Stop if connection is closed

        heartbeat_task = asyncio.create_task(heartbeat())

        # 7. Run Pipeline with stdout interception
        class ResearchStdoutInterceptor:
            def __init__(self, queue):
                self.queue = queue
                self.original_stdout = sys.stdout

            def write(self, message):
                # Write to terminal first to ensure terminal output is not blocked
                self.original_stdout.write(message)
                # Then try to send to frontend (non-blocking, failure doesn't affect terminal output)
                if message.strip():
                    try:
                        # Use call_soon_threadsafe for thread safety
                        loop = asyncio.get_event_loop()
                        loop.call_soon_threadsafe(self.queue.put_nowait, message)
                    except (asyncio.QueueFull, RuntimeError, AttributeError):
                        # Queue full, event loop closed, or no event loop, ignore error, doesn't affect terminal output
                        pass

            def flush(self):
                self.original_stdout.flush()

        sys.stdout = ResearchStdoutInterceptor(log_queue)

        try:
            await safe_send(
                {"type": "status", "content": "started", "research_id": pipeline.research_id}
            )
            
            # 8. Execute Research directly
            # Note: We removed the concurrent WebSocket listener pattern because
            # cancelling a pending websocket.receive_json() corrupts the connection,
            # preventing subsequent sends from working.
            result = await pipeline.run(topic)

            # 9. Handle Result
            if result:
                report_content = result.get("report", "")
                final_report_path = result.get("final_report_path", "")
                if not report_content and final_report_path:
                    try:
                        report_path = Path(final_report_path)
                        if report_path.exists():
                            report_content = report_path.read_text(encoding="utf-8")
                    except Exception as exc:
                        logger.warning(f"Failed to read report from {final_report_path}: {exc}")
                
                # Send completion message
                # For backward compatibility with simpler client
                await safe_send({"type": "report_path", "path": str(final_report_path)})
                
                # Save to history
                history_manager.add_entry(
                    activity_type=ActivityType.RESEARCH,
                    title=topic,
                    content={"topic": topic, "report": report_content, "kb_name": kb_name},
                    summary=f"Research ID: {result['research_id']}",
                )

                if await safe_send(
                    {
                        "type": "result",
                        "report": report_content,
                        "metadata": result["metadata"],
                        "research_id": result["research_id"],
                    }
                ):
                    # Rate limiting / buffer flush assurance
                    await asyncio.sleep(1.0)
                else:
                    research_logger.error(f"[{task_id}] Failed to send result message")
                _persist_research_session(
                    notebook_id,
                    session_id,
                    report_content,
                    topic,
                    metadata=result.get("metadata"),
                )

            # Update task status to completed
            try:
                log_dir = config.get("paths", {}).get("user_log_dir") or config.get(
                    "logging", {}
                ).get("log_dir")
                research_logger = get_logger("Research", log_dir=log_dir)
                research_logger.success(f"[{task_id}] Research flow completed: {topic[:50]}...")
                task_manager.update_task_status(task_id, "completed")
            except Exception as e:
                logger.warning(f"Failed to log completion: {e}")

        finally:
            sys.stdout = original_stdout  # Safely restore using saved reference

    except Exception as e:
        await safe_send({"type": "error", "content": str(e)})
        logging.error(f"Research error: {e}", exc_info=True)

        # Update task status to error
        try:
            log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get(
                "log_dir"
            )
            research_logger = get_logger("Research", log_dir=log_dir)
            research_logger.error(f"[{task_id}] Research flow failed: {e}")
            task_manager.update_task_status(task_id, "error", error=str(e))
        except Exception as log_err:
            logger.warning(f"Failed to log error: {log_err}")
    finally:
        if pusher_task:
            pusher_task.cancel()
        if progress_pusher_task:
            progress_pusher_task.cancel()
        if heartbeat_task:
            heartbeat_task.cancel()


class ExportMindmapRequest(BaseModel):
    """Request model for mindmap export"""
    markdown: str
    use_llm: bool = False


@router.post("/export_mindmap")
async def export_mindmap(request: ExportMindmapRequest):
    """
    Generate Mermaid mindmap code from research report
    
    Args:
        markdown: Markdown content of the report
        use_llm: If True, use LLM for better structure extraction
        
    Returns:
        {"mindmap": "mermaid mindmap code"}
    """
    try:
        from src.services.export.mindmap_generator import (
            generate_mindmap_code,
        )
        
        if request.use_llm:
            # Get LLM config for enhanced generation
            try:
                llm_config = get_llm_config()
                # TODO: Implement LLM callable for mindmap generation
                # For now, use rule-based
                mindmap_code = generate_mindmap_code(request.markdown)
            except Exception:
                mindmap_code = generate_mindmap_code(request.markdown)
        else:
            mindmap_code = generate_mindmap_code(request.markdown)
        
        return {"mindmap": mindmap_code}
        
    except Exception as e:
        logger.error(f"Mindmap export failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
