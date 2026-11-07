"""Shared LLM response data models."""

from collections.abc import AsyncGenerator

from pydantic import BaseModel, Field

from src.logging import get_logger

logger = get_logger(__name__)


class TutorResponse(BaseModel):
    """LLM completion response container."""

    content: str
    raw_response: dict[str, object] = Field(default_factory=dict)
    usage: dict[str, int] = Field(
        default_factory=lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
    )
    provider: str = ""
    model: str = ""
    finish_reason: str | None = None
    cost_estimate: float = 0.0


class TutorStreamChunk(BaseModel):
    """Chunk emitted during streamed LLM responses."""

    delta: str
    content: str = ""
    provider: str = ""
    model: str = ""
    is_complete: bool = False
    usage: dict[str, int] | None = None


AsyncStreamGenerator = AsyncGenerator[TutorStreamChunk, None]

# Backwards-compatible type aliases used by some callers/tests.
LLMResponse = TutorResponse
StreamChunk = TutorStreamChunk

__all__ = [
    "AsyncStreamGenerator",
    "LLMResponse",
    "StreamChunk",
    "TutorResponse",
    "TutorStreamChunk",
]
