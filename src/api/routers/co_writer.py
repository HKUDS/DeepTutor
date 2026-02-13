import asyncio
from pathlib import Path
import sys
import traceback
from typing import Literal
import tempfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

# Ensure co_writer module can be imported
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import json

from src.agents.co_writer.edit_agent import TOOL_CALLS_DIR, EditAgent, print_stats
from src.agents.co_writer.narrator_agent import NarratorAgent, get_narrator_agent
from src.logging import get_logger
from src.services.config import load_config_with_main
from src.services.tts import get_tts_config
from src.services.storage.file_store import get_file_record, save_file_record
from src.services.storage.history_store import get_history_item, list_history, update_history_item
from src.services.storage.object_store import get_bucket_name, get_object_stream, upload_file

router = APIRouter()

# Initialize logger with config
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)  # Use any config to get main.yaml
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("CoWriter", level="INFO", log_dir=log_dir)

agent = EditAgent()


class EditRequest(BaseModel):
    text: str
    instruction: str
    action: Literal["rewrite", "shorten", "expand"] = "rewrite"
    source: Literal["rag", "web"] | None = None
    kb_name: str | None = None


class EditResponse(BaseModel):
    edited_text: str
    operation_id: str


class AutoMarkRequest(BaseModel):
    text: str


class AutoMarkResponse(BaseModel):
    marked_text: str
    operation_id: str


@router.post("/edit", response_model=EditResponse)
async def edit_text(request: EditRequest):
    try:
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


