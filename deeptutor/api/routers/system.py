"""
System Status API Router
Manages system status checks and model connection tests
"""

from datetime import datetime
import time

from fastapi import APIRouter
from pydantic import BaseModel

from deeptutor.multi_user.context import get_current_user
from deeptutor.services.config import resolve_search_runtime_config
from deeptutor.services.embedding import get_embedding_client, get_embedding_config
from deeptutor.services.llm import complete as llm_complete
from deeptutor.services.llm import get_llm_config, get_token_limit_kwargs
from deeptutor.services.search import web_search

router = APIRouter()


class TestResponse(BaseModel):
    success: bool
    message: str
    model: str | None = None
    response_time_ms: float | None = None
    error: str | None = None


@router.get("/runtime-topology")
async def get_runtime_topology():
    """
    Describe the current execution topology.

    This makes the unified runtime explicit for operators and frontend code:
    interactive chat turns should prefer `/api/v1/ws`, while a few routers still
    exist as compatibility or isolated subsystem endpoints.
    """
    return {
        "primary_runtime": {
            "transport": "/api/v1/ws",
            "manager": "TurnRuntimeManager",
            "orchestrator": "ChatOrchestrator",
            "session_store": "SQLiteSessionStore",
            "capability_entry": "CapabilityRegistry",
            "tool_entry": "ToolRegistry",
        },
        "compatibility_routes": [
            {"router": "chat", "mode": "legacy_adapter_target"},
            {"router": "solve", "mode": "legacy_adapter_target"},
            {"router": "question", "mode": "legacy_specialized"},
            {"router": "research", "mode": "legacy_specialized"},
        ],
        "isolated_subsystems": [
            {"router": "co_writer", "mode": "independent_subsystem"},
            {"router": "plugins_api", "mode": "playground_transport"},
        ],
    }


@router.get("/status")
async def get_system_status():
    """
    Get overall system status including backend and model configurations

    Returns:
        Dictionary containing status of backend, LLM, embeddings, and search
    """
    result = {
        "backend": {"status": "online", "timestamp": datetime.now().isoformat()},
        "llm": {"status": "unknown", "model": None, "testable": True},
        "embeddings": {"status": "unknown", "model": None, "testable": True},
        "search": {"status": "optional", "provider": None, "testable": True},
    }

    # Check backend status (this endpoint itself proves backend is online)
    result["backend"]["status"] = "online"

    # Check LLM configuration
    try:
        llm_config = get_llm_config()
        result["llm"]["model"] = llm_config.model
        result["llm"]["status"] = "configured"
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
    except ValueError as e:
        result["embeddings"]["status"] = "not_configured"
        result["embeddings"]["error"] = str(e)
    except Exception as e:
        result["embeddings"]["status"] = "error"
        result["embeddings"]["error"] = str(e)

    try:
        search_config = resolve_search_runtime_config()
        if search_config.requested_provider:
            result["search"]["provider"] = search_config.provider
            if search_config.unsupported_provider:
                result["search"]["status"] = "unsupported"
                result["search"]["error"] = (
                    f"{search_config.requested_provider} is deprecated/unsupported. "
                    "Switch to brave/tavily/jina/searxng/duckduckgo/perplexity."
                )
            elif search_config.deprecated_provider:
                result["search"]["status"] = "deprecated"
                result["search"]["error"] = (
                    f"{search_config.requested_provider} is deprecated. "
                    "Switch to brave/tavily/jina/searxng/duckduckgo/perplexity."
                )
            elif search_config.missing_credentials:
                result["search"]["status"] = "not_configured"
                result["search"]["error"] = (
                    f"{search_config.requested_provider} requires api_key. "
                    "Set profile.api_key or PERPLEXITY_API_KEY."
                )
            else:
                result["search"]["status"] = "configured"
                if search_config.fallback_reason:
                    result["search"]["status"] = "fallback"
                    result["search"]["error"] = search_config.fallback_reason
    except Exception as e:
        result["search"]["status"] = "error"
        result["search"]["error"] = str(e)

    # Non-admin users have no need to know which model the admin configured;
    # exposing the name leaks operational detail and would let curious users
    # fingerprint the deployment. Strip the identifying fields.
    if not get_current_user().is_admin:
        for section in ("llm", "embeddings"):
            result[section].pop("model", None)
        result["search"].pop("provider", None)

    return result


@router.post("/test/llm", response_model=TestResponse)
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


@router.post("/test/embeddings", response_model=TestResponse)
async def test_embeddings_connection():
    """
    Test Embeddings model connection by sending a simple embedding request

    Returns:
        Test result with success status and response time
    """
    start_time = time.time()

    try:
        embedding_config = get_embedding_config()
        embedding_client = get_embedding_client()

        model = embedding_config.model
        binding = embedding_config.binding

        # Probe a tiny batch so "connection OK" also exercises the path RAG
        # uses for multi-chunk indexing.
        test_texts = ["test", "retrieval batch probe"]
        embeddings = await embedding_client.embed(test_texts)

        response_time = (time.time() - start_time) * 1000

        if (
            embeddings is not None
            and len(embeddings) == len(test_texts)
            and all(len(vector) > 0 for vector in embeddings)
            and len({len(vector) for vector in embeddings}) == 1
        ):
            return TestResponse(
                success=True,
                message=f"Embeddings connection successful ({binding} provider)",
                model=model,
                response_time_ms=round(response_time, 2),
            )
        return TestResponse(
            success=False,
            message="Embeddings connection failed: Invalid response",
            model=model,
            error="Embedding response must contain one non-empty vector per input",
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


@router.post("/test/search", response_model=TestResponse)
async def test_search_connection():
    start_time = time.time()

    try:
        search_config = resolve_search_runtime_config()
        if not search_config.requested_provider:
            return TestResponse(
                success=False,
                message="Search not configured",
                error="Missing SEARCH_PROVIDER",
            )
        if search_config.unsupported_provider:
            return TestResponse(
                success=False,
                message=(
                    f"Search provider `{search_config.requested_provider}` is deprecated/unsupported."
                ),
                error="Switch to brave/tavily/jina/searxng/duckduckgo/perplexity",
            )
        if search_config.missing_credentials:
            return TestResponse(
                success=False,
                message=f"Search provider `{search_config.requested_provider}` missing credentials.",
                error="Set profile.api_key or PERPLEXITY_API_KEY",
            )
        result = web_search("DeepTutor health check", provider=search_config.provider)
        response_time = (time.time() - start_time) * 1000
        answer = result.get("answer") or result.get("search_results")
        if not answer:
            raise ValueError("Search provider returned no content")
        return TestResponse(
            success=True,
            message="Search connection successful",
            model=search_config.provider,
            response_time_ms=round(response_time, 2),
        )

    except ValueError as e:
        return TestResponse(
            success=False, message=f"Search configuration error: {e!s}", error=str(e)
        )
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return TestResponse(
            success=False,
            message=f"Search connection check failed: {e!s}",
            response_time_ms=round(response_time, 2),
            error=str(e),
        )
