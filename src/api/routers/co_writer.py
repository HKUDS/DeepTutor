import asyncio
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time
import traceback
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

# Ensure co_writer module can be imported
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import json

from src.agents.co_writer.edit_agent import TOOL_CALLS_DIR, EditAgent, print_stats
from src.agents.co_writer.narrator_agent import get_narrator_agent
from src.logging import get_logger
from src.services.config import load_config_with_main
from src.services.storage.file_store import get_file_record, save_file_record
from src.services.storage.history_store import get_history_item, list_history, update_history_item
from src.services.storage.object_store import get_bucket_name, get_object_stream, upload_file
from src.services.tts import get_tts_config

router = APIRouter()

# Initialize logger with config
project_root = Path(__file__).parent.parent.parent.parent
config = load_config_with_main("solve_config.yaml", project_root)  # Use any config to get main.yaml
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("CoWriter", level="INFO", log_dir=log_dir)

agent = EditAgent()
AUDIO_PENDING_TTL_SECONDS = 15 * 60
_AUDIO_TIMEOUT_ERROR = "Audio generation timed out. Please retry."


def _normalize_tts_retry_state(retry_state: dict | None) -> dict:
    """Normalize retry metrics to a stable structure for history payloads."""
    retry_state = retry_state or {}
    attempted = retry_state.get("attempted_retries")
    max_retries = retry_state.get("max_retries_per_chunk")
    return {
        "attempted_retries": attempted if isinstance(attempted, int) else 0,
        "max_retries_per_chunk": max_retries if isinstance(max_retries, int) else 0,
        "last_error_code": retry_state.get("last_error_code"),
        "last_error_retryable": retry_state.get("last_error_retryable"),
        "last_error": retry_state.get("last_error"),
    }


def _attach_tts_retry_history(
    history_item: dict,
    retry_state: dict | None,
    *,
    include_error_class: bool = False,
) -> None:
    summary = _normalize_tts_retry_state(retry_state)
    history_item["tts_retry"] = summary
    if include_error_class:
        retryable = summary.get("last_error_retryable")
        if retryable is True:
            history_item["error_type"] = "retryable"
        elif retryable is False:
            history_item["error_type"] = "non_retryable"
        error_code = summary.get("last_error_code")
        if isinstance(error_code, str) and error_code:
            history_item["error_code"] = error_code


def _history_age_seconds(history_item: dict) -> float | None:
    """Estimate age of a history record in seconds from payload timestamp."""
    ts_value = history_item.get("timestamp")
    if ts_value is None:
        return None

    try:
        if isinstance(ts_value, (int, float)):
            created_at = float(ts_value)
        else:
            normalized = str(ts_value).replace("Z", "+00:00")
            created_at = datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return None

    return max(0.0, time.time() - created_at)


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
        logger.warning(f"⚠️ Failed to get history (DB might be down): {e}")
        # Return empty list instead of 500 error to allow UI to render without history
        return {"history": [], "total": 0}


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
        logger.warning(f"⚠️ Failed to get operation {operation_id} (DB might be down): {e}")
        raise HTTPException(status_code=404, detail="Operation not found (or DB error)")


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


class PodcastConfig(BaseModel):
    """播客配置（仅 Doubao Podcast 模式生效）"""

    speakers: list[str] | None = None  # 发声人列表
    speech_rate: float = 1.0  # 语速倍率 0.5~2.0 (1.0=正常)


