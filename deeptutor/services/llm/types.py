"""Shared LLM response data models."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: Terminal reasons that mean "the provider stopped because output hit a cap",
#: i.e. the response is incomplete rather than finished. One table: the agent
#: loop, the research pipeline and the streaming callers all read this.
TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})


def finish_was_truncated(reason: str | None) -> bool:
    """Return whether a provider ended generation because output hit a cap."""
    return str(reason or "").strip().lower() in TRUNCATED_FINISH_REASONS


@dataclass
class StreamOutcome:
    """How a streamed call ended, for callers that only see text chunks.

    :func:`deeptutor.services.llm.factory.stream` yields strings, so a caller
    parsing the result could not tell a complete response from one the provider
    cut off at ``max_tokens`` — which is how a reasoning model's truncated JSON
    surfaced as an undiagnosable parse error (#1545, #1547). Pass one of these
    in and the stream fills it once the provider reports the finish.
    """

    finish_reason: str = ""
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        """Whether the provider stopped at an output cap."""
        return finish_was_truncated(self.finish_reason)


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
    "TRUNCATED_FINISH_REASONS",
    "AsyncStreamGenerator",
    "LLMResponse",
    "StreamChunk",
    "StreamOutcome",
    "TutorResponse",
    "TutorStreamChunk",
    "finish_was_truncated",
]
