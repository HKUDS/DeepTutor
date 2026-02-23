"""
System Status API Router
Manages system status checks and model connection tests
"""

from datetime import datetime
import time

from fastapi import APIRouter
from pydantic import BaseModel

from src.services.embedding import get_embedding_client, get_embedding_config
from src.services.llm import complete as llm_complete
from src.services.llm import get_llm_config, get_token_limit_kwargs
from src.services.tts import get_tts_config

router = APIRouter()


class TestResponse(BaseModel):
    success: bool
    message: str
    model: str | None = None
    response_time_ms: float | None = None
    error: str | None = None


@router.get("/status")
async def get_system_status():
    """
    Get overall system status including backend and model configurations

    Returns:
        Dictionary containing status of backend, LLM, embeddings, and TTS
    """
    result = {
        "backend": {"status": "online", "timestamp": datetime.now().isoformat()},
        "llm": {"status": "unknown", "model": None, "testable": True},
        "embeddings": {"status": "unknown", "model": None, "testable": True},
        "tts": {"status": "unknown", "model": None, "testable": True},
    }

    # Check backend status (this endpoint itself proves backend is online)
    result["backend"]["status"] = "online"

    # Check LLM configuration
    try:
        llm_config = get_llm_config()
        result["llm"]["model"] = llm_config.model
        result["llm"]["status"] = "configured"
        result["llm"]["base_url"] = llm_config.base_url
    except ValueError as e:
        result["llm"]["status"] = "not_configured"
        result["llm"]["error"] = str(e)
    except Exception as e:
        result["llm"]["status"] = "error"
        result["llm"]["error"] = str(e)

    # Check Embeddings configuration
    try:
        embedding_config = get_embedding_config()
        result["embeddings"]["model"] = embedding_config.model
        result["embeddings"]["status"] = "configured"
        result["embeddings"]["base_url"] = embedding_config.base_url
    except ValueError as e:
        result["embeddings"]["status"] = "not_configured"
        result["embeddings"]["error"] = str(e)
    except Exception as e:
        result["embeddings"]["status"] = "error"
        result["embeddings"]["error"] = str(e)

    # Check TTS configuration
    try:
        tts_config = get_tts_config()
        result["tts"]["model"] = tts_config.get("model")
        result["tts"]["status"] = "configured"
        result["tts"]["provider"] = tts_config.get("provider", "openai")
        result["tts"]["base_url"] = tts_config.get("base_url")
    except ValueError as e:
        result["tts"]["status"] = "not_configured"
        result["tts"]["error"] = str(e)
    except Exception as e:
        result["tts"]["status"] = "error"
        result["tts"]["error"] = str(e)

    return result


@router.post("/test/llm/", response_model=TestResponse)
async def test_llm_connection():
    """
    Test LLM model connection by sending a simple completion request

    Returns:
        Test result with success status and response time
    """
    start_time = time.time()

    try:
        llm_config = get_llm_config()
        model = llm_config.model
        base_url = llm_config.base_url.rstrip("/")

        # Sanitize Base URL (remove /chat/completions suffix if present)
        for suffix in ["/chat/completions", "/completions"]:
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]

        # Handle API Key (inject dummy if missing for local LLMs)
        api_key = llm_config.api_key
        if not api_key:
            api_key = "sk-no-key-required"

        # Send a minimal test request with a prompt that guarantees output
        test_prompt = "Say 'OK' to confirm you are working. Do not produce long output."
        token_kwargs = get_token_limit_kwargs(model, max_tokens=200)

        response = await llm_complete(
            model=model,
            prompt=test_prompt,
            system_prompt="You are a helpful assistant. Respond briefly.",
            binding=llm_config.binding,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            **token_kwargs,
        )

        response_time = (time.time() - start_time) * 1000

        if response and len(response.strip()) > 0:
            return TestResponse(
                success=True,
                message="LLM connection successful",
                model=model,
                response_time_ms=round(response_time, 2),
            )
        return TestResponse(
            success=False,
            message="LLM connection failed: Empty response",
            model=model,
            error="Empty response from API",
        )

    except ValueError as e:
        return TestResponse(success=False, message=f"LLM configuration error: {e!s}", error=str(e))
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return TestResponse(
            success=False,
            message=f"LLM connection failed: {e!s}",
            response_time_ms=round(response_time, 2),
            error=str(e),
        )


@router.post("/test/embeddings/", response_model=TestResponse)
async def test_embeddings_connection():
    """
    Test Embeddings model connection by sending a simple embedding request

    Returns:
        Test result with success status and response time
    """
    start_time = time.time()

    try:
        embedding_config = get_embedding_config()

        from src.services.embedding import reset_embedding_client

        reset_embedding_client()
        embedding_client = get_embedding_client()

        model = embedding_config.model
        binding = embedding_config.binding

        # Send a minimal test request using unified client
        test_texts = ["test"]
        embeddings = await embedding_client.embed(test_texts)

        response_time = (time.time() - start_time) * 1000

        if embeddings is not None and len(embeddings) > 0 and len(embeddings[0]) > 0:
            return TestResponse(
                success=True,
                message=f"Embeddings connection successful ({binding} provider)",
                model=model,
                response_time_ms=round(response_time, 2),
            )
        return TestResponse(
            success=False,
            message="Embeddings connection failed: Empty response",
            model=model,
            error="Empty embedding vector",
        )

    except ValueError as e:
        return TestResponse(
            success=False, message=f"Embeddings configuration error: {e!s}", error=str(e)
        )
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return TestResponse(
            success=False,
            message=f"Embeddings connection failed: {e!s}",
            response_time_ms=round(response_time, 2),
            error=str(e),
        )


@router.post("/test/tts/", response_model=TestResponse)
async def test_tts_connection():
    """
    Test TTS model connection by checking configuration

    Note: We don't actually generate audio for testing to avoid unnecessary API calls.
    We only verify the configuration is valid.

    Returns:
        Test result with success status
    """
    start_time = time.time()

    try:
        tts_config = get_tts_config()
        provider = tts_config.get("provider", "openai")

        if provider == "doubao":
            app_id = tts_config.get("app_id")
            access_token = tts_config.get("access_token")

            if not app_id or not access_token:
                return TestResponse(
                    success=False,
                    message="TTS configuration incomplete (Doubao)",
                    model="doubao-podcast",
                    error="Missing Doubao AppID or Access Token",
                )

            model = "doubao-podcast"

        else:
            model = tts_config.get("model")
            api_key = tts_config.get("api_key")
            base_url = tts_config.get("base_url")

            if not model or not api_key or not base_url:
                return TestResponse(
                    success=False,
                    message="TTS configuration incomplete",
                    model=model,
                    error="Missing required configuration",
                )

        # For TTS, we just verify the config is valid
        # Actual audio generation would be expensive, so we skip it
        response_time = (time.time() - start_time) * 1000

        return TestResponse(
            success=True,
            message=f"TTS configuration valid ({provider})",
            model=model,
            response_time_ms=round(response_time, 2),
        )

    except ValueError as e:
        return TestResponse(success=False, message=f"TTS configuration error: {e!s}", error=str(e))
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return TestResponse(
            success=False,
            message=f"TTS connection check failed: {e!s}",
            response_time_ms=round(response_time, 2),
            error=str(e),
        )