class NarrateRequest(BaseModel):
    """Narration request"""

    content: str
    style: Literal["friendly", "academic", "concise"] = "friendly"
    voice: str | None = None  # If None, will use default value from config
    skip_audio: bool = False
    podcast_config: PodcastConfig | None = None


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
async def narrate_content(request: NarrateRequest, background_tasks: BackgroundTasks):
    """
    Generate note narration script and optionally generate TTS audio.
    Audio generation is triggered as a background task and can be polled via /audio_status.
    """
    try:
        narrator = get_narrator_agent()
        podcast_config_dict = None
        if request.podcast_config:
            podcast_config_dict = request.podcast_config.model_dump(exclude_none=True)
        result = await narrator.narrate(
            content=request.content,
            style=request.style,
            voice=request.voice,
            skip_audio=request.skip_audio,
            podcast_config=podcast_config_dict,
        )

        # Trigger background audio generation if audio was requested
        if result.get("has_audio") and result.get("audio_id"):
            background_tasks.add_task(
                generate_audio_background,
                audio_id=result["audio_id"],
            )

        return result
    except ValueError as e:
        # TTS configuration related error
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def generate_audio_background(audio_id: str):
    """
    Background task: generate audio, save to MinIO, update status.
    Runs after /narrate response is sent.
    """
    from src.agents.co_writer.narrator_agent import (
        get_generation_lock,
        get_narrator_agent,
        get_pending_stream,
        remove_pending_stream,
    )

    pending = get_pending_stream(audio_id)
    if not pending:
        logger.warning(f"No pending stream found for {audio_id}, skipping background generation.")
        return

    narrator = get_narrator_agent()
    lock = await get_generation_lock(audio_id)
    async with lock:
        # Double-check: another path may have already generated it
        file_record = get_file_record(audio_id)
        if file_record:
            remove_pending_stream(audio_id)
            return

        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        temp_path = Path(temp_file.name)
        temp_file.close()
        retry_state: dict = {}

        try:
            # Generate complete audio
            async for chunk in narrator.generate_audio_stream(
                script=pending["script"],
                voice=pending["voice"],
                audio_id=audio_id,
                output_path=temp_path,
                podcast_config=pending.get("podcast_config"),
                retry_state=retry_state,
            ):
                pass  # Chunks are written to temp_path by generate_audio_stream

            remove_pending_stream(audio_id)

            # Save to MinIO
            try:
                bucket = get_bucket_name()
                if bucket:
                    object_key = f"co-writer/audio/{audio_id}.mp3"
                    upload_file(bucket, object_key, str(temp_path), "audio/mpeg")
                    save_file_record(
                        file_id=audio_id,
                        file_type="audio",
                        filename=f"{audio_id}.mp3",
                        bucket=bucket,
                        object_key=object_key,
                        content_type="audio/mpeg",
                        metadata={"voice": pending.get("voice")},
                    )
                    logger.info(f"✅ Background audio generation completed: {audio_id}")

                history_item = get_history_item(audio_id)
                if history_item:
                    history_item["status"] = "completed"
                    _attach_tts_retry_history(history_item, retry_state)
                    update_history_item(audio_id, history_item)

            except Exception as e:
                logger.warning(f"⚠️ Failed to save audio to MinIO: {e}")
                # Still mark as failed so polling can report it
                history_item = get_history_item(audio_id)
                if history_item:
                    history_item["status"] = "failed"
                    history_item["error"] = f"Storage error: {e}"
                    _attach_tts_retry_history(history_item, retry_state)
                    update_history_item(audio_id, history_item)

        except Exception as e:
            remove_pending_stream(audio_id)
            logger.error(f"❌ Background audio generation failed for {audio_id}: {e}")
            traceback.print_exc()
            # Update history status to "failed"
            try:
                history_item = get_history_item(audio_id)
                if history_item:
                    history_item["status"] = "failed"
                    history_item["error"] = str(e)
                    _attach_tts_retry_history(
                        history_item,
                        retry_state,
                        include_error_class=True,
                    )
                    update_history_item(audio_id, history_item)
            except Exception:
                pass

        finally:
            if temp_path.exists():
                temp_path.unlink()


