"""Tool-free application model calls through the native provider boundary."""

from typing import Any

from . import get_engine_client
from .config import provider_config


async def complete_native(
    config: Any, *, system: str, prompt: str, temperature: float, max_tokens: int
) -> str:
    from deeptutor.runtime.agentic.client import build_completion_kwargs

    class NoEffects:
        async def invoke(self, operation: str, args: dict, state: dict) -> None:
            raise ValueError("A tool-free model call cannot invoke application effects")

    result = await get_engine_client().run_native(
        NoEffects(),
        {
            "provider": provider_config(
                config,
                build_completion_kwargs(
                    temperature=temperature,
                    model=config.model,
                    max_tokens=max_tokens,
                    binding=config.binding,
                    reasoning_effort=config.reasoning_effort,
                ),
            ),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        },
        kind="completion",
    )
    return result["text"]
