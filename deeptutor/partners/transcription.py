"""Voice transcription provider using Groq."""

import os
from pathlib import Path

import httpx
from loguru import logger


class GroqTranscriptionProvider:
    """
    Voice transcription provider using Groq's Whisper API.

    Groq offers extremely fast transcription with a generous free tier.
    """

    def __init__(self, api_key: str | None = None):
        # Optionally point at a self-hosted OpenAI-compatible transcription
        # endpoint (e.g. speaches) instead of Groq:
        #   export DEEPTUTOR_TRANSCRIPTION_URL="http://127.0.0.1:9872/v1/audio/transcriptions"
        #   export DEEPTUTOR_TRANSCRIPTION_MODEL="Systran/faster-whisper-small"
        self.api_url = os.environ.get(
            "DEEPTUTOR_TRANSCRIPTION_URL",
            "https://api.groq.com/openai/v1/audio/transcriptions",
        )
        self.api_key = (
            api_key
            or os.environ.get("DEEPTUTOR_TRANSCRIPTION_API_KEY")
            or os.environ.get("GROQ_API_KEY")
        )
        self.model = os.environ.get(
            "DEEPTUTOR_TRANSCRIPTION_MODEL", "whisper-large-v3"
        )

    async def transcribe(self, file_path: str | Path) -> str:
        """
        Transcribe an audio file using Groq.

        Args:
            file_path: Path to the audio file.

        Returns:
            Transcribed text.
        """
        if not self.api_key:
            logger.warning("Groq API key not configured for transcription")
            return ""

        path = Path(file_path)
        if not path.exists():
            logger.error("Audio file not found: {}", file_path)
            return ""

        try:
            async with httpx.AsyncClient() as client:
                with open(path, "rb") as f:
                    files = {
                        "file": (path.name, f),
                        "model": (None, self.model),
                    }
                    headers = (
                        {"Authorization": f"Bearer {self.api_key}"}
                        if self.api_key
                        else {}
                    )

                    response = await client.post(
                        self.api_url, headers=headers, files=files, timeout=60.0
                    )

                    response.raise_for_status()
                    data = response.json()
                    return data.get("text", "")

        except Exception as e:
            logger.error("Groq transcription error: {}", e)
            return ""
