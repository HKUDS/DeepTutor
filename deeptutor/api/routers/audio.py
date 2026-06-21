"""Audio file serving endpoint for TTS output."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from deeptutor.services.path_service import get_path_service

router = APIRouter()


@router.get("/{session_id}/{filename}")
async def serve_audio(session_id: str, filename: str) -> FileResponse:
    """Serve a generated TTS audio file.

    Args:
        session_id: The chat session identifier.
        filename: The audio file name (UUID-based).

    Returns:
        The audio file as a streaming response.

    Raises:
        HTTPException: If the file does not exist or the path is invalid.
    """
    # Validate filename to prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        raise HTTPException(status_code=400, detail="Invalid session ID.")

    audio_path = get_path_service().workspace_root / "chat" / "audio" / session_id / filename
    if not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found.")

    return FileResponse(
        path=str(audio_path),
        media_type="audio/mpeg",
        filename=filename,
    )
