"""Focus material summarization helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from deeptutor.services.llm import get_llm_config
from deeptutor.services.llm.context_window import resolve_effective_context_window


async def build_focus_material(
    complete_focus: Callable[..., Awaitable[str]],
    content: str,
    *,
    language: str,
) -> str:
    cfg = get_llm_config()
    window = resolve_effective_context_window(
        context_window=getattr(cfg, "context_window", None),
        model=cfg.model,
        max_tokens=getattr(cfg, "max_tokens", None),
    )
    safe_chars = max(18_000, (window - 8_000) * 3)
    if len(content) <= safe_chars:
        return content

    # Reuse the service's established source-preserving section splitter.
    from deeptutor.immersive_reading.service import _split_near

    chunks = _split_near(content, target=safe_chars)
    system = (
        "Create a source-faithful checkpoint digest of this PART of a chapter. Preserve all major events, "
        "claims, characters, causality, turning points, and emotionally significant moments. Do not judge the learner."
    )
    semaphore = asyncio.Semaphore(4)

    async def summarise(index: int, chunk: str) -> str:
        async with semaphore:
            return await complete_focus(
                prompt=(
                    f"Language for digest: {language}\n\n"
                    f"Chapter part {index + 1}/{len(chunks)}:\n{chunk}"
                ),
                system_prompt=system,
                temperature=0.1,
                max_tokens=2200,
                reasoning_effort="minimal",
                max_retries=0,
                timeout=30,
            )

    summaries = await asyncio.gather(
        *(summarise(index, chunk) for index, chunk in enumerate(chunks))
    )
    return "\n\n".join(f"[Part {index + 1}]\n{summary}" for index, summary in enumerate(summaries))

