#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
NarratorAgent - Note narration agent.
Uses unified PromptManager for prompt loading.
"""

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, List
from urllib.parse import urlparse
import uuid

# Add project root for imports
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.logging import get_logger
from src.services.config import get_agent_params, load_config_with_main
from src.services.llm import complete as llm_complete
from src.services.llm import get_llm_config
from src.services.prompt import get_prompt_manager
from src.services.tts import get_tts_config

# Initialize logger with config
try:
    config = load_config_with_main(
        "solve_config.yaml", _project_root
    )  # Use any config to get main.yaml
    log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get(
        "log_dir"
    )
    logger = get_logger("Narrator", log_dir=log_dir)
except Exception:
    # Fallback to standard logging
    logger = logging.getLogger(__name__)

# Import shared stats from edit_agent
from src.services.storage.file_store import save_file_record
from src.services.storage.history_store import upsert_history_item
from src.services.storage.object_store import get_bucket_name, upload_bytes

from .edit_agent import get_stats

# Define storage path (unified under user/co-writer/ directory)
# Notes:
# - Consistent with EditAgent's history records, both use user/co-writer as root directory
# - Audio files are stored separately in audio subdirectory for static access via /api/outputs
USER_DIR = Path(__file__).parent.parent.parent.parent / "data" / "user" / "co-writer" / "audio"
DOUBAO_CHUNK_MAX_ATTEMPTS = 3
DOUBAO_RETRY_BACKOFF_BASE_SECONDS = 1.0
DOUBAO_RETRY_BACKOFF_MAX_SECONDS = 6.0


def ensure_dirs():
    """Ensure directories exist"""
    USER_DIR.mkdir(parents=True, exist_ok=True)


class NarratorAgent:
    """Note Narration Agent - Generate narration script and convert to audio"""

    def __init__(self, language: str = "en"):
        # Load agent parameters from unified config (agents.yaml)
        self._agent_params = get_agent_params("narrator")
        self.language = language

        # Load prompts using unified PromptManager
        self._prompts = get_prompt_manager().load_prompts(
            module_name="co_writer",
            agent_name="narrator_agent",
            language=language,
        )

        try:
            self.llm_config = get_llm_config()
        except Exception as e:
            logger.error(f"Failed to load LLM config: {e}")
            self.llm_config = None

        # Load main config file to get TTS default settings
        try:
            config = load_config_with_main("solve_config.yaml", _project_root)
            self.tts_settings = config.get("tts", {})
            self.default_voice = self.tts_settings.get("default_voice", "alloy")
            logger.info(f"TTS settings loaded from config: voice={self.default_voice}")
        except Exception as e:
            logger.warning(f"Failed to load TTS settings from config, using defaults: {e}")
            self.default_voice = "alloy"

        try:
            self.tts_config = get_tts_config()
            # Validate TTS configuration
            self._validate_tts_config()
        except Exception as e:
            logger.error(f"Failed to load TTS config: {e}", exc_info=True)
            self.tts_config = None

    def _validate_tts_config(self):
        """Validate TTS configuration completeness and format"""
        if not self.tts_config:
            raise ValueError("TTS config is None")

        provider = self.tts_config.get("provider", "openai")

        if provider == "doubao":
            required_keys = ["app_id", "access_token"]
            missing_keys = [key for key in required_keys if key not in self.tts_config]
            if missing_keys:
                raise ValueError(f"TTS config missing required keys for Doubao: {missing_keys}")

            # Log configuration info
            logger.info("TTS Configuration Loaded (Doubao):")
            logger.info(f"  Cluster: {self.tts_config.get('cluster')}")
            logger.info(f"  Base URL: {self.tts_config.get('base_url')}")

        else:
            # Check required keys for OpenAI
            required_keys = ["model", "api_key", "base_url"]
            missing_keys = [key for key in required_keys if key not in self.tts_config]
            if missing_keys:
                raise ValueError(f"TTS config missing required keys: {missing_keys}")

            # Validate base_url format
            base_url = self.tts_config["base_url"]
            if not base_url:
                raise ValueError("TTS config 'base_url' is empty")

            if not isinstance(base_url, str):
                raise ValueError(f"TTS config 'base_url' must be a string, got {type(base_url)}")

            # Validate URL format
            if not base_url.startswith(("http://", "https://")):
                raise ValueError(
                    f"TTS config 'base_url' must start with http:// or https://, got: {base_url}"
                )

            try:
                parsed = urlparse(base_url)
                if not parsed.netloc:
                    raise ValueError(f"TTS config 'base_url' has invalid format: {base_url}")
            except Exception as e:
                raise ValueError(f"TTS config 'base_url' parsing error: {e}")

            # Validate api_key
            api_key = self.tts_config.get("api_key")
            if not api_key:
                raise ValueError("TTS config 'api_key' is empty")

            if not isinstance(api_key, str) or len(api_key.strip()) == 0:
                raise ValueError("TTS config 'api_key' must be a non-empty string")

            # Validate model
            model = self.tts_config.get("model")
            if not model:
                raise ValueError("TTS config 'model' is empty")

            # Log configuration info (hide sensitive information)
            api_key_preview = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "*" * 10
            logger.info("TTS Configuration Loaded (OpenAI API):")
            logger.info(f"  Model: {model}")
            logger.info(f"  Base URL: {base_url}")
            logger.info(f"  API Key: {api_key_preview}")
            logger.info(f"  Default Voice: {self.default_voice}")

    async def generate_script(self, content: str, style: str = "friendly") -> dict[str, Any]:
        """
        Generate narration script

        Args:
            content: Note content (Markdown format)
            style: Narration style (friendly, academic, concise)

        Returns:
            Dict containing:
                - script: Narration script text
                - key_points: List of extracted key points
        """
        # Always refresh LLM config before starting to avoid stale credentials
        try:
            self.llm_config = get_llm_config()
        except Exception as e:
            logger.error(f"Failed to refresh LLM config: {e}")

        if not self.llm_config:
            raise ValueError("LLM configuration not available")

        # Estimate target length: OpenAI TTS supports up to 4096 characters
        # We target 4000 characters to leave some margin
        target_length = 4000
        is_long_content = len(content) > 5000

        style_prompts = {
            "friendly": self._prompts.get("style_friendly", ""),
            "academic": self._prompts.get("style_academic", ""),
            "concise": self._prompts.get("style_concise", ""),
        }

        length_instruction = (
            self._prompts.get("length_instruction_long", "")
            if is_long_content
            else self._prompts.get("length_instruction_short", "")
        )

        system_template = self._prompts.get("generate_script_system_template", "")
        system_prompt = system_template.format(
            style_prompt=style_prompts.get(style, style_prompts["friendly"]),
            length_instruction=length_instruction,
        )

        if is_long_content:
            user_template = self._prompts.get("generate_script_user_long", "")
            user_prompt = user_template.format(content=content[:8000] + "...")
        else:
            user_template = self._prompts.get("generate_script_user_short", "")
            user_prompt = user_template.format(content=content)

        logger.info(f"Generating narration script with style: {style}")

        model = self.llm_config.model
        response = await llm_complete(
            binding=self.llm_config.binding,
            model=model,
            prompt=user_prompt,
            system_prompt=system_prompt,
            api_key=self.llm_config.api_key,
            base_url=self.llm_config.base_url,
            max_tokens=self._agent_params["max_tokens"],
            temperature=self._agent_params["temperature"],
        )

        # Track token usage
        stats = get_stats()
        stats.add_call(
            model=model, system_prompt=system_prompt, user_prompt=user_prompt, response=response
        )

        # Clean and truncate response, ensure it doesn't exceed 4000 characters
        script = response.strip()
        if len(script) > 4000:
            logger.warning(
                f"Generated script length {len(script)} exceeds 4000 limit. Truncating..."
            )
            truncated = script[:3997]
            last_period = max(
                truncated.rfind("。"),
                truncated.rfind("！"),
                truncated.rfind("？"),
                truncated.rfind("."),
                truncated.rfind("!"),
                truncated.rfind("?"),
            )
            if last_period > 3500:
                script = truncated[: last_period + 1]
            else:
                script = truncated + "..."

        key_points = await self._extract_key_points(content)

        return {
            "script": script,
            "key_points": key_points,
            "style": style,
            "original_length": len(content),
            "script_length": len(script),
        }

    async def _extract_key_points(self, content: str) -> list:
        """Extract key points from notes"""
        if not self.llm_config:
            return []

        system_prompt = self._prompts.get("extract_key_points_system", "")
        user_template = self._prompts.get(
            "extract_key_points_user",
            "Please extract key points from the following notes:\n\n{content}",
        )
        user_prompt = user_template.format(content=content[:4000])

        try:
            model = self.llm_config.model
            response = await llm_complete(
                binding=self.llm_config.binding,
                model=model,
                prompt=user_prompt,
                system_prompt=system_prompt,
                api_key=self.llm_config.api_key,
                base_url=self.llm_config.base_url,
                max_tokens=self._agent_params["max_tokens"],
                temperature=self._agent_params["temperature"],
            )

            # Track token usage
            stats = get_stats()
            stats.add_call(
                model=model, system_prompt=system_prompt, user_prompt=user_prompt, response=response
            )

            # Try to parse JSON
            json_match = re.search(r"\[.*\]", response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            return []
        except Exception as e:
            logger.warning(f"Failed to extract key points: {e}")
            return []

    async def generate_audio(
        self, script: str, voice: str = None, podcast_config: dict = None
    ) -> dict[str, Any]:
        """
        Convert narration script to audio using OpenAI TTS API

        Args:
            script: Narration script text
            voice: Voice role (alloy, echo, fable, onyx, nova, shimmer)

        Returns:
            Dict containing:
                - audio_url: Audio access URL
                - audio_id: Unique audio identifier
                - voice: Voice used
        """
        if not self.tts_config:
            raise ValueError(
                "TTS configuration not available. Please configure TTS_MODEL, TTS_API_KEY, and TTS_URL in .env"
            )

        # Use default voice if not specified
        if voice is None:
            voice = self.default_voice

        # Validate input parameters
        if not script or not script.strip():
            raise ValueError("Script cannot be empty")

        # Truncate overly long scripts (OpenAI TTS supports up to 4096 characters)
        original_script_length = len(script)
        if len(script) > 4096:
            logger.warning(f"Script length {len(script)} exceeds 4096 limit. Truncating...")
            truncated = script[:4093]
            last_period = max(
                truncated.rfind("。"),
                truncated.rfind("！"),
                truncated.rfind("？"),
                truncated.rfind("."),
                truncated.rfind("!"),
                truncated.rfind("?"),
            )
            if last_period > 3500:
                script = truncated[: last_period + 1]
            else:
                script = truncated + "..."
            logger.info(
                f"Script truncated from {original_script_length} to {len(script)} characters"
            )

        provider = self.tts_config.get("provider", "openai")
        audio_id = str(uuid.uuid4())
        audio_filename = f"{audio_id}.mp3"

        try:
            if provider == "doubao":
                from src.services.tts.doubao_client import DoubaoPodcastClient

                client = DoubaoPodcastClient(
                    app_id=self.tts_config["app_id"],
                    access_token=self.tts_config["access_token"],
                    base_url=self.tts_config.get(
                        "base_url",
                        "wss://openspeech.bytedance.com/api/v3/sami/podcasttts",
                    ),
                )
                pc = podcast_config or {}
                audio_content = await client.generate_audio(
                    script,
                    speakers=pc.get("speakers"),
                    speech_rate=pc.get("speech_rate", 1.0),
                )
            else:
                # Create OpenAI client with custom base_url
                from openai import OpenAI

                client = OpenAI(
                    base_url=self.tts_config["base_url"],
                    api_key=self.tts_config["api_key"],
                )
                # Call OpenAI TTS API
                response = client.audio.speech.create(
                    model=self.tts_config["model"],
                    voice=voice or self.tts_config.get("voice", "alloy"),
                    input=script,
                )
                audio_content = response.content

            bucket = get_bucket_name()
            if not bucket:
                raise ValueError("MinIO bucket not configured")
            object_key = f"co-writer/audio/{audio_filename}"
            upload_bytes(bucket, object_key, audio_content, content_type="audio/mpeg")
            save_file_record(
                file_id=audio_id,
                file_type="audio",
                filename=audio_filename,
                bucket=bucket,
                object_key=object_key,
                content_type="audio/mpeg",
                metadata={"voice": voice},
            )

            return {
                "audio_url": f"/api/v1/co_writer/stream_audio/{audio_id}",
                "audio_id": audio_id,
            }

        except Exception as e:
            logger.error(f"TTS generation failed: {type(e).__name__}: {e}", exc_info=True)
            raise ValueError(f"TTS generation failed: {type(e).__name__}: {e}")

    async def generate_audio_stream(
        self,
        script: str,
        voice: str = None,
        audio_id: str = None,
        output_path: Path | None = None,
        podcast_config: dict = None,
        retry_state: dict | None = None,
    ):
        """
        Generate audio stream and save to file simultaneously.
        Yields audio chunks.
        """
        if not self.tts_config:
            raise ValueError("TTS configuration not available")

        if voice is None:
            voice = self.default_voice

        # Use provided audio_id or generate new one
        if not audio_id:
            audio_id = str(uuid.uuid4())

        if output_path is None:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            output_path = Path(temp_file.name)
            temp_file.close()

        provider = self.tts_config.get("provider", "openai")
        retry_state_ref = retry_state if retry_state is not None else {}
        retry_state_ref.setdefault("attempted_retries", 0)
        retry_state_ref.setdefault("max_retries_per_chunk", DOUBAO_CHUNK_MAX_ATTEMPTS - 1)
        retry_state_ref.setdefault("last_error", None)
        retry_state_ref.setdefault("last_error_code", None)
        retry_state_ref.setdefault("last_error_retryable", None)

        # Helper for splitting text into smaller chunks for Doubao to avoid RPCTimeout
        def split_text(text: str, max_len: int = 1000) -> List[str]:
            chunks = []
            while len(text) > max_len:
                # Find last sentence end within max_len
                split_pos = -1
                for p in ["。", "！", "？", ".", "!", "?"]:
                    pos = text.rfind(p, 0, max_len)
                    if pos > split_pos:
                        split_pos = pos

                if split_pos == -1:
                    split_pos = max_len  # Fallback to hard split

                chunks.append(text[: split_pos + 1])
                text = text[split_pos + 1 :].strip()
            if text:
                chunks.append(text)
            return chunks

        try:
            # Consume stream, write to file, and yield
            with open(output_path, "wb") as f:
                if provider == "doubao":
                    from src.services.tts.doubao_client import (
                        DoubaoPodcastClient,
                        classify_doubao_podcast_error,
                    )

                    client = DoubaoPodcastClient(
                        app_id=self.tts_config["app_id"],
                        access_token=self.tts_config["access_token"],
                        base_url=self.tts_config.get(
                            "base_url", "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
                        ),
                    )
                    pc = podcast_config or {}
                    pc_speakers = pc.get("speakers")
                    pc_speech_rate = pc.get("speech_rate", 1.0)

                    # Split into smaller chunks to avoid server-side RPCTimeout
                    script_chunks = split_text(script, max_len=1500)
                    logger.info(f"Split script into {len(script_chunks)} chunks for Doubao")

                    for i, chunk in enumerate(script_chunks):
                        logger.info(
                            f"Processing chunk {i + 1}/{len(script_chunks)} (len={len(chunk)})"
                        )

                        # Retry logic for each chunk
                        for attempt in range(DOUBAO_CHUNK_MAX_ATTEMPTS):
                            try:
                                async for audio_chunk in client.generate_audio_stream(
                                    chunk,
                                    speakers=pc_speakers,
                                    speech_rate=pc_speech_rate,
                                ):
                                    if audio_chunk:
                                        f.write(audio_chunk)
                                        f.flush()
                                        yield audio_chunk
                                break  # Success, move to next chunk
                            except Exception as e:
                                classification = classify_doubao_podcast_error(e)
                                retry_state_ref["last_error"] = str(e)
                                retry_state_ref["last_error_code"] = classification.code
                                retry_state_ref["last_error_retryable"] = classification.retryable

                                if (
                                    classification.retryable
                                    and attempt < DOUBAO_CHUNK_MAX_ATTEMPTS - 1
                                ):
                                    retry_state_ref["attempted_retries"] += 1
                                    retry_no = attempt + 1
                                    backoff_seconds = min(
                                        DOUBAO_RETRY_BACKOFF_MAX_SECONDS,
                                        DOUBAO_RETRY_BACKOFF_BASE_SECONDS * (2**attempt),
                                    )
                                    logger.warning(
                                        "Retryable Doubao error on chunk %s/%s "
                                        "(attempt %s/%s, code=%s): %s",
                                        i + 1,
                                        len(script_chunks),
                                        retry_no,
                                        DOUBAO_CHUNK_MAX_ATTEMPTS - 1,
                                        classification.code,
                                        e,
                                    )
                                    await asyncio.sleep(backoff_seconds)
                                    continue
                                raise  # Re-raise if other error or no more retries
                else:
                    # OpenAI or other providers
                    # Truncate script if needed for OpenAI
                    openai_script = script
                    if len(openai_script) > 4096:
                        openai_script = openai_script[:4093] + "..."

                    from openai import OpenAI

                    client = OpenAI(
                        base_url=self.tts_config["base_url"],
                        api_key=self.tts_config["api_key"],
                    )
                    response = client.audio.speech.create(
                        model=self.tts_config["model"],
                        voice=voice,
                        input=openai_script,
                    )
                    # For OpenAI we yield as a single chunk (it's small anyway)
                    chunk = response.content
                    if chunk:
                        f.write(chunk)
                        f.flush()
                        yield chunk

        except Exception as e:
            logger.error(f"Audio streaming failed: {e}")
            # If failed, we might want to delete the partial file to avoid serving corrupt data later
            if output_path.exists():
                try:
                    output_path.unlink()
                except Exception:
                    pass
            raise

    async def narrate(
        self,
        content: str,
        style: str = "friendly",
        voice: str = None,
        skip_audio: bool = False,
        podcast_config: dict = None,
    ) -> dict[str, Any]:
        """
        Synthesize script and generate audio for a note.
        """
        # Refresh configs
        try:
            self.tts_config = get_tts_config()
            self.llm_config = get_llm_config()
        except Exception as e:
            logger.error(f"Failed to refresh configs: {e}")

        # ALWAYS generate script to ensure content is optimized for podcast and not too long
        # Doubao Podcast TTS works better with structured script than raw research report
        script_result = await self.generate_script(content, style)

        if voice is None:
            voice = self.default_voice

        result = {
            "script": script_result["script"],
            "key_points": script_result["key_points"],
            "style": style,
            "original_length": script_result["original_length"],
            "script_length": script_result["script_length"],
            "has_audio": False,
        }

        if not skip_audio and self.tts_config:
            # Generate ID but defer generation to stream endpoint
            audio_id = str(uuid.uuid4())

            provider = self.tts_config.get("provider", "openai") if self.tts_config else "openai"

            result.update(
                {
                    "audio_url": f"/api/v1/co_writer/stream_audio/{audio_id}",
                    "audio_id": audio_id,
                    "voice": voice,
                    "has_audio": True,
                }
            )

            # Save to history (Persistence Fix)
            try:
                history_item = {
                    "id": audio_id,
                    "type": "narrate",
                    "timestamp": datetime.now().isoformat(),
                    "content_preview": content[:100] + "...",
                    "result": result,
                    "status": "pending_stream",
                }
                set_pending_stream(
                    audio_id=audio_id,
                    script=script_result["script"],
                    voice=voice,
                    provider=provider,
                    podcast_config=podcast_config,
                )
                upsert_history_item(history_item)
                logger.info(f"Saved narration history item {audio_id}")

            except Exception as e:
                logger.warning(
                    f"⚠️ Failed to save podcast history to database: {e}. "
                    "This is expected if PostgreSQL is not running (e.g., local non-Docker env). "
                    "The audio generation will continue normally."
                )

        else:
            if not self.tts_config:
                result["audio_error"] = "TTS not configured"

        return result


# Simple in-memory store for pending streams and active locks
_PENDING_STREAMS: Dict[str, Any] = {}
_ACTIVE_GENERATIONS: Dict[str, asyncio.Lock] = {}
_narrator_agent = None


def get_narrator_agent():
    """Get or create singleton instance of NarratorAgent"""
    global _narrator_agent
    if _narrator_agent is None:
        _narrator_agent = NarratorAgent()
    return _narrator_agent


def get_pending_stream(audio_id: str):
    # Use get instead of pop to allow multiple requests (like browser range requests)
    # to find the pending stream while it's still generating or just started.
    return _PENDING_STREAMS.get(audio_id)


def set_pending_stream(
    audio_id: str, script: str, voice: str, provider: str, podcast_config: dict = None
):
    _PENDING_STREAMS[audio_id] = {
        "script": script,
        "voice": voice,
        "provider": provider,
        "podcast_config": podcast_config,
    }


async def get_generation_lock(audio_id: str) -> asyncio.Lock:
    """Get or create a lock for a specific audio generation"""
    if audio_id not in _ACTIVE_GENERATIONS:
        _ACTIVE_GENERATIONS[audio_id] = asyncio.Lock()
    return _ACTIVE_GENERATIONS[audio_id]


def remove_pending_stream(audio_id: str):
    """Clean up pending stream once finished"""
    _PENDING_STREAMS.pop(audio_id, None)
    _ACTIVE_GENERATIONS.pop(audio_id, None)


__all__ = [
    "NarratorAgent",
    "get_pending_stream",
    "set_pending_stream",
    "get_narrator_agent",
    "remove_pending_stream",
    "get_generation_lock",
]