@router.get("/audio_status/{audio_id}")
async def get_audio_status(audio_id: str):
    """
    Poll audio generation status.
    Returns: {status: "generating" | "ready" | "failed" | "not_found", error?: string}
    """
    from src.agents.co_writer.narrator_agent import get_pending_stream, remove_pending_stream

    # Check MinIO storage first (definitive "ready" signal)
    file_record = get_file_record(audio_id)
    if file_record:
        return {"status": "ready"}

    # Check in-memory pending stream
    pending = get_pending_stream(audio_id)
    if pending:
        history_item = get_history_item(audio_id)
        if history_item:
            age = _history_age_seconds(history_item)
            if age is not None and age > AUDIO_PENDING_TTL_SECONDS:
                history_item["status"] = "failed"
                history_item["error"] = _AUDIO_TIMEOUT_ERROR
                update_history_item(audio_id, history_item)
                remove_pending_stream(audio_id)
                return {"status": "failed", "error": _AUDIO_TIMEOUT_ERROR}
        return {"status": "generating"}

    # Check DB history
    history_item = get_history_item(audio_id)
    if history_item:
        status = history_item.get("status", "unknown")
        if status == "failed":
            return {"status": "failed", "error": history_item.get("error", "生成失败")}
        if status in ("pending_stream", "generating"):
            age = _history_age_seconds(history_item)
            if age is not None and age > AUDIO_PENDING_TTL_SECONDS:
                history_item["status"] = "failed"
                history_item["error"] = _AUDIO_TIMEOUT_ERROR
                update_history_item(audio_id, history_item)
                return {"status": "failed", "error": _AUDIO_TIMEOUT_ERROR}
            return {"status": "generating"}
        if status == "completed":
            return {"status": "ready"}

    return {"status": "not_found"}


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


@router.get("/tts/doubao_speakers")
async def get_doubao_speakers():
    """
    返回可用的 Doubao Podcast 发声人列表
    """
    speakers = [
        {
            "id": "zh_female_mizaitongxue_v2_saturn_bigtts",
            "name": "米仔同学 (女)",
            "gender": "female",
            "language": "zh",
        },
        {
            "id": "zh_male_dayixiansheng_v2_saturn_bigtts",
            "name": "大义先生 (男)",
            "gender": "male",
            "language": "zh",
        },
        {
            "id": "zh_female_shuangkuaisisi_moon_bigtts",
            "name": "爽快思思 (女)",
            "gender": "female",
            "language": "zh",
        },
        {
            "id": "zh_male_wennuanahu_moon_bigtts",
            "name": "温暖阿虎 (男)",
            "gender": "male",
            "language": "zh",
        },
        {
            "id": "zh_female_tianmeixiaoyuan_moon_bigtts",
            "name": "甜美小源 (女)",
            "gender": "female",
            "language": "zh",
        },
        {
            "id": "zh_male_yangguangqingse_moon_bigtts",
            "name": "阳光青涩 (男)",
            "gender": "male",
            "language": "zh",
        },
    ]
    return {"speakers": speakers}


