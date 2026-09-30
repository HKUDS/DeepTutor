"""Coarse fallback accounting when a provider omits usage.

Image transport bytes are not language tokens. Keep the historical chars/3.5
text heuristic, with a fixed allowance per recognized image content block.
This is not a model-specific vision tokenizer or a billing calculation.
"""

from __future__ import annotations

from typing import Any

ESTIMATED_IMAGE_TOKENS = 1024


def estimate_prompt_tokens(messages: Any) -> int:
    """Estimate without serializing image bytes/URLs or mutating the request.

    Only structured content blocks are images. Image-looking text, tool-call
    arguments, tool results and other message fields still count as text.
    No image is decoded, fetched, or retained by this estimator.
    """
    images = 0

    def without_image_payloads(value: Any, *, content: bool = False) -> Any:
        nonlocal images
        if isinstance(value, dict):
            kind = value.get("type")
            if content and (
                (kind == "image_url" and "image_url" in value)
                or (kind == "input_image" and ("image_url" in value or "file_id" in value))
                or (kind == "image" and "source" in value)
            ):
                images += 1
                return {"type": kind}
            return {
                key: without_image_payloads(item, content=key == "content")
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            items = [without_image_payloads(item, content=content) for item in value]
            return tuple(items) if isinstance(value, tuple) else items
        return value

    text_chars = len(str(without_image_payloads(messages or "")))
    return int(text_chars / 3.5) + images * ESTIMATED_IMAGE_TOKENS
