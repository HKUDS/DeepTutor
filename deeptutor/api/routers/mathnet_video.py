"""MathNet Video Generation API Router

Endpoints for generating narrated video explanations of MathNet problems.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from deeptutor.agents.lecture_script import LectureScriptGenerator
from deeptutor.agents.math_animator.pipeline import MathAnimatorPipeline
from deeptutor.services.tts import get_tts_client
from deeptutor.utils.ffmpeg import mux_audio_video, check_ffmpeg_available

logger = logging.getLogger(__name__)
router = APIRouter()


class VideoGenerationRequest(BaseModel):
    """Request to generate a narrated video."""

    problem_id: str
    tts_provider: str = "edge"
    voice: str | None = None
    quality: str = "medium"  # low, medium, high
    include_steps: list[int] | None = None  # Specific steps to include, None = all


class VideoGenerationResponse(BaseModel):
    """Response from video generation."""

    status: str
    video_url: str | None
    duration_seconds: float
    generation_time_seconds: float


# In-memory store for generation jobs (replace with Redis in production)
_generation_jobs: dict[str, dict[str, Any]] = {}


@router.post("/generate", response_model=VideoGenerationResponse)
async def generate_narrated_video(
    request: VideoGenerationRequest,
    background_tasks: BackgroundTasks,
) -> VideoGenerationResponse:
    """Generate a narrated video explanation for a MathNet problem.

    This is a synchronous endpoint for MVP. For production, use
    /generate/async and poll /status/{job_id}.
    """
    import time

    start_time = time.perf_counter()

    # Check FFmpeg availability
    if not check_ffmpeg_available():
        raise HTTPException(
            status_code=503,
            detail="FFmpeg not available. Video generation requires FFmpeg.",
        )

    # Import here to avoid circular imports
    from deeptutor.api.routers.mathnet import _get_db_connection

    # Fetch problem data
    conn = _get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM problems WHERE id = ?",
        (request.problem_id,),
    )
    problem_row = cursor.fetchone()

    if not problem_row:
        raise HTTPException(
            status_code=404,
            detail=f"Problem '{request.problem_id}' not found",
        )

    # Fetch architecture
    cursor.execute(
        "SELECT * FROM architectures WHERE problem_id = ?",
        (request.problem_id,),
    )
    arch_row = cursor.fetchone()

    if not arch_row:
        raise HTTPException(
            status_code=400,
            detail=f"Problem '{request.problem_id}' has no AI-generated solution yet. "
            "Please wait for the generation pipeline to complete.",
        )

    # Fetch steps
    cursor.execute(
        """
        SELECT * FROM steps
        WHERE architecture_id = ?
        ORDER BY step_index
    """,
        (arch_row[0],),  # architecture_id
    )
    step_rows = cursor.fetchall()

    conn.close()

    # Parse problem data
    import json

    def parse_json_field(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            result = json.loads(value)
            return result if isinstance(result, list) else [str(result)]
        except Exception:
            return []

    problem_data = {
        "id": problem_row[0],
        "problem_markdown": problem_row[1],
        "problem_zh": problem_row[3],
        "solution_markdown": parse_json_field(problem_row[2]),
        "final_answer": problem_row[10],
    }

    architecture_data = {
        "id": arch_row[0],
        "problem_summary_zh": arch_row[2],
        "problem_summary_en": arch_row[3],
        "solution_strategy_zh": arch_row[4],
        "solution_strategy_en": arch_row[5],
        "suggested_tier": arch_row[6],
        "tier_reason_zh": arch_row[7],
        "prerequisites_zh": parse_json_field(arch_row[8]),
        "prerequisites_en": parse_json_field(arch_row[9]),
        "major_categories": parse_json_field(arch_row[12]),
        "step_count": arch_row[13],
        "steps_outline": parse_json_field(arch_row[14]),
    }

    steps_data = []
    for row in step_rows:
        cursor.execute(
            """
            SELECT kp.id, kp.name_zh, kp.name_en, skp.importance
            FROM step_knowledge_points skp
            JOIN knowledge_points kp ON skp.knowledge_point_id = kp.id
            WHERE skp.step_id = ?
        """,
            (row[0],),
        )
        kps = [
            {"id": k[0], "name_zh": k[1], "name_en": k[2], "importance": k[3]}
            for k in cursor.fetchall()
        ]

        steps_data.append(
            {
                "id": row[0],
                "step_index": row[3],
                "step_title_zh": row[4],
                "step_title_en": row[5],
                "step_text_zh": row[6],
                "step_text_en": row[7],
                "explanation_zh": row[8],
                "explanation_en": row[9],
                "role_in_solution_zh": row[10],
                "role_in_solution_en": row[11],
                "knowledge_points": kps,
            }
        )

    # Filter steps if requested
    if request.include_steps:
        steps_data = [
            s for s in steps_data if s["step_index"] in request.include_steps
        ]

    # Step 1: Generate lecture script
    generator = LectureScriptGenerator()
    lecture_script = generator.generate_from_mathnet(
        problem_id=request.problem_id,
        problem_markdown=problem_data["problem_markdown"],
        architecture=architecture_data,
        steps=steps_data,
        final_answer=problem_data["final_answer"],
    )

    # Step 2: Generate TTS audio
    tts = get_tts_client(provider=request.tts_provider)
    full_script = lecture_script.get_full_script()
    tts_result = await tts.synthesize(full_script, voice=request.voice)

    # Step 3: Generate timed animation (simplified for MVP)
    # For MVP, we skip the full MathAnimator pipeline and generate a simple video
    # Full implementation would integrate with the pipeline

    # Create a simple video with FFmpeg (test pattern + audio)
    output_path = Path(tempfile.gettempdir()) / f"mathnet_{request.problem_id}.mp4"

    # For MVP, generate a test video with the audio
    # In production, this would be the rendered Manim animation

    # Simple approach: use FFmpeg to create a video with the audio
    # This creates a 720p test video with the narration
    video_duration = tts_result.duration_seconds

    command = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", f"color=c=black:s=1280x720:d={video_duration}",
        "-i", tts_result.audio_path,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"Video generation failed: {stderr.decode()[:500]}",
            )

    except FileNotFoundError:
        raise HTTPException(
            status_code=503,
            detail="FFmpeg not found. Please install FFmpeg.",
        )

    generation_time = time.perf_counter() - start_time

    return VideoGenerationResponse(
        status="success",
        video_url=f"/api/outputs/{output_path.name}",
        duration_seconds=tts_result.duration_seconds,
        generation_time_seconds=generation_time,
    )


@router.get("/status/{job_id}")
async def get_generation_status(job_id: str) -> dict[str, Any]:
    """Get status of an async video generation job."""
    if job_id not in _generation_jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return _generation_jobs[job_id]


import asyncio

__all__ = ["router"]