@router.get("/stream_audio/{audio_id}")
async def stream_audio(audio_id: str):
    """
    Return complete audio for a specific audio ID.
    If generation is pending, it triggers it, waits for completion, and returns the full file.
    If already generated, it returns from storage.
    Returns with Content-Length header so browsers can display duration and progress.
    """
    from src.agents.co_writer.narrator_agent import (
        get_generation_lock,
        get_narrator_agent,
        get_pending_stream,
        remove_pending_stream,
        set_pending_stream,
    )

    narrator = get_narrator_agent()

    # Case 1: Already stored in MinIO — return complete file
    file_record = get_file_record(audio_id)
    if file_record:
        try:
            response = get_object_stream(file_record["bucket"], file_record["object_key"])
            audio_bytes = response.read()
            response.close()
            response.release_conn()
            return Response(
                content=audio_bytes,
                media_type=file_record["content_type"],
                headers={
                    "Content-Length": str(len(audio_bytes)),
                    "Accept-Ranges": "bytes",
                },
            )
        except Exception as e:
            logger.warning(f"Failed to read from MinIO, will try re-generation: {e}")

    # Case 2: Pending generation — check in-memory store or DB
    pending = get_pending_stream(audio_id)
    if not pending:
        history_item = get_history_item(audio_id)
        if history_item and history_item.get("status") == "pending_stream":
            result = history_item.get("result") or {}
            script = result.get("script")
            voice = result.get("voice") or narrator.default_voice
            provider = (
                narrator.tts_config.get("provider", "openai") if narrator.tts_config else "openai"
            )
            if script:
                set_pending_stream(audio_id, script, voice, provider)
                pending = get_pending_stream(audio_id)

    if pending:
        lock = await get_generation_lock(audio_id)
        async with lock:
            # Double-check if another request already generated it
            file_record = get_file_record(audio_id)
            if file_record:
                try:
                    response = get_object_stream(file_record["bucket"], file_record["object_key"])
                    audio_bytes = response.read()
                    response.close()
                    response.release_conn()
                    return Response(
                        content=audio_bytes,
                        media_type=file_record["content_type"],
                        headers={
                            "Content-Length": str(len(audio_bytes)),
                            "Accept-Ranges": "bytes",
                        },
                    )
                except Exception:
                    pass

            # Generate complete audio
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            temp_path = Path(temp_file.name)
            temp_file.close()
            retry_state: dict = {}

            try:
                audio_data = bytearray()
                async for chunk in narrator.generate_audio_stream(
                    script=pending["script"],
                    voice=pending["voice"],
                    audio_id=audio_id,
                    output_path=temp_path,
                    podcast_config=pending.get("podcast_config"),
                    retry_state=retry_state,
                ):
                    audio_data.extend(chunk)

                remove_pending_stream(audio_id)
                audio_bytes = bytes(audio_data)

                # Persist to MinIO
                try:
                    bucket = get_bucket_name()
                    if bucket:
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
                        _attach_tts_retry_history(history_item, retry_state)
                        update_history_item(audio_id, history_item)

                except Exception as e:
                    logger.warning(
                        f"⚠️ Failed to save audio file to MinIO or update DB: {e}. "
                        "The audio will still be returned to the user."
                    )
                finally:
                    if temp_path.exists():
                        temp_path.unlink()

                return Response(
                    content=audio_bytes,
                    media_type="audio/mpeg",
                    headers={
                        "Content-Length": str(len(audio_bytes)),
                        "Accept-Ranges": "bytes",
                    },
                )

            except Exception as e:
                remove_pending_stream(audio_id)
                if temp_path.exists():
                    temp_path.unlink()
                logger.error(f"Audio generation failed: {e}")
                history_item = get_history_item(audio_id)
                if history_item:
                    history_item["status"] = "failed"
                    history_item["error"] = str(e)
                    _attach_tts_retry_history(
                        history_item,
                        retry_state,
                        include_error_class=True,
                    )
                    update_history_item(audio_id, history_item)
                raise HTTPException(status_code=500, detail=f"Audio generation failed: {e}")

    raise HTTPException(status_code=404, detail="Audio not found or expired")


@router.get("/download_audio/{audio_id}")
async def download_audio(audio_id: str):
    """
    Download generated podcast audio file.
    Returns with Content-Disposition header to trigger browser download.
    """
    file_record = get_file_record(audio_id)
    if not file_record:
        raise HTTPException(
            status_code=404, detail="Audio not found. Please generate the podcast first."
        )

    try:
        response = get_object_stream(file_record["bucket"], file_record["object_key"])
        audio_bytes = response.read()
        response.close()
        response.release_conn()
    except Exception as e:
        logger.error(f"Failed to read audio from storage: {e}")
        raise HTTPException(status_code=500, detail="Failed to read audio file")

    filename = file_record.get("filename", f"podcast-{audio_id}.mp3")
    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(audio_bytes)),
        },
    )