@router.post("/automark", response_model=AutoMarkResponse)
async def auto_mark_text(request: AutoMarkRequest):
    """AI auto-mark text"""
    try:
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
        history = list_history()
        return {"history": history, "total": len(history)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{operation_id}")
async def get_operation(operation_id: str):
    """Get single operation details"""
    try:
        item = get_history_item(operation_id)
        if item:
            return item
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
        for filepath in TOOL_CALLS_DIR.glob(f"{operation_id}_*.json"):
            with open(filepath, encoding="utf-8") as f:
                return json.load(f)
        raise HTTPException(status_code=404, detail="Tool call not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export/markdown")
async def export_markdown(content: dict):
    """Export as Markdown file"""
    try:
        markdown_content = content.get("content", "")
        filename = content.get("filename", "document.md")

        return Response(
            content=markdown_content,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ================= TTS Narration Feature =================


class NarrateRequest(BaseModel):
    """Narration request"""

    content: str
    style: Literal["friendly", "academic", "concise"] = "friendly"
    voice: str | None = None  # If None, will use default value from config
    skip_audio: bool = False


class NarrateResponse(BaseModel):
    """Narration response"""

    script: str
    key_points: list[str]
    style: str
    original_length: int
    script_length: int
    has_audio: bool
    audio_url: str | None = None
    audio_id: str | None = None
    voice: str | None = None
    audio_error: str | None = None


class ScriptOnlyRequest(BaseModel):
    """Script-only generation request"""

    content: str
    style: Literal["friendly", "academic", "concise"] = "friendly"


@router.post("/narrate", response_model=NarrateResponse)
async def narrate_content(request: NarrateRequest):
    """
    Generate note narration script and optionally generate TTS audio

    - style: Narration style
      - friendly: Friendly and approachable tutor style
      - academic: Rigorous academic lecture style
      - concise: Efficient and concise knowledge delivery style
    - voice: TTS voice role (alloy, echo, fable, onyx, nova, shimmer)
    - skip_audio: Whether to skip audio generation (set to true to return only script)
    """
    try:
        narrator = get_narrator_agent()
        result = await narrator.narrate(
            content=request.content,
            style=request.style,
            voice=request.voice,
            skip_audio=request.skip_audio,
        )
        return result
    except ValueError as e:
        # TTS configuration related error
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/narrate/script")
async def generate_script_only(request: ScriptOnlyRequest):
    """
    Generate script only (no audio generation)

    Fast endpoint, suitable for previewing script effect
    """
    try:
        narrator = get_narrator_agent()
        result = await narrator.generate_script(content=request.content, style=request.style)
        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tts/status")
async def get_tts_status():
    """
    Check TTS service status

    Returns whether TTS configuration is available
    """
    try:
        tts_config = get_tts_config()
        return {
            "available": True,
            "model": tts_config.get("model"),
            "default_voice": tts_config.get("voice", "alloy"),
        }
    except ValueError as e:
        return {
            "available": False,
            "error": str(e),
            "hint": "Please configure TTS_MODEL, TTS_API_KEY, TTS_URL in .env file",
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


@router.get("/tts/voices")
async def get_available_voices():
    """
    Get available TTS voice role list (OpenAI TTS voices)
    """
    voices = [
        {
            "id": "alloy",
            "name": "Alloy",
            "description": "Neutral and balanced voice",
        },
        {
            "id": "echo",
            "name": "Echo",
            "description": "Warm and conversational voice",
        },
        {
            "id": "fable",
            "name": "Fable",
            "description": "Expressive and dramatic voice",
        },
        {
            "id": "onyx",
            "name": "Onyx",
            "description": "Deep and authoritative voice",
        },
        {
            "id": "nova",
            "name": "Nova",
            "description": "Friendly and upbeat voice",
        },
        {
            "id": "shimmer",
            "name": "Shimmer",
            "description": "Clear and pleasant voice",
        },
    ]
    return {"voices": voices}


@router.get("/stream_audio/{audio_id}")
async def stream_audio(audio_id: str):
    """
    Stream audio generation for a specific audio ID.
    If generation is pending, it triggers it.
    If already generated, it streams from file.
    """
    from src.agents.co_writer.narrator_agent import (
        get_pending_stream,
        get_narrator_agent,
        get_generation_lock,
        remove_pending_stream,
        set_pending_stream,
    )
    
    narrator = get_narrator_agent()
    file_record = get_file_record(audio_id)
    if file_record:
        response = get_object_stream(file_record["bucket"], file_record["object_key"])
        def iter_stream():
            try:
                for chunk in response.stream(8192):
                    if chunk:
                        yield chunk
            finally:
                response.close()
                response.release_conn()
        return StreamingResponse(iter_stream(), media_type=file_record["content_type"])

    pending = get_pending_stream(audio_id)
    if not pending:
        history_item = get_history_item(audio_id)
        if history_item and history_item.get("status") == "pending_stream":
            result = history_item.get("result") or {}
            script = result.get("script")
            voice = result.get("voice") or narrator.default_voice
            provider = narrator.tts_config.get("provider", "openai") if narrator.tts_config else "openai"
            if script:
                set_pending_stream(audio_id, script, voice, provider)
                pending = get_pending_stream(audio_id)

    if pending:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_path = Path(temp_file.name)
        temp_file.close()

        async def stream_with_lock_and_cleanup():
            lock = await get_generation_lock(audio_id)
            async with lock:
                try:
                    async for chunk in narrator.generate_audio_stream(
                        script=pending["script"],
                        voice=pending["voice"],
                        audio_id=audio_id,
                        output_path=temp_path,
                    ):
                        yield chunk
                finally:
                    remove_pending_stream(audio_id)

            bucket = get_bucket_name()
            if not bucket:
                raise HTTPException(status_code=500, detail="MinIO bucket not configured")
            object_key = f"co-writer/audio/{audio_id}.mp3"
            await asyncio.to_thread(
                upload_file,
                bucket,
                object_key,
                str(temp_path),
                "audio/mpeg",
            )
            await asyncio.to_thread(
                save_file_record,
                file_id=audio_id,
                file_type="audio",
                filename=f"{audio_id}.mp3",
                bucket=bucket,
                object_key=object_key,
                content_type="audio/mpeg",
                metadata={"voice": pending.get("voice")},
            )
            history_item = get_history_item(audio_id)
            if history_item:
                history_item["status"] = "completed"
                update_history_item(audio_id, history_item)
            if temp_path.exists():
                temp_path.unlink()

        return StreamingResponse(
            stream_with_lock_and_cleanup(),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    raise HTTPException(status_code=404, detail="Audio not found or expired")
